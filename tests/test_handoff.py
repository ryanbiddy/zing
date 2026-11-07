"""Uoink hand-offs and capture use synthetic media and fake peers."""
from __future__ import annotations

import hashlib
import io
import json
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import FakeHTTPResponse
from myzing import cli, handoff, mcp_server, storage, suite_peer, uoink_bridge, urls
from myzing.factory import judge, pipeline, serve
from test_mcp_handlers import fake_engine, live_job, wait_done
from test_suite_peer import make_manifest

REF = "uoink://item/short-123"
URL = "https://example.test/watch/123"
TOKEN = "synthetic-suite-credential"
OPEN_NO_REDIRECT = urls.open_no_redirect


def refuse(*args, **kwargs):
    pytest.fail("unmocked external operation")


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace, isolated_uoink_transport):
    monkeypatch.setenv("UOINK_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(urls, "open_no_redirect", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(uoink_bridge, "resolve_kept_media", refuse)
    monkeypatch.setattr(uoink_bridge, "item_metadata", refuse)
    monkeypatch.setattr(handoff.webbrowser, "open", refuse)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    path = tmp_path / "kept" / "media.mp4"
    path.parent.mkdir()
    path.write_bytes(b"synthetic episode")
    data = {"item_ref": REF, "state": "available", "source_url": URL,
            "media": {"path": str(path), "media_type": "video/mp4", "byte_length": path.stat().st_size,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
            "provenance": {"kind": "uoink_sidecar", "sidecar_schema_version": 2, "field": "media_file"}}
    item = {"ok": True, "title": "An episode / about rockets", "source_url": URL}
    calls = []

    def resolve(ref):
        calls.append(("media", ref))
        return {"ok": True, "data": data}

    def metadata(ref):
        calls.append(("metadata", ref))
        return item

    monkeypatch.setattr(uoink_bridge, "resolve_kept_media", resolve)
    monkeypatch.setattr(uoink_bridge, "item_metadata", metadata)
    return SimpleNamespace(path=path, data=data, item=item, calls=calls)


@pytest.fixture
def dashboard(monkeypatch):
    original = serve.serve
    calls = []

    def short(project, **kwargs):
        calls.append({"project": project, **kwargs})
        return original(project, **{**kwargs, "idle_seconds": .02})

    monkeypatch.setattr(serve, "serve", short)
    return calls


def output(capsys):
    captured = capsys.readouterr()
    assert not captured.err
    lines = captured.out.splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_probe_is_one_exact_object_without_network(monkeypatch, capsys):
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
    monkeypatch.setattr(suite_peer, "resolve_uoink_base", refuse)
    assert cli.main(["handoff", "--probe", "--json"]) == 0
    assert output(capsys) == {"ok": True, "contract": "ryan.suite.handoff", "version": 1, "service": "zing",
                              "service_version": cli._version(), "accepts": ["uoink.item/1"],
                              "needs": ["uoink.media.handoff/1"]}


def test_handoff_creates_project_prints_page_and_exits_when_idle(kept, dashboard, zing_workspace, capsys, monkeypatch):
    initialized = []
    init = pipeline.init

    def create(*args, **kwargs):
        initialized.append((args, kwargs))
        return init(*args, **kwargs)

    monkeypatch.setattr(pipeline, "init", create)
    start = time.monotonic()
    assert cli.main(["handoff", "uoink:short-123", "--json", "--no-open"]) == 0
    assert time.monotonic() - start >= .02
    body = output(capsys)
    assert set(body) == {"ok", "contract", "version", "project", "page", "item_ref", "reused"}
    assert body.items() >= {"ok": True, "contract": "ryan.suite.handoff", "version": 1,
                            "item_ref": REF, "reused": False}.items()
    root = Path(body["project"])
    assert root.is_absolute() and root.parent == zing_workspace / "handoff"
    assert re.fullmatch(r"an-episode-about-rockets-[a-f0-9]{8}", root.name)
    settings = pipeline._read(root / "factory.json")
    assert settings["uoink_ref"] == REF
    assert settings.items() >= {k: v for k, v in pipeline.SETTINGS.items() if k != "uoink_ref"}.items()
    assert pipeline._read(root / "source.json").items() >= {
        "name": kept.item["title"], "url": URL, "media": str(kept.path)}.items()
    assert len(initialized) == 1 and kept.calls == [("media", REF), ("metadata", REF)]
    assert dashboard[0]["port"] == 0 and dashboard[0]["judge"] == "host"
    assert dashboard[0]["idle_seconds"] == 3600
    page = urlsplit(body["page"])
    assert page.scheme == "http" and page.hostname == "127.0.0.1" and 0 < page.port < 65536
    assert len(parse_qs(page.query)["t"][0]) >= 24
    with pytest.raises(OSError):
        socket.create_connection((page.hostname, page.port), timeout=.1)


@pytest.mark.parametrize("explicit", [False, True])
def test_same_item_reuses_project_and_keeps_edits(kept, dashboard, tmp_path, capsys, explicit):
    args = ["handoff", REF, "--json", "--no-open"]
    if explicit:
        args += ["--project", str(tmp_path / "chosen")]
    assert cli.main(args) == 0
    first = output(capsys)
    root = Path(first["project"])
    cfg = pipeline._read(root / "factory.json")
    pipeline._write(root / "factory.json", {**cfg, "moments": 2, "focus": "Keep my edits"})
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    kept.item["title"] = "A changed title"
    args[1] = "uoink:short-123"
    assert cli.main(args) == 0
    second = output(capsys)
    assert second["project"] == first["project"] and second["reused"] is True
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


@pytest.mark.parametrize("kind", ["factory", "other_item", "inventory", "corrupt", "file"])
def test_existing_project_is_refused_without_changes(kept, dashboard, tmp_path, capsys, kind):
    root = tmp_path / "chosen"
    if kind == "file":
        root.write_text("keep", encoding="utf-8")
    else:
        root.mkdir()
        if kind in ("factory", "other_item"):
            pipeline.init(root, kept.path, **({"uoink_ref": "uoink://item/other"} if kind == "other_item" else {}))
        else:
            (root / ("factory.json" if kind == "corrupt" else "project.json")).write_text("keep", encoding="utf-8")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} if root.is_dir() else root.read_bytes()
    assert cli.main(["handoff", REF, "--project", str(root), "--json", "--no-open"]) == 1
    assert output(capsys)["error"] == "project_exists"
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} if root.is_dir() else root.read_bytes()
    assert before == after and not dashboard


@pytest.mark.parametrize("code,expected", [(None, "uoink_unavailable"), ("unconfigured", "uoink_unavailable"),
                                         ("invalid_lease", "uoink_unavailable"), ("invalid_ref", "invalid_ref"),
                                         ("not_found", "media_unavailable"), ("media_unavailable", "media_unavailable")])
def test_resolve_errors_have_stable_codes_and_no_private_details(monkeypatch, capsys, tmp_path, code, expected):
    monkeypatch.setenv("UOINK_TOKEN", TOKEN)
    private = str(tmp_path / "private-library")
    monkeypatch.setattr(uoink_bridge, "resolve_kept_media",
                        lambda ref: {"ok": False, "code": code, "error": f"{TOKEN} {private}"})
    assert cli.main(["handoff", REF, "--json", "--no-open"]) == 1
    body = output(capsys)
    assert set(body) == {"ok", "contract", "version", "error", "message"}
    assert body["ok"] is False and body["error"] == expected
    assert body["contract"] == "ryan.suite.handoff" and body["version"] == 1
    assert TOKEN not in json.dumps(body) and private not in body["message"]


@pytest.mark.parametrize("ref", ["", "https://example.test/1", "uoink:", "uoink://item/a/b", "uoink://item/a%2Fb"])
def test_invalid_ref_never_calls_uoink(capsys, ref):
    assert cli.main(["handoff", *([ref] if ref else []), "--json", "--no-open"]) == 1
    assert output(capsys)["error"] == "invalid_ref"


@pytest.mark.parametrize("state", ["not_kept", "missing", "deleted", "changed"])
def test_unavailable_media_stops_before_creating_project(kept, dashboard, zing_workspace, capsys, state):
    if state == "deleted":
        kept.path.unlink()
    elif state == "changed":
        kept.path.write_bytes(b"different media")
    else:
        kept.data.update(state=state, media=None)
    assert cli.main(["handoff", REF, "--json", "--no-open"]) == 1
    assert output(capsys)["error"] == "media_unavailable"
    assert not (zing_workspace / "handoff").exists() and not dashboard


def test_metadata_is_optional(kept, dashboard, capsys, monkeypatch):
    monkeypatch.setattr(uoink_bridge, "item_metadata", lambda ref: {"ok": False, "error": "offline"})
    assert cli.main(["handoff", REF, "--json", "--no-open"]) == 0
    assert Path(output(capsys)["project"]).name.startswith("short-123-")


def test_name_and_url_from_metadata(kept, dashboard, capsys):
    kept.data["source_url"] = None
    assert cli.main(["handoff", REF, "--json", "--no-open"]) == 0
    root = Path(output(capsys)["project"])
    assert pipeline._read(root / "source.json")["url"] == URL


@pytest.mark.parametrize("json_output", [False, True])
def test_browser_opens_after_ready_and_claude_and_idle_are_forwarded(kept, dashboard, capsys, monkeypatch, json_output):
    opened = []

    def open_page(page):
        out = capsys.readouterr().out
        if json_output:
            assert json.loads(out)["page"] == page
        else:
            assert out == f"Open {page}  (Ctrl+C to stop)\n"
        opened.append(page)

    monkeypatch.setattr(handoff.webbrowser, "open", open_page)
    args = ["handoff", REF, "--judge", "claude", "--idle-minutes", "1"] + (["--json"] if json_output else [])
    assert cli.main(args) == 0
    assert len(opened) == 1 and dashboard[0]["judge"] == "claude" and dashboard[0]["idle_seconds"] == 60
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("args", [["--idle-minutes", "0"], ["--idle-minutes", "-1"], ["--idle-minutes", "no"],
                                  ["--judge", "bad"], ["--unknown"]])
def test_argument_failures_are_json(capsys, args):
    assert cli.main(["handoff", REF, "--json", *args]) == 1
    assert output(capsys)["error"] == "failed"


def test_unexpected_failure_is_private_in_plain_output(monkeypatch, capsys):
    def fail(ref):
        raise RuntimeError(TOKEN + " private folders")

    monkeypatch.setattr(uoink_bridge, "resolve_kept_media", fail)
    assert cli.main(["handoff", REF, "--no-open"]) == 1
    assert capsys.readouterr().out == handoff.ERRORS["failed"] + "\n"


def capture_body(status="saved", **changes):
    return {"ok": True, "contract": "uoink.capture", "version": 1, "status": status, "source": "youtube",
            "item_id": "short-123" if status != "queued" else None, "job_id": "job-1" if status == "queued" else None,
            "canonical": URL, "item_uri": REF if status != "queued" else None, **changes}


@pytest.fixture
def peer(monkeypatch):
    monkeypatch.setenv("UOINK_TOKEN", TOKEN)
    manifest = make_manifest(capabilities=["uoink.capture/1"])
    requests, replies, discoveries = [], [], []

    def discover(url):
        discoveries.append(url)
        return 200, manifest

    def request(req, timeout):
        requests.append(req)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return FakeHTTPResponse(json.dumps(reply).encode())

    monkeypatch.setattr(suite_peer, "_get_json", discover)
    monkeypatch.setattr(urls, "open_no_redirect", request)
    return SimpleNamespace(manifest=manifest, requests=requests, replies=replies, discoveries=discoveries)


@pytest.fixture
def clock(monkeypatch):
    now, sleeps = [0], []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(uoink_bridge, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=sleep))
    return sleeps


def test_capture_missing_capability_never_posts(peer):
    peer.manifest["service"]["capabilities"] = ["uoink.media.handoff/1"]
    result = uoink_bridge.capture(URL)
    assert not result["ok"] and result["code"] == "unsupported_capability"
    assert not peer.requests and len(peer.discoveries) == 1


@pytest.mark.parametrize("status", ["saved", "exists", "queued"])
@pytest.mark.parametrize("hint", [None, "zing"])
def test_capture_returns_exact_envelope_with_token_header(peer, status, hint):
    body = capture_body(status)
    peer.replies.append(body)
    assert uoink_bridge.capture(URL, source_hint=hint) == body
    req, = peer.requests
    assert req.full_url == "http://127.0.0.1:1/api/suite/v1/capture" and req.get_method() == "POST"
    assert json.loads(req.data) == {"url": URL, **({"source_hint": hint} if hint is not None else {})}
    assert req.get_header("X-uoink-token") == TOKEN and req.get_header("Content-type") == "application/json"
    assert "X-uoink-token" not in req.headers and TOKEN not in req.full_url


def test_capture_polls_queued_until_saved(peer, clock):
    peer.replies.extend([capture_body("queued"), capture_body("queued"), capture_body()])
    assert uoink_bridge.capture(URL, wait_seconds=10) == capture_body()
    assert clock == [2, 2]
    assert [req.get_method() for req in peer.requests] == ["POST", "GET", "GET"]
    for req in peer.requests[1:]:
        assert req.full_url.endswith("/capture/job-1") and req.data is None
        assert req.get_header("X-uoink-token") == TOKEN


def test_capture_timeout_returns_last_queued_reply(peer, clock):
    body = capture_body("queued")
    peer.replies.extend([body, body])
    assert uoink_bridge.capture(URL, wait_seconds=3) == body
    assert clock == [2, 1] and len(peer.requests) == 2


@pytest.mark.parametrize("code", ["unsupported_url", "consent_required", "media_unavailable", "busy"])
@pytest.mark.parametrize("queued", [False, True])
def test_capture_failure_envelopes_on_http_errors(peer, clock, code, queued):
    body = {"ok": False, "contract": "uoink.capture", "version": 1, "error": code, "message": "Try later."}
    if queued:
        peer.replies.append(capture_body("queued"))
    peer.replies.append(urllib.error.HTTPError("http://127.0.0.1:1", 429, "busy", {}, io.BytesIO(json.dumps(body).encode())))
    assert uoink_bridge.capture(URL, wait_seconds=10) == body
    assert clock == ([2] if queued else [])


@pytest.mark.parametrize("changes", [{"extra": True}, {"version": True}, {"version": 2}, {"ok": 1},
                                     {"contract": "other"}, {"status": "done"}, {"item_id": 1},
                                     {"job_id": []}, {"source": {}}, {"canonical": "file:///private"},
                                     {"item_uri": "uoink://item/other"}, {"item_uri": "https://example.test"}])
def test_capture_rejects_nonconformant_success(peer, changes):
    peer.replies.append(capture_body(**changes))
    result = uoink_bridge.capture(URL)
    assert not result["ok"] and result["code"] == "contract_mismatch"


@pytest.mark.parametrize("changes", [{"extra": True}, {"error": "other"}, {"message": None}, {"version": True}])
def test_capture_rejects_nonconformant_failure(peer, changes):
    peer.replies.append({"ok": False, "contract": "uoink.capture", "version": 1,
                         "error": "busy", "message": "Wait.", **changes})
    assert uoink_bridge.capture(URL)["code"] == "contract_mismatch"


@pytest.mark.parametrize("url", ["file:///private/video.mp4", "ftp://example.test/a", "uoink:1", "http://",
                                 "https://user:secret@example.test/a", "https://example.test:bad/a"])
def test_capture_refuses_non_http_or_invalid_url_before_discovery(peer, url):
    assert uoink_bridge.capture(url)["code"] == "unsupported_url"
    assert not peer.requests and not peer.discoveries


def test_capture_refuses_redirect_without_following_or_forwarding_token(peer, monkeypatch):
    requests = []

    class Redirect:
        def __init__(self, handler):
            self.handler = handler

        def open(self, req, timeout):
            requests.append(req)
            return self.handler.redirect_request(req, io.BytesIO(), 302, "Found",
                                                 {"Location": "https://elsewhere.test"}, "https://elsewhere.test")

    monkeypatch.setattr(urllib.request, "build_opener", Redirect)
    monkeypatch.setattr(urls, "open_no_redirect", OPEN_NO_REDIRECT)
    result = uoink_bridge.capture(URL)
    assert not result["ok"] and "redirect" in result["error"]
    assert len(requests) == 1 and requests[0].full_url.startswith("http://127.0.0.1:1/")


def test_capture_discovery_stops_before_remote_host(peer, monkeypatch):
    monkeypatch.setenv("UOINK_URL", "https://remote.example:443")
    assert uoink_bridge.capture(URL)["code"] == "invalid_configuration"
    assert not peer.requests and not peer.discoveries


def test_capture_uses_runtime_lease(peer, monkeypatch):
    monkeypatch.delenv("UOINK_URL")
    monkeypatch.setattr(suite_peer, "read_lease", lambda service: ("http://127.0.0.1:61234", None, "test lease"))
    peer.replies.append(capture_body())
    assert uoink_bridge.capture(URL)["ok"]
    assert peer.discoveries == ["http://127.0.0.1:61234/.well-known/suite-service.json"]
    assert peer.requests[0].full_url.startswith("http://127.0.0.1:61234/")


def test_capture_without_token_never_discovers(peer, monkeypatch):
    monkeypatch.delenv("UOINK_TOKEN")
    assert uoink_bridge.capture(URL)["code"] == "unconfigured"
    assert not peer.requests and not peer.discoveries


@pytest.mark.parametrize("where", ["url", "hint", "response", "error"])
def test_capture_does_not_echo_credentials(peer, where):
    if where == "response":
        peer.replies.append(capture_body(canonical=URL + "?secret=" + TOKEN))
    elif where == "error":
        peer.replies.append({"ok": False, "contract": "uoink.capture", "version": 1,
                             "error": "busy", "message": TOKEN})
    result = uoink_bridge.capture(URL + ("?secret=" + TOKEN if where == "url" else ""),
                                 source_hint=TOKEN if where == "hint" else None)
    assert not result["ok"] and TOKEN not in json.dumps(result)
    if where in ("url", "hint"):
        assert not peer.requests and not peer.discoveries


@pytest.mark.parametrize("failure", [False, True, "exception"])
def test_study_captures_before_dispatch_and_keeps_studying(monkeypatch, fake_engine, zing_workspace, failure):
    captured = []
    envelope = {"ok": False, "error": "unavailable", "code": "unavailable"} if failure else capture_body()

    def capture(url):
        assert not fake_engine.calls
        captured.append(url)
        if failure == "exception":
            raise OSError(TOKEN)
        return envelope

    monkeypatch.setattr(uoink_bridge, "capture", capture)
    result = mcp_server.h_study_video(URL, save_source_to_uoink=True)
    assert result["ok"] and result["status"] == "started"
    assert captured == [URL] and wait_done(result["slug"])["state"] == "done"
    assert fake_engine.calls == [URL]
    assert result["uoink_capture"] == ({"ok": False, "error": "Uoink capture failed.", "code": "failed"}
                                       if failure == "exception" else envelope)
    assert TOKEN not in json.dumps(result)


@pytest.mark.parametrize("local", [False, True])
def test_study_default_and_local_file_do_not_capture(monkeypatch, fake_engine, zing_workspace, tmp_path, local):
    monkeypatch.setattr(uoink_bridge, "capture", refuse)
    path = tmp_path / "study.mp4"
    path.write_bytes(b"fake")
    result = mcp_server.h_study_video(str(path), save_source_to_uoink=True) if local else mcp_server.h_study_video(URL)
    assert result["ok"] and "uoink_capture" not in result
    assert wait_done(result["slug"])["state"] == "done"


def test_study_already_running_includes_capture(monkeypatch, fake_engine, live_job, zing_workspace):
    storage.write_status(storage.slug_for(URL), state="running")
    live_job(storage.slug_for(URL))
    monkeypatch.setattr(uoink_bridge, "capture", lambda url: capture_body("exists"))
    result = mcp_server.h_study_video(URL, save_source_to_uoink=True)
    assert result["status"] == "already_studying" and result["uoink_capture"] == capture_body("exists")
    assert not fake_engine.calls
