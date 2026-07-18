"""Doctor: honest tiered checks, offline. All external probes are mocked."""

from __future__ import annotations

import json
import urllib.error
from datetime import date

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
    assert names == {"ffmpeg", "yt-dlp", "faster-whisper", "ocr", "uoink"}
    tiers = {c["name"]: c["tier"] for c in payload["checks"]}
    assert tiers["ffmpeg"] == "required"
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


# -- ocr fallback ------------------------------------------------------------

def test_tesseract_counts_as_ok_but_recommends_rapidocr(monkeypatch):
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: "/usr/bin/tesseract" if name == "tesseract" else None,
    )
    check = doctor.check_ocr()
    assert check.ok is True
    assert "RapidOCR" in check.detail or "RapidOCR" in check.fix


# -- summarize is the zing_status contract -----------------------------------

def test_summarize_shape(full_machine):
    summary = doctor.summarize(doctor.run_checks(today=date(2026, 7, 18)))
    assert set(summary) == {"ok", "required_missing", "checks"}
    for c in summary["checks"]:
        assert {"name", "tier", "ok", "detail", "fix", "degraded_mode", "data"} <= set(c)
