"""Find dated archive moments and check their fit to a news angle."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date

from myzing.factory.judge import Judge
from myzing.factory.tools import data_path

from .resurface_corpus import folded, names, pattern, plain

STOP = set("a an and are as at be been by for from has have in is it its of on or that the their this to was were will with".split())
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def _terms(headline: str | None, aliases: list[str]) -> list[str]:
    named = {word for alias in aliases for word in re.findall(r"\w+", alias)}
    return sorted(set(re.findall(r"\b[^\W_]{2,}\b", folded(headline or ""))) - STOP - named)


def _windows(cues: list[dict]):
    previous_end = 0.0
    for i, cue in enumerate(cues):
        start, end = cue["s"], cue["e"]
        crossed = start < previous_end
        previous_end = max(previous_end, end)
        if crossed:
            continue
        j = i + 1
        while j < len(cues) and (end - start < 60 or cues[j]["s"] < end):
            stop = max(end, cues[j]["e"])
            if stop - start > 90:
                break
            end, j = stop, j + 1
        if 30 <= end - start <= 90 and (j == len(cues) or cues[j]["s"] >= end):
            yield i, j, end


def _strength(text: str, seconds: float) -> float:
    words = re.findall(r"\w+", folded(text))
    content = set(words) - STOP
    score = min(len(words) / seconds, 3) + min(len(content), 60) / 60
    score += bool(re.search(r"[.!?]$", text)) + bool(re.search(r"\d", text))
    if re.search(r"\b(sponsor|subscribe|welcome back|thanks for watching)\b", folded(text)):
        score -= 2
    return score


def _context(cues: list[dict], start: float, end: float) -> dict:
    nearby = [cue for cue in cues if cue["e"] > start - 90 and cue["s"] < end + 90]
    return {"start": nearby[0]["s"], "end": max(cue["e"] for cue in nearby),
            "text": " ".join(cue["text"] for cue in nearby), "cues": nearby}


def candidates(index, entity: str, aliases=(), headline: str | None = None, limit: int = 40) -> list[dict]:
    if not isinstance(entity, str) or not entity.strip():
        raise ValueError("entity must be non-empty text")
    if not isinstance(aliases, (list, tuple)) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
        raise ValueError("aliases must list non-empty names")
    if headline is not None and not isinstance(headline, str):
        raise ValueError("headline must be text")
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be a nonnegative integer")
    if not limit:
        return []
    aliases = names([entity, *aliases])
    named, terms = pattern(aliases), _terms(headline, aliases)
    angle = [pattern([term]) for term in terms]
    found = []
    for episode in index.episodes():
        appearance = any(named.search(folded(text)) for text in
                         [episode["title"], episode["description"], *episode["guests"]])
        hits = {hit["cue"] for hit in index.search(aliases + terms if appearance else aliases, episode["id"])}
        if not appearance and not hits:
            continue
        cues = index.cues(episode["id"])
        counts = [0]
        for i in range(len(cues)):
            counts.append(counts[-1] + (i in hits))
        spans = []
        for i, j, end in _windows(cues):
            if hits and counts[j] == counts[i]:
                continue
            text = " ".join(cue["text"] for cue in cues[i:j])
            normalized = folded(text)
            if not appearance and not named.search(normalized):
                continue
            score = (4 * appearance + 10 * min(len(named.findall(normalized)), 3)
                     + 3 * sum(bool(term.search(normalized)) for term in angle)
                     + _strength(text, end - cues[i]["s"]))
            spans.append((round(score, 4), i, j, end))
        selected = []
        for score, i, j, end in sorted(spans, key=lambda row: (-row[0], row[1])):
            start = cues[i]["s"]
            if any(start < b and end > a for a, b in selected):
                continue
            quote = " ".join(cue["text"] for cue in cues[i:j])
            key = json.dumps([episode["id"], start, end, quote], ensure_ascii=False)
            found.append({"id": "moment-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20],
                          "episode_id": episode["id"], "title": episode["title"], "date": episode["date"],
                          "show": episode["show"], "guests": episode["guests"], "url": episode["url"],
                          "media": episode["media"], "timing_source": episode["timing_source"],
                          "complete": episode["complete"], "kind": "appearance" if appearance else "mention",
                          "start": start, "end": end, "quote": quote, "cues": cues[i:j],
                          "context": _context(cues, start, end), "score": score})
            selected.append((start, end))
            if len(selected) == limit or not hits:
                break
        found = sorted(found, key=lambda row: (-row["score"], row["episode_id"], row["start"]))[:limit]
    return found


def _labels(candidate: dict, entity: str) -> list[str]:
    day = date.fromisoformat(candidate["date"])
    speakers = list(candidate["guests"])
    for cue in candidate["context"]["cues"]:
        speaker = re.match(r"^([^:\n]{1,80}):\s", cue["text"])
        if speaker and folded(speaker[1]) not in {"host", "guest", "speaker", "narrator", "question", "answer"}:
            speakers.append(speaker[1])
    if candidate["kind"] == "appearance":
        speakers.append(plain(entity))
    return list(dict.fromkeys(f"{name} on {candidate['show']}, {MONTHS[day.month - 1]} {day.year}"
                              for name in speakers))


def prompt(candidates: list[dict], entity: str, headline: str, n: int) -> str:
    text = data_path("prompts", "resurface.md").read_text(encoding="utf-8")
    value = {"entity": entity, "headline": headline, "limit": n,
             "candidates": [{**candidate, "context_labels": _labels(candidate, entity)} for candidate in candidates]}
    return text.replace("{INPUT}", json.dumps(value, ensure_ascii=False, indent=1))


def check(answer: dict, candidates: list[dict], entity: str, n: int) -> list[dict]:
    if not isinstance(answer, dict) or set(answer) != {"picks"} or not isinstance(answer["picks"], list):
        raise ValueError("resurface answer must contain a picks list")
    if len(answer["picks"]) > n:
        raise ValueError("resurface answer has too many picks")
    known = {candidate["id"]: candidate for candidate in candidates}
    seen, out = set(), []
    fields = {"id", "start", "end", "quote", "why", "on_screen_context", "risk_note"}
    for pick in answer["picks"]:
        if not isinstance(pick, dict) or set(pick) != fields:
            raise ValueError("each resurface pick must have the requested fields")
        ident = pick["id"]
        if not isinstance(ident, str) or ident not in known or ident in seen:
            raise ValueError("resurface pick must name a unique candidate id")
        candidate = known[ident]
        if any(type(pick[key]) not in (int, float) or not math.isfinite(pick[key]) for key in ("start", "end")):
            raise ValueError("pick times must be finite numbers")
        start, end = pick["start"], pick["end"]
        if not candidate["start"] <= start < end <= candidate["end"] or not 30 <= end - start <= 90:
            raise ValueError("pick must stay inside its candidate and last 30 to 90 seconds")
        cues = [cue for cue in candidate["cues"] if cue["s"] < end and cue["e"] > start]
        if (not cues or cues[0]["s"] != start or max(cue["e"] for cue in cues) != end
                or any(cue["s"] < start or cue["e"] > end for cue in cues)):
            raise ValueError("pick times must use whole cue edges")
        for key in ("quote", "why", "on_screen_context", "risk_note"):
            if not isinstance(pick[key], str) or not pick[key].strip():
                raise ValueError(f"{key} must be non-empty text")
        quote = " ".join(cue["text"] for cue in cues)
        if " ".join(pick["quote"].split()) != quote:
            raise ValueError("pick quote must match all the timed cues exactly")
        if pick["on_screen_context"] not in _labels(candidate, entity):
            raise ValueError("on-screen context must use a supplied name, show and original month")
        if any(candidate["episode_id"] == item["episode_id"] and start < item["end"] and end > item["start"] for item in out):
            raise ValueError("resurface picks must not overlap")
        out.append({**candidate, **pick, "quote": quote, "cues": cues})
        seen.add(ident)
    return out


def rank(candidates: list[dict], entity: str, headline: str, judge: Judge, n: int = 5) -> list[dict]:
    if type(n) is not int or n < 0:
        raise ValueError("n must be a nonnegative integer")
    if any(not isinstance(value, str) or not value.strip() for value in (entity, headline)):
        raise ValueError("entity and headline must be non-empty text")
    if not candidates or not n:
        return []
    text = prompt(candidates, entity, headline, n)
    task = "resurface-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]
    if not isinstance(judge, Judge):
        return check(judge.ask(task, text), candidates, entity, n)
    previous = judge.validate

    def validate(ident, answer):
        if ident == task:
            check(answer, candidates, entity, n)
        elif previous:
            previous(ident, answer)
    judge.validate = validate
    try:
        return check(judge.ask(task, text), candidates, entity, n)
    finally:
        judge.validate = previous
