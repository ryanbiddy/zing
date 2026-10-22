"""Seeded, offline starting points ported from MemeForge's eight formulas.

These are formula substitutions. The user's AI supplies editorial judgment.
Template grammar expands beyond MemeForge's two-field fallback where needed.
Topics are read as a thing ("release day", "deploying on a friday") or as a
situation ("when the build finally passes"); each shape gets formulas whose
grammar works for it, and a long topic is cut at a word, never mid-phrase
with an ellipsis.
"""

from __future__ import annotations

import hashlib
import re

from . import MemeError
from .score import idea_score
from .templates import get_template
from .validate import check_texts


TOPIC_LIMIT = 40  # the longest formula adds 30 characters: 40 + 30 = the 70 cap
SITUATION = re.compile(r"^(?:me\s+when|that\s+feeling\s+when|the\s+moment\s+when|when\s+you|when|"
                       r"pov\s*:|pov|the\s+moment)\s+", re.I)
TRYING = re.compile(r"^(?:trying\s+to|time\s+to|how\s+to)\s+", re.I)
# Words that make a topic a situation (a clause), not a thing.
FINITE = {"is", "are", "was", "were", "am", "has", "have", "had", "does", "did", "won't", "can't",
          "doesn't", "don't", "isn't", "aren't", "didn't", "wasn't", "finally", "passes", "works",
          "breaks", "fails", "crashes", "goes", "gets", "compiles", "ships", "lands", "dies",
          "starts", "stops", "says", "asks", "tries", "wants", "needs", "thinks", "knows", "hits",
          "merges", "deploys", "loads", "runs", "returns", "happens", "comes", "leaves", "replies"}
PRONOUNS = {"i", "you", "we", "they", "he", "she", "it", "someone", "everyone", "nobody", "somebody"}
VERBS = {"fix", "ship", "deploy", "write", "debug", "merge", "review", "finish", "start", "make", "run",
         "test", "push", "update", "refactor", "rewrite", "migrate", "clean", "plan", "launch", "learn",
         "read", "try", "explain", "find", "delete", "install", "upgrade", "answer", "organize", "cancel",
         "book", "pay", "file", "move", "sort", "cook", "do", "get", "go", "touch", "train", "name"}
DANGLING_END = {"a", "an", "the", "of", "to", "for", "in", "on", "at", "and", "or", "with", "my", "your", "after"}


def _gerund(verb: str) -> str:
    if verb.endswith("ie"):
        return verb[:-2] + "ying"
    if verb.endswith("e") and not verb.endswith(("ee", "ye", "oe")):
        return verb[:-1] + "ing"
    if (len(verb) >= 3 and verb[-1] not in "aeiouwxy" and verb[-2] in "aeiou"
            and verb[-3] not in "aeiou" and (len(verb) <= 4 or verb in ("debug", "refer"))):
        return verb + verb[-1] + "ing"
    return verb + "ing"


BREAKS = {"and", "but", "while", "because", "so", "until", "after", "before", "then", "or",
          "which", "who", "when"}


def _clip(text: str, limit: int) -> str:
    """Shorten at a clause break ("the meeting runs long | and everyone..."),
    else at a word; never mid-word and never with an ellipsis."""
    if len(text) <= limit:
        return text
    words = text.split(" ")
    clause = None
    for i in range(1, len(words)):
        prefix = " ".join(words[:i]).rstrip(",;:")
        if len(prefix) > limit:
            break
        if len(prefix) >= 12 and (words[i].casefold() in BREAKS or words[i - 1].endswith((",", ";", ":"))):
            clause = prefix
    if clause:
        return clause
    words = text[:limit + 1].split(" ")[:-1] or [text[:limit]]
    while len(words) > 1 and words[-1].casefold() in DANGLING_END:
        words.pop()
    return " ".join(words)


def _topic(value: str) -> tuple[str, str]:
    """(shape, text): shape is ``thing`` or ``situation``."""
    text = " ".join(value.split()).rstrip(".!?")
    situation = bool(SITUATION.match(text))
    text = SITUATION.sub("", text)
    trying = bool(TRYING.match(text))
    text = TRYING.sub("", text)
    words = text.split()
    if words and (trying or words[0].casefold() in VERBS) and words[0].isalpha():
        words[0] = _gerund(words[0].casefold())  # "fix a bug" -> "fixing a bug"
        text = " ".join(words)
    lowered = {w.casefold().strip(",.!?") for w in words}
    if not situation and words and not trying and (
            lowered & FINITE or words[0].casefold() in PRONOUNS):
        situation = True
    return ("situation" if situation else "thing"), _clip(text, TOPIC_LIMIT)


def _short(value: str, limit: int = TOPIC_LIMIT) -> str:
    return _clip(_topic(value)[1], limit)


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
    shape, short = _topic(topic)
    # Multi-panel templates share the 110-character budget across up to six boxes.
    short = (_clip(short, 30) if selected else short) or "looking productive"
    crowd = _clip(" ".join(audience.split()), 18)
    asked = f"{crowd}: how's {short} going" if crowd else f"how's {short} going"
    if len(asked) > 70:
        asked = f"how's {short} going"
    if shape == "situation" and not selected:
        # The photo is the reaction; the situation is the setup.
        # Varied setups, so six concepts are not one setup with six payoffs.
        formulas = [
            ([f"when {short}"], "reaction", "One line; the photo is the reaction."),
            ([f"pov: {short}", "nobody move"], "understatement", "A frozen beat adds tension."),
            ([short, "and nobody knows why"], "mystery", "Shared confusion is the joke."),
            ([f"me explaining why {short}", "(i changed nothing)"], "confession",
             "The aside undercuts the explanation."),
            ([short, "me, acting like i planned this"], "self_own", "Taking credit for luck."),
            ([f"me acting surprised that {short}"], "deadpan", "One line of feigned surprise."),
            ([f"the whole team when {short}"], "group_reaction", "The photo stands in for everyone."),
            ([short, "we are so back"], "celebration", "An outsized reaction to a small win."),
        ]
    else:
        formulas = [
            ([f"day 1 of {short}", "day 47"], "time_jump", "The number jump supplies the reversal."),
            ([f"{short}: should take five minutes", "six hours later"], "underestimate",
             "A short time jump exposes the mistake."),
            (["the plan", short], "expectation", "The image supplies the gap between plan and reality."),
            ([f"pov: {short}, so far so good", "nobody move"], "understatement", "A cautious payoff adds tension."),
            ([f'"{short} can\'t hurt you"', f"{short}:"], "personification", "The image delivers the unfinished threat."),
            ([f'"how hard can {short} be"', "me, building a system first"], "self_own",
             "Overengineering gets in the way of doing it."),
            ([asked, '"define going"'], "evasion", "A tiny evasive answer carries the payoff."),
            ([f"{short} actually worked", "we are so back"], "celebration", "An unexpectedly easy win earns a reaction."),
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
