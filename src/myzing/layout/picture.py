"""Conservative detection of a live picture surrounded by static broadcast chrome."""

import subprocess
from dataclasses import replace

from myzing.composition.framing import CropBounds, CropKeyframe
from .types import Box, Keyframe, box_at


def detect_picture(frames):
    """Try the established border guards, then a dominant composite stage."""
    result = _detect_bordered_picture(frames)
    import numpy as np
    data = np.asarray(frames, dtype=float)
    if data.ndim == 3 and len(data) >= 6 and min(data.shape[1:]) >= 16:
        from .stage import detect_stage
        stage = detect_stage(data, content_bounds=result["bounds_normalized"] if result.get("confident") else None)
        if stage is not None and (stage.get("confident") or not result.get("confident")):
            return stage
    return result


def _detect_bordered_picture(frames):
    """Gray samples -> rectangle/evidence. Requires two persistent horizontal borders.

    This is a static-frame detector, not semantic lower-third removal. Moving
    graphics, cuts, freezes and uncertain borders leave the full source intact.
    """
    import numpy as np
    data = np.asarray(frames, dtype=float)
    if data.ndim != 3 or len(data) < 6:
        return {"version": 1, "confident": False, "confidence": 0., "reason": "need at least six gray samples"}
    _, h, w = data.shape
    temporal = data.std(axis=0)
    mean = data.mean(axis=0)
    moving = temporal > 3
    row_motion = moving.mean(axis=1)
    active = np.flatnonzero(row_motion > .03)
    unknown = {"version": 1, "confident": False, "confidence": 0.,
               "sample_count": len(data), "moving_fraction": float(moving.mean())}
    if len(active) < h*.1:
        return {**unknown, "reason": "too little temporal activity; frozen/static picture is ambiguous"}
    # An edge must be in the same place in every sample, over most of its span.
    differences = np.abs(np.diff(data, axis=1))
    # Side chrome must not dilute horizontal borders: inspect the central 70%
    # first, then require the full candidate's outside to be static below.
    support = (differences[:, :, int(w*.15):int(w*.85)] > 10).mean(axis=2).min(axis=0)
    # Dark/gradient chrome need not have a bright one-pixel edge. A stable
    # transition from static graphics to motion across most of the picture
    # width is independent border evidence. The same static-surround, matte
    # and scenery guards below still apply; a moving face alone is too narrow.
    center_motion = moving[:, int(w*.15):int(w*.85)].mean(axis=1)
    motion_border = np.abs(np.diff(center_motion))
    support = np.maximum(support, np.where(motion_border >= .8, motion_border, 0))
    candidates = [i+1 for i, score in enumerate(support) if score >= .8]
    top = [y for y in candidates if h*.02 <= y <= min(active[0]+2, h*.4)
           and (temporal[:y] <= 3).mean() >= .98]
    bottom = [y for y in candidates if max(active[-1]-1, h*.6) <= y <= h*.98
              and (temporal[y:] <= 3).mean() >= .98]
    if not top or not bottom:
        return {**unknown, "reason": "no pair of consistent borders enclosing motion and static outer bars"}
    y0, y1 = max(top), min(bottom)
    # Side chrome is optional; determine it only with equally strong borders.
    horizontal = data[:, y0:y1]
    col_support = (np.abs(np.diff(horizontal, axis=2)) > 10).mean(axis=1).min(axis=0)
    motion_columns = moving[y0:y1].mean(axis=0)
    motion_border = np.abs(np.diff(motion_columns))
    col_support = np.maximum(col_support, np.where(motion_border >= .8, motion_border, 0))
    col_active = np.flatnonzero(moving[y0:y1].mean(axis=0) > .03)
    x0, x1 = 0, w
    if len(col_active):
        left = [i+1 for i, score in enumerate(col_support) if score >= .8 and w*.02 <= i+1 <= min(col_active[0]+2, w*.35)
                and (temporal[y0:y1, :i+1] <= 3).mean() >= .98]
        right = [i+1 for i, score in enumerate(col_support) if score >= .8 and max(col_active[-1]-1, w*.65) <= i+1 <= w*.98
                 and (temporal[y0:y1, i+1:] <= 3).mean() >= .98]
        x0, x1 = max(left, default=0), min(right, default=w)
    outside = np.ones((h, w), dtype=bool)
    outside[y0:y1, x0:x1] = False
    static_share = float((temporal[outside] <= 3).mean())
    inside_motion = float(moving[y0:y1, x0:x1].mean())
    retained = (x1-x0)*(y1-y0)/(w*h)
    confidence = min(static_share, float(support[y0-1]), float(support[y1-1]))
    geometric = static_share >= .98 and inside_motion >= .03 and .25 <= retained <= .94 and confidence >= .8
    surround = _surround(mean, (x0, y0, x1, y1))
    confident = geometric and surround["kind"] == "chrome"
    reason = ("persistent borders, low temporal variance outside, motion inside, structured flat graphics outside"
              if confident else surround["reason"] if geometric else "candidate below conservative confidence thresholds")
    return {"version": 1, "confident": bool(confident), "confidence": confidence if confident else 0.,
            "geometric_confidence": confidence, "surround": surround,
            "bounds_normalized": [x0/w, y0/h, (x1-x0)/w, (y1-y0)/h],
            "sample_count": len(data), "static_outside_fraction": static_share,
            "outside_mean_std": float(temporal[outside].mean()), "live_moving_fraction": inside_motion,
            "border_support": [float(support[y0-1]), float(support[y1-1])], "retained_area": retained,
            "reason": reason}


# A plain matte (letterbox/pillarbox bars or a flat frame) has almost no
# spatial variation. Broadcast chrome carries structure: text, logos, bars or
# color changes, drawn as mostly flat graphics. Camera scenery around a static
# shot (desk, wall, shelf) is textured: many small gradients. Thresholds are
# in 8-bit gray levels of the 320-wide temporal mean image.
MATTE_MAX_STD = 6.0
CHROME_MIN_FLAT = .75


def _surround(mean, rectangle):
    """Classify the static region outside the picture: matte, chrome or scenery."""
    import numpy as np
    x0, y0, x1, y1 = rectangle
    h, w = mean.shape
    core = np.ones((h, w), dtype=bool)
    # Ignore two sample rows/columns beside the picture: they can blend
    # picture and bar pixels, and codec ringing sits there.
    core[max(0, y0-2):min(h, y1+2), max(0, x0-2):min(w, x1+2)] = False
    if core.sum() < 16:
        return {"kind": "unknown", "reason": "too few static surround pixels to classify"}
    values = mean[core]
    gx = np.zeros_like(mean)
    gy = np.zeros_like(mean)
    gx[:, 1:] = np.abs(np.diff(mean, axis=1))
    gy[1:] = np.abs(np.diff(mean, axis=0))
    gradient = np.maximum(gx, gy)[core]
    std, flat = float(values.std()), float((gradient <= 2).mean())
    evidence = {"spatial_std": std, "flat_fraction": flat, "edge_fraction": float((gradient > 12).mean())}
    if std < MATTE_MAX_STD:
        return {**evidence, "kind": "matte", "reason": "uniform outer bars (letterbox/pillarbox matte or flat frame), "
                "not broadcast chrome; existing framing keeps the source"}
    if flat < CHROME_MIN_FLAT:
        return {**evidence, "kind": "scenery", "reason": "static surround is textured like camera scenery "
                "(desk, wall or shelf), not flat broadcast graphics; existing framing keeps the source"}
    # Require a wide, filled lower-third/logo bar. Sparse bright icons or
    # titles can inflate spatial variance without any broadcast structure.
    background = float(np.median(values))
    graphic = (np.abs(mean - background) >= 12) & core
    widths = []
    for row in graphic:
        edges = np.diff(np.r_[False, row, False].astype(int))
        spans = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
        widths.append(int(spans.max()) if len(spans) else 0)
    wide_rows = np.asarray(widths) >= max(16, w * .35)
    edges = np.diff(np.r_[False, wide_rows, False].astype(int))
    heights = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
    bar_height = int(heights.max()) if len(heights) else 0
    evidence.update(widest_graphic_share=max(widths) / w, bar_height=bar_height)
    if bar_height < max(3, h * .025):
        return {**evidence, "kind": "unknown", "reason": "no wide lower-third or logo bar; "
                "sparse icons/titles or flat UI panels are insufficient broadcast evidence"}
    return {**evidence, "kind": "chrome", "reason": "wide broadcast bar in a structured flat surround"}


def analyze_picture(path, ranges, size, *, ffmpeg="ffmpeg"):
    try:
        import numpy as np
    except ImportError:
        return {"version": 1, "confident": False, "confidence": 0.,
                "reason": 'picture detection needs NumPy; install it with pip install "myzing[color]"'}
    # Area averaging confines each chrome/picture boundary to one sample row
    # or column; never upsample a small source.
    width = max(16, min(320, size[0] // 2 * 2))
    height = max(16, round(size[1]*width/size[0]))
    evidence = []
    merged = []
    for start, end in sorted(set(ranges)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    if len(merged) > 10:
        return {"version": 1, "confident": False, "confidence": 0., "reason": "more than ten disjoint ranges exceed picture sampling budget"}
    try:
        for start, end in merged:
            span = end-start
            if span < 1:
                return {"version": 1, "confident": False, "confidence": 0., "reason": "used trim shorter than one second"}
            result = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-ss", str(start), "-t", str(span),
                "-protocol_whitelist", "file,pipe", "-i", str(path), "-vf",
                f"fps={12/span},scale={width}:{height}:flags=area,format=gray", "-frames:v", "12", "-threads", "1",
                "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], capture_output=True, timeout=60, check=False)
            if result.returncode or len(result.stdout) % (width*height):
                raise ValueError("frame sampling failed")
            data = np.frombuffer(result.stdout, dtype=np.uint8).reshape(-1, height, width)
            evidence.append(detect_picture(data))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"version": 1, "confident": False, "confidence": 0., "reason": f"picture detection unavailable: {exc}"}
    if not evidence or not all(e["confident"] for e in evidence):
        failed = next((e for e in evidence if not e["confident"]), {})
        return {"version": 1, "confident": False, "confidence": 0., "ranges": evidence,
                "reason": "not every used range has a confident static frame" +
                          (f" ({failed['reason']})" if failed.get("reason") else "")}
    first = evidence[0]
    if any(max(abs(a-b) for a, b in zip(e["bounds_normalized"], first["bounds_normalized"])) > .01 for e in evidence):
        return {"version": 1, "confident": False, "confidence": 0., "ranges": evidence, "reason": "picture bounds change between used ranges"}
    x, y, w, h = first["bounds_normalized"]
    # A border can fall inside one area-averaged sample row/column, which then
    # blends chrome and picture. Step one sample inward on every side that has
    # chrome, then round inward to even pixels: no chrome row survives.
    import math
    sx, sy = size[0] / width, size[1] / height
    inset_left = sx if x > 0 else 0
    inset_right = sx if x + w < 1 - 1e-9 else 0
    left = math.ceil((x*size[0] + inset_left)/2)*2
    top = math.ceil((y*size[1] + sy)/2)*2
    right = math.floor(((x+w)*size[0] - inset_right)/2)*2
    bottom = math.floor(((y+h)*size[1] - sy)/2)*2
    if right - left < 16 or bottom - top < 16:
        return {"version": 1, "confident": False, "confidence": 0., "ranges": evidence,
                "reason": f"live picture collapses to {max(0, right-left)}x{max(0, bottom-top)} px after inward "
                          "rounding; keeping the full frame"}
    return {**first, "bounds_pixels": [left, top, right-left, bottom-top], "ranges": evidence,
            "method": "static-picture-v2", "decision": "crop to live picture"}


def select_picture_framing(requested, sw, sh, width, height, clip, tracks, *, picture=None, policy="auto", **kwargs):
    from .crop_planner import select_framing
    if policy == "on" and not (picture and picture.get("confident")):
        reason = (picture or {}).get("reason", "picture evidence unavailable")
        raise ValueError("Crop to live picture requested, but no confident static frame was detected: " +
                         reason + "; inspect source or use --picture-crop off")
    if policy == "off" or not picture or not picture.get("confident"):
        return select_framing(requested, sw, sh, width, height, clip, tracks, **kwargs)
    tracks = [_used_track(t, clip) for t in tracks
              if t.keyframes[0].time < clip.src_out and t.keyframes[-1].time > clip.src_in]
    if picture.get("kind") == "broadcast-composite" and picture.get("secondary_bounds_normalized"):
        faces = [t for t in tracks if t.id.startswith("face") and t.confidence >= .8
                 and _covers_shot(t, clip)]
        if len(faces) == 1 and _inside_share(faces[0], picture["secondary_bounds_normalized"]) > .5:
            reason = "Only confident full-shot face is in the inset tile; plan framing from the full source."
            f = select_framing(requested, sw, sh, width, height, clip, tracks, **kwargs)
            return replace(f, picture={**picture, "confident": False, "confidence": 0.,
                "reason": reason, "decision": "reject large-stage crop", "subject_selection": {
                    "focused": False, "inset_speaker": faces[0].id}}, warnings=[*f.warnings, reason])
    x, y, pw, ph = picture["bounds_pixels"]
    projected, excluded = [], []
    shares = {}
    for track in tracks:
        share = shares[track.id] = _inside_share(track, (x/sw, y/sh, pw/sw, ph/sh))
        if share <= (.5 if track.id.startswith("face") else 0):
            excluded.append(track.id)
            continue
        keys = []
        for k in track.keyframes:
            left, top = max(x, k.box.x*sw), max(y, k.box.y*sh)
            right, bottom = min(x+pw, k.box.right*sw), min(y+ph, k.box.bottom*sh)
            if right <= left or bottom <= top:
                continue
            keys.append(Keyframe(k.time, Box((left-x)/pw, (top-y)/ph, (right-left)/pw, (bottom-top)/ph)))
        if keys:
            projected.append(replace(track, keyframes=keys))
        else:
            excluded.append(track.id)
    details = {"outside_stage_tracks": excluded, "stage_inside_area_share": shares,
               "minimum_stage_inside_area_share": .5}
    if picture.get("kind") == "broadcast-composite":
        projected, focus = _stage_subjects(clip, projected, measurements={t.id: t for t in tracks})
        details.update(focus)
    mode = ("zoomfill" if requested == "auto" and width < height and details.get("focused") else requested)
    f = select_framing(mode, pw, ph, width, height, clip, projected, **kwargs)
    return replace(f, source_width=sw, source_height=sh, bounds=CropBounds(x, y, pw, ph),
                   center_x=f.center_x+x, center_y=f.center_y+y,
                   keyframes=[CropKeyframe(k.time, k.center_x+x, k.center_y+y) for k in f.keyframes],
                   picture={**picture, "subject_selection": details}, warnings=[*f.warnings,
                   *([focus["reason"]] if picture.get("kind") == "broadcast-composite" and focus.get("focused") else []),
                   f"Crop to live picture: {pw}x{ph} at ({x},{y}); static-frame confidence {picture['confidence']:.3f}; sampled evidence, not semantic recognition."])


def _used_track(track, clip):
    start, end = max(clip.src_in, track.keyframes[0].time), min(clip.src_out, track.keyframes[-1].time)
    times = sorted({start, end, *(k.time for k in track.keyframes if start < k.time < end)})
    return replace(track, keyframes=[Keyframe(t, box_at(track.keyframes, t)) for t in times])


def _inside_share(track, bounds):
    """Time-weighted retained face area, not a veto by one edge sample."""
    x,y,w,h = bounds
    values = [max(0, min(x+w,k.box.right)-max(x,k.box.x)) *
              max(0, min(y+h,k.box.bottom)-max(y,k.box.y)) / (k.box.width*k.box.height)
              for k in track.keyframes]
    span = track.keyframes[-1].time-track.keyframes[0].time
    return (sum((a+b)/2*(right.time-left.time) for a,b,left,right in
                zip(values,values[1:],track.keyframes,track.keyframes[1:])) / span if span else values[0])


def _covers_shot(track, clip):
    return track.keyframes[0].time <= clip.src_in+1e-4 and track.keyframes[-1].time >= clip.src_out-1e-4


def _stage_subjects(clip, tracks, *, measurements=None):
    """Keep plausible participants; disclose small background faces separately."""
    from statistics import median
    tracks = [t for t in tracks if t.keyframes[0].time < clip.src_out and t.keyframes[-1].time > clip.src_in]
    faces = [t for t in tracks if t.id.startswith("face")]
    sources = {t.id: (measurements or {}).get(t.id, t) for t in faces}
    observed = {t.id: [o.box for o in sources[t.id].observations if clip.src_in <= o.time <= clip.src_out]
                for t in faces}
    use_raw = all(observed.values())
    # A track without recorded padding may hold raw boxes. Guessing an inset
    # can shrink a real speaker into a bystander, so compare every face's
    # keyframes as stored instead (the 775f30f behavior).
    legacy = not use_raw and any(sources[t.id].padding is None for t in faces)
    basis = ("raw face observations" if use_raw else
             "keyframes as stored (padding unknown on a track)" if legacy else "keyframes minus tracking padding")
    def unpad(box, margin):
        # Clipped frame edges cannot be reconstructed: preserve them rather
        # than inventing an inset. Bound the inset for tiny legacy boxes.
        dx, dy = min(margin, box.width*.499999), min(margin, box.height*.499999)
        left, top = box.x + (dx if box.x > 1e-12 else 0), box.y + (dy if box.y > 1e-12 else 0)
        right = box.right - (dx if box.right < 1-1e-12 else 0)
        bottom = box.bottom - (dy if box.bottom < 1-1e-12 else 0)
        return Box(left, top, right-left, bottom-top)
    def measure(t):
        source = sources[t.id]
        margin = 0. if use_raw or legacy else source.padding
        boxes = observed[t.id] if use_raw else [unpad(k.box, margin) for k in source.keyframes]
        return {"area": median(b.width*b.height for b in boxes),
                "height": median(b.height for b in boxes), "center_y": median(b.center[1] for b in boxes),
                "basis": basis, "padding_removed": margin,
                "padding_source": "track" if source.padding is not None else "unknown (compared as stored)"}
    measured = {t.id: measure(t) for t in faces}
    size = lambda t: measured[t.id]["area"]
    primary = max(faces, key=size, default=None)
    if (primary is None or primary.confidence < .8 or primary.keyframes[0].time > clip.src_in
            or primary.keyframes[-1].time < clip.src_out-1e-4):
        return tracks, {"focused": False, "reason": "no confident full-shot stage face"}
    others = [t for t in faces if t is not primary]
    ratio = max((size(t)/size(primary) for t in others), default=0.)
    main, evidence = measured[primary.id], {}
    for t in others:
        peer = measured[t.id]
        scale = min(peer["height"], main["height"]) / max(peer["height"], main["height"])
        vertical = abs(peer["center_y"]-main["center_y"]) / max(peer["height"], main["height"])
        depth = scale >= .5 and vertical <= .5
        evidence[t.id] = {"face_area_ratio": size(t)/size(primary), "relative_height": scale,
                          "vertical_distance_in_face_heights": vertical, "similar_depth_band": depth,
                          "basis": peer["basis"], "padding_removed": peer["padding_removed"],
                          "padding_source": peer["padding_source"],
                          "plausible_participant": size(t)/size(primary) >= .12 or depth}
    bystanders = [t.id for t in others if not evidence[t.id]["plausible_participant"]]
    persistent = [t.id for t in others if t.id not in bystanders
                  and t.keyframes[-1].time-t.keyframes[0].time >= .5*(clip.src_out-clip.src_in)]
    details = {"main_face": primary.id, "face_confidence": primary.confidence,
               "primary_measurement_basis": main["basis"], "primary_padding_removed": main["padding_removed"],
               "primary_padding_source": main["padding_source"], "bystander_tracks": bystanders,
               "participant_evidence": evidence, "persistent_stage_faces": persistent,
               "participant_thresholds": {"minimum_face_area_ratio": .12, "minimum_relative_height": .5,
                   "maximum_vertical_distance_in_face_heights": .5, "speaking_activity_available": False}}
    def incidental(t):
        return (t.id in bystanders or
                (t in others and t.id not in persistent and size(t)/size(primary) <= .25 and t.confidence < .8)
                or t.id.startswith("saliency-") or
                (t.id.startswith("person-") and t.confidence <= .5 and t.observations
                 and all(o.detector == "hog-fallback" for o in t.observations)))
    kept = [t for t in tracks if not incidental(t)]
    incidental_ids = [t.id for t in tracks if t not in kept]
    if any(t in kept for t in others):
        return kept, {**details, "focused": False,
                      "incidental_tracks": incidental_ids,
                      "reason": "another plausible persistent, substantial or confident stage participant remains"}
    if any(t is not primary for t in kept):
        return kept, {**details, "focused": False, "incidental_tracks": incidental_ids,
                      "reason": "independent person evidence remains in the stage"}
    return kept, {**details, "focused": True,
                  "maximum_incidental_face_area_ratio": ratio,
                  "incidental_tracks": incidental_ids,
                  "reason": f"Stage focus: one full-shot face at confidence {primary.confidence:.3f}; "
                            f"other stage faces are at most {ratio:.1%} of its measured area. "
                            "Disclosed small background faces, transient incidental detections and low-confidence HOG scenery "
                            "do not widen the shot; geometry estimates participant depth, not identity or speaking activity."}
