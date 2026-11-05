"""Deterministic title heuristics; these labels are not language understanding."""
from __future__ import annotations

import re

WORDS = {
    "past_tense": ("was", "were", "had", "got", "said", "told", "banned", "forced", "traded", "almost",
                   "never", "nearly", "used to", "went", "became", "left", "lost", "won", "took", "made",
                   "saw", "broke", "thought", "bought", "caught", "built", "quit", "knew", "gave", "felt"),
    "ed_stoplist": ("red", "bed", "need", "speed", "seed", "feed", "weed", "greed", "bleed", "indeed",
                    "hundred", "naked", "wicked"),
    "present_news": ("is", "are", "stepping up", "now", "today", "just", "breaking"),
    "superlative": ("worst", "best", "biggest", "greatest", "most", "first", "last", "only"),
    "taboo_or_conflict": ("banned", "fired", "drug", "hungover", "fight", "beef", "rivalry", "cheated",
                          "broke", "lawsuit", "arrested", "refused", "fed up", "hated"),
    "how_or_why": ("how", "why", "what", "when"),
    "first_person_quote": ("i", "i'm", "i’m", "my"),
    "known_names": (),
}
LABELS = {
    "starts_lowercase": "starting with a lowercase letter",
    "ends_with_emoji": "ending with an emoji",
    "has_number": "with a number",
    "has_question": "with a question mark",
    "has_quote": "with a quote mark",
    "has_name": "with a name",
    "past_tense": "with a past-tense story verb",
    "present_news": "with a phrase about current news",
    "superlative": "with a superlative",
    "taboo_or_conflict": "with a conflict word",
    "how_or_why": "starting with how, why, what or when",
    "first_person_quote": "with I, I'm or my",
}
_emoji_base = r"[\u2600-\u27bf\u2300-\u23ff\u2b00-\u2bff\U0001f300-\U0001f3fa\U0001f400-\U0001faff]"
_emoji_part = _emoji_base + r"[\ufe0e\ufe0f]?[\U0001f3fb-\U0001f3ff]?"
EMOJI = re.compile(r"[0-9#*]\ufe0f?\u20e3|[\U0001f1e6-\U0001f1ff]{2}|" + _emoji_part + r"(?:\u200d" + _emoji_part + r")*")


def _contains(title, words):
    return any(re.search(r"\b" + re.escape(word).replace(r"\ ", r"\s+") + r"\b", title, re.I) for word in words)


def features(title: str, known_names=()) -> dict:
    words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", title)
    emojis = list(EMOJI.finditer(title))
    return {"words": len(words), "chars": len(title),
            "starts_lowercase": bool(title.lstrip() and title.lstrip()[0].islower()),
            "ends_with_emoji": bool(emojis and emojis[-1].end() == len(title.rstrip())),
            "emoji_count": len(emojis), "has_number": bool(re.search(r"\d", title)),
            "has_question": "?" in title,
            "has_quote": bool(re.search(r'''["“”‘]|(?<!\w)['’]|['’](?!\w)''', title)),
            "has_name": bool(re.search(r"\b[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?\s+[A-Z][a-z]+\b", title)
                             or _contains(title, (*WORDS["known_names"], *known_names))),
            "past_tense": _contains(title, WORDS["past_tense"]) or any(
                word.lower().endswith("ed") and word.lower() not in WORDS["ed_stoplist"] for word in words),
            **{name: _contains(title, WORDS[name]) for name in
               ("present_news", "superlative", "taboo_or_conflict", "first_person_quote")},
            "how_or_why": bool(words and words[0].lower() in WORDS["how_or_why"])}
