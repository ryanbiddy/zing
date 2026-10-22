"""Deterministic placement with continuous collision checks, not frame guesses."""

from __future__ import annotations

import math

from .types import (
    Box, CaptionEvent, EventLayout, FaceTrack, Keyframe, LayoutPlan, Mask,
    OverlapCheck, ZONES, box_at, number, union, validate_path,
)


def _intersects(a: Box, b: Box) -> bool:
    return (min(a.right, b.right) - max(a.x, b.x) > 1e-12 and
            min(a.bottom, b.bottom) - max(a.y, b.y) > 1e-12)


def _moving_intersects(a0: Box, a1: Box, b0: Box, b1: Box) -> bool:
    """Solve four linear strict inequalities over u in [0,1].

    Axis-aligned boxes overlap iff all four separations are positive.
    Intersect their time intervals to catch collisions between keyframes,
    including very brief crossings. Touching edges are allowed.
    """
    def separations(a, b):
        return (a.right - b.x, b.right - a.x, a.bottom - b.y, b.bottom - a.y)

    low, high = 0.0, 1.0
    for start, end in zip(separations(a0, b0), separations(a1, b1)):
        delta = end - start
        if abs(delta) < 1e-15:
            if start <= 1e-12:
                return False
        elif delta > 0:
            low = max(low, (1e-12 - start) / delta)
        else:
            high = min(high, (1e-12 - start) / delta)
    return low < high


def _paths_intersect(a: list[Keyframe], b: list[Keyframe], start: float, end: float) -> bool:
    if start > end:
        return False
    if start == end:
        return _intersects(box_at(a, start), box_at(b, start))
    times = sorted({start, end, *(k.time for k in a + b if start < k.time < end)})
    return any(_moving_intersects(box_at(a, t0), box_at(a, t1),
                                  box_at(b, t0), box_at(b, t1))
               for t0, t1 in zip(times, times[1:]))


def check_overlap(path: list[Keyframe], tracks: list[FaceTrack], masks: list[Mask]) -> OverlapCheck:
    """Check the whole path against already padded face tracks and UI masks."""
    validate_path(path)
    start, end = path[0].time, path[-1].time
    faces = [t.id for t in tracks if _paths_intersect(
        path, t.keyframes, max(start, t.keyframes[0].time), min(end, t.keyframes[-1].time))]
    blocked = [m.name for m in masks if _paths_intersect(
        path, [Keyframe(start, m.box)], start, end)]
    return OverlapCheck(not faces and not blocked, faces, blocked)


def _at(center: tuple[float, float] | list[float], width: float, height: float) -> Box:
    return Box(max(0, min(1 - width, center[0] - width / 2)),
               max(0, min(1 - height, center[1] - height / 2)), width, height)


def _static(box: Box, start: float, end: float) -> list[Keyframe]:
    return [Keyframe(start, box), Keyframe(end, box)]


def _candidates(event: CaptionEvent, width: float, height: float,
                tracks: list[FaceTrack], masks: list[Mask],
                anchors: list[tuple[float, float]] | None) -> list[Box]:
    centers = list(ZONES.values())
    centers += [(width / 2 + (1 - width) * x / 8,
                 height / 2 + (1 - height) * y / 12)
                for y in range(13) for x in range(9)]
    centers += anchors or []
    # Obstacle-edge candidates also find narrow gaps between grid points.
    obstacles = [m.box for m in masks]
    for track in tracks:
        start = max(event.start, track.keyframes[0].time)
        end = min(event.end, track.keyframes[-1].time)
        if start <= end:
            obstacles.append(union([box_at(track.keyframes, start), box_at(track.keyframes, end)] +
                                   [k.box for k in track.keyframes if start < k.time < end]))
    xs, ys = {width / 2, 1 - width / 2}, {height / 2, 1 - height / 2}
    for box in obstacles:
        xs.update((box.x - width / 2, box.right + width / 2))
        ys.update((box.y - height / 2, box.bottom + height / 2))
    preferred = ZONES[event.preferred_anchor] if isinstance(event.preferred_anchor, str) else event.preferred_anchor
    # Bound candidate count on crowded footage, retaining nearest edges.
    xs = sorted(xs, key=lambda x: (abs(x - preferred[0]), x))[:24]
    ys = sorted(ys, key=lambda y: (abs(y - preferred[1]), y))[:24]
    centers += [(x, y) for x in xs for y in ys if width / 2 <= x <= 1 - width / 2
                and height / 2 <= y <= 1 - height / 2]
    boxes = list(dict.fromkeys(_at(c, width, height) for c in centers))
    return sorted(boxes, key=lambda b: (math.dist(b.center, preferred), b.y, b.x))


def _short_path(event: CaptionEvent, candidates: list[Box], tracks: list[FaceTrack],
                masks: list[Mask], reference: Box) -> list[Keyframe] | None:
    """Bounded three-keyframe search. Every connecting segment is checked."""
    times = [event.start, (event.start + event.end) / 2, event.end]
    layers = []
    for time in times:
        free = [b for b in candidates if check_overlap([Keyframe(time, b)], tracks, masks).safe]
        free.sort(key=lambda b: (math.dist(b.center, reference.center), b.y, b.x))
        layers.append(free[:32])
    states = [(math.dist(b.center, reference.center), [Keyframe(times[0], b)]) for b in layers[0]]
    for time, layer in zip(times[1:], layers[1:]):
        next_states = []
        for box in layer:
            best = None
            for cost, path in states:
                step = [path[-1], Keyframe(time, box)]
                if check_overlap(step, tracks, masks).safe:
                    candidate = (cost + math.dist(path[-1].box.center, box.center), path + [step[-1]])
                    if best is None or candidate[0] < best[0]:
                        best = candidate
            if best is not None:
                next_states.append(best)
        states = next_states
        if not states:
            return None
    return min(states, key=lambda item: item[0])[1] if states else None


def choose_layout(events: list[CaptionEvent], tracks: list[FaceTrack], masks: list[Mask], *,
                  platform: str = "none", anchors: list[tuple[float, float]] | None = None,
                  allow_motion: bool = True, shrink_scales: tuple[float, ...] = (0.85, 0.7, 0.55)) -> LayoutPlan:
    """Prefer anchor, previous position, nearest zone, short path, then shrink.

    A plate fallback stays unsafe if it overlaps. Search exhaustion is reported
    as infeasible under this bounded policy, not a proof about all possible paths.
    """
    if len({e.id for e in events}) != len(events):
        raise ValueError("caption event ids must be unique")
    if len({t.id for t in tracks}) != len(tracks):
        raise ValueError("face track ids must be unique")
    for center in anchors or []:
        if len(center) != 2:
            raise ValueError("candidate anchors must be [center_x, center_y]")
        for coordinate in center:
            number(coordinate, "anchor coordinate", 0, 1)
    for scale in shrink_scales:
        number(scale, "shrink scale", 0.1, 0.99)
    previous = None
    layouts = []
    for event in sorted(events, key=lambda e: (e.start, e.end, e.id)):
        warnings = []
        chosen = None
        if event.path:
            check = check_overlap(event.path, tracks, masks)
            if check.safe:
                chosen = EventLayout(event.id, event.start, event.end, "explicit-path", check, path=event.path)
            else:
                warnings.append("explicit_path_blocked: requested path overlaps a face or UI mask; replanned")
        for scale in (1.0, *shrink_scales) if chosen is None else ():
            width, height = event.width * scale, event.height * scale
            anchor = ZONES[event.preferred_anchor] if isinstance(event.preferred_anchor, str) else event.preferred_anchor
            preferred = _at(anchor, width, height)
            candidates = _candidates(event, width, height, tracks, masks, anchors)
            ranked = [(preferred, "preferred-anchor")]
            if previous is not None:
                ranked.append((_at(previous.center, width, height), "previous-position"))
            ranked.extend((b, "nearest-free-zone") for b in candidates)
            for box, reason in ranked:
                check = check_overlap(_static(box, event.start, event.end), tracks, masks)
                if check.safe:
                    chosen = EventLayout(event.id, event.start, event.end, reason, check, box=box,
                                         warnings=list(warnings), scale=scale,
                                         fallback="smaller-box" if scale < 1 else None)
                    break
            if chosen is None and allow_motion:
                path = _short_path(event, candidates, tracks, masks, previous or preferred)
                if path:
                    chosen = EventLayout(event.id, event.start, event.end, "short-motion-path",
                                         check_overlap(path, tracks, masks), path=path,
                                         warnings=list(warnings), scale=scale,
                                         fallback="smaller-box" if scale < 1 else None)
            if chosen is not None:
                if scale < 1:
                    chosen.warnings.append(
                        f"infeasible_requested_size: using {scale:.0%} box; compiler must resize text and effects")
                break
        if chosen is None:
            anchor = ZONES[event.preferred_anchor] if isinstance(event.preferred_anchor, str) else event.preferred_anchor
            box = _at(anchor, event.width, event.height)
            warnings.append("infeasible: no safe layout found by bounded search; plate still overlaps; "
                            "review, reframe footage, or reserve an external top/bottom bar before rendering")
            chosen = EventLayout(event.id, event.start, event.end, "infeasible",
                                 check_overlap(_static(box, event.start, event.end), tracks, masks),
                                 box=box, warnings=warnings, fallback="plate")
        layouts.append(chosen)
        if chosen.overlap.safe:
            previous = chosen.box or chosen.path[-1].box
    return LayoutPlan(layouts, tracks, masks, platform)
