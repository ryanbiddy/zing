"""Check a cut and its hook against the surrounding transcript."""
from __future__ import annotations

import json
import re

from .tools import data_path

KINDS = ("reversed", "qualified", "joke", "answer_without_question", "dropped_condition", "hook_claim")


def windows(segments: list[dict], words: dict, spans: list[list[float]]) -> list[dict]:
    ranges = words.get("ranges") or spans

    def episode(t, end=False):
        offset = 0.0
        for a, b in ranges:
            if t < offset + b - a or (end and t <= offset + b - a):
                return round(a + max(0, t - offset), 3)
            offset += b - a
        return ranges[-1][1]

    timed = [{"w": w["w"], "s": episode(w["os"]), "e": episode(w["oe"], True)} for w in words["words"]]
    last = max((s["e"] for s in segments), default=max(b for _, b in spans))
    out = []
    for a, b in spans:
        ws = [w for w in timed if a <= w["s"] < b]
        a, b = (ws[0]["s"], ws[-1]["e"]) if ws else (a, b)
        a, b = max(0, min(a, last)), max(0, min(b, last))
        window = {"before": [max(0, a - 90), a], "after": [b, min(last, b + 90)]}
        text = {k: " ".join(s["text"] for s in segments if lo < hi and s["s"] < hi and s["e"] > lo)
                for k, (lo, hi) in window.items()}
        out.append({"words": " ".join(w["w"] for w in ws), "window": window, "text": text})
    return out


def prompt(hook: str, spans: list[dict]) -> str:
    text = data_path("prompts", "context.md").read_text(encoding="utf-8")
    return text.replace("{INPUT}", json.dumps({"hook": hook, "spans": spans}, ensure_ascii=False, indent=1))


def _norm(text: str) -> str:
    return " " + " ".join(re.sub(r"[\W_]+", " ", re.sub(r"['’]", "", text.casefold())).split()) + " "


def check(answer: dict, hook: str, spans: list[dict]) -> list[dict]:
    if not isinstance(answer, dict) or not isinstance(answer.get("flags"), list):
        raise ValueError("context answer needs a flags list")
    supplied = [_norm(hook)] + [_norm(text) for s in spans for text in (s["words"], *s["text"].values())]
    flags = []
    for f in answer["flags"]:
        if not isinstance(f, dict):
            raise ValueError("context flag must be an object")
        if f.get("kind") not in KINDS or f.get("where") not in ("start", "end", "hook"):
            continue
        if any(not isinstance(f.get(k), str) or not f[k].strip() for k in ("quote", "why")):
            raise ValueError("context flag needs a quote and a reason")
        quote = _norm(f["quote"])
        if not quote.strip() or len(f["quote"].split()) > 30 or not any(quote in text for text in supplied):
            continue
        flags.append({k: f[k].strip() for k in ("kind", "where", "quote", "why")})
    return flags
