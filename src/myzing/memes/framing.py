"""Aspect framing for photo memes: subject-aware fill and blur-fill.

``contain`` letterboxes, ``cover`` is a centered crop, ``fill`` is a crop that
keeps a focus box (faces or an estimated subject) in frame, and ``blur``
places the whole photo over a blurred, darkened copy of itself. ``auto``
crops only when the face detector ran: on detected faces, or (when it found
none) on a measured subject box while keeping 75% of the photo, and only when
the crop keeps all of it with a margin. Without a detector it never crops, since
it cannot see where faces are. Otherwise it blur-fills and says why. Geometry
here is stdlib-only; Pillow is imported lazily.
"""

from __future__ import annotations

import math

from . import MemeError

FITS = ("cover", "contain", "fill", "blur")
REQUESTS = FITS + ("auto",)
# Faces smaller than this share of the largest face (or of the image height)
# are background crowd: still protected from text, but they never steer a crop.
PROMINENT_SHARE = .25
PROMINENT_MIN_HEIGHT = .05
# When the detector found no face, a subject crop must keep this share of the
# photo, so a face the detector missed is unlikely to be cut.
MIN_SCENERY_AREA = .75
# A crop keeps the focus plus this margin (share of the photo) on every side.
MARGIN = .03
BLUR_SUFFIX = ", so auto kept the whole photo over a blurred copy instead of cropping."
BLUR_NO_EVIDENCE = "No detected face or measured subject to frame on" + BLUR_SUFFIX
BLUR_NO_DETECTOR = ("No local face detector, so auto did not crop (it cannot see where faces are) and kept "
                    "the whole photo over a blurred copy. Run 'zing layout fetch-model' (with "
                    "myzing[layout]) for face-aware crops.")


def _box(values) -> list[float]:
    x, y, w, h = (float(v) for v in values)
    x, y = min(max(x, 0.), 1.), min(max(y, 0.), 1.)
    return [x, y, max(1e-6, min(w, 1 - x)), max(1e-6, min(h, 1 - y))]


def union(boxes: list[list[float]]) -> list[float]:
    left = min(b[0] for b in boxes)
    top = min(b[1] for b in boxes)
    right = max(b[0] + b[2] for b in boxes)
    bottom = max(b[1] + b[3] for b in boxes)
    return _box([left, top, right - left, bottom - top])


def head_box(face: list[float]) -> list[float]:
    """A detector face box grown to the whole head: hair above, chin below."""
    x, y, w, h = face
    return _box([x - .2 * w, y - .3 * h, 1.4 * w, 1.5 * h])


def prominent_faces(faces: list[list[float]]) -> list[list[float]]:
    if not faces:
        return []
    largest = max(f[3] for f in faces)
    return [f for f in faces if f[3] >= max(PROMINENT_MIN_HEIGHT, largest * PROMINENT_SHARE)]


def focus_box(faces: list[list[float]] | None, face_method: str,
              subject: list[float] | None) -> tuple[list[float] | None, str]:
    """The evidence a crop must keep, and what it is: ``faces`` (prominent
    detected heads), ``subject`` (a measured subject box after the detector
    found no prominent face), ``none``, or ``no_detector``.

    ``faces`` are normalized [x, y, w, h] detector boxes. Without a detector
    (``center_heuristic``) nothing counts as evidence: a subject estimate can
    sit beside an undetected face, and the central-60% text heuristic says
    nothing about where faces are.
    """
    if face_method == "center_heuristic":
        return None, "no_detector"
    heads = [head_box(f) for f in prominent_faces(faces or [])]
    if heads:
        return union(heads), "faces"
    if subject is not None:
        # The estimate trims the faintest 10% of its mass on each side; grow
        # it back so a crop does not shave the subject's edges.
        x, y, w, h = subject
        return _box([x - .15 * w, y - .15 * h, 1.3 * w, 1.3 * h]), "subject"
    return None, "none"


def with_margin(focus: list[float]) -> list[float]:
    x, y, w, h = focus
    left, top = max(0., x - MARGIN), max(0., y - MARGIN)
    return _box([left, top, min(1., x + w + MARGIN) - left, min(1., y + h + MARGIN) - top])


def crop_window(source: tuple[float, float], viewport: tuple[float, float]) -> tuple[float, float]:
    """Normalized width and height of the source that a full-bleed crop keeps."""
    sw, sh = source
    vw, vh = viewport
    scale = max(vw / sw, vh / sh)
    return min(1., vw / scale / sw), min(1., vh / scale / sh)


def fits_window(focus: list[float], source: tuple[float, float], viewport: tuple[float, float]) -> bool:
    cw, ch = crop_window(source, viewport)
    return focus[2] <= cw + 1e-9 and focus[3] <= ch + 1e-9


def resolve(requested: str, source: tuple[float, float], viewport: tuple[float, float],
            focus: list[float] | None, basis: str) -> tuple[str, list[float] | None, list[str]]:
    """Return (fit, focus, notes).

    ``auto`` crops (``fill``) only with evidence (``basis`` faces or subject)
    that fits the crop with margin; a subject crop must also keep 75% of the
    photo and carries a note. Without a detector, or anything else, it is
    ``blur`` with a note saying why. An explicit ``fill`` without evidence is
    a centered crop, with a note.
    """
    if requested not in REQUESTS:
        raise MemeError("fit must be auto, fill, blur, cover, or contain")
    if requested in ("cover", "contain", "blur"):
        return requested, None, []
    if basis == "no_detector":
        if requested == "fill":
            return "cover", None, ["No local face detector; fill used a centered crop that may cut faces."]
        return "blur", None, [BLUR_NO_DETECTOR]
    if focus is None or basis not in ("faces", "subject"):
        if requested == "fill":
            return "cover", None, ["fill found no detected face or measured subject; used a centered crop."]
        return "blur", None, [BLUR_NO_EVIDENCE]
    kept = with_margin(focus)
    fits = fits_window(kept, source, viewport)
    if requested == "fill":
        notes = [] if fits else ["fill crops part of the faces/subject at this aspect; "
                                 "use fit blur or contain to keep it."]
        return "fill", kept, notes
    cw, ch = crop_window(source, viewport)
    if fits and basis == "faces":
        return "fill", kept, []
    if fits and cw * ch >= MIN_SCENERY_AREA - 1e-9:
        return "fill", kept, [f"No face was detected, so the crop follows an estimated subject and keeps "
                              f"{round(cw * ch * 100)}% of the photo; a face the detector missed could "
                              "still be cut. Use fit blur to keep the whole photo."]
    if basis == "faces":
        why = "The detected faces do not fit a full-bleed crop at this aspect with margin"
    elif not fits:
        why = "The measured subject does not fit a full-bleed crop at this aspect with margin"
    else:
        why = ("No face was detected and a crop around the estimated subject would drop more than "
               f"{round((1 - MIN_SCENERY_AREA) * 100)}% of the photo")
    return "blur", None, [why + BLUR_SUFFIX]


def offset(span: float, window: float, low: float, high: float, anchor: float) -> float:
    """Start of a 1-D window of length ``window`` inside [0, span] that keeps
    [low, high] when possible, placing ``anchor`` near the window's anchor
    point (centered horizontally, 40% from the top vertically)."""
    start = low + (high - low) * anchor - window * anchor
    if window >= high - low:
        start = max(min(start, low), high - window)  # keep both focus edges
    return min(max(start, 0.), span - window)


def fill_origin(source: tuple[float, float], scale: float, viewport_size: tuple[float, float],
                focus: list[float] | None) -> tuple[float, float] | None:
    """Top-left of the crop in source pixels, or None for a centered crop."""
    if focus is None:
        return None
    sw, sh = source
    cw, ch = viewport_size[0] / scale, viewport_size[1] / scale
    fx, fy, fw, fh = focus[0] * sw, focus[1] * sh, focus[2] * sw, focus[3] * sh
    left = offset(sw, cw, fx, fx + fw, .5)
    top = offset(sh, ch, fy, fy + fh, .4)
    centered = ((sw - cw) / 2, (sh - ch) / 2)
    # Exactly centered windows reuse the centered geometry (byte-identical cover).
    if abs(left - centered[0]) <= 1e-6 * sw and abs(top - centered[1]) <= 1e-6 * sh:
        return None
    return left, top


def saliency_box(image) -> list[float] | None:
    """Estimate a subject box from color distinctness, with a mild center prior.

    Frequency-tuned saliency (distance from the mean color after a small blur)
    on a 64-pixel thumbnail. Returns None when the photo has no distinct
    region (flat or uniformly busy). This is an estimate, not recognition.
    """
    from PIL import ImageFilter, ImageStat

    small = image.convert("RGB")
    small.thumbnail((64, 64))
    width, height = small.size
    if width < 4 or height < 4:
        return None
    mean = ImageStat.Stat(small.convert("YCbCr")).mean
    blurred = small.filter(ImageFilter.GaussianBlur(1.2)).convert("YCbCr")
    # Pillow 12 renamed getdata (deprecated, removed in Pillow 14).
    pixels = list(getattr(blurred, "get_flattened_data", blurred.getdata)())
    weights = []
    for i, (y, cb, cr) in enumerate(pixels):
        px, py = (i % width + .5) / width - .5, (i // width + .5) / height - .5
        distance = ((y - mean[0]) ** 2 + 2 * ((cb - mean[1]) ** 2 + (cr - mean[2]) ** 2)) ** .5
        # Bright, nearly neutral areas are usually sky, haze, or blank walls.
        neutral = y > 190 and abs(cb - 128) + abs(cr - 128) < 18
        weights.append(distance * (1 - .8 * (px * px + py * py)) * (.4 if neutral else 1))
    ordered = sorted(weights)
    low, high = ordered[len(ordered) // 2], ordered[-max(1, len(ordered) // 50)]
    if high < 12 or high - low < 8:
        return None
    # Keep the most distinct quarter of the image and take robust extents.
    threshold = ordered[(len(ordered) * 3) // 4]
    columns, rows = [0.] * width, [0.] * height
    for i, value in enumerate(weights):
        if value > threshold:
            columns[i % width] += value - threshold
            rows[i // width] += value - threshold

    def extent(mass: list[float]) -> tuple[float, float]:
        total = sum(mass)
        running, start, end = 0., 0, len(mass) - 1
        for index, value in enumerate(mass):
            running += value
            if running >= total * .1:
                start = index
                break
        running = 0.
        for index in range(len(mass) - 1, -1, -1):
            running += mass[index]
            if running >= total * .1:
                end = index
                break
        return start / len(mass), (end + 1) / len(mass)

    if not sum(columns):
        return None
    x0, x1 = extent(columns)
    y0, y1 = extent(rows)
    return [round(v, 4) for v in _box([x0, y0, x1 - x0, y1 - y0])]


def blur_background(source, size: tuple[int, int]):
    """A blurred, darkened full-bleed copy of ``source`` at ``size`` (RGBA)."""
    from PIL import Image, ImageFilter

    w, h = size
    small = (max(8, math.ceil(w / 8)), max(8, math.ceil(h / 8)))
    sw, sh = source.size
    scale = max(small[0] / sw, small[1] / sh)
    cw, ch = small[0] / scale, small[1] / scale
    # Clamp: float rounding can put a full-width box a hair outside the image.
    box = (max(0., (sw - cw) / 2), max(0., (sh - ch) / 2), min(sw, (sw + cw) / 2), min(sh, (sh + ch) / 2))
    reduced = source.convert("RGB").resize(small, Image.Resampling.BILINEAR, box=box)
    blurred = reduced.filter(ImageFilter.GaussianBlur(3)).point(lambda v: round(v * .62))
    return blurred.resize((w, h), Image.Resampling.BICUBIC).convert("RGBA")


def detect_faces(image, detector) -> list[list[float]]:
    """Normalized face boxes from a YuNet detector on a bounded RGB copy."""
    import numpy as np  # supplied by the optional layout extra

    sample = image.convert("RGB")
    sample.thumbnail((1280, 1280))
    return [[d.box.x, d.box.y, d.box.width, d.box.height]
            for d in detector.detect(np.asarray(sample)[:, :, ::-1].copy())]


def photo_faces(image) -> tuple[list[list[float]], str]:
    """Local cached YuNet faces (never a download): (boxes, "yunet"), or
    ([], "center_heuristic") when the detector is unavailable."""
    from myzing.layout.detector import LayoutError, YuNetDetector

    try:
        detector = YuNetDetector(download=False)
        return detect_faces(image, detector), "yunet"
    except (LayoutError, ImportError):
        return [], "center_heuristic"


def photo_focus(image, faces=None) -> tuple[list[float] | None, str, list[str]]:
    """Focus for a single render: local cached YuNet when available (never a
    download), else the central-60% heuristic. Returns (focus, basis, notes).
    ``faces`` reuses a photo_faces() result."""
    faces, method = faces if faces is not None else photo_faces(image)
    if method == "center_heuristic":
        # Never crop on a subject estimate when faces cannot be seen.
        return focus_box(None, "center_heuristic", None) + ([],)
    subject = None if prominent_faces(faces) else saliency_box(image)
    return focus_box(faces, method, subject) + ([],)
