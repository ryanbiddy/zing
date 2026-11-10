"""Check supplied captions against speech before choosing and cutting moments."""
from __future__ import annotations

import math
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median

from . import source

MISMATCH = ('The transcript does not match this video. Check that it is for this file. '
            'If you are sure it matches, run zing factory run "{project}" --no-sync-check '
            'or zing factory run "{project}" --offset SECONDS.')
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


def duration(media: Path) -> float:
    from myzing.project.probe import probe_file
    seconds = probe_file(media).duration
    if seconds is None or not math.isfinite(seconds) or seconds <= 0:
        raise RuntimeError("Could not measure the media duration.")
    return seconds


def shift(rows: list[dict], offset: float, duration: float = math.inf) -> list[dict]:
    shifted = [{**row, "s": max(0.0, round(row["s"] + offset, 3)),
                "e": min(duration, round(row["e"] + offset, 3))} for row in rows
               if row["e"] + offset > 0 and row["s"] + offset < duration]
    return [row for row in shifted if row["s"] < row["e"]]


def model() -> str | None:
    from myzing.study import speech_models
    configured = speech_models.resolve_name(None, require_cached=False)
    if configured == "skip":
        return None
    name = source.scout_model() or configured
    if speech_models.local_path(name):
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
        from myzing.study import speech_models
        off = speech_models.resolve_name(None, require_cached=False) == "skip"
        return {"status": "skipped", "method": "speech_off" if off else "no_cached_model"}
    try:
        seconds = duration(media)
    except (RuntimeError, OSError, subprocess.SubprocessError, ImportError) as exc:
        return {"status": "skipped", "method": "probe_error", "error": " ".join(str(exc).split())[:300]}
    transcript = timed(words or segments)
    probes = []
    result = {"status": "failed", "method": "probes", "model": name, "probes": probes}
    for fraction in (.1, .3, .5, .7, .9):
        start = max(0.0, min(seconds - 20, seconds * fraction - 10))
        end = min(seconds, start + 20)
        if any(p["start"] == start for p in probes):
            continue
        if start >= end:
            probes.append({"start": start, "note": "Past the media end."})
            continue
        try:
            heard = source._speech(media, start, end, model=name, **({"vocab": vocab} if vocab else {}))[0]
            if not timed(heard):
                probes.append({"start": start, "note": "No speech heard."})
                continue
            probes.append({"start": start, **match(heard, transcript)})
        except (RuntimeError, OSError, subprocess.SubprocessError, ImportError) as exc:
            error = " ".join(str(exc).split())[:300] or type(exc).__name__
            if "speech transcription produced no words" in error:
                probes.append({"start": start, "note": "No speech heard."})
            elif "past the end" in error:
                probes.append({"start": start, "note": "Past the media end."})
            else:
                probes.append({"start": start, "error": error})
            continue
        good = [p["offset"] for p in probes if p.get("match", 0) >= AGREE and p["offset"] is not None]
        groups = [[d for d in good if low <= d <= low + 1.5] for low in good]
        agreed = max(groups, key=len, default=[])
        if len(agreed) >= 2:
            offset = median(agreed)
            return {**result, "status": "matched", "offset": round(offset, 3) if abs(offset) >= .75 else 0.0}
    if probes and all("error" in p for p in probes):
        return {**result, "status": "skipped", "method": "probe_error", "error": probes[0]["error"]}
    if sum("match" in p for p in probes) < 2:
        return {**result, "status": "skipped", "method": "too_little_speech"}
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
