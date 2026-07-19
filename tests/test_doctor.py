"""Doctor: honest tiered checks, offline. All external probes are mocked."""

from __future__ import annotations

import json
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from myzing import doctor


@pytest.fixture
def bare_machine(monkeypatch):
    """A machine with nothing installed and no network."""
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "")

    def refuse(url, timeout=0):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(doctor.urllib.request, "urlopen", refuse)


@pytest.fixture
def full_machine(monkeypatch):
    """Everything installed, current yt-dlp, uoink absent."""
    monkeypatch.setattr(doctor, "_which", lambda name: f"C:/tools/{name}.exe")
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(
        doctor, "_run_version",
        lambda cmd: "2026.07.01" if "yt-dlp" in cmd[0] else "ffmpeg version 7.1",
    )

    def refuse(url, timeout=0):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(doctor.urllib.request, "urlopen", refuse)


# -- bare machine ------------------------------------------------------------

def test_bare_machine_exits_nonzero(bare_machine, capsys):
    assert doctor.run([]) == 1
    out = capsys.readouterr().out
    assert "NOT ready" in out
    assert "ffmpeg" in out


def test_bare_machine_messages_are_actionable(bare_machine, capsys):
    doctor.run([])
    out = capsys.readouterr().out
    # every failing non-optional line names its fix command
    assert "pip install" in out or "winget" in out or "apt install" in out or "brew" in out
    # degraded modes are named, not implied
    assert "transcription is skipped" in out
    assert "caption OCR is skipped" in out
    assert "shot detection is skipped" in out
    assert "local files only" in out


def test_bare_machine_uoink_absence_is_calm(bare_machine, capsys):
    doctor.run([])
    out = capsys.readouterr().out
    assert "standalone" in out  # absent uoink is fine, not an error


def test_only_required_gates_exit_code(bare_machine, monkeypatch):
    # ffmpeg present but everything else still missing -> ready (exit 0)
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: "C:/tools/bin" if name in ("ffmpeg", "ffprobe") else None,
    )
    assert doctor.run([]) == 0


# -- full machine ------------------------------------------------------------

def test_full_machine_exits_zero(full_machine, capsys):
    assert doctor.run([]) == 0
    assert "Ready." in capsys.readouterr().out


def test_json_output_is_parseable_and_complete(full_machine, capsys):
    assert doctor.run(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["required_missing"] == []
    names = {c["name"] for c in payload["checks"]}
    assert names == {
        "ffmpeg", "yt-dlp", "scenedetect", "faster-whisper", "ocr",
        "tts", "uoink",
    }
    tiers = {c["name"]: c["tier"] for c in payload["checks"]}
    assert tiers["ffmpeg"] == "required"
    assert tiers["scenedetect"] == "recommended"
    assert tiers["uoink"] == "optional"


def test_json_on_bare_machine_reports_required_missing(bare_machine, capsys):
    assert doctor.run(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["required_missing"] == ["ffmpeg"]


# -- yt-dlp staleness --------------------------------------------------------

def test_ytdlp_stale_version_warns_with_fix(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2025.01.15")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.ok is True  # stale is a warning, not a failure
    assert check.data["stale"] is True
    assert "pip install -U yt-dlp" in check.fix
    assert "days old" in check.detail


def test_ytdlp_fresh_version_is_quiet(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.data["stale"] is False
    assert check.fix == ""


def test_ytdlp_unparsable_version_does_not_crash(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "nightly-abc123")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.ok is True
    assert check.data["age_days"] is None


# -- B-Q12: JS-runtime coverage (yt-dlp needs deno/node for YouTube) ----------

def test_ytdlp_without_js_runtime_warns_with_fix(monkeypatch):
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: f"/bin/{name}" if name == "yt-dlp" else None,
    )
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.ok is True  # warning-grade, like staleness
    assert check.data["js_runtime"] is None
    assert "JS runtime" in check.detail and "YouTube" in check.detail
    assert "deno" in check.fix.lower()


def test_ytdlp_with_deno_is_quiet(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.data["js_runtime"] == "deno"
    assert "JS runtime" not in check.detail
    assert check.fix == ""


def test_stale_and_no_js_runtime_both_reported(monkeypatch):
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: f"/bin/{name}" if name == "yt-dlp" else None,
    )
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2025.01.15")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.data["stale"] is True and check.data["js_runtime"] is None
    assert "days old" in check.detail and "JS runtime" in check.detail
    assert "pip install -U yt-dlp" in check.fix and "deno" in check.fix.lower()


# -- F-05: ocr check must match what the pipeline imports ---------------------
#
# study/captions.py imports `from rapidocr import RapidOCR` and nothing else.
# Doctor blessing rapidocr_onnxruntime or tesseract is a lie: study would skip
# OCR on those machines while doctor prints ok (S1-FIXLIST F-05, lane-a #2).

def test_ocr_ok_only_when_rapidocr_module_present(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(doctor, "_has_module", lambda name: name == "rapidocr")
    check = doctor.check_ocr()
    assert check.ok is True
    assert "rapidocr" in check.detail


def test_ocr_rapidocr_onnxruntime_alone_is_not_ok(monkeypatch):
    # The old package installs fine but the pipeline never imports it.
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(
        doctor, "_has_module", lambda name: name == "rapidocr_onnxruntime"
    )
    check = doctor.check_ocr()
    assert check.ok is False
    assert "rapidocr_onnxruntime" in check.detail  # found, but honestly not wired
    assert "myzing[study]" in check.fix
    assert "caption OCR is skipped" in check.degraded_mode


def test_ocr_tesseract_alone_is_not_ok(monkeypatch):
    # The pipeline has no tesseract backend; a binary on PATH changes nothing.
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: "/usr/bin/tesseract" if name == "tesseract" else None,
    )
    check = doctor.check_ocr()
    assert check.ok is False
    assert "tesseract" in check.detail  # found, but honestly not wired
    assert "myzing[study]" in check.fix


def test_ocr_check_agrees_with_pipeline_import():
    captions_src = (
        Path(doctor.__file__).parent / "study" / "captions.py"
    ).read_text(encoding="utf-8")
    assert f"from {doctor.OCR_MODULE} import" in captions_src


# -- F-10: scenedetect is checked, and "Ready." is never unqualified ----------
#
# Shot detection is the core measurement; a fresh install without scenedetect
# used to print "Ready." while measuring zero shots (S1-FIXLIST F-10,
# lane-a #5).

def test_scenedetect_missing_is_recommended_with_fix(bare_machine):
    check = doctor.check_scenedetect()
    assert check.tier == "recommended"
    assert check.ok is False
    assert "myzing[study]" in check.fix
    assert "shot detection is skipped" in check.degraded_mode


def test_scenedetect_present_is_ok(monkeypatch):
    monkeypatch.setattr(doctor, "_has_module", lambda name: name == "scenedetect")
    check = doctor.check_scenedetect()
    assert check.ok is True


def test_scenedetect_check_agrees_with_pipeline_import():
    shots_src = (
        Path(doctor.__file__).parent / "study" / "shots.py"
    ).read_text(encoding="utf-8")
    assert f"import {doctor.SHOT_MODULE}" in shots_src


def test_no_unqualified_ready_when_scenedetect_missing(bare_machine, monkeypatch, capsys):
    # ffmpeg present (required tier satisfied), scenedetect still missing.
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: "C:/tools/bin" if name in ("ffmpeg", "ffprobe") else None,
    )
    assert doctor.run([]) == 0  # recommended tier never fails the machine
    out = capsys.readouterr().out
    assert "Ready." not in out  # the unqualified verdict is reserved
    assert "scenedetect" in out


def test_full_machine_ready_is_unqualified(full_machine, capsys):
    assert doctor.run([]) == 0
    out = capsys.readouterr().out
    assert "Ready." in out
    assert "degraded" not in out.lower()


# -- summarize is the zing_status contract -----------------------------------

def test_summarize_shape(full_machine):
    summary = doctor.summarize(doctor.run_checks(today=date(2026, 7, 18)))
    assert set(summary) == {"ok", "required_missing", "checks"}
    for c in summary["checks"]:
        assert {"name", "tier", "ok", "detail", "fix", "degraded_mode", "data"} <= set(c)
