from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from myzing import storage
from myzing.schemas import Breakdown, VideoMeta
from tools.eval.performance import (
    PhaseTimer,
    StudyBenchmarkAdapter,
    budget_assessment,
    summarize_performance,
)


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def test_phase_timer_turns_begin_events_into_stage_spans() -> None:
    clock = FakeClock([0.0, 1.0, 3.0, 6.0, 10.0])
    timer = PhaseTimer(clock)

    timer.start()
    timer.begin("ingest")
    timer.begin("shots")
    timer.begin("audio")
    timer.finish()

    assert timer.report() == {
        "study_total_seconds": 10.0,
        "stage_order": ["ingest", "shots", "audio"],
        "stages": {"ingest": 2.0, "shots": 3.0, "audio": 4.0},
    }


def test_benchmark_adapter_records_study_phases_and_render(tmp_path: Path) -> None:
    media = tmp_path / "fixture.mp4"
    media.write_bytes(b"fixture")
    phases = [
        "ingest",
        "shots",
        "keyframes",
        "transcribe",
        "ocr",
        "audio",
        "markdown",
    ]
    rendered = {}

    def fake_study(source, workspace, phase_callback):
        assert source == str(media)
        assert workspace.is_dir()
        for phase in phases:
            phase_callback(phase)
        return Breakdown(
            meta=VideoMeta(
                source_url=source,
                platform="file",
                duration=3.0,
            ),
            warnings=["transcription skipped in fixture"],
        )

    def fake_render(source, duration, output, ffmpeg, ffprobe):
        rendered.update(
            source=source,
            duration=duration,
            output=output,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )

    clock = FakeClock(
        [0.0, 1.0, 3.0, 6.0, 10.0, 15.0, 21.0, 28.0, 36.0, 45.0, 55.0]
    )
    adapter = StudyBenchmarkAdapter(
        study_fn=fake_study,
        render_fn=fake_render,
        clock=clock,
        ffmpeg="custom-ffmpeg",
        ffprobe="custom-ffprobe",
    )

    breakdown = adapter(media)
    measurement = adapter.performance_for(media)

    assert breakdown.meta.duration == 3.0
    assert measurement["available"] is True
    assert measurement["study_total_seconds"] == 36.0
    assert measurement["render_seconds"] == 10.0
    assert measurement["total_seconds"] == 46.0
    assert measurement["stages"] == {
        "ingest": 2.0,
        "shots": 3.0,
        "keyframes": 4.0,
        "transcribe": 5.0,
        "ocr": 6.0,
        "audio": 7.0,
        "markdown": 8.0,
        "render": 10.0,
    }
    assert measurement["study_warnings"] == [
        "transcription skipped in fixture"
    ]
    assert measurement["budget_assessment"]["status"] == "pass"
    assert rendered["source"] == media
    assert rendered["duration"] == 3.0
    assert rendered["ffmpeg"] == "custom-ffmpeg"
    assert rendered["ffprobe"] == "custom-ffprobe"


def test_performance_summary_flags_cells_over_twice_the_roadmap_budget() -> None:
    fast = budget_assessment(45.0, 250.0)
    warning = budget_assessment(45.0, 450.0)
    defect = budget_assessment(45.0, 601.0)
    cases = [
        {
            "directory": "youtube-short-vertical",
            "performance": {
                "available": True,
                "input_duration_seconds": 45.0,
                "total_seconds": 250.0,
                "budget_assessment": fast,
                "stages": {"ingest": 1.0, "render": 4.0},
            }
        },
        {
            "directory": "x-short-horizontal",
            "performance": {
                "available": True,
                "input_duration_seconds": 45.0,
                "total_seconds": 450.0,
                "budget_assessment": warning,
                "stages": {"ingest": 3.0, "render": 6.0},
            }
        },
        {
            "directory": "instagram-short-vertical",
            "performance": {
                "available": True,
                "input_duration_seconds": 45.0,
                "total_seconds": 601.0,
                "budget_assessment": defect,
                "stages": {"ingest": 2.0, "render": 5.0},
            },
        },
        {
            "directory": "tiktok-short-vertical",
            "performance": {"available": False, "reason": "fetch blocked"},
        },
    ]

    summary = summarize_performance(cases)

    assert fast["status"] == "pass"
    assert warning["status"] == "warning"
    assert defect["status"] == "defect"
    assert defect["defect_threshold_seconds"] == 600.0
    assert summary["status"] == "gated"
    assert summary["passed"] is False
    assert summary["available_case_count"] == 3
    assert summary["total_case_count"] == 4
    assert summary["defect_count"] == 1
    assert summary["defects"][0]["case"] == "instagram-short-vertical"
    assert summary["warning_count"] == 1
    assert summary["unavailable_count"] == 1
    assert summary["stages"]["ingest"] == {
        "total_seconds": 6.0,
        "mean_seconds": 2.0,
        "max_seconds": 3.0,
    }
    assert summary["roadmap_budget"]["scope"] == (
        "zing study on a 30-60 second short"
    )
    assert budget_assessment(120.0, 1_201.0)["status"] == "defect"


def test_benchmark_adapter_can_preserve_study_artifacts(tmp_path: Path) -> None:
    media = tmp_path / "fixture.mp4"
    media.write_bytes(b"fixture")
    workspace = tmp_path / "workspace"

    def fake_study(source, workspace, phase_callback):
        phase_callback("ingest")
        artifact_directory = (
            workspace / "breakdowns" / storage.slug_for(source)
        )
        artifact_directory.mkdir(parents=True)
        return Breakdown(
            meta=VideoMeta(
                source_url=source,
                platform="file",
                duration=3.0,
            )
        )

    adapter = StudyBenchmarkAdapter(
        study_fn=fake_study,
        render_fn=lambda *args: None,
        clock=FakeClock([0.0, 1.0, 2.0, 3.0, 4.0]),
        workspace=workspace,
    )

    adapter(media)

    assert adapter.artifact_directory_for(media) == (
        workspace / "breakdowns" / storage.slug_for(str(media))
    )
