"""Conservative, versioned additions to the public study shot list.

The two-frame AdaptiveDetector and strong thumbnail content changes propose
boundaries; decoded neighborhoods must show a persistent, isolated picture
change. This map is planning evidence, not ground truth. Imports stay
stdlib-only until decoding.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from myzing.contracts import Record
from myzing.schemas import Shot

METHOD = "adaptive-and-content-confirmed-v1"


@dataclass
class SourceMap(Record):
    fps: float
    duration: float
    base_cuts: list[float]
    candidates: list[dict[str, Any]] = field(default_factory=list)
    status: str = "measured"
    warnings: list[str] = field(default_factory=list)
    method: str = METHOD
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if self.fps <= 0 or self.duration <= 0:
            raise ValueError("source map requires positive fps and duration")
        if self.status not in {"measured", "unmeasured"} or self.method != METHOD:
            raise ValueError("unsupported source map status or method; restudy the source")
        if self.base_cuts != sorted(set(self.base_cuts)) or any(
            not 0 < t < self.duration for t in self.base_cuts
        ):
            raise ValueError("source map base cuts must be ordered inside the video")
        seen = set()
        for row in self.candidates:
            frame = row.get("frame")
            if type(frame) is not int or frame in seen or not 0 < frame / self.fps < self.duration:
                raise ValueError("source map candidate frame is invalid or duplicated")
            seen.add(frame)
            if type(row.get("accepted")) is not bool or row.get("confidence") not in {"high", "rejected"}:
                raise ValueError("source map candidate requires a decision and confidence")
            if row["accepted"] != (row["confidence"] == "high") or not isinstance(row.get("evidence"), dict):
                raise ValueError("source map candidate has inconsistent evidence")


def planning_shots(breakdown) -> list[Shot]:
    """Use validated extra cuts; historical studies retain their original map."""
    data = breakdown.provenance.get("source_map")
    if data is None:
        return breakdown.shots
    source_map = SourceMap.from_dict(data)
    if (abs(source_map.duration - breakdown.meta.duration) > .001
            or abs(source_map.fps - breakdown.meta.fps) > .001
            or source_map.base_cuts != [s.start for s in breakdown.shots[1:]]):
        raise ValueError("source map does not match study shots/clock; restudy the source")
    if source_map.status != "measured" or not breakdown.shots:
        return breakdown.shots
    extra = [r["frame"] / source_map.fps for r in source_map.candidates if r["accepted"]]
    if not extra:
        return breakdown.shots
    # Split each original interval independently: never fill an unmeasured gap.
    shots = []
    for shot in breakdown.shots:
        boundaries = [shot.start, *sorted(t for t in extra if shot.start < t < shot.end), shot.end]
        for start, end in zip(boundaries, boundaries[1:]):
            shots.append(Shot(index=len(shots), start=start, end=end,
                              keyframe=shot.keyframe if start == shot.start else ""))
    return shots


def build_source_map(media: Path, duration: float, fps: float, shots: list[Shot]) -> SourceMap:
    from .shots import _run_detector

    result = SourceMap(fps, duration, [s.start for s in shots[1:]])
    try:
        import cv2

        spans, _ = _run_detector(str(media), 2)
        base_frames = {round(t * fps) for t in result.base_cuts}
        proposed = {round(start * fps) for start, _ in spans if start > 0} - base_frames
        capture = cv2.VideoCapture(str(media))
        try:
            if not capture.isOpened():
                raise ValueError("could not decode source-map neighborhoods")
            # A rolling window bounds memory and avoids frame-seek ambiguity.
            # Strong content changes also propose cuts: adaptive averages can
            # suppress a true boundary during a moving shot even at min_len=2.
            window = deque(maxlen=9)
            decoded = 0
            while True:
                ok, picture = capture.read()
                if not ok:
                    break
                height, width = picture.shape[:2]
                window.append(cv2.resize(picture, (192, max(16, round(192 * height / width))),
                                         interpolation=cv2.INTER_AREA))
                decoded += 1
                if len(window) < 9:
                    continue
                frame = decoded - 5
                if frame in base_frames:
                    continue
                neighborhood = list(window)
                hsv = [cv2.cvtColor(p, cv2.COLOR_BGR2HSV) for p in neighborhood[3:5]]
                content = float(cv2.absdiff(*hsv).mean())
                if frame not in proposed and content < 25:
                    continue
                accepted, evidence = _confirm(neighborhood)
                if frame not in proposed:
                    if evidence["mean_absolute_difference"] < .12 or evidence["local_peak_ratio"] < 1.4:
                        accepted = False
                        evidence["reason"] = "content-only proposal needs a strong isolated boundary"
                    elif any(abs(frame - base) <= 2 for base in base_frames):
                        accepted = False
                        evidence["reason"] = "content peak within two frames of an existing boundary"
                evidence.update(proposal=("AdaptiveDetector threshold=3, content>=15, minimum=2 frames"
                                          if frame in proposed else "thumbnail HSV content>=25"),
                                thumbnail_content_score=content)
                result.candidates.append(_decision(frame, accepted, evidence))
            expected = round(spans[-1][1] * fps) if spans else math.floor(duration * fps)
            if decoded < expected - 1:
                raise ValueError(f"source-map decode stopped at frame {decoded}; expected about {expected}")
            seen = {r["frame"] for r in result.candidates}
            for frame in sorted(proposed - seen):
                result.candidates.append(_decision(frame, False, {"reason": "insufficient context"}))
            result.candidates.sort(key=lambda r: r["frame"])
        finally:
            capture.release()
    except Exception as exc:
        # Do not retain a partial map after a decode or optional-extra failure.
        result.status = "unmeasured"
        result.candidates = []
        result.warnings.append(f"Fine source map unavailable: {exc}; using public study shots. "
                               "Install myzing[study] and restudy to retry.")
    return result


def _decision(frame, accepted, evidence):
    return {"frame": frame, "accepted": accepted,
            "confidence": "high" if accepted else "rejected", "evidence": evidence}


def _confirm(pictures):
    import cv2
    import numpy as np

    frames = [p.astype(np.float32) / 255 for p in pictures]
    difference = lambda a, b: float(np.abs(a - b).mean())
    jump = difference(frames[3], frames[4])
    surrounding = [difference(frames[i - 1], frames[i]) for i in (1, 2, 3, 5, 6, 7, 8)]
    peak_ratio = jump / max(.001, float(np.median(surrounding)))
    local_peak_ratio = jump / max(.001, difference(frames[2], frames[3]), difference(frames[4], frames[5]))
    # A brief excursion returns to a pre-cut picture, unlike a new shot.
    persistence = min(difference(a, b) for a in frames[:4] for b in frames[4:]) / max(.001, jump)
    a, b = [cv2.cvtColor(p, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255 for p in pictures[3:5]]
    blank_endpoint = any(p.std() < .015 and (p.mean() < .03 or p.mean() > .97) for p in (a, b))
    centered_a, centered_b = a - a.mean(), b - b.mean()
    norm = float(np.linalg.norm(centered_a) * np.linalg.norm(centered_b))
    correlation = float((centered_a * centered_b).sum() / norm) if norm > .001 else 0.0
    # Exposure pulses preserve image structure. Translation preserves it after
    # alignment, even when unaligned frame differences look like a hard cut.
    shift, response = cv2.phaseCorrelate(a, b)
    aligned = cv2.warpAffine(b, np.float32([[1, 0, -shift[0]], [0, 1, -shift[1]]]),
                            (b.shape[1], b.shape[0]), borderMode=cv2.BORDER_CONSTANT)
    mask = cv2.warpAffine(np.ones_like(b), np.float32([[1, 0, -shift[0]], [0, 1, -shift[1]]]),
                         (b.shape[1], b.shape[0]), flags=cv2.INTER_NEAREST) > .99
    aligned_ratio = (float(np.abs(a[mask] - aligned[mask]).mean()) / max(.001, difference(a, b))
                     if mask.mean() > .6 else 1.0)
    histograms = [cv2.calcHist([p], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3).ravel()
                  for p in pictures[3:5]]
    hist_distance = float(np.abs(histograms[0] / histograms[0].sum()
                                 - histograms[1] / histograms[1].sum()).sum() / 2)
    reason = "persistent isolated picture change"
    if blank_endpoint:
        reason = "blank flash/fade endpoint; insufficient picture evidence"
    elif jump < .06 or peak_ratio < 3:
        reason = "weak or gradual change"
    elif persistence < .55:
        reason = "brief excursion/flash or continuing motion"
    elif correlation > .92:
        reason = "same structure/exposure change"
    elif response > .15 and aligned_ratio < .45:
        reason = "translation explains the change"
    elif hist_distance < .12:
        reason = "histogram does not confirm a new picture"
    evidence = {"reason": reason, "mean_absolute_difference": jump, "peak_ratio": peak_ratio,
                "persistence_ratio": persistence, "local_peak_ratio": local_peak_ratio, "gray_correlation": correlation,
                "translation_response": float(response), "aligned_difference_ratio": aligned_ratio,
                "histogram_distance": hist_distance, "context_frames": 9,
                "blank_endpoint": bool(blank_endpoint),
                "confidence_basis": "heuristic confirmation, not a calibrated probability"}
    return reason == "persistent isolated picture change", evidence
