"""Dashboard connection lifetimes and POST errors use real loopback sockets."""
import http.client
import json
import queue
import socket
import sys
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from myzing.factory import judge, pipeline, serve
from myzing.factory.tools import FactoryError


@pytest.fixture
def project(tmp_path, zing_workspace, monkeypatch):
    monkeypatch.setattr(judge.subprocess, "run", lambda *a, **kw: pytest.fail("unmocked judge"))
    root = tmp_path / "project"
    pipeline._write(root / "factory.json", {**pipeline.SETTINGS, "moments": 0})
    pipeline._write(root / "source.json", {"name": "Show"})
    pipeline._write(root / "moments.json", {"moments": [{"start": 0, "end": 10, "hook": "One"}]})
    pipeline._write(root / "clip01" / "plan-raw.json", {"hook": "One"})
    pipeline._write(root / "clip01" / "post.json", {"x": "old"})
    pipeline._write(root / "clip01" / "visuals" / "manifest.json", {"v1": [{"path": "a.jpg"}]})
    return root


@pytest.fixture
def dashboard(project, monkeypatch):
    @contextmanager
    def start(*, idle_seconds=None, timeout=2):
        pages, servers, errors = queue.Queue(), [], []
        closed, closing, finished = threading.Event(), threading.Event(), threading.Event()
        original_handler, close = serve.handler, serve.Studio.close

        class Server(serve.ThreadingHTTPServer):
            def __init__(self, *args):
                super().__init__(*args)
                servers.append(self)

            def process_request_thread(self, *args):
                try:
                    super().process_request_thread(*args)
                finally:
                    finished.set()

            def server_close(self):
                closing.set()
                super().server_close()

        def handler(*args):
            cls = original_handler(*args)
            cls.timeout = timeout
            return cls

        def stopped(studio):
            close(studio)
            assert studio.stopped.is_set()
            closed.set()

        def run():
            try:
                serve.serve(project, port=0, say=lambda line: None, ready=pages.put, idle_seconds=idle_seconds)
            except Exception as exc:
                errors.append(exc)

        monkeypatch.setattr(serve, "ThreadingHTTPServer", Server)
        monkeypatch.setattr(serve, "handler", handler)
        monkeypatch.setattr(serve.Studio, "close", stopped)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            page = urlsplit(pages.get(timeout=5))
            cookie = f"zing_dash_{page.port}={parse_qs(page.query)['t'][0]}"
            yield SimpleNamespace(page=page, cookie=cookie, server=servers[0], worker=worker,
                                  closed=closed, closing=closing, finished=finished)
        finally:
            if idle_seconds is None and servers and worker.is_alive():
                stopper = threading.Thread(target=servers[0].shutdown, daemon=True)
                stopper.start()
                stopper.join(3)
                assert not stopper.is_alive()
            worker.join(3)
            assert not worker.is_alive() and not errors and closed.is_set()
    return start


def request(dashboard, method, path, body=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", dashboard.page.port, timeout=3)
    try:
        conn.request(method, path, body, {"Content-Type": "application/json",
                                        "Cookie": dashboard.cookie if cookie is None else cookie})
        response = conn.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        conn.close()


def test_handler_has_a_socket_timeout(project):
    assert serve.handler(serve.Studio(project), 8765, "test").timeout == 30


@pytest.mark.parametrize("partial", ["empty", "headers", "body"])
def test_stalled_connection_expires_and_closes_studio(dashboard, capsys, partial):
    with dashboard(idle_seconds=.1, timeout=.2) as live:
        assert live.server.block_on_close
        with socket.create_connection(("127.0.0.1", live.page.port), timeout=2) as conn:
            if partial == "headers":
                conn.sendall(f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{live.page.port}\r\n".encode())
            elif partial == "body":
                conn.sendall((f"POST /api/text HTTP/1.1\r\nHost: 127.0.0.1:{live.page.port}\r\n"
                              f"Cookie: {live.cookie}\r\nContent-Type: application/json\r\n"
                              "Content-Length: 10\r\n\r\n{").encode())
            live.worker.join(3)
            assert not live.worker.is_alive() and live.closed.is_set()
            assert conn.recv(1) == b""
    assert not capsys.readouterr().err


def test_request_at_idle_deadline_finishes_before_the_next_idle_period(dashboard, monkeypatch, capsys):
    now = [0.0]
    parsing, parsed, allow_parse = threading.Event(), threading.Event(), threading.Event()
    acting, allow_action, polling = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(serve, "time", SimpleNamespace(monotonic=lambda: now[0]))
    original_handler, handle_request = serve.handler, serve.ThreadingHTTPServer.handle_request
    result = {"saved": "x", "text": "x" * 4096}

    def handler(*args):
        cls = original_handler(*args)
        parse_request = cls.parse_request

        def parse(self):
            parsing.set()
            assert allow_parse.wait(3)
            answer = parse_request(self)
            parsed.set()
            return answer

        cls.parse_request = parse
        return cls

    def poll(server):
        if now[0] >= 2:
            polling.set()
        handle_request(server)

    def action(studio, body):
        assert body == {"clip": "clip01", "field": "x", "text": "new"}
        acting.set()
        assert allow_action.wait(3)
        return result

    monkeypatch.setattr(serve, "handler", handler)
    monkeypatch.setattr(serve.ThreadingHTTPServer, "handle_request", poll)
    monkeypatch.setattr(serve.Studio, "text", action)
    with dashboard(idle_seconds=1) as live:
        conn = http.client.HTTPConnection("127.0.0.1", live.page.port, timeout=3)
        try:
            now[0] = .9
            raw = json.dumps({"clip": "clip01", "field": "x", "text": "new"}).encode()
            conn.putrequest("POST", "/api/text")
            conn.putheader("Cookie", live.cookie)
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(raw)))
            conn.endheaders(raw[:-1])
            assert parsing.wait(2)
            now[0] = 2
            assert polling.wait(2) and not live.closing.is_set()
            allow_parse.set()
            assert parsed.wait(2)
            polling.clear()
            now[0] = 4
            assert polling.wait(2) and not live.closing.is_set() and not acting.is_set()
            conn.send(raw[-1:])
            assert acting.wait(2)
            polling.clear()
            now[0] = 6
            assert polling.wait(2) and not live.closing.is_set()
            allow_action.set()
            response = conn.getresponse()
            assert response.status == 200 and json.loads(response.read()) == {"ok": True, **result}
            assert live.finished.wait(2)
            polling.clear()
            now[0] = 6.9
            assert polling.wait(2) and not live.closing.is_set()
            now[0] = 7.1
            live.worker.join(3)
            assert not live.worker.is_alive() and live.closed.is_set()
        finally:
            allow_parse.set()
            allow_action.set()
            conn.close()
            live.finished.wait(3)
            now[0] = 100
    assert not capsys.readouterr().err


@pytest.mark.parametrize("kind", ["nested", "text", "visual", "array", "invalid"])
def test_bad_post_bodies_return_json(dashboard, capsys, monkeypatch, kind):
    depth = sys.getrecursionlimit() + 100
    if kind == "nested":                                # how deep the C scanner recurses varies by Python version
        real = json.loads

        def loads(value, *args, **kwargs):
            if isinstance(value, bytes) and value.startswith(b'{"text":[['):
                raise RecursionError("maximum recursion depth exceeded while decoding a JSON array")
            return real(value, *args, **kwargs)
        monkeypatch.setattr(json, "loads", loads)
    path, raw = {
        "nested": ("text", '{"text":' + "[" * depth + "0" + "]" * depth + "}"),
        "text": ("text", '{"clip":"clip01","field":[],"text":"x"}'),
        "visual": ("visual", '{"clip":"clip01","request":[],"index":0}'),
        "array": ("text", "[]"),
        "invalid": ("text", "{"),
    }[kind]
    assert len(raw) < 64 << 10
    with dashboard() as live:
        status, raw, headers = request(live, "POST", "/api/" + path, raw)
        body = json.loads(raw)
        assert headers["Content-Type"] == "application/json" and body["ok"] is False
        if kind in {"text", "visual"}:
            assert status == 500 and body["error"] == "TypeError: unhashable type: 'list'"
        else:
            assert status == 400
            if kind == "invalid":
                assert body["error"].startswith("Expecting property name")
            else:
                assert body["error"] == "send a JSON object"
        assert request(live, "GET", "/api/project")[0] == 200
    assert not capsys.readouterr().err


@pytest.mark.parametrize("error,status", [(FactoryError("no clip"), 400), (ValueError("bad value"), 400),
    (TypeError("bad field"), 500), (RuntimeError("failed"), 500), (RecursionError("action failed"), 500),
    (TimeoutError("action timed out"), 500)])
def test_action_errors_return_json(dashboard, monkeypatch, capsys, error, status):
    def action(studio, body):
        raise error

    monkeypatch.setattr(serve.Studio, "text", action)
    with dashboard() as live:
        code, raw, headers = request(live, "POST", "/api/text", "{}")
        message = str(error) if status == 400 else f"{type(error).__name__}: {error}"
        assert code == status and headers["Content-Type"] == "application/json"
        assert json.loads(raw) == {"ok": False, "error": message}
    assert not capsys.readouterr().err


def test_dashboard_cookie_get_and_post_still_work(dashboard, project, capsys):
    with dashboard() as live:
        status, _, headers = request(live, "GET", "/?" + live.page.query, cookie="")
        assert status == 303 and headers["Location"] == "/"
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        assert cookie == live.cookie
        status, page, _ = request(live, "GET", "/", cookie=cookie)
        assert status == 200 and b'id="mock"' in page
        status, raw, _ = request(live, "POST", "/api/text",
                                 '{"clip":"clip01","field":"x","text":"new copy"}', cookie=cookie)
        assert status == 200 and json.loads(raw) == {"ok": True, "saved": "x"}
        assert pipeline._read(project / "clip01" / "post.json") == {"x": "new copy"}
        status, raw, _ = request(live, "GET", "/api/project", cookie=cookie)
        assert status == 200 and json.loads(raw)["clips"][0]["post"]["x"] == "new copy"
    assert not capsys.readouterr().err
