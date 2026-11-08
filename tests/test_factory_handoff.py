"""The hand-off dashboard reports its bound port and expires after idle time."""
import http.client
import queue
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from myzing.factory import judge, pipeline, serve


@pytest.fixture
def project(tmp_path, zing_workspace, monkeypatch):
    monkeypatch.setattr(judge.subprocess, "run", lambda *a, **kw: pytest.fail("unmocked judge"))
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"synthetic")
    root = tmp_path / "project"
    pipeline.init(root, media)
    return root


def test_ephemeral_dashboard_auth_and_http_activity_extend_idle(project, monkeypatch):
    now, pages, errors, closed = [0], queue.Queue(), [], []
    monkeypatch.setattr(serve, "time", SimpleNamespace(monotonic=lambda: now[0]))
    close = serve.Studio.close

    def stopped(studio):
        close(studio)
        closed.append(studio.stopped.is_set())

    monkeypatch.setattr(serve.Studio, "close", stopped)

    def run():
        try:
            serve.serve(project, port=0, say=lambda line: None, ready=pages.put, idle_seconds=1)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        for _ in range(60):                     # slow CI runners (macOS) can take a while to bind
            if errors:
                raise errors[0]
            try:
                page = urlsplit(pages.get(timeout=.5))
                break
            except queue.Empty:
                continue
        else:
            raise AssertionError("the dashboard never reported ready")
        assert page.hostname == "127.0.0.1" and page.port > 0

        def request(path, headers=None):
            conn = http.client.HTTPConnection(page.hostname, page.port, timeout=2)
            try:
                conn.request("GET", path, headers=headers or {})
                response = conn.getresponse()
                return response.status, response.read(), response.getheader("Set-Cookie")
            finally:
                conn.close()

        now[0] = .8
        status, _, cookie = request("/?" + page.query)
        assert status == 303 and f"zing_dash_{page.port}=" in cookie
        now[0] = 1.2
        worker.join(.6)
        assert worker.is_alive()
        assert request("/", {"Cookie": cookie})[0] == 200
        assert request("/api/project", {"Cookie": cookie})[0] == 200
        assert request("/", {"Host": "elsewhere.test", "Cookie": cookie})[0] == 403
        assert request("/")[0] == 403
    finally:
        for step in range(1, 31):               # a connection that finishes late refreshes the idle clock
            now[0] = 100 * step
            worker.join(.1)
            if not worker.is_alive():
                break
    assert not worker.is_alive() and not errors and closed == [True]


def test_ready_failure_closes_bound_server_and_studio(project, monkeypatch):
    closed = []
    original = serve.ThreadingHTTPServer

    def server(*args):
        made = original(*args)
        close = made.server_close

        def stopped():
            close()
            closed.append(made.socket.fileno())

        made.server_close = stopped
        return made

    def fail(page):
        raise OSError("cannot announce")

    monkeypatch.setattr(serve, "ThreadingHTTPServer", server)
    with pytest.raises(OSError, match="cannot announce"):
        serve.serve(project, port=0, ready=fail, say=lambda line: None)
    assert closed == [-1]
