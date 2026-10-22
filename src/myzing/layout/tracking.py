"""Geometric linking only: no face identity or embeddings."""

from __future__ import annotations

import math

from .types import Box, Detection, FaceTrack, FrameDetections, Keyframe, bounds, number, union


def iou(a: Box, b: Box) -> float:
    area = max(0, min(a.right, b.right) - max(a.x, b.x)) * max(
        0, min(a.bottom, b.bottom) - max(a.y, b.y))
    return area / (a.width * a.height + b.width * b.height - area)


def build_tracks(
    frames: list[FrameDetections], *, duration: float, max_gap: float = 1.5,
    centroid_gate: float = 0.35, min_iou: float = 0.1, smooth_radius: int = 1,
    margin: float = 0.04,
) -> list[FaceTrack]:
    """Link with IoU and a centroid gate, bridge short gaps, then smooth/pad.

    Smoothing uses a centered mean, expanded to contain the measured box.
    This prevents the filter from erasing an observed face edge. Endpoints
    are held for max_gap seconds; longer gaps remain explicitly uncertain.
    """
    number(duration, "duration", 1e-6)
    number(max_gap, "max_gap", 1e-6, 10)
    number(centroid_gate, "centroid_gate", 1e-6, 2)
    number(min_iou, "min_iou", 0, 1)
    number(margin, "margin", 0, 0.5)
    if type(smooth_radius) is not int or not 0 <= smooth_radius <= 10:
        raise ValueError("smooth_radius must be an integer from 0 to 10")
    if any(a.time >= b.time for a, b in zip(frames, frames[1:])):
        raise ValueError("detection frames must have increasing timestamps")
    if any(f.time > duration for f in frames):
        raise ValueError("sample time exceeds video duration")
    chains: list[list[tuple[int, float, Detection]]] = []
    for index, frame in enumerate(frames):
        pairs = []
        for track_index, chain in enumerate(chains):
            _, last_time, last = chain[-1]
            if frame.time - last_time > max_gap:
                continue
            for detection_index, detection in enumerate(frame.detections):
                distance = math.dist(last.box.center, detection.box.center)
                overlap = iou(last.box, detection.box)
                if distance <= centroid_gate and (overlap >= min_iou or distance <= centroid_gate / 2):
                    pairs.append((-overlap, distance, track_index, detection_index))
        used_tracks, used_detections = set(), set()
        for _, _, track_index, detection_index in sorted(pairs):
            if track_index in used_tracks or detection_index in used_detections:
                continue
            chains[track_index].append((index, frame.time, frame.detections[detection_index]))
            used_tracks.add(track_index)
            used_detections.add(detection_index)
        for detection_index, detection in enumerate(frame.detections):
            if detection_index not in used_detections:
                chains.append([(index, frame.time, detection)])

    result = []
    for index, chain in enumerate(chains):
        keys = []
        warnings = []
        for j, (_, time, detection) in enumerate(chain):
            window = [d.box for _, _, d in chain[max(0, j - smooth_radius):j + smooth_radius + 1]]
            smoothed = bounds(*(sum(getattr(b, attr) for b in window) / len(window)
                                for attr in ("x", "y", "right", "bottom")))
            keys.append(Keyframe(time, union([detection.box, smoothed]).pad(margin)))
        if any(b[0] - a[0] > 1 for a, b in zip(chain, chain[1:])):
            warnings.append("occlusion_gap: missing detections bridged by linear interpolation")
        start = max(0, keys[0].time - max_gap)
        end = min(duration, keys[-1].time + max_gap)
        if start < keys[0].time:
            keys.insert(0, Keyframe(start, keys[0].box))
        if end > keys[-1].time:
            keys.append(Keyframe(end, keys[-1].box))
        if start > 0 or end < duration:
            warnings.append("track_limited: face position outside the held interval is unknown")
        result.append(FaceTrack(f"face-{index + 1}", keys,
                                min(d.confidence for _, _, d in chain), warnings))
    return result
