"""Embargo projects, local visuals and the factory's network ledger."""
from __future__ import annotations

import hashlib
import io
import json
import socket
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from myzing import mcp_server
from myzing.factory import command, cutout, depth, judge, network, pick, pipeline, review, source, upscale, visuals
from myzing.factory.tools import FactoryError, data_path

URL = "https://user:password@example.org/demo?key=secret#private"
VIDEO = b"\0\0\0\x18ftypisom\0\0\0\0"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(visuals.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(visuals.urllib.request.OpenerDirector, "open", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])


def project(tmp_path, **settings):
    media = tmp_path / "demo.mp4"
    media.write_bytes(VIDEO)
    transcript = tmp_path / "demo.srt"
    transcript.write_text("1\n00:00:00,000 --> 00:00:30,000\nWe built a rocket.\n", encoding="utf-8")
    return Path(pipeline.init(tmp_path / "project", media, transcript=transcript, moments=1, **settings)["project"])


def rows(root):
    return [json.loads(line) for line in (root / "network.jsonl").read_text(encoding="utf-8").splitlines()]


def http(monkeypatch, body=b'{"ok": true}', redirect=False):
    calls = []

    def opener(handler, *handlers):
        def opened(req, **kwargs):
            calls.append(req)
            if redirect:
                handler.redirect_request(req, io.BytesIO(), 302, "Found", {}, "https://cdn.example.org/file?token=private")
            response = io.BytesIO(body)
            response.headers = {}
            return response
        return SimpleNamespace(open=opened)
    monkeypatch.setattr(network.urllib.request, "build_opener", opener)
    monkeypatch.setattr(visuals, "_check_host", lambda url: None)
    monkeypatch.setattr(network, "_public_address", lambda ip: True)
    return calls


@pytest.mark.parametrize("method,purpose", [("open", "visual request"), ("get_json", "visual search"),
                                           ("post_json", "visual search"), ("get_bytes", "visual download"),
                                           ("download_to", "visual download")])
def test_http_paths_record_hosts_and_bytes(tmp_path, monkeypatch, method, purpose):
    root = project(tmp_path)
    calls = http(monkeypatch)
    client = visuals.Http(0, project=root)
    args = {"get_json": (), "post_json": ({"query": "private prompt"},), "get_bytes": (100,),
            "download_to": (root / "download", 100)}
    if method == "open":
        with client.open(URL, {"Authorization": "private header"}) as response:
            response.read()
    else:
        getattr(client, method)(URL, *args[method])
    row, = rows(root)
    assert set(row) == {"at", "host", "purpose", "bytes"}
    assert row["host"] == "example.org" and row["purpose"] == purpose and row["bytes"] == 12
    assert len(calls) == 1
    text = (root / "network.jsonl").read_text()
    assert all(secret not in text for secret in ("secret", "password", "private", "https://", "Authorization"))


def test_redirects_and_failed_requests_are_recorded(tmp_path, monkeypatch):
    root = project(tmp_path)
    http(monkeypatch, redirect=True)
    client = visuals.Http(0, project=root)
    client.get_json(URL)
    assert [(r["host"], r["bytes"]) for r in rows(root)] == [("example.org", 0), ("cdn.example.org", 12)]

    def fail(*args, **kwargs):
        raise OSError("connection failed")
    monkeypatch.setattr(network.urllib.request, "build_opener", lambda *handlers: SimpleNamespace(open=fail))
    with pytest.raises(OSError):
        client.get_json(URL)
    assert rows(root)[-1]["host"] == "example.org" and rows(root)[-1]["bytes"] == 0


def test_requests_are_recorded_before_connecting_and_close_independently(tmp_path, monkeypatch):
    root = project(tmp_path)
    http(monkeypatch, b"hello")
    client = visuals.Http(0, project=root)
    first = client.open(URL)
    second = client.open("https://cdn.example.org/image")
    assert [r["bytes"] for r in rows(root)] == [None, None]
    second.read(2)
    second.close()
    first.read()
    first.close()
    assert [r["bytes"] for r in rows(root)] == [5, 2]
    (root / "network.jsonl").unlink()
    (root / "network.jsonl").mkdir()
    called = http(monkeypatch)
    with pytest.raises(OSError):
        client.open(URL)
    assert called == []


@pytest.mark.parametrize("entry", ["open", "get_json", "post_json", "get_bytes", "download_to", "og", "capture",
                                   "probe", "short_video", "excerpt", "candidate", "depth", "cutout", "upscale", "claude"])
def test_every_network_entry_refuses_offline_before_connecting(tmp_path, entry):
    root = project(tmp_path, offline=True)
    ctx = visuals.Ctx(root / "clip01" / "visuals")
    client = ctx.http
    candidate = {"source": "commons", "media_type": "video", "file_url": URL, "width": 1920, "height": 1080}
    calls = {
        "open": lambda: client.open(URL), "get_json": lambda: client.get_json(URL),
        "post_json": lambda: client.post_json(URL, {}), "get_bytes": lambda: client.get_bytes(URL, 100),
        "download_to": lambda: client.download_to(URL, root / "out", 100),
        "og": lambda: visuals._og_from_html(client, URL),
        "capture": lambda: visuals.capture_site(ctx, URL, root, 1, "request"),
        "probe": lambda: visuals.probe_video(URL, project=root),
        "short_video": lambda: visuals.fetch_video(ctx, {**candidate, "duration": 5}, URL, root),
        "excerpt": lambda: visuals.fetch_video(ctx, {**candidate, "duration": 100}, URL, root),
        "candidate": lambda: visuals.fetch_candidate(ctx, candidate, root, []),
        "depth": lambda: depth.fetch(consent=True, project=root),
        "cutout": lambda: cutout.fetch(consent=True, project=root),
        "upscale": lambda: upscale.fetch(consent=True, project=root),
        "claude": lambda: judge.Judge(root)._claude("scout", "secret", False),
    }
    with pytest.raises(FactoryError, match="^offline project:"):
        calls[entry]()
    assert rows(root) == []


def test_project_context_is_scoped_and_claude_is_refused(tmp_path, monkeypatch):
    root = project(tmp_path, offline=True)
    with pytest.raises(FactoryError, match="offline project:.*Claude"):
        judge.Judge(root, "claude")
    with network.scope(root):
        with pytest.raises(FactoryError, match="offline project:"):
            visuals.Http(0).open(URL)
        with pytest.raises(FactoryError, match="offline project:"):
            depth.fetch(consent=True)
    monkeypatch.chdir(root)                       # outside a run, the working folder doesn't make a project
    assert not network.Network().offline and network.Network().record("example.com", "test") is None
    assert (root / "network.jsonl").read_text(encoding="utf-8") == ""


def test_remote_video_paths_and_local_probes(tmp_path, monkeypatch):
    root = project(tmp_path)
    http(monkeypatch, VIDEO)
    monkeypatch.setattr(visuals, "_max_redirects", lambda: True)   # this test covers the FFmpeg path
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "-show_entries" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"streams": [{"width": 1920, "height": 1080}],
                                                                     "format": {"duration": "5"}}), "")
        Path(argv[-1]).write_bytes(VIDEO)
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    monkeypatch.setattr(visuals.subprocess, "run", run)
    ctx = visuals.Ctx(root / "visuals")
    visuals.fetch_video(ctx, {"source": "commons"}, URL, root)
    # the redirect check before FFmpeg is a request of its own, so the ledger records it too
    assert [(r["purpose"], r["bytes"]) for r in rows(root)] == [("video redirect", 0), ("video probe", None),
                                                               ("visual download", len(VIDEO))]
    visuals.fetch_video(ctx, {"source": "commons", "width": 1920, "height": 1080, "duration": 100}, URL, root)
    assert rows(root)[-1]["purpose"] == "video excerpt" and rows(root)[-1]["bytes"] is None
    assert [r["purpose"] for r in rows(root)[3:]] == ["video redirect", "video excerpt"]   # known size: no probe
    assert len(calls) == 4


def test_ffmpeg_range_requests_and_redirect_hosts_are_recorded(tmp_path, monkeypatch):
    root = project(tmp_path)
    http(monkeypatch)
    log = "[https @ 123] request: GET /demo?key=secret HTTP/1.1\r\nHost: example.org\r\n\r\n"
    log += "[https @ 456] request: GET /file?token=secret HTTP/1.1\r\nHost: cdn.example.org:443\r\n\r\n" * 2
    monkeypatch.setattr(network.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stderr=log))
    network.Network(root).run_video(URL, "video excerpt", ["ffmpeg"], validate=lambda url: None)
    assert [r["host"] for r in rows(root)] == ["example.org", "cdn.example.org", "cdn.example.org"]
    assert "secret" not in (root / "network.jsonl").read_text()


def test_capture_and_og_paths_are_logged(tmp_path, monkeypatch):
    from myzing.factory import tools
    root = project(tmp_path)
    http(monkeypatch, b'<meta property="og:image" content="picture.jpg">')
    monkeypatch.setattr(tools, "node_sidecar", lambda: ("node", root))
    monkeypatch.setattr(tools, "sidecar_env", lambda tmp: {})
    event = json.dumps({"network": {"at": "2026-11-04T00:00:00Z", "host": "cdn.example.org"}})
    monkeypatch.setattr(visuals.subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(
        argv, 0, event + '\n{"ok": false}', ""))
    ctx = visuals.Ctx(root / "visuals")
    got = visuals.capture_site(ctx, URL, root, 1, "request", scroll=False)
    assert got[0]["source"] == "ogimage"
    assert {(r["host"], r["purpose"]) for r in rows(root)} == {
        ("example.org", "site capture"), ("cdn.example.org", "site resource"), ("example.org", "visual download")}


@pytest.mark.parametrize("module", [depth, cutout, upscale])
def test_model_fetches_use_the_ledger(tmp_path, monkeypatch, module, zing_workspace):
    root = project(tmp_path)
    if module is upscale:
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as archive:
            for name in upscale.members():
                archive.writestr(name, name.encode())
        body = blob.getvalue()
        monkeypatch.setitem(upscale.BUILDS, upscale.build(), (hashlib.sha256(body).hexdigest(), len(body)))
    else:
        body = b"fake weights"
        monkeypatch.setattr(module, "SIZE", len(body))
        monkeypatch.setattr(module, "SHA256", hashlib.sha256(body).hexdigest())
    http(monkeypatch, body, redirect=True)
    assert module.fetch(consent=True, project=root).is_file()
    assert rows(root)[-1]["bytes"] == len(body)
    assert all(r["purpose"] == module.__name__.split(".")[-1] + " model download" for r in rows(root))
    count = len(rows(root))
    module.fetch(consent=True, project=root)
    assert len(rows(root)) == count


def test_claude_retries_are_logged_without_prompts(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setattr(judge.shutil, "which", lambda name: "claude")
    calls = []

    def run(argv, **kwargs):
        calls.append(1)
        return subprocess.CompletedProcess(argv, 1 if len(calls) == 1 else 0, '{"result": "{}"}', "")
    monkeypatch.setattr(judge.subprocess, "run", run)
    ask = judge.Judge(root, "claude", retry_wait=0)
    assert ask.ask("scout", "SECRET PROMPT") == {}
    ask.ask("scout", "cached")
    assert [(r["host"], r["purpose"], r["bytes"]) for r in rows(root)] == [(network.CLAUDE, "scout", None)] * 2
    assert "SECRET" not in (root / "network.jsonl").read_text()


@pytest.mark.parametrize("offline", [False, True])
def test_local_candidates_are_picked_and_credited(tmp_path, monkeypatch, offline):
    folder = tmp_path / "own"
    folder.mkdir()
    Image.new("RGB", (200, 100), "red").save(folder / "rocket.png")
    Image.new("RGB", (400, 200), "blue").save(folder / "other.jpeg")
    (folder / "notes.txt").write_text("not a visual")
    root = project(tmp_path, offline=offline, visuals=folder)
    searched = []
    monkeypatch.setattr(visuals, "gather", lambda ctx, q, route: searched.extend(route) or [])
    reqs = [{"id": "v1", "query": "rocket", "kind": "photo"}]
    out = root / "clip01" / "visuals"
    found = visuals.find(reqs, out, visuals=folder, say=lambda m: None)
    first = found["v1"][0]
    assert first["title"] == "rocket.png" and (first["width"], first["height"]) == (200, 100)
    assert first["bytes"] == (folder / "rocket.png").stat().st_size
    assert (out / "contact_sheet.jpg").is_file() and pick.sheet(out, reqs, found).is_file()
    assert pick.chosen(out, reqs, found, {"v1": {"pick": 0}})["v1"]["credit"] == "Your file: rocket.png"
    assert bool(searched) is not offline and rows(root) == []
    visuals.find(reqs, out, visuals=folder, say=lambda m: None)
    assert (folder / "rocket.png").is_file() and (folder / "other.jpeg").is_file()
    if not offline:
        with pytest.raises(judge.NeedsAnswer):
            judge.Judge(root, "claude").ask("clip01-pick", "pick a file", images=(out / "pick_sheet.jpg",))
        assert rows(root) == []


@pytest.mark.parametrize("extension", ["mp4", "mov", "webm"])
def test_local_videos_have_metadata_and_thumbnails(tmp_path, monkeypatch, extension):
    folder = tmp_path / "own"
    folder.mkdir()
    (folder / f"rocket.{extension}").write_bytes(VIDEO)
    root = project(tmp_path, offline=True, visuals=folder)

    def run(argv, **kwargs):
        if "-show_entries" in argv:
            assert "file,pipe" in argv
            return subprocess.CompletedProcess(argv, 0, '{"streams":[{"width":800,"height":450}],"format":{"duration":"5"}}', "")
        if argv[-1] == "-":
            data = io.BytesIO()
            Image.new("RGB", (80, 45)).save(data, format="PNG")
            return subprocess.CompletedProcess(argv, 0, data.getvalue(), b"")
        Image.new("RGB", (80, 45)).save(argv[-1])
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(visuals.subprocess, "run", run)
    monkeypatch.setattr(pick, "ffmpeg", lambda: "ffmpeg")
    out = root / "clip01" / "visuals"
    reqs = [{"id": "v1", "query": "rocket", "kind": "video"}]
    found = visuals.find(reqs, out, visuals=folder, say=lambda m: None)
    c, = found["v1"]
    assert (c["media_type"], c["duration_s"], c["width"], c["height"]) == ("video", 5, 800, 450)
    assert c["credit_text"] == f"Your file: rocket.{extension}"
    assert pick.sheet(out, reqs, found).is_file() and (out / c["path"]).with_suffix(".pick.jpg").is_file()
    assert rows(root) == []


@pytest.mark.parametrize("mode", ["context", "fun", "documentary"])
def test_offline_without_local_files_never_searches_even_for_urls(tmp_path, mode):
    root = project(tmp_path, offline=True)
    reqs = [{"id": kind, "query": "NASA rocket", "kind": kind, "url": URL} for kind in visuals.KINDS]
    manifest = visuals.find(reqs, root / "clip01" / "visuals", mode, say=lambda m: None)
    assert manifest == {kind: [] for kind in visuals.KINDS} and rows(root) == []


def test_offline_pipeline_finishes_with_an_empty_ledger(tmp_path, monkeypatch):
    folder = tmp_path / "own"
    folder.mkdir()
    Image.new("RGB", (200, 100)).save(folder / "rocket.png")
    root = project(tmp_path, offline=True, visuals=folder, mode="launch", shapes=["16x9"])
    ask = judge.Judge(root)

    def cut(d, media, words, start, end):
        pipeline._write(d / "cams.json", {})
        pipeline._write(d / "words.json", {"words": [{"w": "Rocket.", "os": 0, "oe": 4}], "duration": 4, "start": start})

    def render(d, shape, pack):
        (d / f"clip{pipeline.render.suffix(shape, pack)}.mp4").write_bytes(VIDEO)

    monkeypatch.setattr(pipeline.cut, "cut", cut)
    monkeypatch.setattr(pipeline.render, "render", render)
    assert pipeline.run(root, ask, say=lambda m: None)["state"] == "waiting"
    pipeline.answer(root, "scout", {"moments": [{"start": 1, "end": 8, "hook": "Rocket"}]})
    pipeline.run(root, ask, say=lambda m: None)
    pipeline.answer(root, "clip01-copy", {k: "Rocket." for k in pipeline.postcopy.FIELDS})
    pipeline.answer(root, "clip01-plan", {"hook": "Rocket", "shots": [{"from": 0, "layout": "split", "visual": "v1"}],
                                         "visual_requests": [{"id": "v1", "query": "rocket", "kind": "screenshot", "url": URL}]})
    assert pipeline.run(root, ask, say=lambda m: None)["pending"][0]["task"] == "clip01-pick"
    pipeline.answer(root, "clip01-pick", {"v1": {"pick": 1, "why": "Your demo"}})
    result = pipeline.run(root, ask, say=lambda m: None)
    if any(p["task"] == "clip01-context" for p in result["pending"]):    # the context check asks once the plan is final
        pipeline.answer(root, "clip01-context", {"flags": []})
        result = pipeline.run(root, ask, say=lambda m: None)
    assert result["state"] == "done" and result["failed"] == {} and result["clips"][0]["renders"]
    assert result["network"]["summary"] == "offline: nothing fetched" and rows(root) == []
    assert "Your file: rocket.png" in (root / "clip01" / "plan.json").read_text()
    assert "offline: nothing fetched" in Path(result["review"]).read_text(encoding="utf-8")


def test_status_counts_hosts_and_purposes_and_never_hides_history(tmp_path):
    root = project(tmp_path, offline=True)
    net = network.Network(root)
    net.record("example.org", "visual download", 12)
    net.record("example.org", "visual search", 20)
    net.record(network.CLAUDE, "scout")
    status = pipeline.status(root)["network"]
    assert status["requests"] == 3 and status["hosts"] == {"example.org": 2, network.CLAUDE: 1}
    assert status["purposes"] == {"visual download": 1, "visual search": 1, "scout": 1}
    assert "nothing fetched" not in status["summary"]
    net.record("</script><script>alert(1)</script>", "visual search")
    page = review.build(root).read_text(encoding="utf-8")
    assert "getElementById('network').textContent" in page and "</script><script>" not in page
    assert '$("#network").textContent = p.network' in data_path("dashboard.html").read_text(encoding="utf-8")


def test_cli_and_mcp_save_offline_and_visuals(tmp_path, capsys):
    media = tmp_path / "demo.mp4"
    media.write_bytes(VIDEO)
    folder = tmp_path / "own"
    folder.mkdir()
    root = tmp_path / "cli"
    assert command.run(["new", str(root), "--media", str(media), "--offline", "--visuals", str(folder)]) == 0
    assert json.loads(capsys.readouterr().out)["settings"]["offline"] is True
    assert command.run(["run", str(root), "--judge", "claude"]) == 2
    assert "offline project:" in capsys.readouterr().err
    assert command.run(["fetch-depth", "--project", str(root), "--yes"]) == 2
    assert "offline project:" in capsys.readouterr().err
    result = mcp_server.h_factory_new(str(tmp_path / "mcp"), str(media), offline=True, visuals=str(folder))
    assert result["ok"] and result["settings"]["offline"] and result["settings"]["visuals"] == str(folder.resolve())
    assert not mcp_server.h_factory_new(str(root), str(media), visuals=str(folder / "missing"))["ok"]
