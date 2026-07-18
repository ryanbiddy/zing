from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from myzing.schemas import Breakdown
from tools.eval.make_goldens import CASES, generate_goldens
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
    assert report["report_schema_version"] == 2
    assert report["scorer_version"] == "1.0.0"
    assert len(report["manifest_sha256"]) == 64
    assert report["ffmpeg"] is None
    assert report["wall_clock_seconds"] >= 0
    assert report["performance"]["status"] == "tracked-not-gated"
    assert report["performance"]["available_case_count"] == 0
    saved = json.loads(report_path.read_text(encoding="utf-8"))
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
    assert "N/A" in result.stdout
    assert json.loads(report_path.read_text(encoding="utf-8"))["passed"] is True


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
    assert report["report_schema_version"] == 2
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
