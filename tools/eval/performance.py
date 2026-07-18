"""Non-gating study/render performance measurements for eval reports."""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from myzing import storage
from myzing.schemas import Breakdown, Clip, EDL


ROADMAP_BUDGET = {
    "scope": "zing study on a 30-60 second short",
    "target": "low single-digit minutes on Ryan's PC with GPU whisper",
    "cpu_fallback": "must remain honest",
    "failure_example": "20 minutes is a failed gate",
    "status": "tracked-not-gated",
    "source": "handoff/ROADMAP.md#done-criteria",
}
REFERENCE_DURATION_MIN = 30.0
REFERENCE_DURATION_MAX = 60.0


def _rounded(value: float) -> float:
    return round(value, 6)


class PhaseTimer:
    """Measure phase spans from a begin-only callback."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._current_phase: str | None = None
        self._current_started_at: float | None = None
        self._stages: dict[str, float] = {}
        self._order: list[str] = []

    def start(self) -> None:
        if self._started_at is not None:
            raise RuntimeError("phase timer has already started")
        self._started_at = self._clock()

    def begin(self, phase: str) -> None:
        if self._started_at is None:
            self.start()
        now = self._clock()
        self._close_current(now)
        self._current_phase = phase
        self._current_started_at = now
        self._order.append(phase)

    def finish(self) -> None:
        if self._started_at is None:
            self.start()
        now = self._clock()
        self._close_current(now)
        self._finished_at = now

    def _close_current(self, now: float) -> None:
        if self._current_phase is None or self._current_started_at is None:
            return
        elapsed = max(0.0, now - self._current_started_at)
        self._stages[self._current_phase] = (
            self._stages.get(self._current_phase, 0.0) + elapsed
        )
        self._current_phase = None
        self._current_started_at = None

    def report(self) -> dict[str, Any]:
        if self._started_at is None or self._finished_at is None:
            raise RuntimeError("phase timer must be finished before reporting")
        return {
            "study_total_seconds": _rounded(
                max(0.0, self._finished_at - self._started_at)
            ),
            "stage_order": list(self._order),
            "stages": {
                phase: _rounded(seconds) for phase, seconds in self._stages.items()
            },
        }


StudyFunction = Callable[..., Breakdown]
RenderFunction = Callable[[Path, float, Path, str, str], None]


def _load_study() -> StudyFunction:
    try:
        from myzing.study.api import study
    except ImportError as exc:
        raise RuntimeError("Lane A study API is unavailable") from exc
    return study


def _render_source(
    media_path: Path,
    duration: float,
    output_path: Path,
    ffmpeg: str,
    ffprobe: str,
) -> None:
    from myzing.render.pipeline import render_edl

    render_edl(
        EDL(clips=[Clip(str(media_path), 0.0, duration, 0.0)]),
        output_path,
        base_dir=media_path.parent,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )


@contextmanager
def _study_workspace(root: Path | None):
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        yield root
        return
    with tempfile.TemporaryDirectory(prefix="zing-eval-study-") as workspace:
        yield Path(workspace)


class StudyBenchmarkAdapter:
    """Run Lane A study plus a representative default-profile render."""

    def __init__(
        self,
        *,
        study_fn: StudyFunction | None = None,
        render_fn: RenderFunction = _render_source,
        clock: Callable[[], float] = time.perf_counter,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        workspace: Path | None = None,
    ) -> None:
        self._study_fn = study_fn
        self._render_fn = render_fn
        self._clock = clock
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._workspace = workspace
        self._records: dict[str, dict[str, Any]] = {}
        self._artifact_directories: dict[str, Path] = {}

    def __call__(self, media_path: Path) -> Breakdown:
        media_path = media_path.resolve()
        study_fn = self._study_fn or _load_study()
        timer = PhaseTimer(self._clock)
        with _study_workspace(self._workspace) as workspace:
            timer.start()
            try:
                breakdown = study_fn(
                    str(media_path),
                    workspace=workspace,
                    phase_callback=timer.begin,
                )
            finally:
                timer.finish()
            if self._workspace is not None:
                self._artifact_directories[str(media_path)] = (
                    workspace
                    / "breakdowns"
                    / storage.slug_for(str(media_path))
                )

        measurement = timer.report()
        render_started = self._clock()
        with tempfile.TemporaryDirectory(prefix="zing-eval-render-") as render_dir:
            self._render_fn(
                media_path,
                breakdown.meta.duration,
                Path(render_dir) / "benchmark.mp4",
                self._ffmpeg,
                self._ffprobe,
            )
        render_seconds = max(0.0, self._clock() - render_started)
        measurement["stages"]["render"] = _rounded(render_seconds)
        measurement["stage_order"].append("render")
        measurement["render_seconds"] = _rounded(render_seconds)
        measurement["total_seconds"] = _rounded(
            measurement["study_total_seconds"] + render_seconds
        )
        measurement["input_duration_seconds"] = _rounded(
            breakdown.meta.duration
        )
        measurement["real_time_factor"] = (
            _rounded(measurement["total_seconds"] / breakdown.meta.duration)
            if breakdown.meta.duration > 0
            else None
        )
        measurement["render_profile"] = {
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
        }
        measurement["study_warnings"] = list(breakdown.warnings)
        measurement["budget_assessment"] = budget_assessment(
            breakdown.meta.duration
        )
        measurement["available"] = True
        self._records[str(media_path)] = measurement
        return breakdown

    def performance_for(self, media_path: Path) -> dict[str, Any]:
        return self._records.get(
            str(media_path.resolve()),
            {
                "available": False,
                "reason": "no benchmark record for this media path",
            },
        )

    def artifact_directory_for(self, media_path: Path) -> Path | None:
        return self._artifact_directories.get(str(media_path.resolve()))


def budget_assessment(input_duration_seconds: float) -> dict[str, Any]:
    comparable = (
        REFERENCE_DURATION_MIN
        <= input_duration_seconds
        <= REFERENCE_DURATION_MAX
    )
    return {
        "status": "tracked-not-gated" if comparable else "not-comparable",
        "comparable_duration": comparable,
        "reason": (
            "input is in the ROADMAP's 30-60 second reference range"
            if comparable
            else "input is outside the ROADMAP's 30-60 second reference range"
        ),
    }


def unavailable_performance(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def summarize_performance(cases: list[dict[str, Any]]) -> dict[str, Any]:
    available = [
        case["performance"]
        for case in cases
        if case.get("performance", {}).get("available")
    ]
    stage_values: dict[str, list[float]] = {}
    for measurement in available:
        for stage, seconds in measurement["stages"].items():
            stage_values.setdefault(stage, []).append(float(seconds))
    stages = {
        stage: {
            "total_seconds": _rounded(sum(values)),
            "mean_seconds": _rounded(sum(values) / len(values)),
            "max_seconds": _rounded(max(values)),
        }
        for stage, values in stage_values.items()
    }
    return {
        "status": "tracked-not-gated",
        "roadmap_budget": dict(ROADMAP_BUDGET),
        "available_case_count": len(available),
        "total_case_count": len(cases),
        "stages": stages,
    }
