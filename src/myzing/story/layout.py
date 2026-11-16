"""Conservative caption clearance checks without loading a browser or image tools."""
from __future__ import annotations

import math
import struct
from pathlib import Path

from . import StoryError
from .contract import CAPTION_BAND, VOCABULARY, cue_time, finite


# Average glyph advance as a share of the font size. The bundled faces run
# from about 0.42 (Anton) to 0.56 (IBM Plex Sans); 0.62 leaves headroom
# without reserving twice the room a card needs. The page still checks the
# measured boxes before it draws captions.
CHAR_EM = .62
# The headline face (Anton) is condensed: about 0.44 em a glyph in capitals.
NARROW_EM = .5
HEAD_GEOMETRY = VOCABULARY["head_geometry"]
HEAD_MARGIN = 3
# The head box is the whole cut with its sway. A settled card may clip this
# much of each edge (hair, the sticker border) before it reaches the face.
FACE_INSET = .2


def _number(item: dict, key: str, default: float) -> float:
    value = item.get(key, default)
    low, high = {"x": (0, 1080), "y": (0, 1920), "size": (16, 300),
                 "w": (80, 1000), "rot": (-360, 360), "scale": (.1, 5),
                 "head_scale": (.1, 3)}[key]
    return float(value) if finite(value) and low <= value <= high else default


def _lines(value, width: float, em: float, *, narrow: bool = False) -> int:
    """Estimate word wrapping from an average glyph width (see CHAR_EM)."""
    em *= NARROW_EM if narrow else CHAR_EM
    words = str(value).split()
    count, used = 1 if words else 0, 0.0
    for word in words:
        length = len(word) * em
        if used and used + em + length > max(1, width):
            count += 1
            used = 0
        used += (em if used else 0) + length
    return count


def card_box(card: dict, *, resting: bool = False) -> tuple[float, float, float, float]:
    """Bound the authored box, including wrapping, rotation and entry overshoot.

    ``resting`` leaves out the entry animation: the box the card settles into.

    Text width is estimated, so this can reserve a little more room than the
    font needs. The page also checks its measured boxes before drawing captions.
    """
    kind = card.get("kind")
    if not isinstance(kind, str):
        return 0, 0, 0, 0
    size = _number(card, "size", 120 if kind == "sticker" else 74)
    length = len(str(card.get("text", "")))
    if kind == "credits":
        size = _number(card, "size", 27)
        w = _number(card, "w", 900)
        # Each span has 12 px padding on either side; long unbroken credits
        # wrap too because the page uses overflow-wrap:anywhere.
        h = 6 + sum(max(1, _lines(line, w - 24, size),
                        math.ceil(len(str(line)) * size * CHAR_EM / (w - 24)))
                    * size * 1.5 for line in card.get("lines", []))
    elif kind == "note":
        w = _number(card, "w", 520)
        heading = _lines(card.get("k", ""), w - 68, 32.4) * 38 + (8 if card.get("k") else 0)
        h = 58 + heading + max(1, _lines(card.get("text", ""), w - 68, size, narrow=True)) * size * 1.04
    elif kind == "list":
        w = _number(card, "w", 470)
        rows = card.get("rows", [])
        rows = rows if isinstance(rows, list) else []
        heading = _lines(card.get("k", ""), w - 68, 32.4) * 38 + (8 if card.get("k") else 0)
        h = 58 + heading + sum(max(1, _lines(r.get("text", ""), w - 138, 60)) * 75 for r in rows if isinstance(r, dict))
    elif kind == "doc":
        w = 520
        h = (150 + _lines(card.get("k", ""), 440, 30) * 34
             + max(1, _lines(card.get("text", ""), 440, 104, narrow=True)) * 107
             + _lines(card.get("sub", ""), 440, 60) * 68)
    elif kind == "plaque":
        w = 640
        h = (110 + max(1, _lines(card.get("text", ""), 532, 69, narrow=True)) * 80
             + _lines(card.get("sub", ""), 532, 66) * 65)
    else:
        font, pad, height = {
            "sticker": (size, size * .52, size * 1.24),
            "pill": (39, 68, 74), "tag": (32, 40, 62 if not card.get("sub") else 88),
            "sign": (64, 82, 112 if not card.get("sub") else 154), "stamp": (66, 60, 104),
        }.get(kind, (36, 0, 0))
        w, h = max(1, length) * font * (NARROW_EM if kind in ("sticker", "sign", "stamp") else CHAR_EM) + pad, height
        if kind in ("tag", "sign") and card.get("sub"):
            sub_size, tracking = (22, 0) if kind == "tag" else (28, 28 * .14)
            w = max(w, len(str(card["sub"])) * (sub_size * CHAR_EM + tracking) + pad)
    angle = math.radians(abs(_number(card, "rot", 0)) + .45)
    rw = abs(math.cos(angle)) * w + abs(math.sin(angle)) * h
    rh = abs(math.sin(angle)) * w + abs(math.cos(angle)) * h
    x, y = _number(card, "x", 0), _number(card, "y", 0)
    if resting:
        return x, y, rw, rh
    # Card.fit anchors the rotated box at the authored top-left and scales to
    # the frame. Reserve the full height here so check errs toward clearance.
    overshoot = 2.6 if card.get("anim") == "stamp" else 1.15
    extra = (overshoot - 1) * rh / 2 + 12
    top = y - extra - (520 if card.get("anim") == "drop" else 0)
    if card.get("anim") == "stamp":
        # Stamp grows about the box's center on both axes. A resting card
        # beside a face can still cover it during the first two page ticks.
        horizontal = (overshoot - 1) * rw / 2
        x, rw = x - horizontal, rw + 2 * horizontal
    elif card.get("anim") == "slide":
        distance = card.get("from", -600)
        distance = float(distance) if finite(distance) and -2160 <= distance <= 2160 else -600
        # backOut travels a little past the destination before settling.
        low, high = min(0, distance, -.15 * distance), max(0, distance, -.15 * distance)
        x, rw = x + low, rw + high - low
    return x, top, rw, y + rh + extra - top


def card_overlaps_captions(card: dict) -> bool:
    if not isinstance(card, dict) or not finite(card.get("y")):
        return False
    _, top, _, height = card_box(card)
    return top < CAPTION_BAND["y"] + CAPTION_BAND["height"] and top + height > CAPTION_BAND["y"]


def head_overlaps_captions(actor: dict) -> bool:
    if not isinstance(actor, dict):
        return False
    _, top, _, height = head_box(actor)
    return top < CAPTION_BAND["y"] + CAPTION_BAND["height"] and top + height > CAPTION_BAND["y"]


def _face(head):
    """The middle of a head box: the part a card must never hide."""
    x, y, w, h = head
    return x + FACE_INSET * w, y + FACE_INSET * h, (1 - 2 * FACE_INSET) * w, (1 - 2 * FACE_INSET) * h


def boxes_overlap(first, second) -> float:
    """Return the shared area of two (x, y, width, height) boxes."""
    x, y, w, h = first
    a, b, c, d = second
    return max(0, min(x + w, a + c) - max(x, a)) * max(0, min(y + h, b + d) - max(y, b))


def _bounce(value: float) -> float:
    value = max(0, min(1, value))
    n, d = 7.5625, 2.75
    if value < 1 / d:
        return n * value * value
    if value < 2 / d:
        return n * (value - 1.5 / d) ** 2 + .75
    if value < 2.5 / d:
        return n * (value - 2.25 / d) ** 2 + .9375
    return n * (value - 2.625 / d) ** 2 + .984375


def _changes(actor, key, timings):
    return sorted(({**item, "t": cue_time(item["at"], timings)}
                   for item in actor.get(key, [])), key=lambda item: item["t"])


def _head_points(actor, photo, aspect):
    geometry = HEAD_GEOMETRY
    if photo:
        # Without a prepared PNG reserve the full frame. The page caps only
        # unusually tall cuts; normal head images keep their existing width.
        width = geometry["width"]
        if aspect is None:
            height = geometry["max_height"]
        else:
            width = min(width, geometry["max_height"] / aspect)
            height = width * aspect
        left, top = -width / 2, geometry["pivot_y"] - height + geometry["width"] * geometry["photo_bottom"]
    else:
        left, top, width, height = geometry["blank_bounds"]
    scale, pivot = _number(actor, "head_scale", 1), geometry["pivot_y"]
    return [(px * scale, pivot + (py - pivot) * scale)
            for px in (left, left + width) for py in (top, top + height)]


def _transformed_head(actor, points, x, y, body, tilt):
    body, tilt = math.radians(body), math.radians(tilt)
    cb, sb, ct, st = math.cos(body), math.sin(body), math.cos(tilt), math.sin(tilt)
    scale, flip, pivot = _number(actor, "scale", 1), -1 if actor.get("flip") else 1, HEAD_GEOMETRY["pivot_y"]
    transformed = []
    for px, py in points:
        hx, hy = px * ct - (py - pivot) * st, px * st + (py - pivot) * ct + pivot
        transformed.append((x + flip * scale * (hx * cb - hy * sb), y + scale * (hx * sb + hy * cb)))
    return transformed


def _bounds(points, margin=HEAD_MARGIN):
    left, top = min(p[0] for p in points) - margin, min(p[1] for p in points) - margin
    return left, top, max(p[0] for p in points) + margin - left, max(p[1] for p in points) + margin - top


def head_box(actor: dict, t: float | None = None, *, timings: dict | None = None,
             panel_start: float = 0, head_aspect: float | list | None = None,
             photo: bool = True) -> tuple[float, float, float, float] | None:
    """Head bounds in panel pixels, using the page's geometry and 12 fps clock.

    ``head_aspect`` is height / width of a prepared PNG, or one value per
    photo variant. Without it the complete permitted photo frame is reserved.
    A missing time returns the standing/pose envelope at the authored x/y.
    A table pose changes the arms; seated height comes from the actor's y.
    """
    geometry = HEAD_GEOMETRY
    x, y = _number(actor, "x", 0), _number(actor, "y", geometry["default_y"])
    if t is None:
        aspects = (head_aspect or [None]) if isinstance(head_aspect, list) else [head_aspect]
        points = [p for aspect in aspects for p in _head_points(actor, photo, aspect)]
        name = actor.get("pose", "idle")
        offset = geometry["head_think"] if name == "think" else geometry["head_shrug"] if name == "shrug" else 0
        result = []
        for body_step in range(-4, 5):
            for tilt_step in range(-16, 17):
                result.extend(_transformed_head(actor, points, x, y, body_step * geometry["body_sway"] / 4,
                                                offset + tilt_step * geometry["head_sway"] / 16))
        left, top, width, height = _bounds(result)
        return left, top - geometry["idle_bob"], width, height + 2 * geometry["idle_bob"]
    times = timings or {"beats": [], "outro_start": panel_start}
    tq = math.floor(t * geometry["fps"] + 1e-6) / geometry["fps"]
    enter = actor.get("enter")
    enter_time = cue_time(enter, times) if enter is not None and enter != "walk" else None
    if enter_time is not None and tq < enter_time:
        return None
    name = actor.get("pose", "idle")
    for pose in _changes(actor, "poses", times):
        if tq >= pose["t"]:
            name = pose["pose"]
    moves = _changes(actor, "moves", times)
    if enter == "walk":
        moves = sorted([{"t": panel_start - .45, "dur": .95, "from": x - 430, "to": x}, *moves],
                       key=lambda item: item["t"])
    walking = False
    for index, move in enumerate(moves):
        if tq >= move["t"]:
            progress = max(0, min(1, (tq - move["t"]) / move["dur"]))
            x = move["from"] + (move["to"] - move["from"]) * progress
            walking = progress < 1
        elif index == 0:
            x = move["from"]
    step = math.sin(tq * 13) if walking else 0
    body = math.sin(tq * 1.9 + actor["x"]) * geometry["body_sway"] + (geometry["body_walk"] if walking else 0)
    bob = -abs(step) * geometry["walk_bob"] if walking else math.sin(tq * 2.6 + actor["x"]) * geometry["idle_bob"]
    hop = (1 - _bounce((tq - enter_time) / geometry["enter_duration"])) * -geometry["enter_hop"] if enter_time is not None else 0
    tilt = (math.sin(tq * 2.3 + actor["x"] * .01) * geometry["head_sway"]
            + (geometry["head_think"] if name == "think" else geometry["head_shrug"] if name == "shrug" else 0)
            + (step * geometry["head_walk"] if walking else 0))
    aspect = head_aspect
    if isinstance(aspect, list):
        index = actor.get("head", 0)
        for change in _changes(actor, "head_at", times):
            if tq >= change["t"]:
                index = change["head"]
        aspect = aspect[index % len(aspect)] if aspect else None
    points = _head_points(actor, photo, aspect)
    return _bounds(_transformed_head(actor, points, x, y + bob + hop, body, tilt))


def actor_head_boxes(actor: dict, start: float, end: float, timings: dict, *, panel_start: float = 0,
                     head_aspect=None, photo=True) -> list[tuple[float, float, float, float]]:
    """All visible, on-screen head boxes during the half-open time window."""
    fps = HEAD_GEOMETRY["fps"]
    first, last = math.floor(start * fps + 1e-6), math.ceil(end * fps - 1e-6)
    # At most one hour of frames is useful for a short story. Rejecting an
    # absurd timing range avoids letting a malformed timing file hang check.
    if last - first > fps * 3600:
        raise StoryError("layout timing range exceeds one hour; run zing story voice again")
    result = []
    for frame in range(first, last):
        box = head_box(actor, frame / fps, timings=timings, panel_start=panel_start,
                       head_aspect=head_aspect, photo=photo)
        if box and boxes_overlap(box, (0, 0, 1080, 1920)):
            result.append(box)
    return result


def _aspects(member, ident, directory):
    if not directory:
        return None
    result = []
    for index, _ in enumerate(member.get("photos", [])):
        try:
            # Prepared heads are PNGs. Reading their header keeps check free of
            # image-library imports and does not decode the source photograph.
            with (Path(directory) / "heads" / f"{ident}-{index}.png").open("rb") as stream:
                header = stream.read(24)
            width, height = struct.unpack(">II", header[16:24])
            aspect = height / width if header[:8] == b"\x89PNG\r\n\x1a\n" and width and height else None
        except (OSError, ValueError, struct.error):
            aspect = None
        result.append(aspect)
    return result or None


def panel_overlaps(panel: dict, timings: dict, *, end: float | None = None,
                   cast: dict | None = None, directory: Path | None = None) -> list[str]:
    """Report timed card/head and card/card collisions in one panel.

    Messages start at cards[j], so callers can prefix the authored panel path.
    Generated outro cards use this same check when choosing their placement.
    """
    start = cue_time(panel["from"], timings)
    stop = end if end is not None else timings["duration"]
    cards, problems = panel.get("cards", []), []
    fps = HEAD_GEOMETRY["fps"]
    visible_at = lambda cue: math.ceil(cue_time(cue, timings) * fps - 1e-6) / fps
    windows = [(max(start, visible_at(card["at"])),
                min(stop, visible_at(card["until"]) if "until" in card else stop)) for card in cards]
    for index, (card, (a, b)) in enumerate(zip(cards, windows)):
        if b <= a:
            continue
        # A card that brushes a face on its way in is fine. What matters is
        # where it settles and how much of the face it then hides.
        box = card_box(card, resting=True)
        if card.get("over_head") is not True:
            for actor in panel.get("actors", []):
                member = cast.get(actor["who"], {}) if cast is not None else None
                photo = bool(member.get("photos") or member.get("heads")) if member is not None else True
                candidates = actor_head_boxes(actor, a, b, timings, panel_start=start,
                                              head_aspect=_aspects(member or {}, actor["who"], directory), photo=photo)
                hits = [head for head in candidates if boxes_overlap(box, _face(head))]
                if hits:
                    left = math.floor(min(h[0] for h in hits))
                    right = math.ceil(max(h[0] + h[2] for h in hits))
                    top = math.floor(min(h[1] for h in hits))
                    bottom = math.ceil(max(h[1] + h[3] for h in hits))
                    # Give an authored y, not merely the head's top. It leaves
                    # ten pixels between the card's full box and every head.
                    clear_y = math.floor(min(h[1] for h in candidates) - (box[1] + box[3] - card["y"]) - 10)
                    advice = f"move the card above y={clear_y} or to the side" if clear_y >= 0 else "move the card to the side"
                    problems.append(f"cards[{index}]: covers {actor['who']}'s head (about y={top}..{bottom} at x={left}..{right}); {advice}")
        for other in range(index):
            oa, ob = windows[other]
            if min(b, ob) <= max(a, oa):
                continue
            other_box = card_box(cards[other], resting=True)
            area = boxes_overlap(box, other_box)
            if area > .6 * other_box[2] * other_box[3]:
                problems.append(f"cards[{index}]: covers more than 60 percent of cards[{other}] while both are showing; move or retime one card")
            elif area > .6 * box[2] * box[3]:
                problems.append(f"cards[{index}]: more than 60 percent is covered by cards[{other}] while both are showing; move or retime one card")
    return problems
