"""Subject-safe intermediate crops and word-safe speaker motion."""

import math
from dataclasses import replace

from myzing.composition.framing import CropAssessment, CropKeyframe
from .speakers import output_time, speaker_turns
from .types import box_at, union


def _subjects_at(tracks, time):
    active = [t for t in tracks if t.keyframes[0].time <= time <= t.keyframes[-1].time]
    return [t for t in active if not t.id.startswith("saliency-")] or active


def _headroom(box, source_height):
    # Preserve 8% of box height above its top, at least 2% of source height.
    return max(0, box.y * source_height - max(.02 * source_height, .08 * box.height * source_height))


class Evidence:
    """Per-output-frame subject geometry of one clip, independent of the crop.

    Width searches assess many windows over the same frames; the boxes, their
    pixel edges and headroom lines are interpolated once here, not per width.
    """

    def __init__(self, clip, tracks, fps, source_width, source_height):
        self.frames = []
        for frame in range(max(1, math.ceil(clip.duration * fps))):
            local = min(clip.duration - 1e-7, frame / fps)
            source = clip.source_at(clip.timeline_start + local)
            boxes = []
            for track in _subjects_at(tracks, source):
                b = box_at(track.keyframes, source)
                boxes.append((track.id, b.x * source_width, b.y * source_height, b.right * source_width,
                              b.bottom * source_height, b.width * source_width * b.height * source_height,
                              _headroom(b, source_height)))
            self.frames.append((local, boxes))
        self.targets = {}  # (clip-local time, identity) -> raw target, shared by every width.
        self.vertical = None


def _hold_turn(turns, local):
    """The turn whose subject the window holds at this time, or None while it
    moves between different subjects (a disclosed move during silence)."""
    current = next((t for t in turns if t.start <= local < t.end), None)
    if current is not None:
        return current
    before = next((t for t in reversed(turns) if t.end <= local), None)
    after = next((t for t in turns if t.start > local), None)
    if before is None or after is None:
        return before or after  # Leading/trailing silence holds the nearest turn's subject.
    return before if before.face_track_id == after.face_track_id else None


def _required(turns, local, boxes):
    """Subjects that must stay visible at this frame under speaker-held framing."""
    turn = _hold_turn(turns, local)
    if turn is None:
        return None
    if turn.face_track_id is None:
        return boxes
    return [b for b in boxes if b[0] == turn.face_track_id] or boxes


def _centers(framing, times):
    """Framing.center_at for nondecreasing times, in one pass over the keys."""
    keys = framing.keyframes
    if not keys:
        return [(framing.center_x, framing.center_y)] * len(times)
    result, i = [], 0
    for time in times:
        while i < len(keys) - 1 and time > keys[i + 1].time:
            i += 1
        if i == len(keys) - 1:
            result.append((keys[-1].center_x, keys[-1].center_y))
            continue
        a, b = keys[i], keys[i + 1]
        u = max(0, min(1, (time - a.time) / (b.time - a.time)))
        u = u * u * (3 - 2 * u)
        result.append((a.center_x + (b.center_x - a.center_x) * u, a.center_y + (b.center_y - a.center_y) * u))
    return result


def _vertical(clip, tracks, source_height):
    """Highest headroom line of any subject and the preferred subjects' vertical span."""
    in_range = [t for t in tracks if t.keyframes[0].time <= clip.src_out and t.keyframes[-1].time >= clip.src_in]
    people = any(not t.id.startswith("saliency-") for t in in_range)
    boxes, preferred = [], []
    for t in in_range:
        for time in (max(clip.src_in, t.keyframes[0].time), min(clip.src_out, t.keyframes[-1].time),
                     *[k.time for k in t.keyframes if clip.src_in < k.time < clip.src_out]):
            box = box_at(t.keyframes, time)
            boxes.append(box)
            if not people or not t.id.startswith("saliency-"):
                preferred.append(box)
    line = min((_headroom(b, source_height) for b in boxes), default=0)
    span = ((min(b.y for b in preferred) * source_height, max(b.bottom for b in preferred) * source_height)
            if preferred else None)
    return line, span


def track_framing(framing, clip, tracks, speech_words=(), *, fps=30, follow_speakers=True, evidence=None):
    """Bounded crop motion for reframe/zoomfill.

    follow_speakers=False keeps any speaker turns for disclosure but frames
    every subject (the two-shot), e.g. after a speaker hold failed coverage.
    """
    if framing.mode not in ("reframe", "zoomfill"):
        return framing
    cache = evidence.targets if evidence is not None else {}
    times = sorted({0.0, clip.duration, *[output_time(clip, k.time) for t in tracks for k in t.keyframes
                                       if clip.src_in < k.time < clip.src_out]})
    if len(times) > 256:
        times = [clip.duration * i / 255 for i in range(256)]
    confidences, methods = [], set()
    # One vertical position per shot: center the subjects' vertical span, but
    # never let the crop top fall below the highest subject's headroom line.
    # Smoothing must never average away the rocket nose/headroom bound.
    if evidence is not None and evidence.vertical is not None:
        line, span = evidence.vertical
    else:
        line, span = _vertical(clip, tracks, framing.source_height)
        if evidence is not None:
            evidence.vertical = line, span
    allowed = framing.bounds
    desired = (span[0] + span[1]) / 2 if span else framing.source_height / 2
    cy = min(desired - framing.height / 2, line) + framing.height / 2
    cy = max(allowed.y + framing.height / 2, min(allowed.y + allowed.height - framing.height / 2, cy))

    def target(local, identity=None):
        key = (local, identity)
        if key not in cache:
            source = min(clip.src_out - 1e-7, clip.source_at(clip.timeline_start + local))
            active = _subjects_at(tracks, source)
            selected = [t for t in active if t.id == identity] if identity else active
            if selected:
                box = union([box_at(t.keyframes, source) for t in selected])
                cache[key] = (box.center[0] * framing.source_width, min(t.confidence for t in selected),
                              {"saliency" if t.id.startswith("saliency-") else
                               "people-hog" if t.id.startswith("person-") else "yunet" for t in selected})
            else:
                cache[key] = (framing.source_width / 2, 0, {"center/hold"})
        x, confidence, found = cache[key]
        confidences.append(confidence)
        methods.update(found)
        return min(allowed.x + allowed.width - framing.width / 2,
                   max(allowed.x + framing.width / 2, x)), cy

    turns = speaker_turns(clip, tracks, speech_words)
    keys, dialogue_failed = [], False
    failure = "insufficient silent gap for bounded move; retain two-shot"
    if turns and any(t.face_track_id for t in turns) and not follow_speakers:
        dialogue_failed, failure = True, "speaker hold failed subject checks; follow all subjects"
    elif turns and any(t.face_track_id for t in turns):
        # Hold through spoken turns; move only in the intervening silence.
        for turn in turns:
            x, y = target((turn.start + turn.end) / 2, turn.face_track_id)
            start = max(0, math.floor(turn.start * fps + 1e-9) / fps)
            end = min(clip.duration, math.ceil(turn.end * fps - 1e-9) / fps)
            if not keys:
                keys.append(CropKeyframe(0, x, y))
            else:
                distance = math.hypot(x - keys[-1].center_x, y - keys[-1].center_y)
                if 1.5 * distance > framing.max_velocity * (start - keys[-1].time) + 1e-6:
                    dialogue_failed = True
                    break
            if start > keys[-1].time:
                keys.append(CropKeyframe(start, x, y))
            if end > keys[-1].time:
                keys.append(CropKeyframe(end, x, y))
        if len(keys) > 255:
            dialogue_failed = True
        if not dialogue_failed and keys[-1].time < clip.duration:
            keys.append(CropKeyframe(clip.duration, keys[-1].center_x, keys[-1].center_y))
    if dialogue_failed:
        turns = [replace(t, face_track_id=None, confidence=0, method=failure) for t in turns]
        confidences, methods = [], set()
    if not keys or dialogue_failed:
        targets = [target(t) for t in times]
        smooth = [targets[i] if i in (0, len(targets) - 1) else
                  tuple(sum(p[axis] for p in targets[i - 1:i + 2]) / 3 for axis in (0, 1))
                  for i in range(len(targets))]
        keys = []
        for time, (x, y) in zip(times, smooth):
            if keys:
                previous = keys[-1]
                distance = math.hypot(x - previous.center_x, y - previous.center_y)
                limit = framing.max_velocity * (time - previous.time) / 1.5
                factor = min(1, limit / distance) if distance else 1
                x = previous.center_x + (x - previous.center_x) * factor
                y = previous.center_y + (y - previous.center_y) * factor
            keys.append(CropKeyframe(time, x, y))
    warnings = ["Crop follows sampled geometric evidence; 2 fps sampling, smoothing and velocity limiting can lag fast motion."]
    if not methods <= {"yunet", "people-hog"}:
        warnings.append("Saliency/center fallback used with lower confidence; subject identity and complete visibility are unverified.")
    if turns:
        warnings.append("Speaker turns: " + "; ".join(f"{t.start:.3f}-{t.end:.3f}s {t.method} (confidence {t.confidence:g})" for t in turns))
    return replace(framing, center_x=keys[0].center_x, center_y=keys[0].center_y,
                   keyframes=keys, confidence=min(confidences, default=0), method="+".join(sorted(methods)),
                   warnings=warnings, speaker_turns=turns)


def _assess(candidate, width, height, clip, tracks, fps, evidence=None):
    from .framing import visible_content
    sw, sh = candidate.source_width, candidate.source_height
    evidence = evidence or Evidence(clip, tracks, fps, sw, sh)
    content = visible_content(candidate, width, height)
    if candidate.mode == "zoomfill":
        fw, fh = candidate.foreground_size(width, height)
        scale = max(fw / candidate.width, fh / candidate.height)
    else:
        scale = (min(width / sw, height / sh) if candidate.mode in ("fit", "blurfill") else
                 max(width / candidate.width, height / candidate.height))
    area = candidate.width * candidate.height / (sw * sh)
    coverage, missing, headroom = 1.0, False, True
    full_picture = candidate.mode in ("fit", "blurfill")
    turns = candidate.speaker_turns
    identified = any(t.face_track_id for t in turns)
    centers = ([None] * len(evidence.frames) if full_picture else
               _centers(candidate, [local for local, _ in evidence.frames]))
    for (local, boxes), center in zip(evidence.frames, centers):
        if identified:
            # Speaker-held framing must keep the held subject during turns and
            # during the silences it holds through; only a move between two
            # different subjects is exempt (disclosed).
            boxes = _required(turns, local, boxes)
            if boxes is None:
                continue
        if not boxes:
            missing = True
        if full_picture:
            continue
        cx, cy = center
        left, top = math.floor(cx - candidate.width / 2), math.floor(cy - candidate.height / 2)
        right, bottom = left + candidate.width, top + candidate.height
        for _, x0, y0, x1, y1, box_area, line in boxes:
            iw = max(0, min(right, x1) - max(left, x0))
            ih = max(0, min(bottom, y1) - max(top, y0))
            coverage = min(coverage, iw * ih / box_area)
            headroom &= top <= line + 1e-6
    reasons = []
    if scale > candidate.max_upscale + 1e-9:
        reasons.append(f"crop enlargement {scale:.3f}x exceeds {candidate.max_upscale:g}x")
    if not full_picture:
        if area < .30:
            reasons.append(f"retained area {area:.1%} is below 30%")
        if candidate.height / sh < .60:
            reasons.append(f"retained source height {candidate.height / sh:.1%} is below 60%")
        if coverage < .98:
            reasons.append(f"tracked-subject coverage {coverage:.1%} is below 98%")
        if not headroom:
            reasons.append("tracked subject top/headroom would be clipped")
        unknown_limit = 2 / 3 if candidate.mode == "zoomfill" and candidate.height == sh else .90
        if missing and area < unknown_limit - 1e-9:
            reasons.append(f"subject evidence has gaps while retained area is below {unknown_limit:.1%}")
    return CropAssessment(candidate.mode, content.height, content.width * content.height,
                          scale, area, min(1.0, coverage), headroom, missing, reasons)


def _zoomfill_floor(evidence, turns, source_width):
    """Narrowest full-height window that could pass coverage/evidence checks.

    Uses the least demanding subject set (speaker-held turns); the two-shot
    fallback only adds subjects. 98% box coverage needs the window to reach
    each box's inner 98%, whatever its position, so narrower widths fail.
    """
    identified = any(t.face_track_id for t in turns)
    need, missing = 0.0, False
    for local, boxes in evidence.frames:
        if identified:
            boxes = _required(turns, local, boxes)
            if boxes is None:
                continue
        if not boxes:
            missing = True
            continue
        need = max(need, max(x1 - .02 * (x1 - x0) for _, x0, _, x1, *_ in boxes)
                   - min(x0 + .02 * (x1 - x0) for _, x0, _, x1, *_ in boxes))
    floor = max(math.floor(need) - 1, math.ceil(.30 * source_width) - 1)
    if missing:
        floor = max(floor, math.ceil(source_width * 2 / 3) - 1)
    return floor


def select_framing(requested, sw, sh, width, height, clip, tracks, *, max_upscale=2.5, fps=30, speech_words=()):
    """Largest admissible sharp picture: full crop, <=70%-height zoomfill, full fit."""
    from .framing import centered_framing, framing_mode
    assessments = []
    evidence = Evidence(clip, tracks, fps, sw, sh)

    def finish(candidate, assessment, reason):
        notes = [*candidate.warnings, reason,
                 f"Sharp picture: {assessment.sharp_height_share:.1%} of output height, "
                 f"{assessment.sharp_area_share:.1%} of output area; enlargement {assessment.enlargement:.3f}x; "
                 f"retained source area {assessment.retained_area:.1%}; tracked-subject coverage "
                 f"{assessment.subject_coverage:.1%}; headroom safe {assessment.headroom_safe}."]
        if assessment.evidence_gaps:
            notes.append("Subject evidence has gaps: unknown subjects may be outside the crop; confidence is not a visibility guarantee.")
        if candidate.mode == "zoomfill" and assessment.sharp_height_share < .50:
            notes.append("The 50-70% sharp-height target is infeasible under the enlargement/subject limits; retained the largest admissible intermediate crop.")
        return replace(candidate, assessments=[*assessments, assessment], warnings=notes)

    def plan(candidate, acceptable):
        """Speaker-held framing first; if it fails, the same window following all subjects."""
        f = track_framing(candidate, clip, tracks, speech_words, fps=fps, evidence=evidence)
        a = _assess(f, width, height, clip, tracks, fps, evidence)
        if not acceptable(f, a) and any(t.face_track_id for t in f.speaker_turns):
            g = track_framing(candidate, clip, tracks, speech_words, fps=fps, follow_speakers=False, evidence=evidence)
            b = _assess(g, width, height, clip, tracks, fps, evidence)
            if acceptable(g, b):
                return g, b
        return f, a

    mode = framing_mode(requested, sw, sh, width, height)
    if mode in ("fit", "blurfill"):
        f = replace(centered_framing(mode, sw, sh, width, height), max_upscale=max_upscale,
                    method="aspect-match" if requested == "auto" else "user-specified", warnings=[])
        return finish(f, _assess(f, width, height, clip, tracks, fps, evidence), "Entire source picture retained.")
    if requested != "zoomfill":
        def explicit_ok(f, a):
            # Explicit crops override quality/context checks, but not headroom.
            dialogue_safe = not f.speaker_turns or a.subject_coverage >= .98
            # Reframe promises subject following. With no subject evidence it
            # must not force a large blind crop (the diagonal rocket's nose can
            # leave through a side edge, even when every source row survives).
            evidence_safe = requested != "reframe" or not a.evidence_gaps or a.retained_area >= .90
            return (requested != "auto" and a.headroom_safe and dialogue_safe and evidence_safe) or not a.reasons
        try:
            f, a = plan(replace(centered_framing(mode, sw, sh, width, height), max_upscale=max_upscale), explicit_ok)
            if explicit_ok(f, a):
                return finish(f, a, f"Selected {mode} ({requested}).")
            assessments.append(a)
        except ValueError as exc:
            if requested != "auto":
                raise
            assessments.append(CropAssessment(mode, 0, 0, 1, 0, 0, False, True, [str(exc)]))
    # Keep every source row, including a nose at the top edge without a detector.
    minimum = max(1, math.ceil(width / max_upscale), math.ceil(width * sh / (height * .70)))
    if not tracks:
        minimum = max(minimum, math.ceil(sw * 2 / 3))
    if sw / sh > width / height and minimum < sw:
        base = centered_framing("zoomfill", sw, sh, width, height)
        rejected = None

        def evaluate(cw):
            f = replace(base, width=cw, center_x=sw / 2, max_velocity=min(cw, sh) * .5,
                        keyframes=[CropKeyframe(0, sw / 2, sh / 2)], max_upscale=max_upscale)
            return plan(f, lambda f, a: not a.reasons)

        # Test widths in sharp-picture-size order. Coverage under a velocity
        # limited moving window need not be monotone, so binary search could
        # skip a larger admissible picture. Widths below the coverage/evidence
        # floor cannot pass at any position and are not evaluated. Keep only
        # the first rejected intermediate assessment plus the accepted one.
        start = max(minimum, _zoomfill_floor(evidence, speaker_turns(clip, tracks, speech_words), sw))
        for cw in [minimum, *range(max(minimum + 1, start), sw)]:
            f, a = evaluate(cw)
            if not a.reasons:
                return finish(f, a, "Selected zoomfill: largest admissible intermediate picture, target 70% height; "
                              + "; ".join(r for prior in assessments for r in prior.reasons))
            if rejected is None:
                rejected = a
                assessments.append(a)
    f = replace(centered_framing("blurfill", sw, sh, width, height), max_upscale=max_upscale,
                method="auto-blurfill" if requested == "auto" else "subject-safe-fallback", warnings=[])
    return finish(f, _assess(f, width, height, clip, tracks, fps, evidence),
                  "Selected blurfill: " + "; ".join(r for a in assessments for r in a.reasons))
