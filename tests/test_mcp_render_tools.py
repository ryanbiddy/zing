"""S4-B render/export MCP tools: cheap validation, job honesty, sync export."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from myzing import mcp_server, storage
from myzing.render import pipeline
from myzing.schemas import EDL, Clip


@pytest.fixture
def edl_file(tmp_path: Path) -> Path:
    (tmp_path / "a.mp4").write_bytes(b"fake")
    edl = EDL(clips=[Clip(src="a.mp4", src_in=0.0, src_out=1.0, timeline_start=0.0)])
    p = tmp_path / "draft.json"
    p.write_text(edl.to_json(), encoding="utf-8")
    return p


@pytest.fixture
def has_ffmpeg(monkeypatch):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")


def wait_render(render_id: str, timeout: float = 10.0) -> dict:
    d = storage.render_dir(render_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = storage.read_status_at(d)
        if status and status.get("state") in ("done", "failed"):
            return status
        time.sleep(0.01)
    raise AssertionError("render never finished")


# -- validation (sync, before any job) ---------------------------------------

def test_render_missing_ffmpeg(zing_workspace, monkeypatch, edl_file):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: None)
    result = mcp_server.h_render_edl(str(edl_file))
    assert result["ok"] is False and "zing doctor" in result["error"]


def test_render_missing_edl(zing_workspace, has_ffmpeg):
    result = mcp_server.h_render_edl("C:/nope/ghost.json")
    assert result["ok"] is False and "not found" in result["error"]


def test_render_malformed_edl(zing_workspace, has_ffmpeg, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = mcp_server.h_render_edl(str(bad))
    assert result["ok"] is False and "could not parse EDL" in result["error"]


# -- job lifecycle (pipeline mocked) -----------------------------------------

def test_render_job_success(zing_workspace, has_ffmpeg, edl_file, monkeypatch):
    def fast_render(edl, output_path, *, base_dir=None, **kw):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")
        from types import SimpleNamespace

        return SimpleNamespace(output_path=output_path, duration=1.0)

    monkeypatch.setattr(pipeline, "render_edl", fast_render)
    result = mcp_server.h_render_edl(str(edl_file))
    assert result["ok"] is True and result["status"] == "started"
    status = wait_render(result["render_id"])
    assert status["state"] == "done"
    fetched = mcp_server.h_get_render(result["render_id"])
    assert fetched["ok"] is True and fetched["state"] == "done"
    assert Path(fetched["output"]).name == "output.mp4"
    assert "pid" not in fetched  # internal marker not leaked


def test_render_job_failure_is_honest(zing_workspace, has_ffmpeg, edl_file, monkeypatch):
    def boom(edl, output_path, *, base_dir=None, **kw):
        raise pipeline.RenderError("clip a.mp4 overlaps clip b.mp4")

    monkeypatch.setattr(pipeline, "render_edl", boom)
    result = mcp_server.h_render_edl(str(edl_file))
    status = wait_render(result["render_id"])
    assert status["state"] == "failed"
    assert "overlaps" in status["error"]


def test_get_render_unknown_and_invalid(zing_workspace):
    assert mcp_server.h_get_render("nothing-here")["ok"] is False
    assert mcp_server.h_get_render("../escape")["ok"] is False


def test_get_render_orphaned_running_is_rewritten(zing_workspace):
    import os

    d = storage.render_dir("orphan-job")
    storage.write_status_at(
        d, state="running", pid=os.getpid(), started_at="t"
    )
    result = mcp_server.h_get_render("orphan-job")
    assert result["state"] == "failed"
    assert "worker is gone" in result["error"]
    assert storage.read_status_at(d)["state"] == "failed"  # rewritten on disk


# -- export (sync) -----------------------------------------------------------

def test_export_otio_happy(zing_workspace, edl_file, monkeypatch):
    from myzing.render import otio_export

    calls = {}

    def fake_export(edl, output_path, *, base_dir=None, **kw):
        calls["out"] = output_path
        output_path.write_text("otio", encoding="utf-8")
        return "ok"

    monkeypatch.setattr(otio_export, "export_otio", fake_export)
    result = mcp_server.h_export_otio(str(edl_file))
    assert result["ok"] is True, result.get("error")
    assert result["output"].endswith(".otio")
    assert result["clips"] == 1


def test_export_otio_error_is_data(zing_workspace, edl_file, monkeypatch):
    from myzing.render import otio_export

    def fail(edl, output_path, *, base_dir=None, **kw):
        raise otio_export.OTIOExportError("clip source missing: a.mp4")

    monkeypatch.setattr(otio_export, "export_otio", fail)
    result = mcp_server.h_export_otio(str(edl_file))
    assert result["ok"] is False
    assert "clip source missing" in result["error"]