"""Skin preservation: every face against the SAME clip's ungraded source.

A grade may legitimately warm, cool, brighten, darken or desaturate a picture.
What it should not do is rotate skin hue toward green (or toward magenta). So
each face is measured twice on the same pixels of the same ungraded source
frame: as decoded, and after that clip's own LUT. Skin is never compared with
another person's skin, the reference's faces, or a population "skin tone".
This check feeds no draft-vs-reference verdict.

Hue shift is the signed CIE 1976 hue difference dH*ab in a*/b* units, so a
pure chroma change (desaturation) or lightness change scores zero. It counts
toward green only while a* also falls, and toward magenta only while a* rises
and b* falls; a cooler or warmer face is part of the look, not a hue error.
"""

from __future__ import annotations

import math
from pathlib import Path

POLICY = "skin-preservation-v1"
# Pass at or below / miss above, in CIELAB a*b* units. Calibrated with
# tools/eval/skin_fixture.py: Zing's eight looks at full strength and its
# bounded white-balance/exposure corrections, on six generated skin tones under
# neutral light, stay at or below 2.4, except teal-orange's teal shadows on the
# deepest tone (3.2; 4.5 with the tint bound: approximate). Code-value casts of
# +0.014 G / -0.035 R,B (green) and -0.02 G / +0.05 R,B (magenta) reach 6.2-7.6
# on every tone (miss). See docs/color.md.
BANDS = (2.5, 5.0)
INTERIOR = .2            # inset each box edge by 20%: the central 60% of the face
LONG_SIDE = 640          # decode size for detection and measurement
MIN_PIXELS = 64          # smaller interiors are mostly hair, edges and codec noise
GRAY_CHROMA = 4.0        # below this a face has no reliable hue to preserve
SAMPLES_PER_SOURCE = 6


def hue_shift(source_ab, graded_ab):
    """Directional skin hue change of one face; both inputs are mean a*, b*."""
    a1, b1 = source_ab
    a2, b2 = graded_ab
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    da, db, dc = a2 - a1, b2 - b1, c2 - c1
    rotation = (math.degrees(math.atan2(b2, a2) - math.atan2(b1, a1)) + 180) % 360 - 180
    dh = math.copysign(math.sqrt(max(0.0, da * da + db * db - dc * dc)), rotation)
    if c1 < GRAY_CHROMA:
        # A near-gray face (black-and-white or heavily faded footage) has no hue
        # to rotate; pushing it onto the green side of a* is still a green face.
        green, magenta = max(0.0, min(-da, -a2)), 0.0
    else:
        # Rotation counts toward green only while a* really falls, and toward
        # magenta only while a* rises and b* falls. A cooler face (b* down, a*
        # down) or a golden one (rotation toward yellow, a* up) is the look.
        green = min(max(dh, 0.0), max(-da, 0.0))
        magenta = min(max(-dh, 0.0), max(-db, 0.0), max(da, 0.0))
    return {"a_delta": da, "b_delta": db, "chroma_delta": dc, "hue_delta": dh, "hue_rotation_degrees": rotation,
            "toward_green": green, "toward_magenta": magenta, "shift": max(green, magenta),
            "source_chroma": c1, "gray_source": c1 < GRAY_CHROMA}


def _status(shift):
    inner, outer = BANDS
    return "pass" if shift <= inner else "miss" if shift > outer else "approximate"


def face_pixels(rgb, box):
    """Central 60% of a normalized (left, top, right, bottom) box, or None."""
    try:
        left, top, right, bottom = (float(v) for v in box)
    except (TypeError, ValueError):
        return None, None
    if not all(map(math.isfinite, (left, top, right, bottom))):
        return None, None
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        return None, None
    height, width = rgb.shape[:2]
    dx, dy = INTERIOR * (right - left), INTERIOR * (bottom - top)
    x, y = math.ceil((left + dx) * width), math.ceil((top + dy) * height)
    r, b = math.floor((right - dx) * width), math.floor((bottom - dy) * height)
    if r <= x or b <= y or (r - x) * (b - y) < MIN_PIXELS:
        return None, None
    return rgb[y:b, x:r].reshape(-1, 3), [x, y, r, b]


def compare_face(source_pixels, grade):
    """Same pixels before and after `grade` (a function on (N, 3) RGB in [0, 1])."""
    from myzing.color.science import rgb_to_lab
    before = rgb_to_lab(source_pixels).mean(axis=0)
    after = rgb_to_lab(grade(source_pixels)).mean(axis=0)
    row = {"source_lab": before.tolist(), "graded_lab": after.tolist(), "lightness_delta": float(after[0] - before[0]),
           **hue_shift(before[1:].tolist(), after[1:].tolist())}
    row["status"] = _status(row["shift"])
    return row


def _detector():
    """Verified local YuNet only; never downloads. Returns (boxes_at, error)."""
    from myzing.color.science import np
    try:
        from myzing.layout.detector import YuNetDetector
        detector = YuNetDetector(download=False)
    except (ImportError, OSError, RuntimeError) as exc:  # LayoutError is a RuntimeError
        return None, str(exc)

    def boxes_at(timestamp, rgb):
        bgr = np.ascontiguousarray(np.rint(rgb[..., ::-1] * 255).astype(np.uint8))
        return [(d.box.x, d.box.y, d.box.right, d.box.bottom) for d in detector.detect(bgr)]
    return boxes_at, None


def sample_times(spans, count=SAMPLES_PER_SOURCE):
    """Evenly spaced midpoints over the union of the source spans a draft uses."""
    merged = []
    for start, end in sorted((float(s), float(e)) for s, e in spans if e > s):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    total = sum(e - s for s, e in merged)
    if total <= 0:
        return []
    times = []
    for i in range(count):
        offset = total * (i + .5) / count
        for start, end in merged:
            if offset <= end - start:
                times.append(start + offset)
                break
            offset -= end - start
    return times


def summarize(faces, sources, *, unmeasured_reason=None):
    result = {"version": 1, "policy": POLICY, "status": "approximate", "measurement_status": "unmeasured",
              "pass_max": BANDS[0], "miss_above": BANDS[1], "faces": faces, "sources": sources,
              "basis": "Each detected face is compared only with itself: the same ungraded source pixels before and "
                       "after that clip's LUT. Never compared with another person, the reference, or a skin-tone norm. "
                       "Signed CIE hue difference in a*/b* units, counted toward green while a* falls and toward "
                       "magenta while a* rises and b* falls; lightness and saturation changes are part of the look."}
    if not faces:
        decoded = sum(len(s.get("samples", [])) for s in sources)
        result["reason"] = unmeasured_reason or (
            f"No faces were found in {decoded} sampled source frames; skin preservation unmeasured." if decoded else
            "No source frame could be decoded for face sampling; skin preservation unmeasured.")
        return result
    worst = max(faces, key=lambda f: f["shift"])
    statuses = {f["status"] for f in faces}
    result.update(measurement_status="measured", worst=worst,
                  status="miss" if "miss" in statuses else "approximate" if "approximate" in statuses else "pass")
    direction = "green" if worst["toward_green"] >= worst["toward_magenta"] else "magenta"
    where = f"{Path(worst['source']).name} at {worst['timestamp']:.2f}s"
    if result["status"] == "pass":
        result["reason"] = (f"All {len(faces)} sampled faces keep their own hue through the grade: worst shift "
                            f"{worst['shift']:.1f} a*/b* units toward {direction} ({where}); pass at or below {BANDS[0]:g}.")
    else:
        result["reason"] = (f"The grade shifts skin toward {direction} by {worst['shift']:.1f} a*/b* units on {where} "
                            f"({result['status']}; pass at or below {BANDS[0]:g}, miss above {BANDS[1]:g}). "
                            "Compared with the same face in the ungraded source. Lower the look's strength or protect skin, then review.")
    unsampled = [Path(s["source"]).name for s in sources if not s["faces"]]
    if unsampled:
        result["reason"] += " No faces were found in sampled frames of " + ", ".join(unsampled) + "."
    return result


def measure_plan(plan, *, count=SAMPLES_PER_SOURCE, boxes_at=None):
    """Skin preservation for every graded source a composition plan uses.

    Returns None when no clip carries a grade (nothing can change skin).
    `boxes_at(timestamp, rgb)` may supply normalized face boxes; otherwise the
    verified local YuNet model is used, and its absence is an explicit limit.
    """
    from myzing.color import ColorError
    from myzing.color.cube import apply_cube, read_cube
    from myzing.color.media import frame, probe, sha256

    groups = {}
    for clip in plan.clips:
        if clip.color is None or not clip.color.strength:
            continue  # an ungraded clip cannot change skin
        framing = clip.framing
        # After a picture-in-frame crop only the live picture is delivered:
        # faces in the surrounding broadcast chrome are never sampled.
        picture = (framing.bounds, framing.source_width, framing.source_height) if (
            framing is not None and framing.picture and framing.mode in ("fit", "blurfill", "zoomfill")) else None
        key = (clip.src, clip.color.lut_path, clip.color.strength,
               None if picture is None else (picture[0].x, picture[0].y, picture[0].width, picture[0].height))
        group = groups.setdefault(key, {"sha256": clip.color.sha256, "spans": [], "picture": picture})
        group["spans"].append((clip.src_in, clip.src_out))
    if not groups:
        return None
    detector = "supplied face boxes"
    if boxes_at is None:
        boxes_at, error = _detector()
        if boxes_at is None:
            return summarize([], [], unmeasured_reason=(
                f"Local face detector unavailable; skin preservation unmeasured. {error} "
                'Install "myzing[layout]" and run zing layout fetch-model to enable it.'))
        detector = "local YuNet (verified weights, no download)"
    faces, sources = [], []
    for (src, lut, strength, _), group in groups.items():
        if sha256(lut) != group["sha256"]:
            raise ValueError(f"LUT changed since planning: {lut}. Re-run the match with --resume.")
        cube = read_cube(lut)

        def grade(px, cube=cube, strength=strength):
            # The renderer blends the cube by strength in display code values.
            return px + strength * (apply_cube(px, cube) - px)
        _, width, height, _ = probe(src)
        region = None
        if group["picture"] is not None:
            bounds, framing_width, framing_height = group["picture"]
            sx, sy = width / framing_width, height / framing_height
            x, y = math.ceil(bounds.x * sx), math.ceil(bounds.y * sy)
            region = (x, y, min(width, math.floor((bounds.x + bounds.width) * sx)) - x,
                      min(height, math.floor((bounds.y + bounds.height) * sy)) - y)
            width, height = region[2], region[3]
        scale = LONG_SIDE / max(width, height)
        size = (max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2))
        row = {"source": str(src), "lut_sha256": group["sha256"], "strength": strength, "detector": detector,
               "picture_region": list(region) if region else None, "samples": [], "faces": 0, "gaps": []}
        for timestamp in sample_times(group["spans"], count):
            try:
                rgb = frame(src, timestamp, *size, region=region)
            except ColorError as exc:  # a missing frame is a sampling gap, not a skin verdict
                row["gaps"].append(f"{timestamp:.3f}s: {exc}")
                continue
            row["samples"].append(timestamp)
            for box in boxes_at(timestamp, rgb):
                pixels, interior = face_pixels(rgb, box)
                if pixels is None:
                    continue
                face = compare_face(pixels, grade)
                faces.append({"source": str(src), "timestamp": timestamp, "box": [float(v) for v in box],
                              "interior": interior, "pixels": int(len(pixels)), **face})
                row["faces"] += 1
        sources.append(row)
    return summarize(faces, sources)
