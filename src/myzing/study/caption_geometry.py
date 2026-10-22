"""Opt-in caption measurements, independent of the v1 Breakdown schema.

Coordinates are normalized display-frame edges [left, top, right, bottom].
Samples are point observations at decoded CFR frame times, never intervals
of known geometry. Motion fits describe only contiguous sampled runs; their
interiors remain unobserved. OCR polygons and refined fill-ink boxes are both
retained. No font family, point size, or original editor settings are inferred.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any, Iterator

from . import captions, caption_models, formats

FILENAME = "caption-geometry.json"


class JsonRecord:
    versions = (1,)
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]):
        if value.get("version", 1) not in cls.versions:
            raise ValueError(f"unsupported {cls.__name__} version: {value['version']}")
        return cls(**value)


@dataclass
class Detection(JsonRecord):
    text: str
    confidence: float | None
    polygon: list[list[float]]
    box: list[float]
    appearance: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    validation: dict[str, Any] = field(default_factory=dict)


@dataclass
class FrameSample(JsonRecord):
    t: float
    scheduled_t: float
    step: float
    frame_index: int
    width: int
    height: int
    detections: list[Detection] = field(default_factory=list)
    status: str = "ok"
    version: int = 1
    face_boxes: list[list[float]] | None = None

    @classmethod
    def from_dict(cls, value):
        return super().from_dict({**value, "detections": [
            Detection.from_dict(d) for d in value.get("detections", [])]})


@dataclass
class CaptionTrack(JsonRecord):
    id: str
    text: str
    kind: str
    samples: list[dict[str, Any]]
    median_text_height: float | None
    line_count: int
    alignment: str
    alignment_confidence: float
    motion: str
    path: list[dict[str, Any]]
    classification: dict[str, Any]
    version: int = 1


@dataclass
class CaptionGeometry(JsonRecord):
    versions = (1, 2)
    duration: float
    frames: list[FrameSample] = field(default_factory=list)
    tracks: list[CaptionTrack] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    version: int = 2
    font_candidates: dict[str, Any] | None = None

    def to_dict(self):
        value = super().to_dict()
        if self.font_candidates is None:
            value.pop("font_candidates")
        return value

    @classmethod
    def from_dict(cls, value):
        if value.get("font_candidates") is not None:
            from .font_match import FontCandidates
            FontCandidates.from_dict(value["font_candidates"])
        return super().from_dict({**value,
            "frames": [FrameSample.from_dict(f) for f in value.get("frames", [])],
            "tracks": [CaptionTrack.from_dict(t) for t in value.get("tracks", [])]})

    def summary(self) -> dict[str, Any]:
        return {"file": FILENAME, "caption_tracks": sum(t.kind == "caption" for t in self.tracks),
                "overlay_tracks": sum(t.kind == "overlay" for t in self.tracks),
                "sampled_frames": len(self.frames),
                "low_confidence_frames": len(self.coverage.get("low_confidence_frames", [])),
                "gaps": len(self.coverage.get("gaps", []))}

    def write(self, folder: Path) -> Path:
        path = folder / FILENAME
        # A failed write must not leave half a JSON document at the public path.
        import os
        import tempfile
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder,
                                             suffix=".part", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self.to_dict(), stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path


def _bounds(polygon):
    return [min(p[0] for p in polygon), min(p[1] for p in polygon),
            max(p[0] for p in polygon), max(p[1] for p in polygon)]


def _center(box):
    return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]


def _iou(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    return area / union if union else 0.0


def parse_ocr(out, frame) -> list[Detection]:
    """Retain low/absent scores and reject malformed geometry explicitly."""
    boxes = getattr(out, "boxes", None)
    texts = getattr(out, "txts", None)
    scores = getattr(out, "scores", None)
    boxes = list(boxes) if boxes is not None else []
    texts = list(texts) if texts is not None else []
    scores = list(scores) if scores is not None else []
    if len(texts) != len(boxes) or (scores and len(scores) != len(boxes)):
        raise ValueError("OCR boxes, text and scores have different lengths")
    height, width = frame.shape[:2]
    result = []
    for i, box in enumerate(boxes):
        if len(box) < 3 or any(len(p) != 2 or not all(math.isfinite(float(v)) for v in p) for p in box):
            raise ValueError("OCR returned a nonfinite or malformed polygon")
        polygon = [[min(1., max(0., float(x) / width)), min(1., max(0., float(y) / height))] for x, y in box]
        bounds = _bounds(polygon)
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise ValueError("OCR returned an empty polygon")
        score = float(scores[i]) if scores else None
        if score is not None and (not math.isfinite(score) or not 0 <= score <= 1):
            score = None
        result.append(Detection(str(texts[i] or "").strip(), score, polygon, bounds))
    return result


def iter_frames(path: Path, duration: float) -> Iterator[tuple[float, float, float, int, Any]]:
    """Read every frame once; label samples by actual CFR frame time, not target."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"could not decode {path.name}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise RuntimeError("decoder did not report a valid CFR frame rate")
        schedule = captions.sample_schedule(duration)
        want, index = 0, 0
        while want < len(schedule):
            got, frame = cap.read()
            if not got:
                break
            t = index / fps
            if t >= duration:
                break
            target, step = schedule[want]
            if t + 1e-9 >= target:
                yield t, target, step, index, frame
                # A low-fps source cannot supply several distinct observations
                # at the same decoded time. Missed targets remain coverage gaps.
                while want < len(schedule) and schedule[want][0] <= t + 1e-9:
                    want += 1
            index += 1
    finally:
        cap.release()


def read_geometry(path: Path, duration: float) -> CaptionGeometry:
    result = CaptionGeometry(duration if math.isfinite(duration) and duration > 0 else 0.)
    result.provenance = {
        "method": "caption-geometry-v2", "coordinate_space": "normalized display-frame edges",
        "text_height": "visible fill ink / frame height (not font em size)",
        "colors": "CIE Lab D65 component medians; sRGB estimates from decoded BGR",
        "confidence": "heuristic quality scores, not calibrated probabilities",
        "model_sha256": {role: digest for role, (_, digest) in caption_models.MODELS.items()},
        "network_used": False,
        "motion_threshold_fraction": .015,
        "linear_path_max_residual_fraction": .01,
        "ocr_confidence_threshold": captions.CONF_THRESHOLD,
    }
    if not result.duration:
        result.warnings.append("caption geometry not measured: unknown duration")
        result.coverage = _coverage(result, [])
        return result
    schedule = captions.sample_schedule(duration)
    try:
        if path.is_file():
            import hashlib
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            result.provenance["media"] = {"file": path.name, "sha256": digest.hexdigest()}
        engine, backend = caption_models.engine()
        result.provenance["ocr_backend"] = backend
        import numpy as np
        from .caption_pixels import measure
        from .caption_regions import THRESHOLDS
        from myzing.layout.detector import YuNetDetector, model_path, verified_model
        result.provenance["region_thresholds"] = dict(THRESHOLDS)
        faces = None
        result.provenance["face_evidence"] = "unavailable; no verified local YuNet model"
        if verified_model(model_path()):
            try:
                faces = YuNetDetector()
                result.provenance["face_evidence"] = "local YuNet; same decoded OCR samples"
            except Exception as exc:
                result.provenance["face_evidence"] = f"unavailable: {exc}"
        previous, previous_detections = None, []
        for t, target, step, index, frame in iter_frames(path, duration):
            sample = FrameSample(t, target, step, index, frame.shape[1], frame.shape[0])
            try:
                if previous is not None and np.array_equal(previous, frame):
                    # Validation is sample-specific even for identical pixels.
                    import copy
                    sample.detections = copy.deepcopy(previous_detections)
                else:
                    sample.detections = parse_ocr(engine(frame), frame)
                    for detection in sample.detections:
                        if detection.text and (detection.confidence or 0) >= THRESHOLDS["corroborated_ocr"]:
                            detection.appearance = measure(frame, detection.polygon, detection.text)
                if faces is not None and sample.detections:
                    try:
                        sample.face_boxes = [[d.box.x, d.box.y, d.box.right, d.box.bottom]
                                             for d in faces.detect(frame)]
                    except Exception as exc:
                        result.warnings.append(f"face evidence unavailable at {t:.6f}s: {exc}")
                if not sample.detections:
                    sample.status = "no_text_detected"
                elif any(not _confident(d) for d in sample.detections):
                    sample.status = "low_confidence"
                previous, previous_detections = frame, sample.detections
            except Exception as exc:
                sample.status = "ocr_error"
                previous = None  # Failed inference is never reused as an empty result.
                result.warnings.append(f"caption geometry sample {t:.6f}s failed: {exc}; recorded as a coverage gap")
            result.frames.append(sample)
    except ImportError:
        result.warnings.append("caption geometry not measured: install myzing[study] (rapidocr/onnxruntime/OpenCV)")
    except Exception as exc:
        result.warnings.append(f"caption geometry incomplete: {exc}; run 'zing doctor' for runtime checks")
    if result.frames:
        from .caption_regions import assess
        assess(result.frames)
    result.tracks = track_frames(result.frames, duration)
    result.coverage = _coverage(result, schedule)
    if result.coverage["gaps"]:
        result.warnings.append(f"caption geometry: {len(result.coverage['gaps'])} coverage gap(s); see {FILENAME}")
    return result


def _confident(d):
    if d.validation:
        return d.validation.get("accepted") is True
    return bool(d.text and d.confidence is not None and d.confidence >= captions.CONF_THRESHOLD)


def _coverage(result, schedule):
    gaps = []
    seen = {round(f.scheduled_t, 6) for f in result.frames}
    for target, step in schedule:
        if round(target, 6) not in seen:
            gaps.append({"t": target, "reason": "frame_unavailable"})
    for f in result.frames:
        if f.status != "ok":
            gaps.append({"t": f.t, "reason": f.status,
                         "scope": "uncertain detections" if f.status == "low_confidence" else "frame"})
        for index, d in enumerate(f.detections):
            if d.validation and not d.validation["accepted"]:
                gaps.append({"t": f.t, "reason": "rejected_text_region", "scope": "detection",
                             "detection_index": index, "reasons": d.validation["reasons"]})
    # A watermark can still be recognized while a caption is occluded. Frame
    # status alone would hide that loss, so name missing observations within
    # each linked track as well. We do not infer unseen starts or ends.
    for track in result.tracks:
        for before, after in zip(track.samples, track.samples[1:]):
            for index in range(before["sample_index"] + 1, after["sample_index"]):
                gaps.append({"t": result.frames[index].t, "reason": "track_not_detected",
                             "scope": "track", "track_id": track.id})
    # No claim that no_text_detected means no visible text; it may be occluded
    # or missed entirely by the detector. Every interval between samples is unknown.
    times = [f.t for f in result.frames]
    boundaries = sorted(set([0., result.duration, *times]))
    intervals = [{"start": a, "end": b} for a, b in zip(boundaries, boundaries[1:]) if b > a]
    return {"hook_fps": captions.HOOK_FPS, "body_fps": formats.body_fps(result.duration),
            "hook_window_s": formats.hook_window_s(result.duration),
            "sampled_fps": len(times) / result.duration if result.duration else 0.,
            "expected_frames": len(schedule), "sampled_frames": len(times),
            "low_confidence_frames": [f.t for f in result.frames if f.status == "low_confidence"],
            "gaps": sorted(gaps, key=lambda g: g["t"]), "unsampled_intervals": intervals,
            "geometry_between_samples": "unobserved; paths are fits, not measurements"}


def _groups(frame):
    """Group adjacent rows with horizontal overlap; never merge same-row labels."""
    groups = []
    for index, d in sorted(enumerate(frame.detections), key=lambda p: (p[1].box[1], p[1].box[0])):
        if not _confident(d):
            continue
        best = None
        for group in groups:
            prev = frame.detections[group[-1]].box
            h1, h2 = prev[3] - prev[1], d.box[3] - d.box[1]
            overlap = min(prev[2], d.box[2]) - max(prev[0], d.box[0])
            narrow = min(prev[2] - prev[0], d.box[2] - d.box[0])
            if (-.1 * min(h1, h2) <= d.box[1] - prev[3] <= .8 * max(h1, h2)
                    and min(h1, h2) / max(h1, h2) > .6 and overlap > .5 * narrow):
                best = group
                break
        if best is None:
            groups.append([index])
        else:
            best.append(index)
    return groups


def _normalize(text):
    return " ".join(text.casefold().split())


def _similarity(a, b):
    a, b = _normalize(a), _normalize(b)
    short, long = sorted((a, b), key=len)
    if short and (long == short or long.startswith(short + " ")):
        return 1.
    return SequenceMatcher(None, a, b).ratio()


def track_frames(frames: list[FrameSample], duration: float) -> list[CaptionTrack]:
    streams: list[list[dict]] = []
    for sample_index, frame in enumerate(frames):
        if frame.status == "ocr_error":
            continue
        observations = []
        for group in _groups(frame):
            detections = [frame.detections[i] for i in group]
            boxes = [d.appearance.get("ink_box") or d.box for d in detections]
            box = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                   max(b[2] for b in boxes), max(b[3] for b in boxes)]
            heights = [d.appearance["text_height"] for d in detections if d.appearance.get("text_height") is not None]
            observations.append({"sample_index": sample_index, "t": frame.t,
                "box": box, "box_method": "fill_ink" if all(d.appearance.get("ink_box") for d in detections) else "ocr_proposal",
                "text": " ".join(d.text for d in detections), "detection_indices": group,
                "line_boxes": boxes, "line_count": len(group),
                "text_height": median(heights) if heights else None})
        pairs = []
        for i, stream in enumerate(streams):
            last = stream[-1]
            dt = frame.t - last["t"]
            if dt <= 0 or dt > captions.MAX_FLICKER_GAP_S + 1e-6:
                continue
            predicted = last["box"]
            if len(stream) > 1:
                prior = stream[-2]
                elapsed = last["t"] - prior["t"]
                velocity = [(a - b) / elapsed for a, b in zip(_center(last["box"]), _center(prior["box"]))]
                predicted = [v + velocity[k % 2] * dt for k, v in enumerate(predicted)]
            for j, observation in enumerate(observations):
                similarity = _similarity(last["text"], observation["text"])
                overlap = max(_iou(last["box"], observation["box"]), _iou(predicted, observation["box"]))
                distance = max(abs(a - b) for a, b in zip(_center(predicted), _center(observation["box"])))
                if similarity >= .8 and (overlap > .1 or distance < .08):
                    pairs.append((similarity + overlap - distance, i, j))
        used_tracks, used_observations = set(), set()
        for _, i, j in sorted(pairs, reverse=True):
            if i not in used_tracks and j not in used_observations:
                streams[i].append(observations[j])
                used_tracks.add(i)
                used_observations.add(j)
        streams.extend([obs] for j, obs in enumerate(observations) if j not in used_observations)
    return [_build_track(i, stream, frames, duration) for i, stream in enumerate(streams)]


def _build_track(index, samples, frames, duration):
    centers = [_center(s["box"]) for s in samples]
    displacement = max(max(c[k] for c in centers) - min(c[k] for c in centers) for k in (0, 1))
    texts = [_normalize(s["text"]) for s in samples]
    changes = [b for a, b in zip(texts, texts[1:]) if a != b]
    growth = any(b.startswith(a + " ") for a, b in zip(texts, texts[1:]))
    popping = growth and all(a == b or b.startswith(a + " ") for a, b in zip(texts, texts[1:]))
    motion = "popping" if popping else "moving" if displacement > .015 else "static"
    # Persistence uses the full requested schedule, so decode truncation cannot
    # promote a short-lived caption to a whole-video overlay.
    expected = captions.sample_schedule(duration)
    occupancy = len(samples) / len(expected) if expected else 0.
    covers_ends = bool(expected and samples[0]["t"] <= expected[0][1]
                       and samples[-1]["t"] >= expected[-1][0] - expected[-1][1] - 1e-6)
    stable_text = all(SequenceMatcher(None, texts[0], t).ratio() >= .95 for t in texts)
    overlay = len(samples) >= 3 and covers_ends and occupancy >= .9 and stable_text and motion == "static"
    alignment, alignment_confidence = _alignment(samples)
    heights = [s["text_height"] for s in samples if s["text_height"] is not None]
    return CaptionTrack(f"text-{index + 1:04d}", max((s["text"] for s in samples), key=len),
        "overlay" if overlay else "caption", samples, median(heights) if heights else None,
        Counter(s["line_count"] for s in samples).most_common(1)[0][0],
        alignment, alignment_confidence, motion, _fit_path(samples) if motion == "moving" or displacement > .015 else [],
        {"confidence": .85 if overlay else .6, "sample_fraction": occupancy,
         "reason": "persistent, spatially static, low-change text across the clip" if overlay else "caption candidate",
         "text_changes": len(changes)})


def _alignment(samples):
    costs = {"left": [], "center": [], "right": []}
    for s in samples:
        boxes = s["line_boxes"]
        if len(boxes) > 1:
            for name, values in (("left", [b[0] for b in boxes]),
                                 ("center", [_center(b)[0] for b in boxes]),
                                 ("right", [b[2] for b in boxes])):
                costs[name].append(max(values) - min(values))
    if costs["left"]:
        ranked = sorted((median(v), k) for k, v in costs.items())
        return ranked[0][1], .8 if ranked[1][0] - ranked[0][0] > .01 else .3
    # A single unchanging line cannot identify its typographic alignment.
    # Report its nearest frame anchor as a low-confidence placement estimate.
    x = median(_center(s["box"])[0] for s in samples)
    return ("left" if x < .33 else "right" if x > .67 else "center"), .25


def _fit_path(samples):
    runs = []
    for s in samples:
        if not runs or s["sample_index"] != runs[-1][-1]["sample_index"] + 1 or s["t"] - runs[-1][-1]["t"] > .5:
            runs.append([])
        runs[-1].append(s)
    path = []
    for run in runs:
        times = [s["t"] for s in run]
        centers = [_center(s["box"]) for s in run]
        mean_t = sum(times) / len(times)
        denom = sum((t - mean_t) ** 2 for t in times)
        means = [sum(p[k] for p in centers) / len(centers) for k in (0, 1)]
        slopes = [sum((t - mean_t) * (p[k] - means[k]) for t, p in zip(times, centers)) / denom
                  if denom else 0. for k in (0, 1)]
        fitted = [[means[k] + slopes[k] * (t - mean_t) for k in (0, 1)] for t in times]
        residual = max(max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(centers, fitted))
        linear = residual <= .01 and all(0 <= v <= 1 for p in fitted for v in p)
        indices = sorted(set([0, len(run) - 1])) if linear else range(len(run))
        path.append({"method": "linear_least_squares" if linear else "piecewise_sample_centers",
                     "max_residual": residual if linear else 0.,
                     "keyframes": [{"t": times[i], "center": fitted[i] if linear else centers[i]} for i in indices],
                     "between_keyframes": "fitted, unobserved"})
    return path


def caption_events(geometry: CaptionGeometry):
    """Project opt-in caption tracks into the existing coarse v1 view."""
    events = []
    for track in geometry.tracks:
        if track.kind != "caption":
            continue
        observations = []
        for s in track.samples:
            frame = geometry.frames[s["sample_index"]]
            lines = [captions.Line(d.text, d.confidence, _center(d.box)[1], _center(d.box)[0])
                     for i in s["detection_indices"] for d in [frame.detections[i]]]
            observations.append(captions.Observation(frame.t, min(frame.step, geometry.duration - frame.t), lines))
        event = captions._build_event(observations)
        # Keep actual sample times: millisecond rounding can collapse a very
        # short valid clip to a zero-length v1 interval (the P2 boundary).
        event.start = observations[0].t
        event.end = min(observations[-1].t + observations[-1].step, geometry.duration)
        events.append(event)
    return sorted(events, key=lambda e: (e.start, e.position))
