"""Episode transcripts: caption files (SRT/VTT), word lists, or Zing's own speech model.

Segments are [{s, e, text}] for scouting; words are [{w, s, e}] in episode seconds for cutting.
"""
from __future__ import annotations

import json
import re
import tempfile
import wave
from pathlib import Path

from myzing.word_joins import joins_previous

from .tools import ffmpeg, run

STAMP = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
MARGIN = 6.0
# fast enough on a CPU to read a whole episode (an hour in about 5 minutes); the picked moments get the full model
SCOUT_MODELS = ("small", "base")


def _seconds(match: re.Match) -> float:
    h, m, s, frac = match.groups()
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000


def parse_captions(text: str, offset: float = 0.0) -> list[dict]:
    """SRT or WebVTT cues -> segments. Tags and VTT cue settings are dropped; repeated rolling lines are merged."""
    out = []
    for block in re.split(r"\r?\n\s*\r?\n", text.replace("﻿", "")):
        lines = [ln.strip() for ln in block.strip().splitlines()]
        timing = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing is None:
            continue
        stamps = list(STAMP.finditer(lines[timing]))
        if len(stamps) < 2:
            continue
        body = " ".join(re.sub(r"<[^>]+>|\{[^}]+\}", "", ln) for ln in lines[timing + 1:]).strip()
        body = re.sub(r"\s+", " ", body)
        if not body:
            continue
        s, e = _seconds(stamps[0]) + offset, _seconds(stamps[1]) + offset
        if out and body.startswith(out[-1]["text"]) and s - out[-1]["e"] < 0.5:  # rolling auto-captions
            out[-1].update(e=round(e, 2), text=body)
            continue
        out.append({"s": round(s, 2), "e": round(e, 2), "text": body})
    return out


def segments_from_words(words: list[dict], longest: float = 12.0) -> list[dict]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.?!]$", w["w"]) or cur[-1]["e"] - cur[0]["s"] > longest:
            out.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
            cur = []
    if cur:
        out.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
    return out


def load_transcript(path: Path, offset: float = 0.0) -> tuple[list[dict], list[dict] | None]:
    """(segments, words or None). JSON may be words [{w,s,e}] or [{text,start,end}], or segments [{s,e,text}]."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            data = data.get("words") if isinstance(data, dict) else data
            if not isinstance(data, list) or not data or any(not isinstance(x, dict) for x in data):
                raise ValueError
            if "w" in data[0] or "start" in data[0]:     # {w,s,e} words or Zing Words {text,start,end}
                words = []
                for x in data:
                    w = {"w": str(x["w"] if "w" in x else x["text"]).strip(),
                         "s": round(float(x["s"] if "s" in x else x["start"]) + offset, 3),
                         "e": round(float(x["e"] if "e" in x else x["end"]) + offset, 3)}
                    if words and joins_previous(w["w"]):
                        words[-1]["w"] += w["w"]
                        words[-1]["e"] = w["e"]
                    else:
                        words.append(w)
                return segments_from_words(words), words
            return [{"s": float(x["s"]) + offset, "e": float(x["e"]) + offset, "text": x["text"]} for x in data], None
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ValueError(f"{path.name} is not a transcript Zing can read. Use .srt, .vtt, or JSON words or segments.") from None
    segments = parse_captions(text, offset)
    if not segments:
        raise ValueError(f"no caption cues found in {path.name}")
    return segments, None


def sibling_transcript(media: Path) -> Path | None:
    for ext in (".srt", ".vtt", ".json"):
        path = media.with_suffix(ext)
        if not path.is_file():
            continue
        if ext == ".json":
            try:
                load_transcript(path)
            except (OSError, ValueError):
                continue
        return path
    return None


def scout_model() -> str | None:
    """A small model already on disk for the whole-episode pass, or None when the configured one is as quick."""
    from myzing.study import speech_models
    configured = speech_models.resolve_name(None, require_cached=False)
    if configured in SCOUT_MODELS:
        return None
    return next((name for name in SCOUT_MODELS if speech_models.local_path(name)), None)   # never downloads


def _speech(media: Path, start: float | None = None, end: float | None = None, model: str | None = None,
            language: str | None = None, vocab: list[str] | None = None) -> tuple[list[dict], str | None, float]:
    from myzing.study.transcribe import transcribe
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "speech.wav"
        window = ([] if start is None else ["-ss", f"{start:.3f}"]) + ([] if end is None else ["-t", f"{end - (start or 0):.3f}"])
        run(ffmpeg(), "-v", "error", "-y", *window, "-i", media, "-vn", "-ac", "1", "-ar", "16000", wav)
        duration = (end - (start or 0)) if end else 0.0
        if model and start is None and end is None:       # only the scout pass discards its word timestamps
            try:
                with wave.open(str(wav)) as audio:
                    duration = audio.getnframes() / audio.getframerate()
            except (OSError, EOFError, wave.Error):
                pass                                        # unreadable: decode sequentially, as before
        result = transcribe(wav, model_name=model, duration=duration, local_files_only=bool(model),
                            language=language, **({"vocabulary": vocab} if vocab else {}))
    if not result.words:
        raise RuntimeError("speech transcription produced no words: " + "; ".join(result.warnings or ["no detail"]))
    base = start or 0.0
    words = [{"w": w.text, "s": round(w.start + base, 3), "e": round(w.end + base, 3)} for w in result.words]
    return words, result.provenance.get("language"), float(result.provenance.get("language_probability") or 0.0)


def transcribe_episode(media: Path, model: str | None = None, vocab: list[str] | None = None) -> list[dict]:
    return _speech(media, model=model, **({"vocab": vocab} if vocab else {}))[0]


def main_language(runs: list[tuple[float, float, str | None, float]]) -> str | None:
    """The language most of the speech is in: (start, end, language, probability) per stretch, weighted by length."""
    weight: dict[str, float] = {}
    for a, b, lang, p in runs:
        if lang:
            weight[lang] = weight.get(lang, 0.0) + (b - a) * max(p, 0.01)
    return max(weight, key=weight.get) if weight else None


def transcribe_moments(media: Path, moments: list[dict], vocab: list[str] | None = None) -> list[dict]:
    """Word times for each moment (with a margin), merged in episode time. A short stretch can fool language detection
    (an English span came back as Welsh), so a stretch that disagrees with the main language is redone in it."""
    runs = []
    options = {"vocab": vocab} if vocab else {}
    for m in moments:
        a, b = max(0.0, m["start"] - MARGIN), m["end"] + MARGIN
        runs.append((a, b, *_speech(media, a, b, **options)))
    main = main_language([(a, b, lang, p) for a, b, _, lang, p in runs])
    words: list[dict] = []
    for a, b, got, lang, _ in runs:
        if main and lang != main:
            got = _speech(media, a, b, language=main, **options)[0]
        words = [w for w in words if not (got[0]["s"] <= w["s"] <= got[-1]["e"])] + got
    return sorted(words, key=lambda w: w["s"])
