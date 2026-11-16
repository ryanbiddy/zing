"""Conservative caption clearance checks without loading a browser or image tools."""
from __future__ import annotations

import math

from .contract import CAPTION_BAND, finite


# Average glyph advance as a share of the font size. The bundled faces run
# from about 0.42 (Anton) to 0.56 (IBM Plex Sans); 0.62 leaves headroom
# without reserving twice the room a card needs. The page still checks the
# measured boxes before it draws captions.
CHAR_EM = .62


def _number(item: dict, key: str, default: float) -> float:
    value = item.get(key, default)
    low, high = {"x": (0, 1080), "y": (0, 1920), "size": (16, 300),
                 "w": (80, 1000), "rot": (-360, 360), "scale": (.1, 5),
                 "head_scale": (.1, 3)}[key]
    return float(value) if finite(value) and low <= value <= high else default


def _lines(value, width: float, em: float) -> int:
    """Estimate word wrapping from an average glyph width (see CHAR_EM)."""
    em *= CHAR_EM
    words = str(value).split()
    count, used = 1 if words else 0, 0.0
    for word in words:
        length = len(word) * em
        if used and used + em + length > max(1, width):
            count += 1
            used = 0
        used += (em if used else 0) + length
    return count


def card_box(card: dict) -> tuple[float, float, float, float]:
    """Bound the authored box, including wrapping, rotation and entry overshoot.

    Text width is estimated, so this can reserve a little more room than the
    font needs. The page also checks its measured boxes before drawing captions.
    """
    kind = card.get("kind")
    if not isinstance(kind, str):
        return 0, 0, 0, 0
    size = _number(card, "size", 120 if kind == "sticker" else 74)
    length = len(str(card.get("text", "")))
    if kind == "note":
        w = _number(card, "w", 520)
        heading = _lines(card.get("k", ""), w - 68, 32.4) * 38 + (8 if card.get("k") else 0)
        h = 58 + heading + max(1, _lines(card.get("text", ""), w - 68, size)) * size * 1.04
    elif kind == "list":
        w = _number(card, "w", 470)
        rows = card.get("rows", [])
        rows = rows if isinstance(rows, list) else []
        heading = _lines(card.get("k", ""), w - 68, 32.4) * 38 + (8 if card.get("k") else 0)
        h = 58 + heading + sum(max(1, _lines(r.get("text", ""), w - 138, 60)) * 75 for r in rows if isinstance(r, dict))
    elif kind == "doc":
        w = 520
        h = (150 + _lines(card.get("k", ""), 440, 30) * 34
             + max(1, _lines(card.get("text", ""), 440, 104)) * 107
             + _lines(card.get("sub", ""), 440, 60) * 68)
    elif kind == "plaque":
        w = 640
        h = (110 + max(1, _lines(card.get("text", ""), 532, 69)) * 80
             + _lines(card.get("sub", ""), 532, 66) * 65)
    else:
        font, pad, height = {
            "sticker": (size, size * .52, size * 1.24),
            "pill": (39, 68, 74), "tag": (32, 40, 62 if not card.get("sub") else 88),
            "sign": (64, 82, 112 if not card.get("sub") else 154), "stamp": (66, 60, 104),
        }.get(kind, (36, 0, 0))
        w, h = max(1, length) * font * CHAR_EM + pad, height
    angle = math.radians(abs(_number(card, "rot", 0)) + .45)
    rw = abs(math.cos(angle)) * w + abs(math.sin(angle)) * h
    rh = abs(math.sin(angle)) * w + abs(math.cos(angle)) * h
    x, y = _number(card, "x", 0), _number(card, "y", 0)
    # Card.fit anchors the rotated box at the authored top-left and scales to
    # the frame. Reserve the full height here so check errs toward clearance.
    overshoot = 2.6 if card.get("anim") == "stamp" else 1.15
    extra = (overshoot - 1) * rh / 2 + 12
    top = y - extra - (520 if card.get("anim") == "drop" else 0)
    return x, top, rw, y + rh + extra - top


def card_overlaps_captions(card: dict) -> bool:
    if not isinstance(card, dict) or not finite(card.get("y")):
        return False
    _, top, _, height = card_box(card)
    return top < CAPTION_BAND["y"] + CAPTION_BAND["height"] and top + height > CAPTION_BAND["y"]


def head_overlaps_captions(actor: dict) -> bool:
    if not isinstance(actor, dict):
        return False
    scale = _number(actor, "scale", 1)
    y = _number(actor, "y", 1562)
    head = _number(actor, "head_scale", 1)
    # Reserve room for the head's bottom, tilt and body sway. Actual image
    # dimensions get a second check on the page, including camera movement.
    bottom = y + 4 + scale * (-480 + 90 * head)
    top = y - scale * (900 + 300 * head)
    return top < CAPTION_BAND["y"] + CAPTION_BAND["height"] and bottom > CAPTION_BAND["y"]
