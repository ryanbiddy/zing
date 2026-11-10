"""Factory readiness requires working programs, independent of optional models."""
import json
import subprocess

import pytest

from myzing.factory import command, tools


@pytest.fixture
def ready(monkeypatch, zing_workspace, tmp_path):
    monkeypatch.setattr(tools, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(tools, "browser", lambda: "chrome")
    monkeypatch.setattr(tools, "node_sidecar", lambda: ("node", tmp_path))
    monkeypatch.setattr(tools.shutil, "which", lambda name: "node" if name == "node" else None)
    monkeypatch.setattr(tools, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "v20.19.0", ""))


@pytest.mark.parametrize("missing", ["ffmpeg", "browser", "sidecar", "node", "old-node", "bad-node", None])
def test_factory_doctor_exit_and_node_details(ready, monkeypatch, capsys, missing):
    def fail():
        raise tools.FactoryError("Install the missing piece.")

    if missing in {"ffmpeg", "browser", "sidecar"}:
        monkeypatch.setattr(tools, "node_sidecar" if missing == "sidecar" else missing, fail)
    elif missing == "node":
        monkeypatch.setattr(tools.shutil, "which", lambda _: None)
    elif missing in {"old-node", "bad-node"}:
        monkeypatch.setattr(tools, "run", lambda *a, **kw: subprocess.CompletedProcess(
            a, 0, "v18.20.0" if missing == "old-node" else "not a version", ""))
    assert command.run(["doctor"]) == (1 if missing else 0)
    result = json.loads(capsys.readouterr().out)
    assert set(result) == {"ffmpeg", "node", "browser", "sidecar", "claude", "face_model", "depth_model",
                           "cutout_model", "upscaler", "stock_keys"}
    if missing in {"node", "old-node", "bad-node"}:
        assert not result["node"]["ok"] and "Node.js 20" in result["node"]["fix"]
    else:
        assert result["node"] == {"ok": True, "path": "node", "version": "v20.19.0"}

