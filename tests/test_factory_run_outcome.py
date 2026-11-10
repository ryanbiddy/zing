"""A completed run with only failed clips must fail at both caller boundaries."""
import json

import pytest

from myzing import mcp_server
from myzing.factory import command, pipeline
from myzing.factory.tools import FactoryError


@pytest.fixture
def project(tmp_path, monkeypatch, zing_workspace):
    root = tmp_path / "project"
    pipeline._write(root / "factory.json", {**pipeline.SETTINGS, "offline": True})
    pipeline._write(root / "source.json", {"media": str(tmp_path / "episode.mp4")})
    moments = [{"start": 1, "end": 4, "hook": "Rocket"}, {"start": 5, "end": 8, "hook": "Moon"}]
    pipeline._write(root / "moments.json", {"moments": moments})
    monkeypatch.setattr(pipeline, "_moments", lambda *a, **k: moments)
    monkeypatch.setattr(pipeline.review, "build", lambda *a: None)

    def fail(*args, **kwargs):
        raise FactoryError("YuNet model missing")

    monkeypatch.setattr(pipeline, "_clip", fail)
    return root


def test_cli_all_failed_is_nonzero_and_keeps_json(project, capsys):
    code = command.run(["run", str(project)])
    out = capsys.readouterr()
    result = json.loads(out.out)
    assert result == pipeline.status(project)
    assert result["state"] == "done"
    assert result["failed"] == {"clip01": "YuNet model missing", "clip02": "YuNet model missing"}
    assert code == 1
    assert "No clips rendered. 2 clips failed. YuNet model missing" in out.err


def test_mcp_completed_run_reports_failure(project, monkeypatch):
    monkeypatch.setattr(mcp_server, "_FACTORY_JOBS", {})
    monkeypatch.setattr(mcp_server.threading.Thread, "start", lambda self: None)
    started = mcp_server.h_factory_run(str(project))
    assert started["ok"] and started["status"] == "started"
    mcp_server._FACTORY_JOBS[str(project)].run()
    result = mcp_server.h_factory_status(str(project))
    assert not result["running"]
    assert result["failed"] == pipeline.status(project)["failed"]
    assert result["ok"] is False
    assert result["error"] == "No clips rendered. 2 clips failed. YuNet model missing"


@pytest.mark.parametrize("state,failed,renders", [
    ("done", {}, []),
    ("waiting", {"clip01": "failed"}, []),
    ("stopped", {"clip01": "failed"}, []),
    ("done", {"clip01": "failed"}, ["clip.mp4"]),
])
def test_empty_pending_stopped_and_partial_runs_stay_successful(project, monkeypatch, capsys, state, failed, renders):
    result = {"state": state, "failed": failed, "clips": [{"renders": renders}]}
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: result)
    monkeypatch.setattr(pipeline, "status", lambda *a: result.copy())
    assert command.run(["run", str(project)]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == result and not out.err
    assert mcp_server.h_factory_status(str(project))["ok"]
