"""Pixel estimates inside OCR proposals; no font or original-style recovery.

Colors are component-wise medians in CIE Lab (D65), exported as Lab and sRGB.
Confidence is a heuristic quality score, not a calibrated probability. Flat,
contrasting glyphs are supported; textured, translucent or occluded text may
remain unknown. Text height measures visible fill ink, not a font's em size.
"""

from __future__ import annotations

import math


def measure(frame, polygon: list[list[float]], text: str = "") -> dict:
    return segment(frame, polygon, text)[0]


def segment(frame, polygon: list[list[float]], text: str = ""):
    """Return JSON measurements and a polygon-clipped fill mask for font crops.

    Mask/origin are ephemeral; the sidecar records the method and measurements.
    No recognition or font-library assumptions enter the segmentation.
    """
    import cv2
    import numpy as np

    height, width = frame.shape[:2]
    points = np.array(polygon) * [width, height]
    x0, y0 = np.floor(points.min(axis=0)).astype(int)
    x1, y1 = np.ceil(points.max(axis=0)).astype(int)
    pad = max(5, math.ceil((y1 - y0) * .7))
    left, top = max(0, x0 - pad), max(0, y0 - pad)
    right, bottom = min(width, x1 + pad + 1), min(height, y1 + pad + 1)
    crop = frame[top:bottom, left:right]
    unknown = {"fill": None, "outline": None, "stroke_width_px": None,
               "stroke_width_fraction": None, "stroke_confidence": 0.0,
               "plate_present": None, "plate_color": None, "plate_confidence": 0.0,
               "ink_box": None, "text_height": None, "geometry_confidence": 0.0,
               "segmentation": "component-filtered Lab modes v2",
               "cap_height": None, "x_height": None,
               "ink_evidence": {"component_count": 0, "edge_density": 0., "ink_density": 0.}}
    if crop.size == 0 or y1 <= y0 or x1 <= x0:
        return unknown, None, (left, top)
    lab = cv2.cvtColor(crop.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [np.rint(points - [left, top]).astype(np.int32)], 1)
    inside = mask.astype(bool)
    margin = max(2, round((y1 - y0) * .15))
    expanded = cv2.dilate(mask, np.ones((2 * margin + 1,) * 2, np.uint8)).astype(bool)
    ring = expanded & ~inside
    if ring.sum() < 10:
        return unknown, None, (left, top)
    backdrop = np.median(lab[ring], axis=0)
    ring_spread = float(np.median(np.linalg.norm(lab[ring] - backdrop, axis=1)))
    foreground = (np.linalg.norm(lab - backdrop, axis=2) > 14) & inside
    if foreground.sum() < 12:
        return unknown, None, (left, top)

    # Quantized Lab modes seed deterministic color groups; no random k-means.
    pixels = lab[foreground]
    bins, counts = np.unique(np.round(pixels / 6).astype(int), axis=0, return_counts=True)
    seeds = []
    for index in np.argsort(-counts, kind="stable"):
        candidate = bins[index].astype(float) * 6
        if not seeds or min(np.linalg.norm(candidate - s) for s in seeds) > 18:
            seeds.append(candidate)
        if len(seeds) == 4:
            break
    # Small white glyphs on detailed footage need not be a frequent color mode.
    # Include both luminance tails so scenery cannot crowd them out of the seeds.
    for quantile, bright in ((.9, True), (.1, False)):
        threshold = np.quantile(pixels[:, 0], quantile)
        tail = pixels[pixels[:, 0] >= threshold] if bright else pixels[pixels[:, 0] <= threshold]
        candidate = np.median(tail, axis=0)
        if min(np.linalg.norm(candidate - s) for s in seeds) > 14:
            seeds.append(candidate)
    centers = np.array(seeds)
    for _ in range(3):
        labels = np.argmin(np.linalg.norm(pixels[:, None] - centers, axis=2), axis=1)
        centers = np.array([np.median(pixels[labels == i], axis=0)
                            if np.any(labels == i) else centers[i] for i in range(len(centers))])
    depth = cv2.distanceTransform(foreground.astype(np.uint8), cv2.DIST_L2, 5)[foreground]
    candidates = [i for i in range(len(centers)) if (labels == i).sum() >= max(8, len(labels) * .015)]
    if not candidates:
        return unknown, None, (left, top)

    def components_for(candidate):
        count, components, regions, _ = cv2.connectedComponentsWithStats(candidate.astype(np.uint8), 8)
        keep = [i for i in range(1, count) if regions[i, cv2.CC_STAT_AREA] >= 3
                and regions[i, cv2.CC_STAT_HEIGHT] >= max(2, (y1 - y0) * .15)
                and regions[i, cv2.CC_STAT_WIDTH] <= 3 * regions[i, cv2.CC_STAT_HEIGHT]
                and not (regions[i, cv2.CC_STAT_WIDTH] > .8 * (x1 - x0)
                         and regions[i, cv2.CC_STAT_HEIGHT] > .7 * (y1 - y0))]
        return np.isin(components, keep), regions[keep]

    def glyph_support(i):
        candidate = (np.linalg.norm(lab - centers[i], axis=2) < 13) & inside
        coherent, regions = components_for(candidate)
        area = int(coherent.sum())
        # Anti-alias mixtures can have high depth but no coherent glyph cores.
        support = float(np.median(depth[labels == i])) * min(1., area / max(10, (labels == i).sum()))
        if ring_spread > 5 and len(regions):
            # Favor repeated, aligned glyph-sized components over scenery blobs.
            heights = regions[:, cv2.CC_STAT_HEIGHT]
            centers_y = regions[:, cv2.CC_STAT_TOP] + heights / 2
            alignment = 1 / (1 + float(np.std(centers_y)) / max(1, float(np.median(heights))))
            contrast = min(2., float(np.linalg.norm(centers[i] - backdrop)) / 30)
            support *= min(1., len(regions) / 4) * alignment * contrast
        return support

    fill_index = max(candidates, key=glyph_support)
    fill_lab = centers[fill_index]
    fill = (np.linalg.norm(lab - fill_lab, axis=2) < 13) & inside
    fill, regions = components_for(fill)
    if fill.sum() < 10:
        return unknown, None, (left, top)
    # Geometry includes antialiased half-coverage pixels adjacent to the solid
    # core. Color estimates below still use only core pixels. This avoids
    # shrinking thin white lettering to its few brightest interior pixels.
    competing = [backdrop, *(c for i, c in enumerate(centers) if i != fill_index
                            and np.linalg.norm(c - fill_lab) > 18)]
    background_distance = np.minimum.reduce([np.linalg.norm(lab - c, axis=2) for c in competing])
    extent = ((np.linalg.norm(lab - fill_lab, axis=2) < background_distance) & inside
              & cv2.dilate(fill.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)) | fill
    ys, xs = np.nonzero(extent)
    ink_box = [(left + int(xs.min())) / width, (top + int(ys.min())) / height,
               (left + int(xs.max()) + 1) / width, (top + int(ys.max()) + 1) / height]
    spread = float(np.median(np.linalg.norm(lab[fill] - fill_lab, axis=1)))
    confidence = max(0.1, min(.95, 1 - spread / 25 - ring_spread / 80))

    def color(region, quality):
        value = np.median(lab[region], axis=0).astype(np.float32)
        rgb = cv2.cvtColor(value.reshape(1, 1, 3), cv2.COLOR_LAB2RGB)[0, 0]
        return {"lab": [round(float(v), 3) for v in value],
                "rgb": [int(v) for v in np.rint(np.clip(rgb, 0, 1) * 255)],
                "confidence": round(float(quality), 3)}

    result = dict(unknown, ink_box=ink_box, text_height=ink_box[3] - ink_box[1],
                  geometry_confidence=round(confidence, 3), fill=color(fill, confidence))
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120) != 0
    distance = cv2.distanceTransform(fill.astype(np.uint8), cv2.DIST_L2, 5)[fill]
    result["ink_evidence"] = {
        "component_count": len(regions),
        "edge_density": round(float(edges[inside].mean()), 6),
        "ink_density": round(float(fill.sum() / inside.sum()), 6),
        "stroke_fraction": round(float(np.quantile(distance, .75) * 2 / max(1, y1 - y0)), 6),
        "stroke_to_ink_height": round(float(np.quantile(distance, .75) * 2 / (ys.max() - ys.min() + 1)), 6),
    }
    # Only homogeneous case runs support an observed cap/x-height estimate.
    # Mixed-case lines and joined/occluded glyphs keep these fields unknown.
    letters = [c for c in text if c.isalpha()]
    if len(regions) >= 3 and letters:
        component_height = float(np.median(regions[:, cv2.CC_STAT_HEIGHT])) / height
        if all("A" <= c <= "Z" for c in letters):
            result["cap_height"] = {"value": component_height, "confidence": round(confidence * .8, 3)}
        elif all(c in "acemnorsuvwxz" for c in letters):
            result["x_height"] = {"value": component_height, "confidence": round(confidence * .7, 3)}
    # An outline must contact most of the fill boundary and be a distinct mode.
    edge = cv2.dilate(fill.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & ~fill
    other = [i for i in candidates if i != fill_index]
    if other and edge.sum():
        stroke_index = max(other, key=lambda i: int(((np.linalg.norm(lab - centers[i], axis=2) < 14) & edge).sum()))
        stroke = (np.linalg.norm(lab - centers[stroke_index], axis=2) < 14) & inside & ~fill
        contact = float((stroke & edge).sum() / edge.sum())
        if contact > .35:
            # Area/perimeter gives width for the thin band surrounding glyphs.
            # Distance from fill is less biased by disconnected stroke fragments.
            distance = cv2.distanceTransform((~fill).astype(np.uint8), cv2.DIST_L2, 5)
            near_stroke = stroke & (distance <= max(2, (y1 - y0) * .2))
            if near_stroke.any():
                stroke_width = float(np.quantile(distance[near_stroke], .85))
                result.update(outline=color(near_stroke, confidence * contact),
                              stroke_width_px=round(stroke_width, 3),
                              stroke_width_fraction=stroke_width / height,
                              stroke_confidence=round(confidence * contact, 3))

    # OCR proposals often extend beyond a plate. Inspect a rectangle just
    # outside the measured ink instead of assuming the OCR perimeter is local
    # background. All four sides must support a uniform plate color.
    iy0, iy1, ix0, ix1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    gap = max(3, round((iy1 - iy0) * .15))
    outer = max(6, round((iy1 - iy0) * .3))
    near = np.zeros(inside.shape, dtype=bool)
    near[max(0, iy0 - outer):min(near.shape[0], iy1 + outer),
         max(0, ix0 - outer):min(near.shape[1], ix1 + outer)] = True
    near[max(0, iy0 - gap):min(near.shape[0], iy1 + gap),
         max(0, ix0 - gap):min(near.shape[1], ix1 + gap)] = False
    far = np.zeros(inside.shape, dtype=bool)
    far[:2] = far[-2:] = True
    far[:, :2] = far[:, -2:] = True
    far &= ~expanded
    if far.sum() >= 10 and near.sum() >= 10:
        backdrop = np.median(lab[near], axis=0)
        near_fraction = float(np.mean(np.linalg.norm(lab[near] - backdrop, axis=1) < 10))
        far_color = np.median(lab[far], axis=0)
        far_spread = float(np.median(np.linalg.norm(lab[far] - far_color, axis=1)))
        delta = float(np.linalg.norm(backdrop - far_color))
        if far_spread < 10 and near_fraction > .85:
            present = delta > 14
            result.update(plate_present=present,
                          plate_color=color(near, .7) if present else None,
                          plate_confidence=.7 if present else .6)
            if present and result["outline"] and np.linalg.norm(np.array(result["outline"]["lab"]) - backdrop) < 14:
                result.update(outline=None, stroke_width_px=None, stroke_width_fraction=None, stroke_confidence=0.)
    return result, fill, (left, top)
