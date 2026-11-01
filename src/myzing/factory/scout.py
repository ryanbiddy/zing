"""Scout: pick the strongest self-contained moments from an episode transcript, then snap them to sentences."""
from __future__ import annotations

import re

from .tools import data_path

FILLER = {"and", "so", "yeah", "well", "um", "uh", "like", "okay", "ok"}


def prompt(segments: list[dict], n: int) -> str:
    lines = "\n".join(f"[{s['s']:.1f}-{s['e']:.1f}] {s['text']}" for s in segments)
    return (data_path("prompts", "scout.md").read_text(encoding="utf-8")
            .replace("{N}", str(n)).replace("{TRANSCRIPT}", lines))


def check(answer: dict, duration: float | None = None) -> list[dict]:
    moments = answer.get("moments")
    if not isinstance(moments, list) or not moments:
        raise ValueError("scout answer needs a non-empty 'moments' list")
    out = []
    for m in moments:
        start, end = float(m["start"]), float(m["end"])
        if not 0 <= start < end or (duration and start >= duration):
            raise ValueError(f"moment {start}-{end} is outside the episode")
        out.append({"start": start, "end": end, "hook": str(m["hook"]), "why": str(m.get("why", "")),
                    "topic": str(m.get("topic", "")), "score": m.get("score", "")})
    return out


def snap(moment: dict, words: list[dict]) -> dict:
    """End on a sentence end and start after a leading filler word (And/So/Yeah/Well/Um)."""
    ws = [w for w in words if moment["start"] - 0.05 <= w["s"] <= moment["end"] + 6.5]
    if not ws:
        return moment
    k = 0
    while k < len(ws) - 1 and re.sub(r"[^a-z]", "", ws[k]["w"].lower()) in FILLER:
        k += 1
    start = ws[k]["s"] - 0.05
    inside = [w for w in ws if w["e"] <= moment["end"] + 0.05] or ws[:1]
    end_word = inside[-1]
    if not re.search(r"[.?!]$", end_word["w"]):
        after = [w for w in ws if w["s"] > end_word["s"] and re.search(r"[.?!]$", w["w"])]
        before = [w for w in inside if re.search(r"[.?!]$", w["w"]) and w["e"] > start + 20]
        end_word = after[0] if after else (before[-1] if before else end_word)
    return {**moment, "scout_start": moment["start"], "scout_end": moment["end"],
            "start": round(start, 2), "end": round(end_word["e"] + 0.05, 2)}
