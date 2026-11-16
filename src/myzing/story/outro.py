"""Generate credit copy from the actual voice provider and declared sources."""
from __future__ import annotations

from copy import deepcopy
from textwrap import wrap

from . import StoryError


# Characters that fit the 900 px credits card at its 27 px type.
CREDIT_WRAP = 58


def credit_lines(story: dict, timings: dict, *, width: int = CREDIT_WRAP) -> list[str]:
    provider = timings.get("provider")
    if provider not in ("kokoro", "elevenlabs", "lines"):
        raise StoryError("Unknown narration provider; run zing story voice before rendering credits.")
    # Supplied recordings can be synthetic too; only a declared human read drops the line.
    lines = ["narration is an AI voice"] if provider != "lines" or timings.get("synthetic") is True else []
    # One wrapped line for all sources keeps a long source list off the puppets.
    titles = [source["title"] for source in story["sources"]]
    lines.append(("sources: " if len(titles) > 1 else "source: ") + " · ".join(titles))
    if story.get("music"):
        music = story["music"]
        lines.append(f"music: {music['credit']} · {music['license']}")
    seen = set()
    for member in story.get("cast", {}).values():
        for photo in member.get("photos", []):
            key = (photo["credit"], photo["license"])
            if key not in seen:
                seen.add(key)
                lines.append(f"photo: {photo['credit']} · {photo['license']}")
    for picture in story.get("images", {}).values():
        key = (picture["credit"], picture["license"])
        if key not in seen:
            seen.add(key)
            lines.append(f"image: {picture['credit']} · {picture['license']}")
    return [part for line in lines for part in wrap(line, width=width, break_on_hyphens=False)]


# Average glyph width of the credits face (IBM Plex Sans) as a share of its size.
CREDIT_EM = .52


def _credits_card(story: dict, timings: dict, panel: dict) -> dict:
    """Fit all credits in the frame without covering an authored or waving head."""
    from .layout import card_box, panel_overlaps

    # Some callers only need credit copy and have not generated voice timings yet.
    layout_times = {"beats": [], "outro_start": 0, "duration": story.get("outro", 3.2), **timings}
    preferred_y = 500
    # With someone on stage, the credits take the side they are not standing
    # on, so the text never lies across a body. An empty stage gets the full width.
    actors = [actor.get("x", 540) for actor in panel.get("actors", []) if isinstance(actor.get("x", 540), (int, float))]
    if actors:
        card_w = 560
        card_x = 70 if sum(actors) / len(actors) > 540 else 1080 - 70 - card_w
    else:
        card_w, card_x = 900, 90
    for size in (34, 27, 26, 24, 22, 20, 18, 16):
        width = int((card_w - 24) / (size * CREDIT_EM))
        lines = credit_lines(story, timings, width=width)
        if size == 34 and len(lines) > 5:
            continue
        card = {"kind": "credits", "w": card_w, "x": card_x, "y": preferred_y,
                "size": size, "z": 11, "at": "outro+0.3", "lines": lines}
        # Try the usual location first, then the available space from top to bottom.
        for y in dict.fromkeys([preferred_y, 1180, *range(170, 1841, 20)]):
            card["y"] = y
            x, top, w, h = card_box(card)
            if top < 150 or top + h > 1860:
                continue
            candidate = {**panel, "cards": [card]}
            if panel_overlaps(candidate, layout_times, end=layout_times["duration"], cast=story.get("cast", {}),
                              look=story.get("look", "cutout")):
                continue
            occupied = [card_box(other) for other in panel.get("cards", [])]
            if any(x < ox + ow and x + w > ox and top < oy + oh and top + h > oy
                   for ox, oy, ow, oh in occupied):
                continue
            return card
    raise StoryError("The outro has no clear space for its credits. Move its heads or cards, "
                     "or shorten source titles and credits without removing attribution.")


def prepare(story: dict, timings: dict) -> dict:
    """Make renderer-only fields without changing the user's authored JSON."""
    result = deepcopy(story)
    result.setdefault("look", "cutout")
    result.setdefault("handle", "")
    result.setdefault("cast", {})
    from .images import prepared_path
    for ident, picture in result.get("images", {}).items():
        picture["prepared"] = prepared_path(ident, picture)
    for ident, member in result["cast"].items():
        member["heads"] = [f"{ident}-{i}.png" for i, _ in enumerate(member.get("photos", []))]
        member["portraits"] = [f"{ident}-{i}-portrait.jpg" for i, _ in enumerate(member.get("photos", []))]
        for key, value in {"jacket": "#1F8A8A", "shirt": "#FBF4E4", "legs": "#17161C"}.items():
            member.setdefault(key, value)
    if result["look"] == "headline":
        result["panels"] = []
        result["headline_outro_cast"] = next((ident for ident, member in result["cast"].items()
                                               if member.get("photos")), None)
        # Keep the full-width card above the fixed badge position.
        max_height = 620 if result["headline_outro_cast"] is not None else 1100
        for size in (34, 27, 26, 24, 22, 20, 18, 16):
            lines = credit_lines(story, timings, width=int(876 / (size * CREDIT_EM)))
            if (size != 34 or len(lines) <= 5) and len(lines) * size * 1.35 + 48 <= max_height:
                result["headline_credits"] = lines
                result["headline_credit_size"] = size
                return result
        raise StoryError("The headline credits do not fit. Shorten source titles and credits without removing attribution.")
    for panel in result["panels"]:
        panel.setdefault("set", {})
    outro = next((panel for panel in result["panels"] if panel["from"] == "outro"), None)
    if outro is None:
        outro = {"from": "outro", "set": {"wall": "#17161C", "floor": "#2B50D8", "floor_pattern": "planks"},
                 "props": [{"prop": "star", "x": 940, "y": 270, "scale": 1.2}],
                 "cards": [{"kind": "sticker", "text": "that's the story", "size": 110,
                            "x": 70, "y": 190, "rot": -3, "at": "outro+0.15"},
                           {"kind": "sticker", "text": "made with zing", "size": 64,
                            "bg": "#E8452C", "color": "#FBF4E4", "x": 560, "y": 1660,
                            "rot": 3, "at": "outro+0.4"}]}
        result["panels"].append(outro)
        waving = next((ident for ident, member in result["cast"].items() if member.get("photos")), None)
        if waving is not None:
            # Stand to the right so the credits have the left side to themselves.
            outro["actors"] = [{"who": waving, "x": 810, "pose": "wave"}]
            outro["cards"][1].update(x=70, rot=-3)
    # User-authored outro art cannot disable the generated attribution layer.
    outro.setdefault("cards", []).append(_credits_card(story, timings, outro))
    return result
