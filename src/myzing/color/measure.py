"""Bounded frame sampling, per-sample statistics, and coverage disclosure."""

import math

from . import ColorError
from .media import check_color_space, frame, local_video, probe, sha256
from .models import Measurement, Sample
from .science import np
from .stats import bounded_pixels, statistics


def sample_plan(duration, count=12, shots=None):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError("sample count must be an integer from 1 to 32")
    if not shots:
        return [(duration * (i + 0.5) / count, None) for i in range(count)]
    intervals = []
    for shot in shots:
        start, end = float(shot.start), float(shot.end)
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration + 0.05):
            raise ValueError("breakdown shot intervals must lie within the video duration")
        intervals.append((start, min(end, duration), int(shot.index)))
    intervals.sort()
    if len({v[2] for v in intervals}) != len(intervals) or any(
        a[1] > b[0] for a, b in zip(intervals, intervals[1:])
    ):
        raise ValueError("breakdown shots must have unique indices and non-overlapping intervals")
    if len(intervals) > count:
        indices = np.linspace(0, len(intervals) - 1, count, dtype=int)
        intervals = [intervals[i] for i in indices]
    allocated = [1] * len(intervals)
    while sum(allocated) < count:
        index = max(range(len(intervals)), key=lambda i: (intervals[i][1] - intervals[i][0]) / allocated[i])
        allocated[index] += 1
    return sorted((start + (end - start) * (j + 0.5) / n, index)
                  for (start, end, index), n in zip(intervals, allocated) for j in range(n))


def quality_warnings(stats):
    warnings = []
    if max(stats.clipping.values()) >= 0.15:
        warnings.append("Heavily clipped sample: at least 15% of pixels have a channel at black or white; low confidence.")
    p = stats.luma_percentiles
    if p[-2] - p[1] < 0.28 and p[1] > 0.08 and p[-2] < 0.85:
        warnings.append("LOG-like/flat tonal range: this may also be a low-contrast SDR scene. Confirm the input transform; low confidence.")
    return warnings


def measure_video(path, *, count=12, shots=None):
    path = local_video(path)
    duration, source_width, source_height, metadata = probe(path)
    warnings = check_color_space(metadata)
    plan = sample_plan(duration, count, shots)
    ratio = 160 / max(source_width, source_height)
    width, height = max(1, round(source_width * ratio)), max(1, round(source_height * ratio))
    samples, frames, pixels = [], [], []
    for timestamp, shot_index in plan:
        try:
            rgb = frame(path, timestamp, width, height)
        except ColorError as exc:
            warnings.append(f"Sample {timestamp:.6f}s unavailable: {exc}")
            continue
        px = bounded_pixels(rgb)
        measured = statistics(px)
        warnings.extend(f"At {timestamp:.6f}s: {w}" for w in quality_warnings(measured))
        samples.append(Sample(timestamp, shot_index, measured))
        frames.append(rgb)
        pixels.append(px)
    if not samples:
        raise ColorError("No usable frames were sampled. Check FFmpeg and the input video.")
    pooled = np.concatenate(pixels)
    aggregate = statistics(pooled)
    shot_indices = {v.shot_index for v in samples if v.shot_index is not None}
    coverage = {
        "requested_samples": float(len(plan)), "usable_samples": float(len(samples)),
        "sample_fraction": len(samples) / len(plan),
        "temporal_span_fraction": (samples[-1].timestamp - samples[0].timestamp) / duration,
        "shot_fraction": len(shot_indices) / len(shots) if shots else 0.0,
        "shots_supplied": float(len(shots or [])),
    }
    confidence = 0.85 * coverage["sample_fraction"] * min(1.0, len(samples) / 4)
    if shots:
        confidence *= coverage["shot_fraction"]
    if any("incomplete" in w for w in warnings):
        confidence = min(confidence, 0.6)
    if any("low confidence" in w for w in warnings):
        confidence = min(confidence, 0.2)
    if len(samples) != len(plan) or (shots and len(shot_indices) != len(shots)):
        warnings.append("Sampling coverage is incomplete; unsampled shots may have a different grade.")
    warnings.append("Frame timestamps are requested seek positions; sparse samples cannot establish full-frame coverage.")
    measurement = Measurement(str(path), sha256(path), duration, samples, aggregate,
                              coverage, confidence, metadata, list(dict.fromkeys(warnings)))
    return measurement, frames, pooled
