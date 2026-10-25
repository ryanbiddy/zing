"""Deterministic glyph comparisons, never recovery of an original font.

All scores describe the available file/weight set. Crops use P7 polygons and
fill-color evidence. Textures, occlusion, OCR errors and unsupported glyphs
remain visible as missing evidence or poor scores, never guessed identities.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any

from myzing.fonts import library
from .caption_geometry import CaptionGeometry, FILENAME

# Frozen synthetic calibration, documented in docs/FONT-CANDIDATES.md.
MATCH_THRESHOLD = .90
MAX_SAMPLES = 8


def budget_geometry(geometry):
    """Bound study/explain font work independently of OCR track density."""
    from dataclasses import replace
    from .caption_geometry import sampled
    tracks = []
    total = sum(len(s["detection_indices"]) for t in geometry.tracks for s in t.samples)
    for track in geometry.tracks[:16]:
        samples = [{**s, "detection_indices": s["detection_indices"][:2]}
                   for s in sampled(track.samples, 3)]
        tracks.append(replace(track, samples=samples))
    measured = sum(len(s["detection_indices"]) for t in tracks for s in t.samples)
    return replace(geometry, tracks=tracks), {"tracks_total": len(geometry.tracks), "tracks_measured": len(tracks),
        "observations_total": total, "observations_measured": measured, "observations_omitted": total-measured,
        "max_tracks": 16, "max_samples_per_track": 3, "max_lines_per_sample": 2}


@dataclass
class FontCandidates:
    available_fonts: list[dict] = field(default_factory=list)
    tracks: list[dict] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> FontCandidates:
        if value.get("version") != 1:
            raise ValueError("unsupported font_candidates version")
        return cls(**value)


def _trim(mask):
    import numpy as np
    ys, xs = np.nonzero(mask)
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(xs) else None


def crop_ink(frame, detection):
    """Segment the estimated fill, excluding the outline/plate and polygon exterior."""
    import cv2
    import numpy as np
    from .caption_pixels import measure, segment

    height, width = frame.shape[:2]
    points = np.asarray(detection.polygon, dtype=float) * [width, height]
    if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 3
            or not np.isfinite(points).all()):
        raise ValueError("invalid caption polygon; repeat study --caption-geometry")
    left, top = np.maximum(0, np.floor(points.min(axis=0))).astype(int)
    right, bottom = np.minimum([width, height], np.ceil(points.max(axis=0)) + 1).astype(int)
    if right <= left or bottom <= top:
        return None, "empty polygon crop"
    crop = frame[top:bottom, left:right]
    polygon = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.fillPoly(polygon, [np.rint(points - [left, top]).astype(np.int32)], 1)
    inside = polygon != 0
    if not inside.any():
        return None, "empty polygon interior"
    appearance = detection.appearance or measure(frame, detection.polygon)
    fill = appearance.get("fill")
    if not fill or fill.get("confidence", 0) < .25:
        return None, "fill color uncertain; no reliable glyph mask"
    lab = cv2.cvtColor(crop.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)
    fill_color = np.asarray(fill["lab"])
    edge = inside & ~cv2.erode(polygon, np.ones((5, 5), np.uint8), borderType=cv2.BORDER_CONSTANT,
                              borderValue=0).astype(bool)
    backdrop = np.median(lab[edge if edge.any() else inside], axis=0)
    distance = np.linalg.norm(lab - fill_color, axis=2)
    if np.linalg.norm(fill_color - backdrop) > 18:
        # Nearest-color separation keeps the antialiased half-coverage edge,
        # unlike a narrow distance-to-fill cutoff that thins regular fonts.
        others = [backdrop]
        for name in ("outline", "plate_color"):
            color = appearance.get(name)
            if color and np.linalg.norm(np.asarray(color["lab"]) - fill_color) > 18:
                others.append(np.asarray(color["lab"]))
        background_distance = np.minimum.reduce([np.linalg.norm(lab - c, axis=2) for c in others])
        mask = (distance < background_distance) & inside
        method = "polygon-clipped nearest Lab fill versus backdrop/outline/plate"
    else:
        # Very thin text can make P7's fill mode collapse onto its plate.
        # An Otsu minority-luminance mask is independent of candidate fonts.
        light = np.clip(lab[:, :, 0] * 2.55, 0, 255).astype(np.uint8)
        threshold, _ = cv2.threshold(light[inside], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask = (light > threshold) & inside
        if mask.sum() > inside.sum() / 2:
            mask = (light <= threshold) & inside
        method = "polygon-clipped Otsu minority luminance; P7 fill overlaps backdrop"
    mask = mask.astype(np.uint8)
    if appearance.get("segmentation") == "component-filtered Lab modes v2":
        # Reuse CG2's glyph components. Permit one antialias pixel around each
        # core, but never reintroduce distant scenery of the same fill color.
        _, core, origin = segment(frame, detection.polygon, detection.text)
        if core is None:
            return None, "CG2 glyph segmentation unavailable"
        local = core[top - origin[1]:bottom - origin[1], left - origin[0]:right - origin[0]]
        mask &= cv2.dilate(local.astype(np.uint8), np.ones((3, 3), np.uint8))
        method += "; CG2 component support"
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    keep = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 2]
    mask = _trim(np.isin(labels, keep))
    if mask is None or mask.shape[0] < 8 or mask.sum() < 16 or mask.mean() > .85:
        return None, "insufficient glyph pixels (tiny, solid or empty crop)"
    return mask, {"crop_px": [int(left), int(top), int(right), int(bottom)],
                  "mask_width_px": int(mask.shape[1]), "mask_height_px": int(mask.shape[0]),
                  "fill_lab": fill["lab"], "fill_confidence": fill["confidence"],
                  "segmentation": method,
                  "mask_sha256": __import__("hashlib").sha256(mask.tobytes()).hexdigest()}


def _font(path, size, weight):
    from PIL import ImageFont
    font = ImageFont.truetype(str(path), size=size, layout_engine=ImageFont.Layout.BASIC)
    if weight is not None:
        axes = font.get_variation_axes()
        font.set_variation_by_axes([weight if a["name"] == b"Weight" else a["default"] for a in axes])
    return font


@lru_cache(maxsize=256)
def render_mask(path, text, height, weight=None):
    """Render OCR text near its measured ink height, preserving natural width."""
    import numpy as np
    from PIL import Image, ImageDraw

    font = _font(path, 64, weight)
    # FreeType's .notdef is not evidence of a matching character. Compare the
    # glyph raster to the font's missing-glyph raster before accepting it.
    missing = font.getmask(chr(0x10FFFF))
    missing_key = (missing.size, bytes(missing))
    for char in set(text) - {" "}:
        glyph = font.getmask(char)
        if (glyph.size, bytes(glyph)) == missing_key:
            raise ValueError(f"font lacks OCR character U+{ord(char):04X}")
    bbox = font.getbbox(text)
    size = max(4, min(512, round(64 * height / max(1, bbox[3] - bbox[1]))))
    font = _font(path, size, weight)
    x0, y0, x1, y1 = font.getbbox(text)
    if x1 - x0 > 16000 or y1 - y0 > 2048:
        raise ValueError("rendered OCR text exceeds comparison bounds")
    canvas = Image.new("L", (max(1, x1 - x0 + 4), max(1, y1 - y0 + 4)))
    ImageDraw.Draw(canvas).text((2 - x0, 2 - y0), text, font=font, fill=255)
    mask = _trim(np.asarray(canvas) > 127)
    if mask is None:
        raise ValueError("OCR text has no rendered ink")
    cap_box, x_box = font.getbbox("H"), font.getbbox("x")
    return mask, {"font_size_px": size, "weight": weight,
                  "candidate_cap_height_px": cap_box[3] - cap_box[1],
                  "candidate_x_height_px": x_box[3] - x_box[1],
                  "candidate_x_cap_ratio": round((x_box[3] - x_box[1]) / max(1, cap_box[3] - cap_box[1]), 6)}


def compare_masks(observed, rendered):
    import cv2
    import numpy as np

    for mask in (observed, rendered):
        if mask.ndim != 2 or not mask.size or not mask.any():
            raise ValueError("empty glyph mask; no reliable comparison")
    oh, ow = observed.shape
    rh, rw = rendered.shape
    ratio = (rw / rh) / (ow / oh)
    # Compare shape on a common grid, penalize width independently. Small
    # integer translations absorb pixel-phase/FreeType rasterizer differences.
    width = max(8, min(2048, round(48 * ow / oh)))
    def normalize(mask):
        scaled = cv2.resize(mask.astype(np.uint8), (width, 48), interpolation=cv2.INTER_NEAREST)
        return np.pad(scaled.astype(bool), ((2, 2), (2, 2)))
    a, b = normalize(observed), normalize(rendered)
    best, shift = 0., [0, 0]
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            moved = np.roll(b, (dy, dx), (0, 1))
            iou = float((a & moved).sum() / max(1, (a | moved).sum()))
            if iou > best:
                best, shift = iou, [dx, dy]
    # Integer advance rounding differs between FreeType clients. Align each
    # separated ink run as well as the whole line so accumulated kerning drift
    # does not masquerade as a different glyph design. Keep vertical placement.
    def runs(mask):
        active = np.any(mask, axis=0)
        edges = np.diff(np.pad(active.astype(int), 1))
        return [mask[:, start:end] for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))]
    observed_runs, rendered_runs = runs(observed), runs(rendered)
    glyph_iou = None
    if len(observed_runs) == len(rendered_runs) and len(observed_runs) >= 3:
        glyph_scores = []
        for observed_run, rendered_run in zip(observed_runs, rendered_runs):
            gw = max(3, round(48 * observed_run.shape[1] / oh))
            ga = cv2.resize(observed_run.astype(np.uint8), (gw, 48), interpolation=cv2.INTER_NEAREST).astype(bool)
            gb = cv2.resize(rendered_run.astype(np.uint8), (gw, 48), interpolation=cv2.INTER_NEAREST).astype(bool)
            glyph_scores.append(float((ga & gb).sum() / max(1, (ga | gb).sum())))
        glyph_iou = mean(glyph_scores)
    shape = .75 * glyph_iou + .25 * best if glyph_iou is not None else best
    width_similarity = math.exp(-3 * abs(math.log(ratio)))
    density_ratio = float(rendered.mean() / observed.mean())
    density_similarity = math.exp(-abs(math.log(density_ratio)))
    def stroke(mask):
        padded = np.pad(mask.astype(np.uint8), 1)
        distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[padded != 0]
        return float(np.quantile(distance, .75) * 2 / mask.shape[0])
    metrics = {"aligned_iou": best, "width_height_ratio": ratio,
               "width_similarity": width_similarity, "ink_density_ratio": density_ratio,
               "observed_stroke_fraction": stroke(observed),
               "candidate_stroke_fraction": stroke(rendered)}
    return {"score": round(.78 * shape + .17 * width_similarity + .05 * density_similarity, 6),
            **{k: round(v, 6) for k, v in metrics.items()}, "alignment_shift_px_at_48px": shift,
            "glyph_run_iou": round(glyph_iou, 6) if glyph_iou is not None else None,
            "shape_similarity": round(shape, 6), "observed_ink_runs": len(observed_runs),
            "candidate_ink_runs": len(rendered_runs)}


def _selected(samples):
    if len(samples) <= MAX_SAMPLES:
        return samples
    return [samples[round(i * (len(samples) - 1) / (MAX_SAMPLES - 1))] for i in range(MAX_SAMPLES)]


def _candidate_context(media, geometry, workspace=None, font_ids=None):
    """Collect provenance independently of the optional comparison runtime."""
    from importlib.metadata import version

    result = FontCandidates(provenance={
        "method": "glyph-mask-v1", "network_used": False,
        "geometry_media_hash_verified": False,
        "threshold": MATCH_THRESHOLD, "calibration": "synthetic-latin-v1; see docs/FONT-CANDIDATES.md",
        "score": "0.78 shape + 0.17 exp(-3*abs(log(width ratio))) + 0.05 density similarity; shape = 0.75 glyph-run IoU + 0.25 line IoU when run counts agree, else line IoU",
        "sample_selection": f"up to {MAX_SAMPLES} evenly spaced observations per track; every OCR line",
        "renderer": "Pillow/FreeType BASIC; variable axes other than weight use file defaults",
        "versions": {}, "confidence": "similarity, not probability or original-font identification"})
    errors = {}
    rows = []
    try:
        rows = library.inventory(workspace)
        result.available_fonts = [{k: r[k] for k in ("id", "family", "sha256", "license", "weights", "path", "status")}
                                  for r in rows if r["available"] and (font_ids is None or r["id"] in font_ids)]
        result.provenance.update(
            unavailable_font_ids=[r["id"] for r in rows if not r["available"]],
            excluded_font_ids=[r["id"] for r in rows if font_ids is not None and r["id"] not in font_ids])
    except Exception as exc:
        errors["inventory"] = f"{type(exc).__name__}: {exc}"
    for key, path in (("media_sha256", media), ("manifest_sha256", library.MANIFEST)):
        try:
            result.provenance[key] = library.sha256(path)
        except Exception as exc:
            result.provenance[key] = None
            errors[key] = f"{type(exc).__name__}: {exc}"
    try:
        expected = geometry.provenance.get("media", {}).get("sha256")
        result.provenance["geometry_media_hash_verified"] = bool(expected and expected == result.provenance["media_sha256"])
    except Exception as exc:
        errors["geometry_media_sha256"] = f"{type(exc).__name__}: {exc}"
    for name, package in (("Pillow", "Pillow"), ("OpenCV", "opencv-python-headless"), ("NumPy", "numpy")):
        try:
            result.provenance["versions"][name] = version(package)
        except Exception:
            result.provenance["versions"][name] = None
    if errors:
        result.provenance["errors"] = errors
    return result, rows


def failed_candidates(media: Path, geometry: CaptionGeometry, error: Exception,
                      workspace: Path | None = None) -> FontCandidates:
    """Keep the available assets and per-track failure evidence when study continues."""
    result, _ = _candidate_context(media, geometry, workspace)
    reason = f"{type(error).__name__}: {error}; no font comparison was made; run zing doctor"
    result.provenance["failure"] = {"type": type(error).__name__, "message": str(error)}
    result.warnings.append(f"font candidates unavailable: {reason}")
    for track in geometry.tracks:
        warning = f"font candidates track {track.id}: {reason}"
        result.warnings.append(warning)
        result.tracks.append({"track_id": track.id, "kind": track.kind, "text": track.text,
                              "status": "unmeasured", "original_font": "unknown", "reason": reason,
                              "candidates": [], "evidence": [], "gaps": [], "rejected_candidates": [],
                              "warnings": [warning]})
    return result


def match_geometry(media: Path, geometry: CaptionGeometry, workspace: Path | None = None,
                   *, font_ids: list[str] | None = None) -> FontCandidates:
    """Rank each track using existing, verified assets only. No OCR or network."""
    try:
        import cv2
        import numpy as np
        import PIL
    except ImportError as exc:
        raise RuntimeError(f"font comparison runtime missing; install with {library.INSTALL_HINT}") from exc
    result, rows = _candidate_context(media, geometry, workspace, font_ids)
    if result.provenance.get("errors"):
        raise RuntimeError(f"font comparison provenance unavailable: {result.provenance['errors']}")
    if font_ids is not None and set(font_ids) - {r["id"] for r in rows}:
        raise ValueError("unknown font IDs; run zing fonts list")
    expected = geometry.provenance.get("media", {}).get("sha256")
    if expected and not result.provenance["geometry_media_hash_verified"]:
        raise ValueError("caption geometry media SHA-256 mismatch; repeat study --caption-geometry")
    result.provenance["versions"] = {"Pillow": PIL.__version__, "OpenCV": cv2.__version__, "NumPy": np.__version__}
    available = result.available_fonts
    if not available:
        result.warnings.append("font candidates unavailable: run zing fonts list, then zing fonts fetch --all; tracks remain unmeasured")
    requests: dict[int, list] = {}
    observations = {t.id: [] for t in geometry.tracks}
    gaps = {t.id: [] for t in geometry.tracks}
    track_warnings = {t.id: [] for t in geometry.tracks}

    def warn(track_id, reason):
        warning = f"font candidates track {track_id}: {reason}"
        if warning not in track_warnings[track_id]:
            track_warnings[track_id].append(warning)
            result.warnings.append(warning)

    for track in geometry.tracks:
        for sample in _selected(track.samples):
            frame = geometry.frames[sample["sample_index"]]
            if frame.frame_index < 0:
                raise ValueError("negative caption frame index")
            for index in sample["detection_indices"]:
                requests.setdefault(frame.frame_index, []).append((track.id, frame, index))
    cap = cv2.VideoCapture(str(media))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError("font comparison could not decode study media; run zing doctor")
    try:
        for index in sorted(requests):
            try:
                if not cap.set(cv2.CAP_PROP_POS_FRAMES, index):
                    raise RuntimeError("frame seek failed")
                ok, pixels = cap.read()
                if not ok:
                    raise RuntimeError("frame unavailable")
                if cap.get(cv2.CAP_PROP_POS_FRAMES) != index + 1:
                    raise RuntimeError("frame seek did not reach the requested index")
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                for track_id, frame, detection_index in requests[index]:
                    gaps[track_id].append({"frame_index": index, "t": frame.t, "reason": reason})
                    warn(track_id, reason)
                continue
            for track_id, frame, detection_index in requests[index]:
                detection = frame.detections[detection_index]
                evidence = {"frame_index": index, "t": frame.t, "detection_index": detection_index,
                            "text": detection.text, "ocr_confidence": detection.confidence,
                            "polygon": detection.polygon}
                if (not detection.text.strip() or len(detection.text) > 160 or "\n" in detection.text
                        or detection.confidence is None or detection.confidence < .6):
                    gaps[track_id].append(dict(evidence, reason="unsupported or uncertain OCR text"))
                    continue
                try:
                    if pixels.shape[:2] != (frame.height, frame.width):
                        from .caption_geometry import MAX_SIDE
                        if max(frame.width, frame.height) != MAX_SIDE or abs(pixels.shape[1]/pixels.shape[0]-frame.width/frame.height) > .01:
                            raise ValueError("caption geometry frame dimensions changed; repeat study --caption-geometry")
                        pixels = cv2.resize(pixels, (frame.width, frame.height), interpolation=cv2.INTER_AREA)
                    mask, detail = crop_ink(pixels, detection)
                except Exception as exc:
                    mask, detail = None, f"{type(exc).__name__}: {exc}"
                if mask is None:
                    gaps[track_id].append(dict(evidence, reason=detail))
                    warn(track_id, detail)
                else:
                    observations[track_id].append((mask, dict(evidence, **detail)))
    finally:
        cap.release()
    comparisons = {}
    for track in geometry.tracks:
        evidence = observations[track.id]
        ranked, rejected = [], []
        for row in available if evidence else []:
            variants = []
            for weight in row["weights"]:
                scores = []
                try:
                    for mask, detail in evidence:
                        key = (row["id"], weight, detail["text"], detail["mask_sha256"])
                        if key not in comparisons:
                            rendered, render_detail = render_mask(row["path"], detail["text"], mask.shape[0], weight)
                            comparisons[key] = dict(compare_masks(mask, rendered), **render_detail)
                        scores.append(comparisons[key])
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                    rejected.append({"font_id": row["id"], "weight": weight, "reason": reason})
                    warn(track.id, f"{row['id']} weight {weight}: {reason}")
                    continue
                variants.append({"font_id": row["id"], "family": row["family"], "weight": weight,
                                 "score": round(mean(s["score"] for s in scores), 6), "metrics": scores})
            if variants:
                ranked.append(max(variants, key=lambda v: v["score"]))
        ranked.sort(key=lambda r: (-r["score"], r["font_id"]))
        status = "unmeasured" if not ranked else "plausible candidate" if ranked[0]["score"] >= MATCH_THRESHOLD else "best substitute"
        result.tracks.append({"track_id": track.id, "kind": track.kind, "text": track.text,
                              "status": status, "original_font": "unknown",
                              "reason": ("no usable glyph comparison" if not ranked else
                                         "no available font clears the similarity threshold; the source font may be absent or the pixels/text may differ" if status == "best substitute" else
                                         "similar glyphs in the available set; this does not establish the original font"),
                              "candidates": ranked, "evidence": [d for _, d in evidence],
                              "gaps": gaps[track.id], "rejected_candidates": rejected,
                              "warnings": track_warnings[track.id]})
    return result


def match_study(slug: str, workspace: Path | None = None) -> tuple[Path, FontCandidates]:
    """Add only the font section, preserving other sidecar fields and observations."""
    from myzing import storage
    with storage.use_workspace(storage.resolve_workspace(workspace)):
        folder = storage.breakdown_dir(slug)
        path = folder / FILENAME
        if not path.is_file():
            raise ValueError("caption-geometry.json missing; first run zing study <source> --caption-geometry")
        raw = json.loads(path.read_text(encoding="utf-8"))
        geometry = CaptionGeometry.from_dict({k: v for k, v in raw.items()
                                              if k in {f.name for f in fields(CaptionGeometry)}})
        media = storage.find_media(slug)
        if media is None:
            raise ValueError("study media missing; restore media in the breakdown folder or repeat study")
        result = match_geometry(media, geometry)
        raw["font_candidates"] = result.to_dict()
        # Preserve unfamiliar top-level fields for forward-compatible writers.
        import os
        import tempfile
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder,
                                             suffix=".part", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(raw, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path, result
