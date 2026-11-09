"""Check supplied captions against speech before choosing and cutting moments."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median

from . import source

MISMATCH = ("The transcript does not match this video (checked at 3 points). Make sure it is for this file, "
            "pass --offset SECONDS, or leave out --transcript to transcribe the episode. "
            "If you are sure it matches, create the project again with --no-sync-check.")
AGREE = .45  # share of a probe's heard words found in order; two probes must also agree on the offset


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", re.sub(r"['’]", "", text.casefold()))


def timed(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        words = tokens(row.get("w", row.get("text", "")))
        for i, word in enumerate(words):
            step = (row["e"] - row["s"]) / len(words)
            out.append({"w": word, "s": row["s"] + i * step, "e": row["s"] + (i + 1) * step})
    return out


def stamp(seconds: float) -> str:
    minutes, seconds = divmod(round(abs(seconds)), 60)
    return f"{minutes}:{seconds:02d}"


def shift(rows: list[dict], offset: float) -> list[dict]:
    return [{**row, "s": round(row["s"] + offset, 3), "e": round(row["e"] + offset, 3)} for row in rows]


def model() -> str | None:
    from myzing.study import speech_models
    name = source.scout_model() or speech_models.resolve_name(None, require_cached=False)
    if name != "skip" and speech_models.local_path(name):
        return name
    return next((name for name in source.SCOUT_MODELS if speech_models.local_path(name)), None) or next(
        (row["model"] for row in speech_models.inventory() if row["cached"]), None)


def match(probe: list[dict], transcript: list[dict]) -> dict:
    heard = timed(probe)
    if not heard:
        return {"match": 0.0, "offset": None}
    a, b = [w["w"] for w in heard], [w["w"] for w in transcript]
    best, offset = 0, None
    for start in range(0, len(b), max(1, len(a) // 2)):
        blocks = SequenceMatcher(None, a, b[start:start + 2 * len(a)], autojunk=False).get_matching_blocks()
        deltas = [heard[block.a + i]["s"] - transcript[start + block.b + i]["s"]
                  for block in blocks for i in range(block.size)]
        if not deltas:
            continue
        middle = median(deltas)
        close = [d for d in deltas if abs(d - middle) <= 3]  # cue words have estimated times
        if len(close) > best:
            best, offset = len(close), median(close)
    return {"match": best / len(a), "offset": round(offset, 3) if offset is not None else None}


def check(media: Path, segments: list[dict], words: list[dict] | None = None, vocab: list[str] | None = None) -> dict:
    name = model()
    if not name:
        return {"status": "skipped", "method": "no_cached_model"}
    transcript = timed(words or segments)
    probes = []
    first, last = (segments[0]["s"], segments[-1]["e"]) if segments else (0, 0)
    for fraction in (.2, .5, .8):
        start = max(0.0, first + (last - first) * fraction - 10)
        try:
            heard = source._speech(media, start, start + 20, model=name, **({"vocab": vocab} if vocab else {}))[0]
            probes.append({"start": start, **match(heard, transcript)})
        except RuntimeError as exc:
            probes.append({"start": start, "match": 0.0, "offset": None, "error": str(exc)[:300]})
    good = [p["offset"] for p in probes if p["match"] >= AGREE and p["offset"] is not None]
    groups = [[d for d in good if low <= d <= low + 1.5] for low in good]
    agreed = max(groups, key=len, default=[])
    result = {"status": "matched" if len(agreed) >= 2 else "failed", "method": "probes", "model": name, "probes": probes}
    if len(agreed) >= 2:
        offset = median(agreed)
        result["offset"] = round(offset, 3) if abs(offset) >= .75 else 0.0
    return result


def coverage(expected: list[str], heard: list[str]) -> float:
    counts = [0] * (len(heard) + 1)
    for word in expected:
        previous = 0
        for i, other in enumerate(heard, 1):
            old = counts[i]
            counts[i] = previous + 1 if word == other else max(counts[i], counts[i - 1])
            previous = old
    return counts[-1] / len(expected) if expected else 1.0


def guard(segments: list[dict], words: list[dict], spans: list[list[float]]) -> str | None:
    transcript, heard = timed(segments), timed(words)
    for start, end in spans:
        expected = [w["w"] for w in transcript if start <= (w["s"] + w["e"]) / 2 < end]
        actual = [w["w"] for w in heard if start <= (w["s"] + w["e"]) / 2 < end]
        if coverage(expected, actual) < .4:
            return (f"The words heard at {stamp(start)} do not match the transcript. "
                    "The transcript may be offset from the video.")
    return None
