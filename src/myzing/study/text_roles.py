"""Rule-only OCR roles. Ambiguous text is excluded from caption-style evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re

from myzing.contracts import Record
from myzing.timing import finite


def tokens(text):
    return set(re.findall(r"\w+", text.casefold()))


@dataclass
class TextRole(Record):
    event_index: int
    text: str
    start: float
    end: float
    role: str
    reason: str
    features: dict
    version: int = 1


def classify_text(breakdown, geometry=None):
    """Caption requires time-aligned speech plus lexical or recurring layout evidence.

    A lower anchor alone is not evidence. Credits, persistent overlays and
    moving scene labels are negatives. Missing geometry stays unknown in the
    features; the conservative fallback is scene_text, not caption.
    """
    tracks = (geometry or {}).get("tracks", [])
    roles = []
    for i, event in enumerate(breakdown.captions):
        duration = max(0., event.end - event.start)
        words = [w for w in breakdown.words if finite(w.start) and finite(w.end)
                 and w.end > w.start and w.start < event.end and w.end > event.start]
        speech = sum(max(0., min(w.end, event.end) - max(w.start, event.start)) for w in words)
        overlap = min(1., speech / duration) if duration else 0.
        terms = tokens(event.text)
        lexical = len(terms & tokens(" ".join(w.text for w in words))) / max(1, len(terms))
        matching = [t for t in tracks if tokens(t["text"]) & terms and any(
            event.start - .2 <= s["t"] <= event.end + .2 for s in t.get("samples", []))]
        persistent = any(t.get("kind") == "overlay" for t in matching) or duration >= max(8., breakdown.meta.duration * .7)
        moving = any(t.get("motion") == "moving" for t in matching)
        lower = event.position in {"lower", "bottom"}
        recurring = sum(c.position == event.position and 0 < c.end - c.start <= 4
                        for c in breakdown.captions) >= 3
        credit = bool(re.search(r"\b(directed|produced|written|starring|copyright|production|presents|producer|director|music by|blender foundation|film fund|supported by|financed by|sponsored by)\b|©", event.text, re.I))
        features = {"position": event.position, "duration_seconds": duration,
                    "persistent": persistent, "motion": "moving" if moving else "static" if matching else "unmeasured",
                    "speech_overlap": round(overlap, 4), "speech_text_agreement": round(lexical, 4),
                    "recurring_anchor": recurring, "matched_tracks": [t["id"] for t in matching]}
        if credit and lexical < .6:
            role, reason = "credit", "Credit vocabulary without matching spoken text."
        elif persistent and lexical < .6:
            role, reason = "scene_text", "Persistent text/overlay without matching speech."
        elif overlap >= .15 - 1e-9 and lexical >= .6 and not (moving and not lower and lexical < .9):
            role, reason = "caption", "Text agrees with concurrent speech."
        elif lower and recurring and .4 <= duration <= 4 and overlap >= .5 and not moving and lexical >= .3:
            role, reason = "caption", "Recurring lower text with speech overlap and partial lexical agreement."
        elif event.position == "center" and duration >= 1.5 and overlap < .1 and not moving:
            role, reason = "title", "Sustained centered text outside speech; title heuristic."
        else:
            role, reason = "scene_text", "Insufficient evidence of speech captions; scene text or uncertain OCR."
        roles.append(TextRole(i, event.text, event.start, event.end, role, reason, features))
    return {"version": 1, "method": "text-role-rules-v1", "counts": {
        role: sum(r.role == role for r in roles) for role in ("caption", "title", "credit", "scene_text")},
        "events": [r.to_dict() for r in roles],
        "scope": "Heuristic roles, not labeled ground truth; uncertain events cannot inform caption style."}


def caption_geometry(geometry, roles):
    result = deepcopy(geometry)
    caption_ids = {tid for e in roles["events"] if e["role"] == "caption" for tid in e["features"]["matched_tracks"]}
    excluded_ids = {tid for e in roles["events"] if e["role"] != "caption" for tid in e["features"]["matched_tracks"]}
    allowed = caption_ids - excluded_ids
    result["tracks"] = [t for t in result.get("tracks", []) if t["id"] in allowed]
    if result.get("font_candidates"):
        result["font_candidates"]["tracks"] = [t for t in result["font_candidates"].get("tracks", []) if t["track_id"] in allowed]
    return result
