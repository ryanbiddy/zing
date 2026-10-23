"""Conservative detection of a live picture surrounded by static broadcast chrome."""

import subprocess
from dataclasses import replace

from myzing.composition.framing import CropBounds, CropKeyframe
from .types import Box, Keyframe


def detect_picture(frames):
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
    confident = static_share >= .98 and inside_motion >= .03 and .25 <= retained <= .94 and confidence >= .8
    return {"version": 1, "confident": bool(confident), "confidence": confidence,
            "bounds_normalized": [x0/w, y0/h, (x1-x0)/w, (y1-y0)/h],
            "sample_count": len(data), "static_outside_fraction": static_share,
            "outside_mean_std": float(temporal[outside].mean()), "live_moving_fraction": inside_motion,
            "border_support": [float(support[y0-1]), float(support[y1-1])], "retained_area": retained,
            "reason": "persistent borders, low temporal variance outside, motion inside" if confident else "candidate below conservative confidence thresholds"}


def analyze_picture(path, ranges, size, *, ffmpeg="ffmpeg"):
    try:
        import numpy as np
    except ImportError:
        return {"version": 1, "confident": False, "confidence": 0.,
                "reason": 'picture detection needs NumPy; install it with pip install "myzing[color]"'}
    width = 320
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
                f"fps={12/span},scale={width}:{height},format=gray", "-frames:v", "12", "-threads", "1",
                "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], capture_output=True, timeout=60, check=False)
            if result.returncode or len(result.stdout) % (width*height):
                raise ValueError("frame sampling failed")
            data = np.frombuffer(result.stdout, dtype=np.uint8).reshape(-1, height, width)
            evidence.append(detect_picture(data))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"version": 1, "confident": False, "confidence": 0., "reason": f"picture detection unavailable: {exc}"}
    if not evidence or not all(e["confident"] for e in evidence):
        return {"version": 1, "confident": False, "confidence": 0., "ranges": evidence,
                "reason": "not every used range has a confident static frame"}
    first = evidence[0]
    if any(max(abs(a-b) for a, b in zip(e["bounds_normalized"], first["bounds_normalized"])) > .01 for e in evidence):
        return {"version": 1, "confident": False, "confidence": 0., "ranges": evidence, "reason": "picture bounds change between used ranges"}
    x, y, w, h = first["bounds_normalized"]
    # Round inward to even pixels; never retain a sampled chrome boundary row.
    import math
    left, top = math.ceil(x*size[0]/2)*2, math.ceil(y*size[1]/2)*2
    right, bottom = math.floor((x+w)*size[0]/2)*2, math.floor((y+h)*size[1]/2)*2
    return {**first, "bounds_pixels": [left, top, right-left, bottom-top], "ranges": evidence,
            "method": "static-picture-v1", "decision": "crop to live picture"}


def select_picture_framing(requested, sw, sh, width, height, clip, tracks, *, picture=None, policy="auto", **kwargs):
    from .crop_planner import select_framing
    if policy == "on" and not (picture and picture.get("confident")):
        reason = (picture or {}).get("reason", "picture evidence unavailable")
        raise ValueError("Crop to live picture requested, but no confident static frame was detected: " +
                         reason + "; inspect source or use --picture-crop off")
    if policy == "off" or not picture or not picture.get("confident"):
        return select_framing(requested, sw, sh, width, height, clip, tracks, **kwargs)
    x, y, pw, ph = picture["bounds_pixels"]
    projected = []
    for track in tracks:
        keys = []
        for k in track.keyframes:
            left, top = max(x, k.box.x*sw), max(y, k.box.y*sh)
            right, bottom = min(x+pw, k.box.right*sw), min(y+ph, k.box.bottom*sh)
            if right <= left or bottom <= top:
                break
            keys.append(Keyframe(k.time, Box((left-x)/pw, (top-y)/ph, (right-left)/pw, (bottom-top)/ph)))
        if len(keys) == len(track.keyframes):
            projected.append(replace(track, keyframes=keys))
    f = select_framing(requested, pw, ph, width, height, clip, projected, **kwargs)
    return replace(f, source_width=sw, source_height=sh, bounds=CropBounds(x, y, pw, ph),
                   center_x=f.center_x+x, center_y=f.center_y+y,
                   keyframes=[CropKeyframe(k.time, k.center_x+x, k.center_y+y) for k in f.keyframes],
                   picture=dict(picture), warnings=[*f.warnings,
                   f"Crop to live picture: {pw}x{ph} at ({x},{y}); static-frame confidence {picture['confidence']:.3f}; sampled evidence, not semantic recognition."])
