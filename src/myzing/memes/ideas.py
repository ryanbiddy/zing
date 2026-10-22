"""Seeded, offline starting points ported from MemeForge's eight formulas.

These are formula substitutions. The user's AI supplies editorial judgment.
Template grammar expands beyond MemeForge's two-field fallback where needed.
"""

from __future__ import annotations

import hashlib
import re

from . import MemeError
from .score import idea_score
from .templates import get_template
from .validate import check_texts


def _short(value: str, limit: int = 30) -> str:
    text = " ".join(value.split()).rstrip(".!?")
    text = re.sub(r"^(trying to|when you|the moment)\s+", "", text, flags=re.I)
    if len(text) <= limit:
        return text
    clipped = text[:limit - 1].rsplit(" ", 1)[0] if " " in text[:limit - 1] else text[:limit - 1]
    return clipped + "…"


def _template_texts(key: str, count: int, topic: str, index: int, pair: list[str]) -> list[str]:
    if key == "drake":
        options = [
            [f"a 47-slide plan for {topic}", "one meme"],
            [f"doing {topic}", "building a system first"],
            ["a sensible bedtime", f"{topic} at 2am"],
            ["reading the instructions", "trusting the vibes"],
            ["one quick fix", "a complete rewrite"],
            ["finishing the task", "renaming the project"],
            ["asking for help", "opening another tab"],
            ["the working version", "one tiny improvement"],
        ]
        return options[index]
    if key in ("db", "dg"):
        return [[topic, "me", "my actual priorities"], ["one more tab", "me", topic],
                ["a new system", "me", topic], [topic, "my brain", "sleep"],
                ["a side quest", "me", topic], [topic, "me at 2am", "tomorrow"],
                ["a rewrite", "me", topic], [topic, "the team", "the deadline"]][index]
    if key == "ds":
        return [["do the sensible thing", f"{topic} at 2am", "me"],
                [f"finish {topic}", "start over", "me"],
                ["ask for help", "open another tab", topic],
                ["ship it", "one more tweak", topic],
                ["read the docs", "guess again", topic],
                ["go to bed", "fix one thing", topic],
                ["use the old version", "rewrite everything", topic],
                ["do the work", "make a spreadsheet", topic]][index]
    if key == "gb":
        return [topic, ["planning", "researching", "scheduling", "optimizing"][index % 4],
                ["building a system", "making a dashboard"][index // 4], "calling the chaos iterative"]
    if key == "astronaut":
        # The upstream catalog has four regions; leave scene labels empty.
        return ["", "", f"wait, it's all {topic}?", "always has been"]
    if count == 1:
        return [pair[0]]
    if count == 2:
        return pair
    # Generic multi-panel progression: complete slots, never pretend a two-line
    # idea is a three-label or six-panel composition.
    middle = ["the plan", "the first attempt", "one small fix", "the rewrite"][:count - 2]
    return [topic, *middle, pair[1]]


def generate_ideas(topic: str, template: str = "", n: int = 6,
                   tone: str = "dry", audience: str = "", *, seed: str = "") -> list[dict]:
    if not isinstance(topic, str) or not topic.strip():
        raise MemeError("topic must be a non-empty string")
    if type(n) is not int or not 1 <= n <= 8:
        raise MemeError("n must be an integer from 1 to 8")
    if not isinstance(tone, str) or not isinstance(audience, str):
        raise MemeError("tone and audience must be strings")
    if not isinstance(seed, str):
        raise MemeError("seed must be a string")
    selected = get_template(template) if template else None
    short = _short(topic) or "trying to look productive"
    crowd = _short(audience, 18) or "people who get it"
    formulas = [
        ([f"day 1 of {short}", "day 47"], "time_jump", "The number jump supplies the reversal."),
        ([f"me: quick {short}", "six hours later"], "underestimate", "A short time jump exposes the mistake."),
        (["the plan", short], "expectation", "The image supplies the gap between plan and reality."),
        ([f"pov: {short} finally works", "nobody move"], "understatement", "A cautious payoff adds tension."),
        ([f'"{short} can\'t hurt you"', f"{short.title()}:"], "personification", "The image delivers the unfinished threat."),
        ([f'"just do {short}"', "me, building a system first"], "self_own", "Overengineering gets in the way of doing it."),
        ([f"{crowd}: how's {short} going", '"define going"'], "evasion", "A tiny evasive answer carries the payoff."),
        ([f"{short} works on the first try", "we are so back"], "celebration", "An unexpectedly easy win earns a reaction."),
    ]
    # A fixed hash avoids Python's per-process hash salt and RNG-version drift.
    seed_text = f"{topic.strip()}\0{tone}\0{audience}\0{selected['id'] if selected else ''}"
    if seed:
        seed_text += f"\0{seed}"
    seed = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    offset = int(seed[:8], 16) % len(formulas)
    ideas = []
    for index in range(n):
        pair, formula, why = formulas[(offset + index) % len(formulas)]
        texts = _template_texts(selected["id"], selected["box_count"], short, index, pair) if selected else pair
        validation = check_texts(texts, box_count=selected["box_count"] if selected else None)
        ideas.append({
            "id": f"offline-{seed[:12]}-{index}",
            "title": ["Best fit", "Sharper", "Self-own", "Understated", "Wildcard", "Minimal", "Variation", "Last try"][index],
            "texts": texts, "template": selected["id"] if selected else None,
            "formula": f"{selected['id']}:{formula}" if selected else formula,
            "why": why if not selected else f"Starting point for {selected['name']}; review the image and label order.",
            "score": idea_score(texts, tone), "score_kind": "compression_heuristic",
            "validation": validation, "provider": "offline_formulas",
        })
    return ideas
