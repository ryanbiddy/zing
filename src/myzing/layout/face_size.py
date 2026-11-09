"""Measured face size and bounded reference punch-ins."""

from dataclasses import replace
from math import ceil, gcd
from statistics import median

from myzing.composition.framing import CropKeyframe, FaceSizeMatch
from .caption_safety import is_face
from .crop_planner import Evidence, _assess, _hold_turn, _primary_faces, track_framing
from .framing import visible_content
from .types import box_at

EPS = 1e-8
FACE_SIZE_NOTES = ("Punched in to match the reference's face size.", "Reference face size limited.")


def face_share(box, framing, time, width, height):
    """Visible face height without the caption-safety mapper's 2 px padding."""
    content = visible_content(framing, width, height)
    if framing.mode in ('fit', 'blurfill'):
        if not framing.picture:
            return box.height * content.height
        crop = framing.bounds
        x, y, cw, ch = crop.x, crop.y, crop.width, crop.height
    else:
        cx, cy = framing.center_at(time)
        cw, ch = framing.width, framing.height
        x, y = cx-cw/2, cy-ch/2
    if min(x+cw,box.right*framing.source_width) <= max(x,box.x*framing.source_width):
        return 0.
    visible = max(0., min(y+ch,box.bottom*framing.source_height)-max(y,box.y*framing.source_height))
    return visible/ch*content.height


def measurements(clip, framing, tracks, width, height):
    """30 Hz geometry using the held speaker or the planner's dominant face."""
    faces = [t for t in tracks if is_face(t)]
    rows = []
    for i in range(ceil(clip.duration * 30)):
        local = i / 30
        source = clip.source_at(clip.timeline_start + local)
        active = [t for t in faces if t.keyframes[0].time - EPS <= source <= t.keyframes[-1].time + EPS]
        turn = _hold_turn(framing.speaker_turns, local)
        if turn and turn.face_track_id:
            selected = [t for t in active if t.id == turn.face_track_id]
        else:
            selected = _primary_faces(active, source)
        shares, scales = [], []
        for track in selected:
            box = box_at(track.keyframes, source)
            shares.append(face_share(box, framing, local, width, height))
            scales.append(.10 * height / (box.height * framing.source_height))
        share, scale = min(shares, default=0.), max(scales, default=0.)
        rows.append({"start": source, "end": clip.source_at(clip.timeline_start + min(clip.duration, local + 1/30)),
                     "face_height_share": share, "required_enlargement": scale if selected else None,
                     "bad": not selected or share < .10 - EPS or scale > framing.max_upscale + EPS,
                     "close": bool(selected) and share >= .15 - EPS and scale * 1.5 <= framing.max_upscale + EPS})
    return rows


def match_face_framing(framing, clip, tracks, width, height, reference_share, *, fps=30, speech_words=()):
    if (type(reference_share) not in (int, float) or not 0 < reference_share <= 1 or width * 16 != height * 9
            or framing.mode not in ("reframe", "zoomfill")):
        return framing
    def sampled(candidate):
        rows = measurements(clip, candidate, tracks, width, height)
        if any(t.face_track_id for t in candidate.speaker_turns):
            rows = [r for i, r in enumerate(rows) if _hold_turn(candidate.speaker_turns, i / 30) is not None]
        return rows

    rows = sampled(framing)
    if not rows or any(r["required_enlargement"] is None for r in rows):
        return framing
    before = median(r["face_height_share"] for r in rows)
    if before <= 0 or before >= reference_share:
        return framing
    floor = max(640, ceil(.55 * framing.source_height))
    unit = height // gcd(width, height) if framing.mode == "reframe" else 1
    wanted = framing.height * before / reference_share
    minimum = max(floor, wanted, framing.height * width / (framing.width * framing.max_upscale))
    start = ceil(minimum / unit) * unit
    evidence = Evidence(clip, tracks, fps, framing.source_width, framing.source_height)
    for ch in range(start, framing.height, unit):
        cw = ch * width // height if framing.mode == "reframe" else ceil(framing.width * ch / framing.height)
        candidate = replace(framing, width=cw, height=ch, max_velocity=min(framing.max_velocity, min(cw, ch) * .5),
                            keyframes=[CropKeyframe(0, framing.center_x, framing.center_y)])
        candidate = track_framing(candidate, clip, tracks, speech_words, fps=fps, evidence=evidence,
                                  follow_speakers=not framing.speaker_turns or any(t.face_track_id for t in framing.speaker_turns))
        assessment = _assess(candidate, width, height, clip, tracks, fps, evidence, face_match=True)
        if assessment.reasons or assessment.evidence_gaps or candidate.speaker_turns != framing.speaker_turns:
            continue
        reached = median(r["face_height_share"] for r in sampled(candidate))
        if reached <= before + EPS:
            continue
        limits = []
        if reached < reference_share - .005:
            if minimum > wanted + EPS:
                limits.append("source resolution")
            if ch > start:
                limits.append("subject safety or crop motion")
        note = (f"Punched in to match the reference's face size. About {reached:.0%} of the height "
                f"(reference {reference_share:.0%}).")
        if limits:
            note += " Limited by " + " and ".join(limits) + "."
        return replace(candidate, assessments=[*framing.assessments, assessment],
                       face_match=FaceSizeMatch(reference_share, reached, floor, limits),
                       warnings=list(dict.fromkeys([*[w for w in framing.warnings if not w.startswith("Sharp picture:")],
                                                    *candidate.warnings, note])))
    limits = (["source resolution" if minimum > wanted + EPS else "crop precision"]
              if start >= framing.height else ["subject safety or crop motion"])
    note = (f"Reference face size limited. About {before:.0%} of the height (reference {reference_share:.0%}). "
            f"Limited by {limits[0]}.")
    return replace(framing, face_match=FaceSizeMatch(reference_share, before, floor, limits),
                   warnings=[*framing.warnings, note])
