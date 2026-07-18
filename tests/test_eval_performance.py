from __future__ import annotations

from pathlib import Path

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
    assert measurement["budget_assessment"]["status"] == "not-comparable"
    assert rendered["source"] == media
    assert rendered["duration"] == 3.0
    assert rendered["ffmpeg"] == "custom-ffmpeg"
    assert rendered["ffprobe"] == "custom-ffprobe"


def test_performance_summary_tracks_budget_without_gating() -> None:
    cases = [
        {
            "performance": {
                "available": True,
                "stages": {"ingest": 1.0, "render": 4.0},
            }
        },
        {
            "performance": {
                "available": True,
                "stages": {"ingest": 3.0, "render": 6.0},
            }
        },
        {"performance": {"available": False, "reason": "sample"}},
    ]

    summary = summarize_performance(cases)

    assert summary["status"] == "tracked-not-gated"
    assert summary["available_case_count"] == 2
    assert summary["total_case_count"] == 3
    assert summary["stages"]["ingest"] == {
        "total_seconds": 4.0,
        "mean_seconds": 2.0,
        "max_seconds": 3.0,
    }
    assert summary["roadmap_budget"]["scope"] == (
        "zing study on a 30-60 second short"
    )
    assert budget_assessment(45.0)["status"] == "tracked-not-gated"
    assert budget_assessment(3.0)["status"] == "not-comparable"
