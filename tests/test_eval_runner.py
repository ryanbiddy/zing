from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from myzing.schemas import Breakdown
from tools.eval import run as eval_run
from tools.eval.audio_delivery import parse_ebur128
from tools.eval.make_goldens import CASES, SPEECH_FIXTURE, generate_goldens
from tools.eval.run import SAMPLE_DIRECTORY, evaluate


class TimedAdapter:
    def __call__(self, media_path: Path) -> Breakdown:
        return Breakdown.from_json(
            (SAMPLE_DIRECTORY / "breakdown.json").read_text(encoding="utf-8")
        )

    def performance_for(self, media_path: Path) -> dict:
        return {
            "available": True,
            "stages": {
                "ingest": 1.0,
                "shots": 2.0,
                "transcribe": 3.0,
                "ocr": 4.0,
                "audio": 5.0,
                "render": 6.0,
            },
        }


def test_runner_writes_machine_readable_report(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"

    report = evaluate([SAMPLE_DIRECTORY], report_path, ffmpeg="not-installed-ffmpeg")

    assert report["passed"] is True
    assert report["report_schema_version"] == 5
    assert report["scorer_version"] == "1.3.0"
    assert len(report["manifest_sha256"]) == 64
    assert report["ffmpeg"] is None
    assert report["wall_clock_seconds"] >= 0
    assert report["performance"]["status"] == "tracked-not-gated"
    assert report["performance"]["available_case_count"] == 0
    assert report["audio_delivery"]["advisory_only"] is True
    assert report["audio_delivery"]["integrated_range_lufs"] == [-18.0, -10.0]
    assert report["audio_delivery"]["max_true_peak_dbtp"] == -1.0
    assert report["audio_delivery"]["available_case_count"] == 0
    assert report["profile_eval"]["status"] == "not-run"
    assert report["profile_eval"]["passed"] is None
    assert report["direction_eval"]["status"] == "not-run"
    assert report["direction_eval"]["passed"] is None
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["cases"][0]["audio_delivery"]["available"] is False
    assert saved["cases"][0]["audio_delivery"]["integrated_lufs"] is None
    assert saved["cases"][0]["audio_delivery"]["true_peak_dbtp"] is None
    assert saved["cases"][0]["audio_delivery"]["warnings"] == []
    assert saved["cases"][0]["fixture_hashes"].keys() == {
        "truth.json",
        "breakdown.json",
    }
    matches = saved["cases"][0]["score"]["cuts"]["timing"]["matches"]
    assert [match["delta_seconds"] for match in matches] == [0.0, 0.0]
    caption_match = saved["cases"][0]["score"]["captions"]["similarity"]["matches"][0]
    assert caption_match["start_delta_seconds"] == 0.0
    assert caption_match["end_delta_seconds"] == 0.0
    audio_windows = saved["cases"][0]["score"]["audio"]["window_pattern"]["windows"]
    assert [window["predicted_dbfs"] for window in audio_windows] == [
        -18.0,
        -80.0,
        -18.0,
    ]
    assert saved["cases"][0]["performance"]["available"] is False
    assert "no live study" in saved["cases"][0]["performance"]["reason"]


def test_success_and_error_reports_share_environment_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_run,
        "_report_environment",
        lambda ffmpeg: {"environment_marker": ffmpeg},
    )

    success = evaluate(
        [SAMPLE_DIRECTORY],
        tmp_path / "success.json",
        ffmpeg="success-ffmpeg",
    )
    error_path = tmp_path / "error.json"
    eval_run._write_error_report(
        error_path,
        "error-ffmpeg",
        ValueError("fixture error"),
    )

    assert success["environment_marker"] == "success-ffmpeg"
    error = json.loads(error_path.read_text(encoding="utf-8"))
    assert error["environment_marker"] == "error-ffmpeg"


def test_runner_rejects_empty_case_set(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no evaluation cases"):
        evaluate([], tmp_path / "report.json")


def test_runner_captures_adapter_performance_in_case_and_summary(
    tmp_path: Path,
) -> None:
    report = evaluate(
        [SAMPLE_DIRECTORY],
        tmp_path / "report.json",
        adapter=TimedAdapter(),
        ffmpeg="not-installed-ffmpeg",
    )

    assert report["cases"][0]["performance"]["stages"]["render"] == 6.0
    assert report["performance"]["available_case_count"] == 1
    assert report["performance"]["stages"]["transcribe"]["mean_seconds"] == 3.0


def test_module_cli_passes_on_checked_in_sample(tmp_path: Path) -> None:
    report_path = tmp_path / "cli report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.eval.run",
            "--sample",
            "--report",
            str(report_path),
            "--ffmpeg",
            "not-installed-ffmpeg",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "checked-in-scorer-sample" in result.stdout
    assert "PASS" in result.stdout
    assert json.loads(report_path.read_text(encoding="utf-8"))["passed"] is True


def test_bare_module_cli_names_the_default_sample_mode(tmp_path: Path) -> None:
    report_path = tmp_path / "default report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.eval.run",
            "--report",
            str(report_path),
            "--ffmpeg",
            "not-installed-ffmpeg",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "mode: checked-in sample" in result.stdout


def test_module_cli_writes_report_on_error(tmp_path: Path) -> None:
    report_path = tmp_path / "error report.json"
    empty_goldens = tmp_path / "empty goldens"
    empty_goldens.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.eval.run",
            "--study",
            "--goldens",
            str(empty_goldens),
            "--report",
            str(report_path),
            "--ffmpeg",
            "not-installed-ffmpeg",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["report_schema_version"] == 5
    assert report["profile_eval"]["status"] == "not-run"
    assert report["direction_eval"]["status"] == "not-run"
    assert report["error"]["type"] == "ValueError"
    assert "no evaluation cases" in report["error"]["message"]


@pytest.mark.ffmpeg
def test_make_three_real_goldens_with_hostile_paths(tmp_path: Path) -> None:
    output = tmp_path / "goldens root"

    directories = generate_goldens(output)

    assert len(directories) == 3
    assert any("'" in str(directory) for directory in directories)
    assert [directory.name for directory in directories] == [
        case["directory"] for case in CASES
    ]
    for directory in directories:
        truth = json.loads((directory / "truth.json").read_text(encoding="utf-8"))
        media = directory / truth["media"]
        assert media.stat().st_size > 0
        assert truth["cuts"] == [1.0, 2.0]
        assert truth["audio"]["speech_ratio"] == pytest.approx(2 / 3, abs=0.001)
        assert "tolerance" not in json.dumps(truth)
        assert "drawtext=" in (directory / "filter graph.txt").read_text(
            encoding="utf-8"
        )
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-show_entries",
                "stream=codec_type,width,height,r_frame_rate,sample_rate,channels",
                "-of",
                "json",
                str(media),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        metadata = json.loads(probe.stdout)
        assert float(metadata["format"]["duration"]) == pytest.approx(3.0, abs=0.01)
        video = next(
            stream
            for stream in metadata["streams"]
            if stream["codec_type"] == "video"
        )
        audio = next(
            stream
            for stream in metadata["streams"]
            if stream["codec_type"] == "audio"
        )
        assert (video["width"], video["height"], video["r_frame_rate"]) == (
            320,
            568,
            "30/1",
        )
        assert (audio["sample_rate"], audio["channels"]) == ("48000", 2)


def test_spoken_fixture_has_pinned_public_domain_provenance() -> None:
    provenance_path = SPEECH_FIXTURE.with_name("provenance.json")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(SPEECH_FIXTURE.read_bytes()).hexdigest()

    assert provenance["license"]["spdx"] == "CC-PDDC"
    assert provenance["artifact"]["sha256"] == digest
    with wave.open(str(SPEECH_FIXTURE), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16_000
        assert audio.getnframes() == 16_000


def test_ebur128_parser_uses_final_integrated_and_true_peak_summary() -> None:
    output = """
    I:         -70.0 LUFS
    Peak:      -12.0 dBFS
    Integrated loudness:
      I:         -14.2 LUFS
    True peak:
      Peak:       -1.3 dBFS
    """

    assert parse_ebur128(output) == (-14.2, -1.3)


@pytest.mark.ffmpeg
def test_delivery_warnings_are_reported_but_do_not_gate(
    tmp_path: Path,
) -> None:
    case_directory = tmp_path / "loud case"
    case_directory.mkdir()
    media_path = case_directory / "loud.wav"
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000:duration=1",
            "-af",
            "volume=18dB",
            "-c:a",
            "pcm_s16le",
            str(media_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    truth = json.loads(
        (SAMPLE_DIRECTORY / "truth.json").read_text(encoding="utf-8")
    )
    truth["media"] = media_path.name
    (case_directory / "truth.json").write_text(
        json.dumps(truth),
        encoding="utf-8",
    )
    (case_directory / "breakdown.json").write_text(
        (SAMPLE_DIRECTORY / "breakdown.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    report = evaluate(
        [case_directory],
        tmp_path / "report.json",
    )

    delivery = report["cases"][0]["audio_delivery"]
    assert report["passed"] is True
    assert delivery["integrated_lufs"] > -10.0
    assert delivery["true_peak_dbtp"] > -1.0
    assert len(delivery["warnings"]) == 2
    assert len(report["audio_delivery"]["warnings"]) == 2
