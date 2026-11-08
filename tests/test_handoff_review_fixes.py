"""Hand-off regressions use fake peers and download processes."""
import builtins
import io
import json
import os
import socket
from pathlib import Path

import pytest

from conftest import FakeHTTPResponse
from myzing import doctor, handoff, storage, uoink_bridge, urls
from myzing.factory import judge, pipeline, serve
from myzing.project import references
from myzing.study import downloader, ingest
from test_factory_handoff_download import Process, process_tree
from test_uoink_bridge import handoff_body

REF = "uoink://item/short-123"
URL = "https://example.test/watch/123"


def refuse(*args, **kwargs):
    pytest.fail("unmocked external operation")


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace, isolated_uoink_transport, process_tree):
    monkeypatch.setenv("UOINK_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(urls, "open_no_redirect", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(ingest.subprocess, "Popen", refuse)
    monkeypatch.setattr(ingest, "require_public_host", lambda url: None)
    monkeypatch.setattr(doctor, "resolve_ytdlp_argv", lambda: ["yt-dlp"])
    monkeypatch.setattr(downloader, "runtime_options", lambda: {})
    monkeypatch.setattr(handoff.webbrowser, "open", refuse)
    monkeypatch.setattr(serve, "serve", refuse)
    monkeypatch.setattr(uoink_bridge, "item_metadata", lambda ref: {"ok": True, "title": "Episode", "source_url": URL})


@pytest.fixture
def peer(monkeypatch):
    body = handoff_body(source_url=URL)
    monkeypatch.setenv("UOINK_TOKEN", "synthetic-suite-credential")
    monkeypatch.setattr(uoink_bridge, "helper_url", lambda: "http://127.0.0.1:1")
    monkeypatch.setattr(urls, "open_no_redirect", lambda *a, **kw: FakeHTTPResponse(json.dumps(body).encode()))
    return body["data"]


@pytest.mark.parametrize("line", ["[zing-progress]  42.0%", "[zing-progress] \x1b[0;94m 42.0%\x1b[0m",
                                 "\x1b[32m[zing-progress]  42.0%\x1b[0m  "])
def test_download_marker_reaches_handoff_progress(peer, monkeypatch, tmp_path, capsys, line):
    peer.update(state="not_kept", media=None)
    calls = []

    def start(cmd, **kwargs):
        calls.append(cmd)
        dest = Path(cmd[cmd.index("-P") + 1])
        (dest / "media.mp4").write_bytes(b"episode")
        return Process("downloading\n" + line + "\nmerged\n")

    def ready(project, **kwargs):
        kwargs["ready"]("http://127.0.0.1:1234/")

    monkeypatch.setattr(ingest.subprocess, "Popen", start)
    monkeypatch.setattr(serve, "serve", ready)
    root = tmp_path / "project"
    assert handoff.run([REF, "--allow-download", "--project", str(root), "--json", "--no-open"]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1 and json.loads(captured.out)["downloaded"] is True
    assert [json.loads(line) for line in captured.err.splitlines()] == [
        {"contract": handoff.CONTRACT, "version": 1, "progress": "download", "percent": 42.0}]
    cmd, = calls
    assert cmd[cmd.index("--progress-template") + 1] == "download:[zing-progress] %(progress._percent_str)s"
    assert "--newline" in cmd
    assert pipeline._read(root / "factory.json")["uoink_ref"] == REF


@pytest.mark.parametrize("path", [r"\\host\share\video.mp4", "//host/share/video.mp4",
                                 r"\\.\C:\video.mp4", r"\\?\UNC\host\share\video.mp4",
                                 "//?/C:/video.mp4", "//./C:/video.mp4", r"\/host/share/video.mp4"])
def test_media_paths_are_rejected_before_file_access(peer, monkeypatch, path):
    peer["media"]["path"] = path
    with monkeypatch.context() as guard:
        for target, name in ((builtins, "open"), (io, "open"), (Path, "open"), (Path, "stat"), (os, "stat"),
                             (references, "_verified")):
            guard.setattr(target, name, refuse)
        result = uoink_bridge.resolve_kept_media(REF)
        with pytest.raises(handoff.HandoffError) as caught:
            handoff._project(REF, None)
    assert set(result) == {"ok", "error"} and result["ok"] is False
    assert "not contract-conformant" in result["error"] and "media.path" in result["error"]
    assert caught.value.code == "uoink_unavailable"


@pytest.mark.parametrize("path", [r"\\?\C:\Library\video.mp4", "\\\\?\\E:\\" + "a" * 260 + "\\video.mp4"])
def test_long_path_form_of_a_local_drive_is_accepted(path):
    body = handoff_body(source_url=URL)
    body["data"]["media"]["path"] = path
    assert uoink_bridge.handoff_defect(body) is None


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
def test_lowercased_hostname_is_screened(peer, monkeypatch, zing_workspace, capsys, json_output, fallback):
    token = "private-token"
    url = "https://PRIVATE-TOKEN.example.test/watch/123"
    peer.update(state="not_kept", media=None, source_url=None if fallback else url)
    monkeypatch.setenv("UOINK_TOKEN", token)
    monkeypatch.setattr(uoink_bridge, "item_metadata", lambda ref: {"ok": True, "title": "Episode", "source_url": url})
    assert uoink_bridge.redact(url) == url
    assert handoff.run([REF, "--no-open", *(["--json"] if json_output else [])]) == 1
    captured = capsys.readouterr()
    assert not captured.err and token not in captured.out.lower()
    if json_output:
        assert json.loads(captured.out) == {"ok": False, "contract": handoff.CONTRACT, "version": 1,
                                           "error": "failed", "message": handoff.ERRORS["failed"]}
    else:
        assert captured.out == handoff.ERRORS["failed"] + "\n"
    assert not (zing_workspace / "handoff").exists()


@pytest.mark.parametrize("slug", ["short-123", "episode"])
@pytest.mark.parametrize("partial", [False, True])
def test_same_item_in_progress_refuses_second_launch(peer, zing_workspace, capsys, slug, partial):
    peer.update(state="not_kept", media=None)
    root = zing_workspace / "handoff" / f"{slug}-{storage._hash8(REF.encode())}"
    root.mkdir(parents=True)
    if partial:
        (root / "source").mkdir()
        (root / "source" / "media.mp4.part").write_bytes(b"partial")
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert handoff.run(["uoink:short-123", "--allow-download", "--json", "--no-open"]) == 1
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {"ok": False, "contract": handoff.CONTRACT, "version": 1,
                                      "error": "project_exists", "message": handoff.ERRORS["project_exists"]}
    assert list(root.parent.iterdir()) == [root]
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("media_type", [[], {}])
def test_unhashable_media_type_returns_error_envelope(peer, media_type):
    peer["media"]["media_type"] = media_type
    result = uoink_bridge.resolve_kept_media(REF)
    assert set(result) == {"ok", "error"} and result["ok"] is False
    assert "not contract-conformant" in result["error"] and "unsupported media_type" in result["error"]
