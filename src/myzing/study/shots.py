"""Shot detection -> `Shot[]`, plus the derived pacing metrics.

Detector choice (R1-A, evidence over defaults): PySceneDetect
AdaptiveDetector — best PySceneDetect F1 on the only short-form benchmark
(AutoShot SHOT: 73.86 vs 69.26 ContentDetector; the paper reports SHOT's
average shot length as 2.59s) — with `min_scene_len` lowered to ~0.3s.
That floor is now MEASURED against SHOT's published annotations rather
than asserted (handoff/research/SHOT-THRESHOLD-AUDIT-2026-07-19.md, 344
videos / 6,245 shots): the 0.6s-equivalent default would merge 13.5% of
real short-form shots, and our 0.3s floor still merges 4.7% — so Zing's
cut rate is a slight UNDER-count on fast-montage content, by construction.
Other blind spots, recorded rather than hidden: gradual transitions
under-detected, flash/strobe edits can over-cut. S2 upgrade path is transnetv2-pytorch behind this same
function.

scenedetect is an optional [study] dependency and is imported lazily; when
absent, shots are honestly skipped with a warning (doctor reports the fix).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from myzing.schemas import Shot

ADAPTIVE_THRESHOLD = 3.0
MIN_SCENE_LEN_S = 0.3


@dataclass
class ShotResult:
    shots: list[Shot] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def detect_shots(media_path: Path, duration: float, fps: float) -> ShotResult:
    result = ShotResult()
    min_scene_len_frames = max(2, round(MIN_SCENE_LEN_S * (fps or 30.0)))
    try:
        spans, version = _run_detector(str(media_path), min_scene_len_frames)
    except ImportError:
        result.warnings.append(
            "shot detection skipped: scenedetect not installed "
            "(pip install myzing[study])"
        )
        return result
    except Exception as e:  # decode failure etc. — honest skip, never a guess
        result.warnings.append(
            f"shot detection failed: {e} — scenedetect is installed but "
            "could not read this file; run 'zing doctor' to check the "
            "decode stack"
        )
        return result

    if not spans and duration > 0:
        # Defensive: a video with no detected cuts is still one shot.
        spans = [(0.0, duration)]

    result.shots = [
        Shot(index=i, start=round(s, 3), end=round(e, 3))
        for i, (s, e) in enumerate(spans)
        if e > s
    ]
    result.provenance = {
        "shot_detector": f"scenedetect-{version} AdaptiveDetector",
        "adaptive_threshold": ADAPTIVE_THRESHOLD,
        "min_scene_len_s": MIN_SCENE_LEN_S,
    }
    return result


def _run_detector(
    media_path: str, min_scene_len_frames: int
) -> tuple[list[tuple[float, float]], str]:
    """The one seam that touches scenedetect (tests mock exactly this)."""
    import scenedetect
    from scenedetect.detectors import AdaptiveDetector

    scenes = scenedetect.detect(
        media_path,
        AdaptiveDetector(
            adaptive_threshold=ADAPTIVE_THRESHOLD,
            min_scene_len=min_scene_len_frames,
        ),
        start_in_scene=True,
    )
    def _t(tc):
        # scenedetect renamed get_seconds() -> .seconds (deprecation seen
        # live by the real-seam test); support both so the floating dep
        # can't break us in either direction.
        return tc.seconds if hasattr(tc, "seconds") else tc.get_seconds()

    return (
        [(_t(start), _t(end)) for start, end in scenes],
        getattr(scenedetect, "__version__", "unknown"),
    )


# -- derived pacing (pinned definitions in schemas.py) ----------------------

def avg_shot_duration(shots: list[Shot]) -> float:
    if not shots:
        return 0.0
    return round(sum(s.duration for s in shots) / len(shots), 3)


def cuts_per_10s(shots: list[Shot], duration: float) -> list[float]:
    """Pinned definition: non-overlapping 10s windows from t=0; count of
    cuts per window; trailing partial window counted raw, NOT scaled.

    A cut is the boundary between consecutive shots (the video start is not
    a cut). Empty shots (measurement skipped) -> empty list, so a skip
    stays distinguishable from "no cuts" (which yields windows of zeros).
    """
    if not shots or duration <= 0:
        return []
    cut_times = [s.start for s in shots[1:]]
    n_windows = max(1, math.ceil(duration / 10.0))
    windows = [0.0] * n_windows
    for t in cut_times:
        i = min(int(t // 10.0), n_windows - 1)
        windows[i] += 1.0
    return windows
