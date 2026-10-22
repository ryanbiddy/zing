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


def track_framing(framing, clip, tracks, speech_words=(), *, fps=30):
    if framing.mode not in ("reframe", "zoomfill"):
        return framing
    times = sorted({0.0, clip.duration, *[output_time(clip, k.time) for t in tracks for k in t.keyframes
                                       if clip.src_in < k.time < clip.src_out]})
    if len(times) > 256:
        times = [clip.duration * i / 255 for i in range(256)]
    confidences, methods = [], set()
    # One vertical position protects the highest measured top over the shot.
    # Smoothing must never average away the rocket nose/headroom bound.
    boxes = [box_at(t.keyframes, time) for t in tracks
             for time in (max(clip.src_in, t.keyframes[0].time),
                          min(clip.src_out, t.keyframes[-1].time),
                          *[k.time for k in t.keyframes if clip.src_in < k.time < clip.src_out])
             if clip.src_in <= time <= clip.src_out and t.keyframes[0].time <= time <= t.keyframes[-1].time]
    top = min((_headroom(b, framing.source_height) for b in boxes), default=0)
    allowed = framing.bounds
    cy = min(framing.source_height / 2, top + framing.height / 2)
    cy = max(allowed.y + framing.height / 2, min(allowed.y + allowed.height - framing.height / 2, cy))

    def target(local, identity=None):
        source = min(clip.src_out - 1e-7, clip.source_at(clip.timeline_start + local))
        active = _subjects_at(tracks, source)
        selected = [t for t in active if t.id == identity] if identity else active
        if selected:
            box = union([box_at(t.keyframes, source) for t in selected])
            x = box.center[0] * framing.source_width
            confidences.append(min(t.confidence for t in selected))
            methods.update("saliency" if t.id.startswith("saliency-") else
                           "people-hog" if t.id.startswith("person-") else "yunet" for t in selected)
        else:
            x = framing.source_width / 2
            confidences.append(0)
            methods.add("center/hold")
        return min(allowed.x + allowed.width - framing.width / 2,
                   max(allowed.x + framing.width / 2, x)), cy

    turns = speaker_turns(clip, tracks, speech_words)
    keys, dialogue_failed = [], False
    if turns and any(t.face_track_id for t in turns):
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
        turns = [replace(t, face_track_id=None, confidence=0,
                         method="insufficient silent gap for bounded move; retain two-shot") for t in turns]
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


def _assess(candidate, width, height, clip, tracks, fps):
    from .framing import visible_content
    sw, sh = candidate.source_width, candidate.source_height
    content = visible_content(candidate, width, height)
    scale = (min(width / sw, height / sh) if candidate.mode in ("fit", "blurfill") else
             width / candidate.width if candidate.mode == "zoomfill" else
             max(width / candidate.width, height / candidate.height))
    area = candidate.width * candidate.height / (sw * sh)
    coverage, missing, headroom = 1.0, False, True
    full_picture = candidate.mode in ("fit", "blurfill")
    for frame in range(max(1, math.ceil(clip.duration * fps))):
        local = min(clip.duration - 1e-7, frame / fps)
        source = clip.source_at(clip.timeline_start + local)
        active = _subjects_at(tracks, source)
        turn = next((t for t in candidate.speaker_turns if t.start <= local < t.end), None)
        if turn and turn.face_track_id:
            active = [t for t in active if t.id == turn.face_track_id]
        elif candidate.speaker_turns and any(t.face_track_id for t in candidate.speaker_turns) and turn is None:
            # A disclosed speaker move during silence may omit the other face.
            continue
        if not active:
            missing = True
        if full_picture:
            continue
        cx, cy = candidate.center_at(local)
        left, top = math.floor(cx - candidate.width / 2), math.floor(cy - candidate.height / 2)
        right, bottom = left + candidate.width, top + candidate.height
        for track in active:
            box = box_at(track.keyframes, source)
            iw = max(0, min(right, box.right * sw) - max(left, box.x * sw))
            ih = max(0, min(bottom, box.bottom * sh) - max(top, box.y * sh))
            coverage = min(coverage, iw * ih / (box.width * sw * box.height * sh))
            headroom &= top <= _headroom(box, sh) + 1e-6
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


def select_framing(requested, sw, sh, width, height, clip, tracks, *, max_upscale=2.5, fps=30, speech_words=()):
    """Largest admissible sharp picture: full crop, <=70%-height zoomfill, full fit."""
    from .framing import centered_framing, framing_mode
    assessments = []

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

    mode = framing_mode(requested, sw, sh, width, height)
    if mode in ("fit", "blurfill"):
        f = replace(centered_framing(mode, sw, sh, width, height), max_upscale=max_upscale,
                    method="aspect-match" if requested == "auto" else "user-specified", warnings=[])
        return finish(f, _assess(f, width, height, clip, tracks, fps), "Entire source picture retained.")
    if requested != "zoomfill":
        try:
            f = track_framing(replace(centered_framing(mode, sw, sh, width, height), max_upscale=max_upscale),
                              clip, tracks, speech_words, fps=fps)
            a = _assess(f, width, height, clip, tracks, fps)
            # Explicit crops override quality/context checks, but not headroom.
            dialogue_safe = not f.speaker_turns or a.subject_coverage >= .98
            # Reframe promises subject following. With no subject evidence it
            # must not force a large blind crop (the diagonal rocket's nose can
            # leave through a side edge, even when every source row survives).
            evidence_safe = requested != "reframe" or not a.evidence_gaps or a.retained_area >= .90
            if (requested != "auto" and a.headroom_safe and dialogue_safe and evidence_safe) or not a.reasons:
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

        def evaluate(cw):
            f = replace(base, width=cw, center_x=sw / 2, max_velocity=min(cw, sh) * .5,
                        keyframes=[CropKeyframe(0, sw / 2, sh / 2)], max_upscale=max_upscale)
            f = track_framing(f, clip, tracks, speech_words, fps=fps)
            return f, _assess(f, width, height, clip, tracks, fps)

        # Test widths in sharp-picture-size order. Coverage under a velocity
        # limited moving window need not be monotone, so binary search could
        # skip a larger admissible picture. Keep only the first rejected
        # intermediate assessment plus the accepted one in the saved plan.
        for cw in range(minimum, sw):
            f, a = evaluate(cw)
            if not a.reasons:
                return finish(f, a, "Selected zoomfill: largest admissible intermediate picture, target 70% height; "
                              + "; ".join(r for prior in assessments for r in prior.reasons))
            if cw == minimum:
                assessments.append(a)
    f = replace(centered_framing("blurfill", sw, sh, width, height), max_upscale=max_upscale,
                method="auto-blurfill" if requested == "auto" else "subject-safe-fallback", warnings=[])
    return finish(f, _assess(f, width, height, clip, tracks, fps),
                  "Selected blurfill: " + "; ".join(r for a in assessments for r in a.reasons))
