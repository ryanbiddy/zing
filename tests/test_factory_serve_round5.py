"""Factory review regressions, without external requests or downloads."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.factory import edit, network, pipeline, render, serve, tools, visuals
from test_factory_review_fixes import javascript
from test_factory_security_2 import http


@pytest.fixture
def project(tmp_path, zing_workspace):
    pipeline._write(tmp_path / "factory.json", {"pack": "zing"})
    pipeline._write(tmp_path / "moments.json", {"moments": [
        {"start": 0, "end": 10, "hook": "One"}, {"start": 10, "end": 20, "hook": "Two"}]})
    for name in ("clip01", "clip02"):
        (tmp_path / name).mkdir()
    return tmp_path


@pytest.fixture
def studio(project, monkeypatch):
    monkeypatch.setattr(serve.Studio, "_work", lambda self: None)
    return serve.Studio(project)


def request(studio, method="GET", path="/api/project", headers=None, body=b""):
    cls = serve.handler(studio, 8765, "test")
    req = cls.__new__(cls)
    req.command, req.path = method, path
    req.headers = {"Host": "127.0.0.1:8765", "Cookie": "zing_dash_8765=test", **(headers or {})}
    req.rfile, req.wfile = io.BytesIO(body), io.BytesIO()
    req.send_response = lambda code: setattr(req, "code", code)
    req.sent = {}
    req.send_header = lambda key, value: req.sent.update({key: value})
    req.end_headers = lambda: None
    return req


@pytest.mark.parametrize("host", ["api.pexels.com", "api.exa.ai"])
@pytest.mark.parametrize("same", [False, True])
def test_redirect_drops_secrets_only_for_another_host(host, same):
    req = urllib.request.Request(f"https://{host}/start", headers={
        "aUtHoRiZaTiOn": "secret", "COOKIE": "session", "Proxy-Authorization": "proxy",
        "X-API-KEY": "key", "Accept": "application/json"})
    net = network.Network()
    with net.request(req.full_url, "test") as row:
        dest = f"https://{host.upper() if same else 'cdn.example'}/end"
        redirect = network._Redirect(net, row, None).redirect_request(req, io.BytesIO(), 302, "Found", {}, dest)
    headers = {k.lower(): v for k, v in redirect.header_items()}
    assert headers == ({k.lower(): v for k, v in req.header_items()} if same else {"accept": "application/json"})


@pytest.mark.parametrize("fragment", ["", "#details"])
def test_capture_uses_the_checked_url(project, monkeypatch, fragment):
    checked, captured = [], []
    monkeypatch.setattr(visuals, "_check_host", checked.append)
    monkeypatch.setattr(visuals, "_capture_site", lambda ctx, url, *a: captured.append(url))
    visuals.capture_site(SimpleNamespace(network=network.Network(project)), "http://nasa.gov/a b" + fragment, project, 1, "test")
    assert checked == captured == ["https://nasa.gov/a%20b" + fragment]


@pytest.mark.parametrize("failure", ["timeout", "exit", "missing", "unsupported"])
def test_redirect_probe_retries_failures(monkeypatch, failure):
    calls = []

    class Process:
        returncode = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def communicate(self, timeout=None):
            if len(calls) == 1:
                if failure == "timeout" and timeout:
                    raise subprocess.TimeoutExpired("ffmpeg", timeout)
                self.returncode = 1 if failure == "exit" else 0
                return b"options" if failure == "unsupported" else b"max_redirects", None
            return b"max_redirects", None

        def kill(self):
            pass

    def popen(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1 and failure == "missing":
            raise OSError("missing")
        return Process()

    visuals._max_redirects.cache_clear()
    monkeypatch.setattr(visuals.subprocess, "Popen", popen)
    try:
        assert visuals._max_redirects() is False
        assert visuals._max_redirects() is True
        assert visuals._max_redirects() is True
        assert len(calls) == 2
    finally:
        visuals._max_redirects.cache_clear()


@pytest.mark.parametrize("entry", ["probe", "fetch"])
def test_unsupported_redirect_limit_downloads_before_local_probe(project, monkeypatch, entry):
    calls, downloads = [], []
    video = b"\0\0\0\x18ftypisom\0\0\0\0"
    url = "https://public.example/video.mp4"
    monkeypatch.setattr(visuals, "_max_redirects", lambda: False)
    monkeypatch.setattr(visuals, "_video_url", lambda url, net: url)
    monkeypatch.setattr(visuals, "_check_host", lambda url: None)

    def download(self, src, path, cap, **kwargs):
        downloads.append((src, cap))
        path.write_bytes(video)
        return len(video)

    def run(argv, **kwargs):
        calls.append(argv)
        if "-show_entries" in argv:
            assert downloads and Path(argv[-1]).read_bytes() == video
            return subprocess.CompletedProcess(argv, 0, json.dumps({"streams": [{"width": 1920, "height": 1080}],
                                                                     "format": {"duration": "100"}}), "")
        Path(argv[-1]).write_bytes(video)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(visuals.Http, "download_to", download)
    monkeypatch.setattr(visuals.subprocess, "run", run)
    if entry == "probe":
        assert visuals.probe_video(url, project=project)["width"] == 1920
    else:
        c = {"source": "ogvideo"}
        ctx = SimpleNamespace(network=network.Network(project), http=visuals.Http(project=project), min_video=900)
        visuals.fetch_video(ctx, c, url, project)
        assert c["path"].read_bytes() == video and "excerpt" in c["notes"]
    assert downloads == [(url, visuals.VID_CAP)]
    assert all(url not in argv and "https,http,tls,tcp" not in argv for argv in calls)
    assert not list(project.rglob("*.part"))


@pytest.mark.parametrize("entry", ["probe", "fetch"])
def test_download_rechecks_a_get_only_private_redirect(project, monkeypatch, entry):
    requests = http(monkeypatch, lambda req: (200, {}) if req.get_method() == "HEAD" else
                    (302, {"Location": "http://169.254.169.254/private"}))
    monkeypatch.setattr(visuals, "_max_redirects", lambda: False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("FFmpeg must not fetch the redirect"))
    url = "http://public.example/video.mp4"
    with pytest.raises(ValueError, match="private address"):
        if entry == "probe":
            visuals.probe_video(url, project=project)
        else:
            ctx = SimpleNamespace(network=network.Network(project), http=visuals.Http(0, project), min_video=900)
            visuals.fetch_video(ctx, {"source": "ogvideo"}, url, project)
    assert [r.get_method() for r in requests] == ["HEAD", "GET"]
    assert not list(project.rglob("*.part"))


@pytest.mark.parametrize("entry", ["probe", "fetch"])
def test_failed_download_removes_partial_video(project, monkeypatch, entry):
    monkeypatch.setattr(visuals, "_max_redirects", lambda: False)
    monkeypatch.setattr(visuals, "_video_url", lambda url, net: url)

    def download(self, src, path, cap):
        path.write_bytes(b"partial")
        raise visuals.TooLarge("too large")

    monkeypatch.setattr(visuals.Http, "download_to", download)
    with pytest.raises(visuals.TooLarge):
        if entry == "probe":
            visuals.probe_video("https://public.example/video", project=project)
        else:
            ctx = SimpleNamespace(network=network.Network(project), http=visuals.Http(0, project), min_video=900)
            visuals.fetch_video(ctx, {"source": "ogvideo"}, "https://public.example/video", project)
    assert not list(project.rglob("*.part*"))


@pytest.mark.parametrize("value", ["url(file:///C:/private.png)", "URL('https://example/a')",
    r"u\72l(file:///private.png)", "u/**/rl(file:///private.png)",
    'image-set("file:///private.png" 1x)', '-webkit-image-set("file:///private.png" 1x)'])
@pytest.mark.parametrize("field", ["cap_bg", "grade", "panel"])
def test_pack_css_rejects_resource_references(value, field):
    pack = {field: {"bg": value} if field == "panel" else value}
    assert render.check_pack(pack)


def test_pack_css_keeps_gradients_and_filters():
    assert render.check_pack({"cap_bg": "linear-gradient(90deg, #000, rgba(255,255,255,.5))",
                              "grade": "contrast(1.1) saturate(.8)", "cap_shadow": "0 2px 4px #000"}) == []


@pytest.mark.parametrize("range_header", [None, "bytes=0-20971519", "bytes=100-", "bytes=-100"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_media_reads_bounded_chunks(studio, monkeypatch, range_header, method):
    reads, writes = [], []
    size = 20 << 20

    class File(io.BytesIO):
        def read(self, n=-1):
            reads.append(n)
            assert 0 <= n <= 8 << 20
            n = min(n, size - self.tell())
            self.seek(self.tell() + n)
            return b"x" * n

    target = SimpleNamespace(name="clip.mp4", stat=lambda: SimpleNamespace(st_size=size), open=lambda mode: File())
    req = request(studio, method, headers={"Range": range_header} if range_header else {})
    req.wfile = SimpleNamespace(write=lambda data: writes.append(len(data)))
    req._file(target)
    length = size if not range_header or range_header.startswith("bytes=0-") else (8 << 20 if range_header == "bytes=100-" else 100)
    assert int(req.sent["Content-Length"]) == length
    assert req.code == (206 if range_header else 200)
    assert sum(writes) == (length if method == "GET" else 0)
    if method == "HEAD":
        assert reads == []


@pytest.mark.parametrize("error", [ValueError("torn JSON"), OSError("file busy")])
def test_get_returns_json_for_unreadable_state(studio, monkeypatch, error):
    def fail():
        raise error
    monkeypatch.setattr(studio, "state", fail)
    req = request(studio)
    req.do_GET()
    assert req.code == 500 and json.loads(req.wfile.getvalue())["error"] == str(error)


def test_state_holds_the_queue_mutex(studio):
    class Jobs(list):
        def __iter__(self):
            assert studio.jobs.mutex.locked()
            return super().__iter__()
    studio.jobs.queue = Jobs([("queued", lambda: None)])
    assert studio.state()["jobs"] == ["queued"]


@pytest.mark.parametrize("action", ["copy", "rate"])
@pytest.mark.parametrize("shared", [False, True])
def test_concurrent_saves_keep_both_changes(studio, monkeypatch, action, shared):
    other = serve.Studio(studio.project) if shared else studio
    first, second = threading.Event(), threading.Event()
    module, filename = (edit, "post.json") if action == "copy" else (pipeline, "ratings.json")
    read = module._read

    def paused(path, *args):
        result = read(path, *args)
        if path.name == filename:
            if not first.is_set():
                first.set()
                second.wait(.2)
            else:
                second.set()
        return result

    monkeypatch.setattr(module, "_read", paused)
    with ThreadPoolExecutor(2) as pool:
        if action == "copy":
            a = pool.submit(studio.text, {"clip": "clip01", "field": "x", "text": "One"})
            assert first.wait(2)
            b = pool.submit(other.text, {"clip": "clip01", "field": "instagram", "text": "Two"})
            a.result(), b.result()
            assert read(studio.project / "clip01" / filename) == {"x": "One", "instagram": "Two"}
        else:
            a = pool.submit(studio.rate, {"clip": "clip01", "v": "post"})
            assert first.wait(2)
            b = pool.submit(other.rate, {"clip": "clip02", "v": "no"})
            a.result(), b.result()
            assert set(read(studio.project / filename)) == {"clip01", "clip02"}


@pytest.mark.parametrize("failure", ["read", "write"])
def test_worker_survives_error_reporting_failure(project, monkeypatch, failure):
    studio = serve.Studio(project)
    done = threading.Event()
    if failure == "read":
        (project / "status.json").write_text("{", encoding="utf-8")
    else:
        monkeypatch.setattr(serve, "_write", lambda *a: (_ for _ in ()).throw(OSError("full disk")))
    studio.queue("broken", lambda: (_ for _ in ()).throw(ValueError("bad render")))
    studio.queue("next", done.set)
    try:
        assert done.wait(2)
    finally:
        if hasattr(studio, "close"):
            studio.close()


@pytest.mark.parametrize("streaming", [False, True])
def test_shutdown_stops_the_active_render(project, monkeypatch, streaming):
    started, closed = threading.Event(), threading.Event()
    children = []
    popen = subprocess.Popen

    def launch(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        started.set()
        return child

    monkeypatch.setattr(subprocess, "Popen", launch)
    studio = serve.Studio(project)

    def job():
        argv = [sys.executable, "-c", "import time; time.sleep(30)"]
        if streaming:
            with tools.process(argv) as child:
                child.wait()
        else:
            tools.run(*argv)

    studio.queue("render", job)
    try:
        assert started.wait(3)
        assert not studio.worker.daemon
        closer = threading.Thread(target=lambda: (studio.close(), closed.set()), daemon=True)
        closer.start()
        assert closed.wait(3)
        assert all(child.poll() is not None for child in children)
        with pytest.raises(tools.FactoryError, match="stopping"):
            studio.queue("later", lambda: None)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
        studio.close()


def test_server_shutdown_closes_the_worker(project, monkeypatch):
    closed = []
    close = serve.Studio.close

    def stopped(self):
        closed.append("worker")
        close(self)

    server = SimpleNamespace(server_port=8765, server_close=lambda: closed.append("server"),
                             serve_forever=lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(serve, "ThreadingHTTPServer", lambda *a: server)
    monkeypatch.setattr(serve.Studio, "close", stopped)
    serve.serve(project, say=lambda line: None)
    assert closed == ["server", "worker"]


@pytest.mark.parametrize("length,body,kind,status,consumed", [
    (3, b"abc", "text/plain", 415, 3), (-1, b"", "application/json", 200, 0),
    ((64 << 10) + 1, b"x" * ((64 << 10) + 1), "application/json", 413, 0)], ids=["415", "negative", "413"])
def test_post_body_is_drained_or_rejected(studio, monkeypatch, length, body, kind, status, consumed):
    monkeypatch.setattr(studio, "run", lambda body: {})
    req = request(studio, "POST", "/api/run", {"Content-Type": kind, "Content-Length": str(length)}, body)
    req.do_POST()
    assert req.code == status and req.rfile.tell() == consumed
    if status == 413:
        assert req.close_connection


@pytest.mark.parametrize("revision", ["B", "old", "A"])
def test_save_keeps_a_newer_draft(revision):
    got = javascript("dashboard.html", """
      let finish, posted;
      api.text = () => new Promise(resolve => { finish = resolve; });
      act = (button, call) => posted = call();
      const block = textField({clip: 'clip01'}, {id: 'x', label: 'X', limit: 280}, 'old');
      const area = all(block).find(n => n.tagName === 'textarea');
      const save = all(block).find(n => n.tagName === 'button');
      area.value = 'A'; area.events.input(); save.events.click({currentTarget: save});
      area.value = 'B'; area.events.input(); area.value = REVISION; area.events.input(); finish(); await posted;
      console.log(JSON.stringify(ui.drafts['clip01:x'] || null));
    """.replace("REVISION", json.dumps(revision)))
    assert got == revision


def test_selected_shape_falls_back_to_the_same_shape():
    got = javascript("dashboard.html", """
      ui.project = {settings: {pack: 'zing'}}; ui.pack.clip01 = 'swiss'; ui.shape.clip01 = '4x5';
      const c = {clip: 'clip01', videos: {'clip.mp4': '', 'clip-4x5.mp4': ''}};
      console.log(JSON.stringify(all(clipCard(c)).find(n => n.tagName === 'video').attrs.src));
    """)
    assert got == "/media/clip01/clip-4x5.mp4"


def test_save_clears_only_the_submitted_draft():
    got = javascript("dashboard.html", """
      api.text = async () => {}; let posted;
      act = (button, call) => posted = call();
      const block = textField({clip: 'clip01'}, {id: 'x', label: 'X', limit: 280}, 'old');
      const area = all(block).find(n => n.tagName === 'textarea');
      const save = all(block).find(n => n.tagName === 'button');
      area.value = 'A'; area.events.input(); area.value = 'old'; area.events.input();
      const reverted = Object.hasOwn(ui.drafts, 'clip01:x');
      area.value = 'A'; area.events.input(); save.events.click({currentTarget: save}); await posted;
      console.log(JSON.stringify([reverted, Object.hasOwn(ui.drafts, 'clip01:x'), Object.hasOwn(ui.saving, 'clip01:x')]));
    """)
    assert got == [False, False, False]


def test_poll_keeps_unchanged_players_and_editors():
    got = javascript("dashboard.html", """
      Element.prototype.insertBefore = function(n, old) { this.children.splice(old ? this.children.indexOf(old) : this.children.length, 0, n); };
      Element.prototype.replaceChild = function(n, old) { this.children[this.children.indexOf(old)] = n; };
      ui.project = {state: 'running', jobs: ['clip02'], settings: {pack: 'zing'}, clips: [
        {clip: 'clip01', videos: {'clip.mp4': ''}, post: {x: 'old'}}, {clip: 'clip02', videos: {}}]};
      render();
      const video = all(nodes['#grid']).find(n => n.tagName === 'video');
      const area = all(nodes['#detail']).find(n => n.tagName === 'textarea');
      video.currentTime = 4; video.paused = false; area.value = 'typing'; area.events.input();
      document.activeElement = area;
      ui.project = JSON.parse(JSON.stringify(ui.project)); ui.project.clips[1].plan = {hook: 'Ready'};
      render();
      console.log(JSON.stringify({video: all(nodes['#grid']).includes(video), area: all(nodes['#detail']).includes(area),
        time: video.currentTime, paused: video.paused, focused: document.activeElement === area,
        changed: all(nodes['#grid']).some(n => n.textContent === 'Rendering')}));
    """)
    assert got == {"video": True, "area": True, "time": 4, "paused": False, "focused": True, "changed": True}
