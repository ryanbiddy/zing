"""PH plan checks are stdlib-only; the actual renderer is explicitly opt-in."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

from myzing import doctor
from myzing.render import hyperframes_adapter as hf

SIDECAR = Path(__file__).resolve().parents[1] / "tools/hyperframes-sidecar"


@pytest.fixture
def plan(tmp_path):
    p = json.loads((SIDECAR / "example-plan.json").read_text(encoding="utf-8"))
    font = tmp_path / "font's folder" / "test font.ttf"
    font.parent.mkdir()
    font.write_bytes(b"validation does not decode fonts")
    for event in p["captions"]:
        event["style"]["font"] = str(font)
    return p


def test_plan_round_trip_and_writer_preserve_input(plan, tmp_path):
    plan["captions"][0]["words"][0]["text"] = '<tag> & "quoted" café'
    original = copy.deepcopy(plan)
    typed = hf.HyperframesPlan.from_dict(plan)
    assert typed.to_dict() == original
    path = hf.write_plan(typed, tmp_path / "new folder" / "plan.json")
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert plan == original
    assert path.read_bytes().endswith(b"\n")
    assert b"caf\xc3\xa9" in path.read_bytes()


def test_relative_assets_resolve_against_explicit_base(plan, tmp_path):
    asset = Path(plan["captions"][0]["style"]["font"])
    for event in plan["captions"]:
        event["style"]["font"] = str(asset.relative_to(tmp_path))
    plan["background"] = {"video": "clip's name.mp4"}
    (tmp_path / "clip's name.mp4").write_bytes(b"placeholder")
    path = hf.write_plan(plan, tmp_path / "nested/plan.json", base_dir=tmp_path)
    written = json.loads(path.read_text())
    assert written["captions"][0]["style"]["font"] == str(asset.resolve())
    assert written["background"]["video"] == str((tmp_path / "clip's name.mp4").resolve())


@pytest.mark.parametrize("keys,value", [
    (("version",), 2), (("version",), True),
    (("width",), 641), (("height",), 0), (("fps",), 29.97),
    (("duration",), float("nan")), (("duration",), float("inf")),
    (("duration",), True), (("duration",), 3.001),
    (("background",), {"color": "#101820", "video": "a.mp4"}),
    (("background",), {"video": "https://example.com/a.mp4"}),
    (("background",), {"video": "\\\\server\\video.mp4"}),
    (("background",), {"color": "red; url(https://example.com)"}),
    (("captions", 0, "template"), "shader"),
    (("captions", 0, "style", "font"), "https://example.com/font.ttf"),
    (("captions", 0, "style", "font"), "font.js"),
    (("captions", 0, "style", "size"), -1),
    (("captions", 0, "style", "outline_width"), 21),
    (("captions", 0, "style", "highlight"), "yellow"),
    (("captions", 0, "box", "x"), .3),
    (("captions", 0, "box", "height"), 0),
    (("captions", 0, "words", 0, "text"), ""),
    (("captions", 0, "words", 0, "text"), "a\nb"),
    (("captions", 0, "words", 0, "start"), .1),
    (("captions", 0, "words", 0, "end"), .2),
    (("captions", 0, "words", 1, "start"), .5),
    (("captions", 0, "words", 2, "end"), 1.5),
    (("captions", 1, "path", 0, "time"), 1.7),
    (("captions", 1, "path", 1, "time"), 1.6),
    (("captions", 1, "path", 1, "box", "x"), .5),
    (("captions", 1, "path"), []),
    (("shader",), "wipe"),
])
def test_invalid_plans_fail_without_node(plan, keys, value):
    target = plan
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    with pytest.raises(hf.HyperframesError):
        hf.HyperframesPlan.from_dict(plan)


def test_missing_asset_has_remedy_and_does_not_write(plan, tmp_path):
    plan["captions"][0]["style"]["font"] = "missing.ttf"
    output = tmp_path / "plan.json"
    with pytest.raises(hf.HyperframesError, match="missing file.*supply an existing"):
        hf.write_plan(plan, output, base_dir=tmp_path)
    assert not output.exists()


def test_box_and_path_together_rejected(plan):
    plan["captions"][1]["box"] = plan["captions"][0]["box"]
    with pytest.raises(hf.HyperframesError, match="exactly one"):
        hf.validate_plan(plan)


def test_missing_node_remedy(monkeypatch):
    monkeypatch.setattr(hf.shutil, "which", lambda _: None)
    with pytest.raises(hf.HyperframesError, match="install Node.js 24"):
        hf.check_install()


def test_missing_install_and_browser_remedies(monkeypatch, tmp_path):
    monkeypatch.setattr(hf.shutil, "which", lambda _: "node")
    monkeypatch.setattr(hf.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "v24.18.0"))
    with pytest.raises(hf.HyperframesError, match="npm ci --ignore-scripts"):
        hf.check_install(sidecar=tmp_path)
    package = tmp_path / "node_modules/hyperframes/package.json"
    package.parent.mkdir(parents=True)
    package.write_text(json.dumps({"version": hf.HYPERFRAMES_VERSION}))
    cli = tmp_path / "node_modules/hyperframes/bin/hyperframes.mjs"
    cli.parent.mkdir()
    cli.touch()
    (tmp_path / "render.mjs").touch()
    with pytest.raises(hf.HyperframesError, match="HYPERFRAMES_BROWSER_PATH"):
        hf.check_install(sidecar=tmp_path, browser=tmp_path / "absent.exe")


def probe_data():
    return {"streams": [{"width": 640, "height": 360, "avg_frame_rate": "30/1", "duration": "3.000", "nb_read_frames": "90"}], "format": {"duration": "3.000"}}


@pytest.mark.parametrize("key,value", [("width", 1280), ("height", 720), ("avg_frame_rate", "24/1"), ("duration", "2.5"), ("duration", "nan"), ("nb_read_frames", "89")])
def test_wrong_output_rejected(plan, monkeypatch, tmp_path, key, value):
    probe = probe_data()
    probe["streams"][0][key] = value
    monkeypatch.setattr(hf.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(probe)))
    with pytest.raises(hf.HyperframesError, match="ffprobe verification failed"):
        hf.verify_output(tmp_path / "wrong.mp4", plan)


def test_valid_probe(plan, monkeypatch, tmp_path):
    probe = probe_data()
    monkeypatch.setattr(hf.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(probe)))
    assert hf.verify_output(tmp_path / "valid.mp4", plan) == probe


def test_existing_output_is_preserved(plan, tmp_path):
    output = tmp_path / "keep.mp4"
    output.write_bytes(b"keep")
    with pytest.raises(hf.HyperframesError, match="already exists"):
        hf.render_hyperframes(plan, output)
    assert output.read_bytes() == b"keep"


def test_timeout_stops_process_tree(monkeypatch, tmp_path):
    calls = []

    class Process:
        pid = 123456

        def communicate(self, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired("node", timeout)
            return b"render stopped", None

    monkeypatch.setattr(hf.subprocess, "Popen", lambda *a, **k: Process())
    killed = []
    monkeypatch.setattr(hf.subprocess, "run", lambda cmd, **k: killed.append(cmd))
    if os.name != "nt":
        monkeypatch.setattr(hf.os, "killpg", lambda pid, sig: killed.append(pid))
    with pytest.raises(hf.HyperframesError, match="timed out.*tree stopped"):
        hf._run_process(["node"], env={}, timeout=1, log=tmp_path / "timeout.log")
    assert killed
    assert (tmp_path / "timeout.log").read_text() == "render stopped"


def test_doctor_reports_optional_remedy(monkeypatch):
    def missing():
        raise hf.HyperframesError("install local sidecar")
    monkeypatch.setattr(hf, "check_install", missing)
    check = doctor.check_hyperframes()
    assert not check.ok and check.tier == doctor.OPTIONAL
    assert check.fix == "install local sidecar"


@pytest.mark.skipif(os.environ.get("ZING_REQUIRE_HYPERFRAMES") != "1", reason="optional real HyperFrames check; set ZING_REQUIRE_HYPERFRAMES=1 after setup")
def test_real_hyperframes_render(tmp_path):
    # When requested, every missing prerequisite is a failure, not a skip.
    hf.check_install()
    spec = importlib.util.spec_from_file_location("hyperframes_proof", SIDECAR / "proof.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    font = Path(os.environ.get("ZING_HYPERFRAMES_FONT", str(SIDECAR.parents[1] / "zing-workspace/hyperframes/fonts/Anton-Regular.ttf")))
    result = module.run_proof(tmp_path / "proof", font)
    assert result["external_node_requests"] == 0
    assert result["probe"]["streams"][0]["nb_read_frames"] == "90"
