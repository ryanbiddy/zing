"""Conservative OCR-region validation using pixels and neighboring samples.

OCR confidence is recognition evidence, not proof of text. Reasons and raw
scores stay in the sidecar even when a proposal cannot enter a caption track.
Script disagreement and face overlap are supporting evidence, never a veto on
legitimate multilingual subtitles or text deliberately placed over a face.
"""

from collections import Counter
from difflib import SequenceMatcher
import unicodedata


THRESHOLDS = {
    "ocr": .75, "corroborated_ocr": .65, "neighbor_seconds": .5,
    "edge_density_min": .015, "ink_density_min": .015,
    "ink_density_max": .8, "stroke_fraction_max": .5,
    "full_frame_area": .6, "single_character_height_max": .35,
    "line_height_max": .6, "aspect_per_character_min": .08,
    "aspect_per_character_max": 2., "face_overlap": .35,
}


def script(text):
    counts = Counter()
    for char in text:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, "")
        family = next((s for s in ("LATIN", "CYRILLIC", "GREEK", "ARABIC", "HEBREW",
                                   "HIRAGANA", "KATAKANA", "HANGUL", "CJK", "DEVANAGARI")
                       if s in name), "OTHER")
        counts[family] += 1
    return counts.most_common(1)[0][0] if counts else None


def _intersection(a, b):
    return max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))


def _area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def assess(frames):
    """Finalize each detection once all neighboring samples are available."""
    limits = THRESHOLDS
    scripts = Counter()
    for frame in frames:
        for d in frame.detections:
            if (d.confidence or 0) >= limits["ocr"] and d.appearance.get("ink_box"):
                scripts[script(d.text)] += sum(c.isalpha() for c in d.text)
    dominant = scripts.most_common(1)[0][0] if scripts else None
    dominant = dominant if dominant and scripts[dominant] >= 20 and scripts[dominant] >= .8 * sum(scripts.values()) else None
    for index, frame in enumerate(frames):
        for d in frame.detections:
            reasons = []
            if frame.status == "ocr_error":
                reasons.append("sample_measurement_failed")
            box = d.box
            chars = max(1, sum(not c.isspace() for c in d.text))
            h = box[3] - box[1]
            aspect = (box[2] - box[0]) * frame.width / (h * frame.height)
            neighbors = set()
            # A bounded temporal neighborhood; never count duplicate times or
            # multiple detections in one frame as repeated evidence.
            for other in frames[max(0, index - 8):index + 9]:
                if not 0 < abs(other.t - frame.t) <= THRESHOLDS["neighbor_seconds"] + 1e-6:
                    continue
                for candidate in other.detections:
                    intersection = _intersection(box, candidate.box)
                    union = _area(box) + _area(candidate.box) - intersection
                    if other.status != "ocr_error" and (candidate.confidence or 0) >= limits["corroborated_ocr"] and intersection / max(union, 1e-9) > .2 and SequenceMatcher(
                            None, d.text.casefold(), candidate.text.casefold()).ratio() >= .6:
                        neighbors.add(other.t)
            stable = len(neighbors) >= 2
            if not d.text.strip() or (d.confidence or 0) < limits["corroborated_ocr"]:
                reasons.append("ocr_text_uncertain")
            if _area(box) >= THRESHOLDS["full_frame_area"]:
                reasons.append("full_frame_region")
            if (h > limits["line_height_max"] or (chars == 1 and h > limits["single_character_height_max"])
                    or not limits["aspect_per_character_min"] <= aspect / chars <= limits["aspect_per_character_max"]):
                reasons.append("size_or_aspect_inconsistent_with_string")
            pixels = d.appearance.get("ink_evidence", {})
            density = pixels.get("ink_density", 0.)
            edge = pixels.get("edge_density", 0.)
            components = pixels.get("component_count", 0)
            textlike = bool(d.appearance.get("ink_box") and limits["ink_density_min"] <= density <= limits["ink_density_max"]
                            and edge >= limits["edge_density_min"] and components >= min(3, chars)
                            and 0 < pixels.get("stroke_fraction", 0.) <= limits["stroke_fraction_max"])
            if not textlike:
                reasons.append("insufficient_text_strokes")
            overlap = max((_intersection(box, face) / max(1e-9, min(_area(box), _area(face)))
                           for face in frame.face_boxes), default=0.) if frame.face_boxes is not None else None
            inconsistent = bool(dominant and script(d.text) and script(d.text) != dominant)
            if not stable and ((overlap or 0) > limits["face_overlap"]) and (chars <= 2 or not textlike):
                reasons.append("isolated_region_over_face")
            if inconsistent and not stable and (chars <= 2 or not textlike):
                reasons.append("isolated_script_disagreement")
            if (d.confidence or 0) < limits["ocr"] and not (stable and textlike and not inconsistent):
                reasons.append("recognition_not_corroborated")
            d.validation = {"accepted": not reasons, "reasons": reasons,
                "confidence": 0. if reasons else min(.95, d.confidence or 0),
                "textlike": textlike, "aspect_per_character": aspect / chars,
                "neighbor_samples": len(neighbors), "temporal_stability": stable,
                "face_overlap": overlap, "script": script(d.text), "dominant_script": dominant,
                "script_consistent": None if not dominant or not script(d.text) else not inconsistent}
        if frame.status != "ocr_error":
            frame.status = ("no_text_detected" if not frame.detections else
                            "low_confidence" if any(not d.validation["accepted"] for d in frame.detections) else "ok")
