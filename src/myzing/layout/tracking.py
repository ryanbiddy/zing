"""Geometric and color-appearance linking: no named identity or embeddings."""

from __future__ import annotations

import math

from .types import Box, Detection, FaceTrack, FrameDetections, Keyframe, TrackObservation, bounds, number, union


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
                                min(d.confidence for _, _, d in chain), warnings,
                                [TrackObservation(t, d.box, d.appearance) for _, t, d in chain]
                                if any(d.appearance for _, _, d in chain) else []))
    return result


def appearance(image, box):
    """Small RGB histograms, not identity embeddings; lighting changes can veto links."""
    h, w = image.shape[:2]
    crop = image[max(0, int(box.y*h)):min(h, max(1, int(box.bottom*h))),
                 max(0, int(box.x*w)):min(w, max(1, int(box.right*w)))]
    if not crop.size:
        return []
    import numpy as np
    return [float(v / (crop.shape[0] * crop.shape[1] * 3)) for channel in range(3)
            for v in np.histogram(crop[:, :, channel], bins=8, range=(0, 256))[0]]


def stitch_tracks(tracks, *, max_gap=1.25):
    """Conservative fragment links within one shot, using raw observations.

    Held/smoothed intervals may overlap. Two detections at the same sampled
    instant are a hard conflict, even with similar colors or overlapping boxes.
    Missing appearance leaves fragments separate. Confidence is a heuristic.
    """
    from dataclasses import replace
    number(max_gap, "stitch max_gap", 0, 10)
    groups = [[t] for t in tracks]

    def observations(group):
        return sorted((o for t in group for o in t.observations), key=lambda o: o.time)

    def link(a, b):
        aa, bb = observations(a), observations(b)
        if not aa or not bb:
            return None
        if any(abs(x.time-y.time) < 1e-6 for x in aa for y in bb):
            return None
        if aa[0].time > bb[0].time:
            aa, bb = bb, aa
        if bb[0].time < aa[-1].time:
            # Interleaved observations could be two faces with alternating recall.
            return None
        gap = bb[0].time-aa[-1].time
        if gap > max_gap:
            return None
        x, y = aa[-1], bb[0]
        if not x.appearance or len(x.appearance) != len(y.appearance):
            return None
        similarity = 1 - sum(abs(p-q) for p, q in zip(x.appearance, y.appearance)) / 2
        size_ratio = max(x.box.width/y.box.width, y.box.width/x.box.width,
                         x.box.height/y.box.height, y.box.height/x.box.height)
        distance = math.dist(x.box.center, y.box.center) / max(.01, min(x.box.width, x.box.height))
        if similarity < .82 or size_ratio > 1.3 or distance > .45:
            return None
        confidence = min(similarity, 1/size_ratio, 1-distance/2)
        return {"version": 1, "fragments": [t.id for t in [*a, *b]], "gap_seconds": gap,
                "appearance_similarity": similarity, "size_ratio": size_ratio,
                "center_distance_face_units": distance, "confidence": confidence,
                "co_visible_conflicts": 0, "method": "raw-observation position/size/RGB-histogram; not biometric identity"}

    while True:
        candidates = [(e["confidence"], i, j, e) for i, a in enumerate(groups) for j, b in enumerate(groups)
                      if i < j and (e := link(a, b)) is not None]
        if not candidates:
            break
        # An equally plausible alternative is uncertainty, not an arbitrary identity.
        candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
        def endpoints(candidate):
            i, j = candidate[1:3]
            return (i, j) if observations(groups[i])[0].time < observations(groups[j])[0].time else (j, i)
        selected = next((c for c in candidates if not any(
            other is not c and abs(other[0]-c[0]) < .05 and
            (endpoints(c)[0] == endpoints(other)[0] or endpoints(c)[1] == endpoints(other)[1])
            for other in candidates)), None)
        if selected is None:
            break
        _, i, j, evidence = selected
        combined = [*groups[i], *groups[j]]
        obs = observations(combined)
        # Raw boxes preserve the measured face; retain conservative padding from
        # contributing tracks by taking their envelopes at each observation.
        from .types import box_at
        times = sorted({k.time for t in combined for k in t.keyframes})
        keys = [Keyframe(time, union([box_at(t.keyframes, time) for t in combined
                                     if t.keyframes[0].time <= time <= t.keyframes[-1].time])) for time in times]
        merged = replace(combined[0], keyframes=keys, observations=obs,
                         confidence=min(evidence["confidence"], *(t.confidence for t in combined)),
                         warnings=list(dict.fromkeys(w for t in combined for w in t.warnings)),
                         stitching=[e for t in combined for e in t.stitching] + [evidence])
        groups[i] = [merged]
        groups.pop(j)
    return [t for group in groups for t in group]
