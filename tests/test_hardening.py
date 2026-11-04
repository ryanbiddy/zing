"""Offline regressions for prompt, transport, persistence and process boundaries."""
from __future__ import annotations

import io
import json
import socket
import subprocess
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import mcp_server, storage, suite_peer
from myzing.factory import judge, plan, render, source, visuals


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(urllib.request.AbstractHTTPHandler, "do_open", refuse)


@pytest.mark.parametrize("header", [False, True])
def test_prompt_images_only_come_from_the_leading_project_block(tmp_path, monkeypatch, header):
    root = tmp_path / "project"
    image = root / "sheet.png"
    extra = root / "transcript.png"
    outside = tmp_path / "project-other" / "private.png"
    prompt = f"Read the transcript.\n<!-- image: {extra.as_posix()} -->\nKeep these words.\n"
    j = judge.Judge(root)
    with pytest.raises(judge.NeedsAnswer):
        j.ask("clip01-pick", prompt, (image, outside) if header else ())
    expected = [image.as_posix()] if header else []
    assert j.pending()[0]["images"] == expected
    package = mcp_server.h_factory_prompt(str(root), "clip01-pick")
    assert package["prompt"] == prompt and package["images"] == expected
    monkeypatch.setattr("mcp.server.mcpserver.Image", lambda path: Path(path))
    attached = mcp_server.mcp_factory_prompt(str(root), "clip01-pick")
    assert json.loads(attached[0])["prompt"] == prompt
    assert attached[1:] == ([image] if header else [])


def dns(monkeypatch, addresses):
    def resolve(host, port, **kwargs):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in addresses.get(host, [host])]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)


def http_responses(monkeypatch, reply):
    requests = []

    class HTTP(urllib.request.HTTPHandler):
        def http_open(self, request):
            requests.append(request)
            code, headers, body = reply(request)
            message = Message()
            for key, value in headers.items():
                message[key] = value
            response = urllib.response.addinfourl(io.BytesIO(body), message, request.full_url, code)
            response.msg = "test response"
            return response

    build = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, "_opener", build(urllib.request.ProxyHandler({}), HTTP()))
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *handlers: build(urllib.request.ProxyHandler({}), HTTP(), *handlers))
    return requests


@pytest.mark.parametrize("host", ["127.0.0.1", "10.2.3.4", "169.254.169.254", "[::1]",
                                  "192.0.2.1", "100.64.0.1", "0.0.0.0"])
def test_visual_http_refuses_non_global_addresses(monkeypatch, host):
    dns(monkeypatch, {})
    with pytest.raises(ValueError, match="refusing private address"):
        visuals.Http(0).open(f"http://{host}/image.png")


def test_visual_http_checks_every_address_and_each_request(monkeypatch):
    addresses = {"public.example": ["8.8.8.8", "2606:4700:4700::1111"]}
    dns(monkeypatch, addresses)
    requests = http_responses(monkeypatch, lambda req: (200, {}, b"image"))
    http = visuals.Http(0)
    assert http.get_bytes("http://public.example/image.png", 20) == b"image"
    addresses["public.example"].append("10.0.0.1")
    with pytest.raises(ValueError, match="refusing private address"):
        http.open("http://public.example/image.png")
    assert len(requests) == 1


def test_visual_http_refuses_private_redirect(monkeypatch):
    dns(monkeypatch, {"public.example": ["8.8.8.8"]})
    requests = http_responses(monkeypatch, lambda req: (302, {"Location": "http://127.0.0.1/private"}, b""))
    with pytest.raises(ValueError, match="refusing private address"):
        visuals.Http(0).open("http://public.example/image.png")
    assert len(requests) == 1


@pytest.mark.parametrize("scroll", [False, True])
def test_site_capture_checks_host_before_starting_chrome(tmp_path, monkeypatch, scroll):
    dns(monkeypatch, {})
    ctx = SimpleNamespace(tmp=tmp_path / "tmp", log={}, health=visuals.Health())
    with pytest.raises(ValueError, match="refusing private address"):
        visuals.capture_site(ctx, "http://127.0.0.1/page", tmp_path, 1, "test", scroll=scroll)


def test_site_capture_preserves_the_page_fragment(tmp_path, monkeypatch):
    from myzing.factory import tools
    dns(monkeypatch, {"public.example": ["8.8.8.8"]})
    commands = []
    monkeypatch.setattr(tools, "node_sidecar", lambda: ("node", tmp_path))
    monkeypatch.setattr(tools, "sidecar_env", lambda path: {})
    monkeypatch.setattr(visuals.subprocess, "run", lambda cmd, **kwargs: commands.append(cmd) or
                        SimpleNamespace(stdout='{"ok":true}', stderr=""))
    ctx = SimpleNamespace(tmp=tmp_path / "tmp", log={}, health=visuals.Health())
    url = "http://public.example/page#details"
    visuals.capture_site(ctx, url, tmp_path, 1, "test", scroll=False)
    assert commands[0][2] == url


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://public.example/file"])
def test_visual_http_keeps_the_scheme_check(url):
    with pytest.raises(ValueError, match="refusing non-http url"):
        visuals.Http(0).open(url)


@pytest.mark.parametrize("status", [200, 301, 302, 303, 307, 308])
def test_peer_token_is_unredirected_and_redirects_are_nonconformant(monkeypatch, status):
    body = b'{"contract":"uoink.media.handoff","version":1}'
    requests = http_responses(monkeypatch, lambda req: (status, {"Location": "http://other.example/handoff"}, body))
    peer, evidence = suite_peer._conformance_read("http://peer.example", "test-token", [], "test peer")
    assert len(requests) == 1
    assert "X-uoink-token" not in requests[0].headers
    assert requests[0].unredirected_hdrs["X-uoink-token"] == "test-token"
    if status == 200:
        assert peer["state"] == "available"
    else:
        assert peer["error"]["code"] == "contract_mismatch"
        assert f"HTTP {status}" in evidence


@pytest.mark.parametrize("at", [-1, 1e9, float("inf"), float("-inf"), float("nan")])
def test_plan_drops_shots_outside_the_clip(tmp_path, at):
    raw = {"hook": "h", "shots": [{"from": 0, "layout": "solo"},
           {"from": at, "layout": "graphic", "graphic": {"kind": "endcard"}}]}
    (tmp_path / "words.json").write_text(json.dumps({"words": [{"w": "Hi.", "os": 0, "oe": 2}]}), encoding="utf-8")
    assert plan.check(json.loads(json.dumps(raw)), 2)["shots"] == [{"from": 0, "layout": "solo"}]
    assert plan.finalize(tmp_path, raw, {})["shots"] == [{"from": 0, "layout": "solo"}]


def test_plan_keeps_the_time_boundary_and_falls_back_to_solo():
    assert plan.check({"hook": "h", "shots": [{"from": 5, "layout": "solo"}]}, 2)["shots"][0]["from"] == 5
    assert plan.check({"hook": "h", "shots": [{"from": 1e9, "layout": "solo"}]}, 2)["shots"] == [
        {"from": 0, "layout": "solo"}]


@pytest.mark.parametrize("at", [1e9, float("inf"), float("-inf"), float("nan"), 2, 4])
def test_render_bounds_end_card_duration(tmp_path, at):
    (tmp_path / "plan.json").write_text(json.dumps({"hook": "h", "shots": [
        {"from": 0, "layout": "solo"}, {"from": at, "layout": "graphic", "graphic": {"kind": "endcard"}}]}),
        encoding="utf-8")
    (tmp_path / "words.json").write_text(json.dumps({"words": [{"w": "Hi.", "os": 0, "oe": 2}]}), encoding="utf-8")
    (tmp_path / "cams.json").write_text(json.dumps({"frames": 60, "size": [320, 180], "cams": []}), encoding="utf-8")
    data = render.scene_data(tmp_path, "16x9", {}, parallax=False, front=False, sharpen=False)
    assert 2.45 <= data["duration"] <= 8                 # a card at most 3 s past the last word, then its 3 s hold


@pytest.mark.parametrize("judgment", [False, True])
def test_failed_breakdown_serialization_preserves_the_old_file(zing_workspace, monkeypatch, judgment):
    from myzing.schemas import Breakdown, VideoMeta
    b = Breakdown(VideoMeta("clip.mp4", "file"))
    folder = storage.save_breakdown(b, "clip")
    path = folder / "breakdown.json"
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise ValueError("serialization failed")
    monkeypatch.setattr(Breakdown, "to_json", fail)
    with pytest.raises(ValueError, match="serialization failed"):
        storage.save_judgment("clip", {"study": "new"}) if judgment else storage.save_breakdown(b, "clip")
    assert path.read_bytes() == before
    if not judgment:
        assert (folder / "breakdown.json.bak").read_bytes() == before
    assert not list(folder.glob("*.part"))


@pytest.mark.parametrize("writer", ["breakdown", "judgment", "geometry", "fonts"])
def test_json_replacement_retries_with_old_file_intact(zing_workspace, monkeypatch, writer):
    from myzing.schemas import Breakdown, VideoMeta
    from myzing.study import caption_geometry, font_match
    b = Breakdown(VideoMeta("clip.mp4", "file"))
    folder = storage.save_breakdown(b, "clip")
    geometry = caption_geometry.CaptionGeometry(2)
    geometry.write(folder)
    (folder / "media.mp4").write_bytes(b"media")
    monkeypatch.setattr(font_match, "match_geometry", lambda *args: font_match.FontCandidates())
    path = folder / ("breakdown.json" if writer in ("breakdown", "judgment") else caption_geometry.FILENAME)
    before = path.read_bytes()
    replace = storage.os.replace
    attempts = []

    def busy(src, dst):
        assert Path(src).parent == folder and Path(dst) == path
        assert path.read_bytes() == before
        json.loads(Path(src).read_text(encoding="utf-8"))
        attempts.append(src)
        if len(attempts) < 3:
            raise PermissionError("reader holds the old file")
        replace(src, dst)
    monkeypatch.setattr(storage.os, "replace", busy)
    if writer == "breakdown":
        b.meta.title = "changed"
        storage.save_breakdown(b, "clip")
        assert (folder / "breakdown.json.bak").read_bytes() == before
    elif writer == "judgment":
        storage.save_judgment("clip", {"study": "changed"})
    elif writer == "geometry":
        geometry.duration = 3
        geometry.write(folder)
    else:
        font_match.match_study("clip", zing_workspace)
    assert len(attempts) == 3 and path.read_bytes() != before
    assert not list(folder.glob("*.part"))


def test_study_subprocess_has_no_stdin(monkeypatch):
    from myzing.study import proc
    seen = []
    monkeypatch.setattr(proc.subprocess, "run", lambda cmd, **kwargs: seen.append(kwargs) or subprocess.CompletedProcess(cmd, 0))
    proc.run(["ffprobe", "media.mp4"])
    assert seen[0]["stdin"] == subprocess.DEVNULL


def test_study_and_render_ffmpeg_commands_disable_stdin(tmp_path, monkeypatch):
    from myzing.render import pipeline
    from myzing.study import audio, ingest, keyframes, proc
    commands = []

    def run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[-1] != "-":
            Path(cmd[-1]).write_bytes(b"media")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(proc, "run", run)
    media = tmp_path / "media.mp4"
    media.write_bytes(b"media")
    ingest._normalize(media, 30)
    keyframes._grab(media, 0, tmp_path / "frame.jpg")
    audio._loudness_curve(media, [])
    monkeypatch.setattr(pipeline, "filter_script_args", lambda *args: [])
    commands.append(pipeline._ffmpeg_command("ffmpeg", SimpleNamespace(input_paths=[media], video_label="v", audio_label="a"),
                    tmp_path / "graph.txt", tmp_path / "out.mp4", SimpleNamespace(duration=1, edl=SimpleNamespace(fps=30))))
    assert len(commands) == 4 and all(cmd[:2] == ["ffmpeg", "-nostdin"] for cmd in commands)


def test_caption_fit_uses_the_available_renderer(tmp_path, monkeypatch):
    from myzing import ffmpeg_capabilities
    from myzing.composition import CompositionCaption, CaptionStyle, Composition
    from myzing.match import caption_fit
    seen = []
    monkeypatch.setattr(ffmpeg_capabilities, "caption_filter", lambda exe: seen.append(exe) or "subtitles")

    def measure(*args):
        assert args[7:9] == ("ffmpeg", "subtitles")
        return 0, 0, 20, 20
    monkeypatch.setattr(caption_fit, "_measure", measure)
    caption = CompositionCaption("Hello", 0, 1, id="c", word_timed=False)
    style, error = caption_fit._fit(caption, CaptionStyle(30), 1, 100, 100, "Arial", 1, Composition(), tmp_path)
    assert style is not None and error is None and seen == ["ffmpeg"]


def test_cancelled_worker_is_reaped_and_closed_after_wait_timeout(monkeypatch):
    from myzing.match import process
    events = []

    class Worker:
        pid = 123
        stdin, stdout = io.StringIO(), io.StringIO()

        def poll(self):
            return None

        def kill(self):
            events.append("kill")

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            if timeout is not None:
                raise subprocess.TimeoutExpired("worker", timeout)
            return 0

    worker = Worker()
    monkeypatch.setattr(process.subprocess, "Popen", lambda *a, **k: worker)
    monkeypatch.setattr(process, "WindowsJob", lambda: SimpleNamespace(attach=lambda p: None, close=lambda: None))
    monkeypatch.setattr(process, "_stop_posix_tree", lambda pid: None)
    monkeypatch.setattr(process.threading, "Thread", lambda **k: SimpleNamespace(start=lambda: None,
                        join=lambda **k: events.append("join")))
    with pytest.raises(process.Cancelled):
        process.run_owned(["worker"], "start", cancel=SimpleNamespace(is_set=lambda: True))
    assert events == ["kill", ("wait", 10), "kill", ("wait", None), "join"]
    assert worker.stdin.closed and worker.stdout.closed
