"""Generate credit copy from the actual voice provider and declared sources."""
from __future__ import annotations

from copy import deepcopy
from textwrap import wrap

from . import StoryError


# Characters that fit the 900 px credits card at its 27 px type.
CREDIT_WRAP = 58


def credit_lines(story: dict, timings: dict) -> list[str]:
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
    return [part for line in lines for part in wrap(line, width=CREDIT_WRAP, break_on_hyphens=False)]


def prepare(story: dict, timings: dict) -> dict:
    """Make renderer-only fields without changing the user's authored JSON."""
    result = deepcopy(story)
    result.setdefault("handle", "")
    result.setdefault("cast", {})
    for panel in result["panels"]:
        panel.setdefault("set", {})
    for ident, member in result["cast"].items():
        member["heads"] = [f"{ident}-{i}.png" for i, _ in enumerate(member.get("photos", []))]
        for key, value in {"jacket": "#1F8A8A", "shirt": "#FBF4E4", "legs": "#17161C"}.items():
            member.setdefault(key, value)
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
    # User-authored outro art cannot disable the generated attribution layer.
    outro.setdefault("cards", []).append({"kind": "credits", "w": 900, "x": 90, "y": 500,
                                          "z": 11, "at": "outro+0.3", "lines": credit_lines(story, timings)})
    return result
