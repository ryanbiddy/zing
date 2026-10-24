"""Conservative, versioned additions to the public study shot list.

The two-frame AdaptiveDetector and strong thumbnail content changes propose
boundaries; decoded neighborhoods must show a persistent, isolated picture
change. This map is planning evidence, not ground truth. Imports stay
stdlib-only until decoding.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from myzing.contracts import Record
from myzing.schemas import Shot

METHOD = "adaptive-and-content-confirmed-v2"
ADAPTIVE = "AdaptiveDetector threshold=3, content>=15, minimum=2 frames"
CONTENT = "thumbnail HSV content>=25"
# Rejections beyond this many are counted, not stored (strongest kept).
MAX_REJECTED_RECORDED = 64
# Strobes measured 0.08-0.20 and confirmed real cuts 0.47+ (review corpus, Oct 23).
TONE_RESIDUAL_MAX = .3


@dataclass
class SourceMap(Record):
    fps: float
    duration: float
    base_cuts: list[float]
    candidates: list[dict[str, Any]] = field(default_factory=list)
    # Rejections by proposal and reason; `recorded` of each are in candidates.
    rejected_counts: list[dict[str, Any]] = field(default_factory=list)
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
        keys = set()
        for row in self.rejected_counts:
            key = (row.get("proposal"), row.get("reason"))
            if (set(row) != {"proposal", "reason", "count", "recorded"} or key in keys
                    or not all(isinstance(k, str) for k in key)
                    or type(row["count"]) is not int or type(row["recorded"]) is not int
                    or not 0 <= row["recorded"] <= row["count"] or row["count"] < 1):
                raise ValueError("source map rejection counts are invalid")
            keys.add(key)
        if sum(row["recorded"] for row in self.rejected_counts) != sum(not r["accepted"] for r in self.candidates):
            raise ValueError("source map rejection counts disagree with recorded candidates")


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
    result = SourceMap(fps, duration, [s.start for s in shots[1:]])
    try:
        import cv2
        import scenedetect

        base_frames = {round(t * fps) for t in result.base_cuts}
        # One decode serves both the two-frame AdaptiveDetector proposals and
        # the confirmation thumbnails; a separate detect() pass doubled the cost.
        video = scenedetect.open_video(str(media))
        try:
            proposer = _Proposer(video.frame_size, fps)
            recorder = _Recorder()
            evaluated = set()
            # A rolling window bounds memory and avoids frame-seek ambiguity.
            # Strong content changes also propose cuts: adaptive averages can
            # suppress a true boundary during a moving shot even at min_len=2.
            window = deque(maxlen=9)
            decoded = 0
            while True:
                picture = video.read()
                if picture is False:
                    break
                proposer.feed(picture, video.position)
                height, width = picture.shape[:2]
                window.append(cv2.resize(picture, (192, max(16, round(192 * height / width))),
                                         interpolation=cv2.INTER_AREA))
                decoded += 1
                if len(window) < 9:
                    continue
                # The detector decides frame F when it reads F + 2, so every
                # proposal for the window's center frame is already known.
                frame = decoded - 5
                if frame in base_frames:
                    continue
                proposed = frame in proposer.cuts
                neighborhood = list(window)
                hsv = [cv2.cvtColor(p, cv2.COLOR_BGR2HSV) for p in neighborhood[3:5]]
                content = float(cv2.absdiff(*hsv).mean())
                if not proposed and content < 25:
                    continue
                evaluated.add(frame)
                accepted, evidence = _confirm(neighborhood)
                if not proposed:
                    if evidence["mean_absolute_difference"] < .12 or evidence["local_peak_ratio"] < 1.4:
                        accepted = False
                        evidence["reason"] = "content-only proposal needs a strong isolated boundary"
                    elif any(abs(frame - base) <= 2 for base in base_frames):
                        accepted = False
                        evidence["reason"] = "content peak within two frames of an existing boundary"
                evidence.update(proposal=ADAPTIVE if proposed else CONTENT, thumbnail_content_score=content)
                recorder.add(_decision(frame, accepted, evidence))
            expected = round(shots[-1].end * fps)
            if decoded < expected - 1:
                raise ValueError(f"source-map decode stopped at frame {decoded}; expected about {expected}")
            for frame in sorted(proposer.cuts - base_frames - evaluated):
                recorder.add(_decision(frame, False, {"reason": "insufficient context", "proposal": ADAPTIVE}))
            result.candidates, result.rejected_counts = recorder.finish()
        finally:
            capture = getattr(video, "capture", None)
            if capture is not None:
                capture.release()
    except Exception as exc:
        # Do not retain a partial map after a decode or optional-extra failure.
        result.status = "unmeasured"
        result.candidates, result.rejected_counts = [], []
        result.warnings.append(f"Fine source map unavailable: {exc}; using public study shots. "
                               "Install myzing[study] and restudy to retry.")
    return result


class _Proposer:
    """The two-frame AdaptiveDetector, fed exactly as scenedetect.detect feeds it."""

    def __init__(self, frame_size, fps):
        from scenedetect.detectors import AdaptiveDetector
        from scenedetect.scene_manager import compute_downscale_factor

        from .shots import ADAPTIVE_THRESHOLD

        self.detector = AdaptiveDetector(adaptive_threshold=ADAPTIVE_THRESHOLD, min_scene_len=2)
        self.downscale = compute_downscale_factor(max(frame_size))
        self.fps = fps
        self.cuts: set[int] = set()

    def feed(self, picture, position):
        import cv2

        if self.downscale > 1.0:
            picture = cv2.resize(picture, (max(1, round(picture.shape[1] / self.downscale)),
                                           max(1, round(picture.shape[0] / self.downscale))),
                                 interpolation=cv2.INTER_LINEAR)
        for cut in self.detector.process_frame(position, picture):
            seconds = cut.seconds if hasattr(cut, "seconds") else cut.get_seconds()
            if seconds > 0:
                self.cuts.add(round(seconds * self.fps))


class _Recorder:
    """Every accepted cut, plus a bounded sample of rejections with exact counts.

    Shaky or strobing footage can propose a candidate on most frames; storing
    each one made a ten-minute study's provenance megabytes long.
    """

    def __init__(self):
        self.accepted, self.rejected, self.counts, self.order = [], [], {}, 0

    def add(self, row):
        if row["accepted"]:
            self.accepted.append(row)
            return
        key = (row["evidence"]["proposal"], row["evidence"]["reason"])
        self.counts[key] = self.counts.get(key, 0) + 1
        # Keep the strongest rejected picture changes: the closest calls.
        strength = row["evidence"].get("mean_absolute_difference", 0.0)
        self.order += 1
        item = (strength, -row["frame"], self.order, row)
        if len(self.rejected) < MAX_REJECTED_RECORDED:
            heapq.heappush(self.rejected, item)
        elif item[:3] > self.rejected[0][:3]:
            heapq.heapreplace(self.rejected, item)

    def finish(self):
        kept = [item[3] for item in self.rejected]
        recorded = {}
        for row in kept:
            key = (row["evidence"]["proposal"], row["evidence"]["reason"])
            recorded[key] = recorded.get(key, 0) + 1
        counts = [{"proposal": proposal, "reason": reason, "count": count,
                   "recorded": recorded.get((proposal, reason), 0)}
                  for (proposal, reason), count in sorted(self.counts.items())]
        return sorted(self.accepted + kept, key=lambda r: r["frame"]), counts


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
    correlation = _correlation(a, b)
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
    reason, tone_residual = "persistent isolated picture change", None
    if blank_endpoint:
        reason = "blank flash/fade endpoint; insufficient picture evidence"
    elif jump < .06 or peak_ratio < 3:
        reason = "weak or gradual change"
    elif persistence < .55:
        reason = "brief excursion/flash or continuing motion"
    elif correlation > .92:
        reason = "same structure/exposure change"
    # A strobe or light switch changes tones, often with clipping, but keeps
    # the picture: mapping one frame's tones onto the other leaves little.
    # Only computed when the cheaper checks have not already decided.
    elif (tone_residual := _tone_matched_residual(pictures[3], pictures[4])) < TONE_RESIDUAL_MAX:
        reason = "tone/exposure change explains the picture (strobe or clipping)"
    elif response > .15 and aligned_ratio < .45:
        reason = "translation explains the change"
    elif hist_distance < .12:
        reason = "histogram does not confirm a new picture"
    evidence = {"reason": reason, "mean_absolute_difference": jump, "peak_ratio": peak_ratio,
                "persistence_ratio": persistence, "local_peak_ratio": local_peak_ratio, "gray_correlation": correlation,
                "tone_matched_residual": tone_residual,
                "translation_response": float(response), "aligned_difference_ratio": aligned_ratio,
                "histogram_distance": hist_distance, "context_frames": 9,
                "blank_endpoint": bool(blank_endpoint),
                "confidence_basis": "heuristic confirmation, not a calibrated probability"}
    return reason == "persistent isolated picture change", evidence


def _tone_matched_residual(p, q):
    """Spatial difference left after mapping one picture's tones onto the other's.

    Per-channel histogram matching absorbs any monotonic exposure or color
    change, clipping included. The residual is relative to the reference's own
    spread, so a near-uniform frame cannot explain a picture (or be explained).
    """
    import numpy as np

    def match(source, reference):
        _, inverse, counts = np.unique(source, return_inverse=True, return_counts=True)
        ends = np.cumsum(counts)
        totals = np.concatenate([[0.0], np.cumsum(np.sort(reference, axis=None), dtype=np.float64)])
        return ((totals[ends] - totals[ends - counts]) / counts)[inverse.ravel()].reshape(source.shape)

    residuals = []
    for source, reference in ((q, p), (p, q)):
        reference = reference.astype(np.float64)
        spread = sum(float(np.abs(reference[:, :, c] - reference[:, :, c].mean()).sum()) for c in range(3))
        error = sum(float(np.abs(match(source[:, :, c], reference[:, :, c]) - reference[:, :, c]).sum())
                    for c in range(3))
        residuals.append(error / spread if spread > 0 else 1.0)
    return min(residuals)


def _correlation(a, b):
    import numpy as np

    a, b = a - a.mean(), b - b.mean()
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float((a * b).sum() / norm) if norm > .001 else 0.0
