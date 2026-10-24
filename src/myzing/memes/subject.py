"""Model-free subject estimate and text protection for photo memes.

Faces are protected by the local face detector. Pets, objects and other
non-face subjects are estimated here from pixels only: color distance from
the photo's border color plus local edge strength, a mild center prior, an
Otsu threshold and the strongest connected region. It finds "a distinct
region", never a dog, cat or any other category; its confidence is an
uncalibrated separation score. Users can add explicit protected boxes.
Pillow only (the memes extra); stdlib geometry.
"""

from __future__ import annotations

import math

from . import MemeError

METHOD = ("color contrast against the photo border plus edge strength, mild center prior; "
          "a distinct-region estimate, not recognition")
# Below this separation score the estimate is reported but not protected.
MIN_CONFIDENCE = .5
GRID = 96  # analysis thumbnail, long side
MARGIN = .03  # grown on every side: thumbnail quantization and soft edges
CENTER_HEURISTIC = [.2, .2, .6, .6]
# More similar-sized distinct regions than this reads as a pattern, not a subject.
MAX_PEERS = 4


def _otsu(values: list[int]) -> tuple[int, float]:
    """Threshold and separability (between-class / total variance)."""
    histogram = [0] * (max(values) + 1)
    for value in values:
        histogram[value] += 1
    total = len(values)
    mean = sum(i * c for i, c in enumerate(histogram)) / total
    variance = sum(c * (i - mean) ** 2 for i, c in enumerate(histogram)) / total
    if variance <= 0:
        return 0, 0.0
    best, threshold, weight, running = 0.0, 0, 0, 0.0
    for i, count in enumerate(histogram):
        weight += count
        running += i * count
        if weight == 0 or weight == total:
            continue
        low = running / weight
        high = (mean * total - running) / (total - weight)
        between = weight * (total - weight) * (low - high) ** 2 / total ** 2
        if between > best:
            best, threshold = between, i
    return threshold, best / variance


def _components(mask: list[bool], width: int, height: int) -> list[list[int]]:
    seen, result = [False] * len(mask), []
    for start, on in enumerate(mask):
        if not on or seen[start]:
            continue
        stack, members = [start], []
        seen[start] = True
        while stack:
            index = stack.pop()
            members.append(index)
            x, y = index % width, index // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    neighbor = ny * width + nx
                    if mask[neighbor] and not seen[neighbor]:
                        seen[neighbor] = True
                        stack.append(neighbor)
        result.append(members)
    return result


def _position(box: list[float]) -> str:
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    row = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else "middle"
    column = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "center"
    return "center" if (row, column) == ("middle", "center") else f"{row}-{column}"


def estimate_subject(image) -> dict | None:
    """The most distinct region of a photo, or None when nothing stands out.

    Returns ``{"version", "box", "confidence", "method", "evidence"}`` with a
    normalized ``[x, y, width, height]`` box in source coordinates.
    """
    from PIL import ImageFilter, ImageStat

    small = image.convert("RGB")
    small.thumbnail((GRID, GRID))
    width, height = small.size
    if width < 8 or height < 8:
        return None
    blurred = small.filter(ImageFilter.GaussianBlur(1)).convert("YCbCr")
    pixels = list(getattr(blurred, "get_flattened_data", blurred.getdata)())
    edges = small.convert("L").filter(ImageFilter.FIND_EDGES).filter(ImageFilter.BoxBlur(1))
    edge = list(getattr(edges, "get_flattened_data", edges.getdata)())
    ring = [pixels[y * width + x] for y in range(height) for x in range(width)
            if x < 2 or y < 2 or x >= width - 2 or y >= height - 2]
    background = [sorted(p[c] for p in ring)[len(ring) // 2] for c in range(3)]
    scores = []
    for i, (luma, cb, cr) in enumerate(pixels):
        x, y = i % width, i // width
        if x < 2 or y < 2 or x >= width - 2 or y >= height - 2:
            edge_value = 0  # FIND_EDGES' artificial frame border, spread by the blur
        else:
            edge_value = edge[i]
        distance = math.sqrt((luma - background[0]) ** 2
                             + 2 * ((cb - background[1]) ** 2 + (cr - background[2]) ** 2))
        dx, dy = (x + .5) / width - .5, (y + .5) / height - .5
        prior = 1 - .5 * (dx * dx + dy * dy)
        scores.append(int(min(510, (distance + .5 * edge_value) * prior)))
    if max(scores) < 24:
        return None  # flat photo: nothing differs from the border color
    threshold, separability = _otsu(scores)
    mask = [s > threshold for s in scores]
    share = sum(mask) / len(mask)
    if not .002 <= share <= .7:
        return None  # a speck, or "subject" is most of the frame (busy/no border)
    components = _components(mask, width, height)
    main = max(components, key=lambda members: (sum(scores[i] for i in members), -min(members)))
    xs, ys = [i % width for i in main], [i // width for i in main]
    left, top, right, bottom = min(xs), min(ys), max(xs) + 1, max(ys) + 1
    # Join nearby distinct pieces (a collar, ears, a second color patch).
    grow_x, grow_y = .1 * (right - left) + 1, .1 * (bottom - top) + 1
    for members in components:
        if members is main or len(members) < .1 * len(main):
            continue
        mx, my = [i % width for i in members], [i // width for i in members]
        if (min(mx) <= right + grow_x and max(mx) + 1 >= left - grow_x
                and min(my) <= bottom + grow_y and max(my) + 1 >= top - grow_y):
            left, top = min(left, min(mx)), min(top, min(my))
            right, bottom = max(right, max(mx) + 1), max(bottom, max(my) + 1)
    inside = [scores[i] for i in range(len(scores)) if mask[i]]
    outside = [scores[i] for i in range(len(scores)) if not mask[i]]
    inner, outer = sum(inside) / len(inside), sum(outside) / max(1, len(outside))
    contrast = max(0.0, (inner - outer) / max(inner, 1e-6))
    area = (right - left) * (bottom - top) / (width * height)
    fill = len(main) / max(1, (right - left) * (bottom - top))
    size_factor = 1.0 if area <= .45 else max(0.0, (.85 - area) / .4)
    if size_factor == 0:
        return None  # the "region" is most of the photo: nothing stands out
    # A full-width band at the top/bottom (sky, floor) or a full-height band
    # at a side (wall) is scenery, not a subject.
    spans_width = right - left >= .95 * width and (top == 0 or bottom == height)
    spans_height = bottom - top >= .95 * height and (left == 0 or right == width)
    band = .3 if spans_width or spans_height else 1.0
    # A repeated pattern (stripes, a fence, tiles) has many regions as large
    # as the strongest one: no single region stands out.
    peers = sum(1 for members in components if len(members) >= .5 * len(main))
    pattern = 1.0 if peers <= MAX_PEERS else MAX_PEERS / peers
    confidence = round(min(1.0, separability * contrast * (.6 + .4 * fill) * size_factor * band * pattern * 1.25), 2)
    x0 = max(0.0, left / width - MARGIN)
    y0 = max(0.0, top / height - MARGIN)
    x1 = min(1.0, right / width + MARGIN)
    y1 = min(1.0, bottom / height + MARGIN)
    box = [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]
    stats = ImageStat.Stat(small.convert("L"))
    return {"version": 1, "box": box, "confidence": confidence, "method": METHOD,
            "evidence": {"area_share": round(area, 4), "separability": round(separability, 3),
                         "similar_regions": peers,
                         "contrast": round(contrast, 3), "fill": round(fill, 3),
                         "position": _position(box),
                         "border_color": "#%02x%02x%02x" % _rgb(background),
                         "photo_brightness": round(stats.mean[0] / 255, 3)}}


def _rgb(ycbcr: list[int]) -> tuple[int, int, int]:
    y, cb, cr = ycbcr
    r = y + 1.402 * (cr - 128)
    g = y - .344136 * (cb - 128) - .714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    return tuple(max(0, min(255, round(v))) for v in (r, g, b))


def user_boxes(values) -> list[list[float]]:
    """Validate explicit ``--protect`` boxes: normalized [x, y, width, height]."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]  # one "x,y,w,h" box, not a sequence of characters
    if isinstance(values, (list, tuple)) and len(values) == 4 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        values = [values]
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 6:
        raise MemeError("protect takes 1-6 normalized [x, y, width, height] boxes.")
    result = []
    for box in values:
        if isinstance(box, str):
            try:
                box = [float(v) for v in box.split(",")]
            except ValueError as exc:
                raise MemeError(f"protect box {box!r}: use x,y,w,h with numbers from 0 to 1.") from exc
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)):
            raise MemeError("Each protect box needs four finite numbers: x, y, width, height (0..1).")
        x, y, w, h = (float(v) for v in box)
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
            raise MemeError("protect boxes must lie inside the photo: 0 <= x, y and x+w, y+h <= 1.")
        result.append([x, y, w, h])
    return result


def protected_regions(faces: list[list[float]] | None, face_method: str, estimate: dict | None,
                      protect: list[list[float]] | None = None, detections: list[dict] | None = None) -> list[dict]:
    """Source-normalized boxes text must avoid, each with its kind and basis.

    Faces (padded 2.5%) or, without a detector, the central-60% heuristic;
    the subject estimate when no prominent face was found and its confidence
    reaches MIN_CONFIDENCE; and every explicit user box.
    """
    from .framing import prominent_faces

    regions = []
    if face_method == "center_heuristic":
        regions.append({"kind": "center_heuristic", "box": list(CENTER_HEURISTIC), "confidence": 0})
    else:
        for face in faces or []:
            x, y, w, h = face
            left, top = max(0., x - .025), max(0., y - .025)
            right, bottom = min(1., x + w + .025), min(1., y + h + .025)
            regions.append({"kind": "face", "box": [left, top, right - left, bottom - top], "confidence": None})
    for detection in detections or []:
        from myzing.layout.types import Box
        box = Box.from_dict(detection["box"]).pad(MARGIN)
        regions.append({"kind": "detected_subject", "class_name": detection["class_name"],
                        "confidence": detection["confidence"], "detector": detection["detector"],
                        "box": [box.x, box.y, box.width, box.height]})
    if (not detections and estimate is not None and estimate.get("confidence", 0) >= MIN_CONFIDENCE
            and not prominent_faces(faces or [])):
        regions.append({"kind": "subject_estimate", "box": list(estimate["box"]),
                        "confidence": estimate["confidence"]})
    for box in protect or []:
        regions.append({"kind": "user", "box": list(box), "confidence": None})
    return regions


def describe_detections(detections: list[dict]) -> str:
    return "Detected subjects: " + ", ".join(
        f"{d['class_name']} ({d['confidence']:.2f}, {d['detector']})" for d in detections
    ) + ". Model confidence is uncalibrated; each detected region is protected from text."


def describe_estimate(estimate: dict | None, clear: bool | None = None) -> str:
    """One honest line; ``clear`` is the placement outcome when known."""
    if estimate is None:
        return ("Subject estimate: no distinct non-face region found (flat or evenly busy photo); "
                "only faces and explicit protect boxes are protected.")
    x, y, w, h = estimate["box"]
    protected = estimate["confidence"] >= MIN_CONFIDENCE
    return (f"Subject estimate ({estimate['evidence']['position']}, box [{x:.2f}, {y:.2f}, {w:.2f}, {h:.2f}], "
            f"confidence {estimate['confidence']:.2f}, uncalibrated) from color contrast and edges; it marks a "
            "distinct region, not what it is. "
            + (("It is protected from text." if clear is None else "Text is kept off it." if clear else
                "Text overlaps it because the requested layout was kept.") if protected else
               f"Below {MIN_CONFIDENCE:g}, so it is reported but not protected; pass --protect to protect it."))
