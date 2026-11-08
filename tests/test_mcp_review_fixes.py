"""MCP job endings and errors, with no model calls or downloads."""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest

from myzing import mcp_server, shot_list, storage
from myzing.factory import judge, pipeline
from myzing.render import otio_export
from myzing.render.pipeline import RenderError
from test_mcp_render_tools import edl_file
from test_shot_list import SLUG, VALID_DOC, studied, validate_contract_payload


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unexpected judge call")
    monkeypatch.setattr(judge.Judge, "_claude", refuse)


@pytest.mark.parametrize("kind", ["match", "render"])
@pytest.mark.parametrize("state", ["done", "failed"])
def test_poll_keeps_worker_ending(tmp_path, monkeypatch, kind, state):
    registry = {}
    if kind == "match":
        key = str(tmp_path / "match")
        directory = Path(key) / "match-job"
        monkeypatch.setattr(mcp_server, "_MATCH_JOBS", registry)
    else:
        key = "review-render"
        directory = storage.render_dir(key)
        monkeypatch.setattr(mcp_server, "_RENDER_JOBS", registry)
    storage.write_status_at(directory, state="running", pid=os.getpid())
    ending = {"state": state, "error": "fixture failure" if state == "failed" else "", "finished_at": "new"}

    class Finished:
        def is_alive(self):
            storage.write_status_at(directory, **ending)
            registry.pop(key)
            return False

    registry[key] = Finished()
    result = mcp_server.h_match_status(key, cancel=True) if kind == "match" else mcp_server.h_get_render(key)
    assert result["ok"] and "pid" not in result
    assert {k: result[k] for k in ending} == ending
    assert storage.read_status_at(directory) == {"pid": os.getpid(), **ending}
    if kind == "match":
        assert result["cancellation_requested"] is False


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    pipeline._write(root / "factory.json", {**pipeline.SETTINGS, "moments": 0, "offline": True})
    return root


@pytest.mark.parametrize("previous", ["done", "failed"])
@pytest.mark.parametrize("setup", ["source", "judge"])
def test_factory_setup_failure_replaces_previous_ending(project, monkeypatch, previous, setup):
    pipeline._write(project / "status.json", {"state": previous, "error": "old error", "at": "old"})
    if setup == "judge":
        def broken(self, *args, **kwargs):
            raise PermissionError(errno.EACCES, "Permission denied", str(project))
        monkeypatch.setattr(judge.Judge, "__init__", broken)
    monkeypatch.setattr(mcp_server, "_FACTORY_JOBS", {})
    monkeypatch.setattr(mcp_server.threading.Thread, "start", lambda self: None)

    result = mcp_server.h_factory_run(str(project))
    assert result["ok"] and result["status"] == "started"
    mcp_server._FACTORY_JOBS[str(project)].run()

    status = pipeline._read(project / "status.json")
    assert status["state"] == "failed" and status["at"] != "old"
    assert ("PermissionError" if setup == "judge" else "FactoryError") in status["error"]
    assert status["error"] != "old error" and len(status["error"]) < 200
    assert str(project) not in status["error"] and project.parent.name not in status["error"]
    assert str(project) not in mcp_server._FACTORY_JOBS


@pytest.mark.parametrize("state", ["done", "waiting", "stopped", "failed"])
def test_factory_keeps_pipeline_ending(project, monkeypatch, state):
    pipeline._write(project / "status.json", {"state": "done", "at": "old"})
    ending = {"state": state, "error": "pipeline detail", "at": "new"}

    def run(root, ask, **kwargs):
        pipeline._write(root / "status.json", ending)
        raise RuntimeError("after the pipeline ending")
    monkeypatch.setattr(pipeline, "run", run)
    mcp_server._run_factory(project)
    assert pipeline._read(project / "status.json") == ending


@pytest.mark.parametrize("message", ["ffprobe not found on PATH", "could not probe video"])
def test_export_otio_probe_error_is_data(edl_file, monkeypatch, message):
    calls = []

    def probe(path, *args, **kwargs):
        calls.append(path)
        raise RenderError(message)
    monkeypatch.setattr(otio_export, "probe_media", probe)
    result = mcp_server.h_export_otio(str(edl_file))
    assert calls == [edl_file.parent / "a.mp4"]
    assert result == {"ok": False, "error": f"OTIO export failed: {message}"}
    assert not edl_file.with_suffix(".otio").exists()


@pytest.mark.parametrize("operation", ["is_file", "read_bytes", "mkdir", "write_bytes"])
@pytest.mark.parametrize("in_message", [False, True])
def test_shot_list_permission_error_is_path_free(studied, tmp_path, monkeypatch, operation, in_message):
    doc = tmp_path / "private-shot-list.md"
    doc.write_text(VALID_DOC, encoding="utf-8")
    imports = storage.breakdown_dir(SLUG) / shot_list.IMPORTS_DIRNAME
    original = getattr(Path, operation)

    def denied(path, *args, **kwargs):
        if path == doc or path == imports or path.parent == imports:
            if in_message:
                raise PermissionError(f"Access denied for {path}")
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, operation, denied)
    receipt = mcp_server.h_import_shot_list(str(doc), SLUG)
    assert receipt["ok"] is False
    assert receipt["error"]["code"] == ("invalid_file" if operation in {"is_file", "read_bytes"} else "storage_unavailable")
    assert receipt["error"]["retryable"] is (operation in {"mkdir", "write_bytes"})
    assert "PermissionError" in receipt["error"]["message"]
    assert tmp_path.name not in json.dumps(receipt) and doc.name not in json.dumps(receipt)
    assert validate_contract_payload("zing.shot-list.import/1", receipt)["issues"] == []
