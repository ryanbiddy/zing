"""Bounded supplied vocabulary and conservative VAD edge suppression.

The silence-suppression idea follows stable-ts (MIT); this implementation is
stdlib-only and consumes faster-whisper's Silero regions on the source clock.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import replace
from collections.abc import Iterable, Mapping

MAX_TERMS = 64
MAX_TERM_CHARS = 80
MAX_VOCABULARY_CHARS = 500
# Untrusted metadata (a Uoink or file title) is data, not a prompt: only short,
# term-like strings are used, never sentences, links or addresses.
MAX_METADATA_WORDS = 8
# Whisper's decoder holds 448 tokens per window, prompt included. faster-whisper
# caps `hotwords` and the previous-text prompt at 223 tokens each, so the same
# 500-byte vocabulary sent as both (about 260 tokens each for CJK or accented
# names) overflowed position 448 and failed the whole transcription. The fitted
# prompt stays well inside Whisper's own 223-token prompt budget instead. At 150
# hotword tokens large-v2 dropped a fifth of a 79-second test file's words and
# tiny repeated prompt names as speech; at 64 neither happened.
HOTWORD_TOKENS = 64
INITIAL_PROMPT_TOKENS = 64
METHOD = "vad_edge_snap"
EDGE_VAD_PARAMETERS = {"min_silence_duration_ms": 200, "speech_pad_ms": 80}
_LINK = re.compile(r"(?i)\b(?:[a-z][a-z0-9+.-]*://|www\.)|[^\s@]+@[^\s@]+\.[^\s@]+")


def _clean(value: str) -> str:
    """NFC, no control/format/private-use characters, single spaces."""
    value = unicodedata.normalize("NFC", value)
    value = "".join(" " if unicodedata.category(c) in ("Zl", "Zp") else c for c in value
                    if unicodedata.category(c) not in ("Cc", "Cf", "Co", "Cs", "Cn") or c in "\t\n\r")
    return " ".join(value.split())


def vocabulary_context(vocabulary=(), *, brief=None, metadata=None) -> dict:
    """Use supplied spellings only. Explicit vocabulary precedes brief, then metadata.

    No name extraction, spelling inference, or external lookup. A brief adds
    only its spelling lists (`exact_spellings`, and `names`/`vocabulary` in API
    mappings): its purpose or topic describes the edit, not words to hear, and
    a default purpose was never supplied by anyone. Metadata is untrusted: a
    malformed entry is skipped, and sentences, links and addresses are omitted.
    Whitespace and Unicode are normalized; duplicates are removed; oversize
    terms are omitted whole.
    """
    if isinstance(vocabulary, str):
        vocabulary = vocabulary.split(",")
    if not isinstance(vocabulary, Iterable):
        raise ValueError("vocabulary must be a list of names/terms")
    candidates = [(v, "user") for v in vocabulary]
    brief = brief.to_dict() if hasattr(brief, "to_dict") else brief or {}
    for key in ("exact_spellings", "names", "vocabulary"):
        values = brief.get(key, [])
        if isinstance(values, list):
            candidates.extend((v, "brief." + key) for v in values)
    omitted = []
    if isinstance(metadata, Mapping):
        for key in ("title", "names", "tags"):
            value = metadata.get(key)
            values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
            for item in values:
                if isinstance(item, str):
                    candidates.append((item, "reference." + key))
                else:
                    omitted.append({"source": "reference." + key, "reason": "not a string"})
    terms, sources, seen = [], [], set()
    for value, source in candidates:
        if not isinstance(value, str):
            raise ValueError("vocabulary entries must be strings")
        value = _clean(value)
        if not value or value.casefold() in seen:
            continue
        reason = ("longer than the term limit" if len(value) > MAX_TERM_CHARS else
                  "term limit reached" if len(terms) >= MAX_TERMS else
                  "vocabulary byte limit reached" if len(", ".join(terms + [value]).encode("utf-8")) > MAX_VOCABULARY_CHARS else None)
        if reason is None and source.startswith("reference."):
            reason = ("metadata link or address" if _LINK.search(value) else
                      "metadata sentence, not a term" if len(value.split()) > MAX_METADATA_WORDS else None)
        if reason:
            omitted.append({"source": source, "reason": reason, "characters": len(value)})
            continue
        terms.append(value)
        sources.append(source)
        seen.add(value.casefold())
    data = {"version": 1, "terms": terms, "sources": sources, "text": ", ".join(terms),
            "omitted_terms": len(omitted), "omitted": omitted,
            "limits": {"terms": MAX_TERMS, "term_characters": MAX_TERM_CHARS,
                       "total_utf8_bytes": MAX_VOCABULARY_CHARS, "metadata_words": MAX_METADATA_WORDS,
                       "hotword_tokens": HOTWORD_TOKENS, "initial_prompt_tokens": INITIAL_PROMPT_TOKENS}}
    data["cache_key"] = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return data


def _tokens(text: str, tokenizer) -> tuple[int, str]:
    if not text:
        return 0, "empty"
    if tokenizer is not None:
        try:
            ids = tokenizer.encode(" " + text.strip(), add_special_tokens=False).ids
            if isinstance(ids, list):
                return len(ids), "model tokenizer"
        except Exception:  # an unusable tokenizer falls back to the strict bound
            pass
    # Byte-level BPE never needs more tokens than UTF-8 bytes.
    return len((" " + text.strip()).encode("utf-8")), "UTF-8 byte upper bound"


BATCHED_PROMPT_NOTE = ("not sent: the batched pipeline repeats initial_prompt as previous text in every "
                       "chunk, which ended a 33-second chunk at 18 seconds in review; hotwords reach every chunk")


def fit_prompt(terms, tokenizer=None, *, initial_prompt=True) -> dict:
    """Whole terms, in priority order, inside each decoder token budget.

    Sequential decoding uses initial_prompt for its first window only, as
    Whisper intends. The batched pipeline would prepend it to every chunk, so
    it gets hotwords alone (``initial_prompt=False``).
    """
    record = {"version": 1, "budget": {"hotwords": HOTWORD_TOKENS, "initial_prompt": INITIAL_PROMPT_TOKENS,
                                       "whisper_context": 448}}
    counting = "empty"
    fields = (("hotwords", HOTWORD_TOKENS),) + ((("initial_prompt", INITIAL_PROMPT_TOKENS),) if initial_prompt else ())
    if not initial_prompt:
        record.update(initial_prompt=None, initial_prompt_tokens=0, initial_prompt_terms=0,
                      initial_prompt_note=BATCHED_PROMPT_NOTE)
    for key, limit in fields:
        kept = []
        for term in terms:
            count, method = _tokens(", ".join(kept + [term]), tokenizer)
            if count <= limit:
                kept.append(term)
                counting = method
        text = ", ".join(kept)
        record[key] = text or None
        record[key + "_tokens"] = _tokens(text, tokenizer)[0]
        record[key + "_terms"] = len(kept)
    record["terms_dropped"] = len(terms) - record["hotwords_terms"]
    record["counting"] = counting
    return record


def speech_coverage(words, regions, *, pad=.5) -> dict:
    """Seconds of VAD speech farther than ``pad`` from every recognized word.

    Recall evidence for vocabulary hints: a prompt can make Whisper end a chunk
    early or skip a window, which leaves detected speech without any words.
    """
    spans = sorted((max(0.0, w.start - pad), w.end + pad) for w in words)
    speech = longest = total = 0.0
    for a, b in regions:
        speech += b - a
        t = a
        for s, e in spans:
            if e <= t or s >= b:
                continue
            if s > t:
                total += min(s, b) - t
                longest = max(longest, min(s, b) - t)
            t = max(t, e)
            if t >= b:
                break
        if t < b:
            total += b - t
            longest = max(longest, b - t)
    return {"speech_seconds": round(speech, 3), "uncovered_seconds": round(total, 3),
            "longest_uncovered_seconds": round(longest, 3), "pad_seconds": pad}


def coverage_margin(speech_seconds: float) -> float:
    """Uncovered speech a hinted transcript may add before it is rechecked."""
    return 1.0 + .02 * speech_seconds


def clamp_words(words, regions, *, min_word_duration=.1, tolerance=.02):
    """Shrink edges only; never shift a word wholly in silence into speech.

    First-word ends and last-word starts within each speech region are protected.
    Short/ambiguous intersections remain unchanged and are reported for review.
    """
    spans = []
    for start, end in sorted(regions):
        if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
            raise ValueError("VAD regions require finite 0 <= start < end")
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(end, spans[-1][1])
        else:
            spans.append([start, end])
    original = [{"text": w.text, "start": w.start, "end": w.end} for w in words]
    adjusted, changes, unresolved = [], [], []
    first, last = set(), set()
    for a, b in spans:
        indices = [i for i, w in enumerate(words) if max(w.start, a) < min(w.end, b)]
        if indices:
            first.add(indices[0])
            last.add(indices[-1])
    for i, w in enumerate(words):
        intersections = [(max(w.start, a), min(w.end, b)) for a, b in spans
                         if max(w.start, a) < min(w.end, b)]
        start, end = w.start, w.end
        if intersections:
            a, b = intersections[0][0], intersections[-1][1]
            if i not in last or i in first:  # a single word can shrink both edges
                if a - start > tolerance:
                    start = a
            if i not in first or i in last:
                if end - b > tolerance:
                    end = b
            if end - start < min_word_duration - 1e-9:
                start, end = w.start, w.end
                unresolved.append({"index": i, "reason": "speech intersection shorter than minimum word duration"})
        else:
            unresolved.append({"index": i, "reason": "word has no VAD speech overlap; unchanged"})
        start = max(w.start, round(start, 3)) if start != w.start else w.start
        end = min(w.end, round(end, 3)) if end != w.end else w.end
        if i + 1 < len(words) and start > words[i + 1].start:
            # Native/batched words can overlap. Preserve text/start order when
            # the next word's protected start prevents a safe inward move.
            start = w.start
            unresolved.append({"index": i, "reason": "start clamp would reorder overlapping words; start unchanged"})
        adjusted.append(replace(w, start=start, end=end))
        if (start, end) != (w.start, w.end):
            changes.append({"index": i, "text": w.text, "method": METHOD,
                            "original": {"start": w.start, "end": w.end},
                            "adjusted": {"start": start, "end": end}})
    return adjusted, {"version": 1, "method": METHOD, "original": original,
        "adjusted": [{"text": w.text, "start": w.start, "end": w.end} for w in adjusted],
        "adjustments": changes, "unresolved": unresolved, "speech_regions": spans,
        "min_word_duration": min_word_duration, "tolerance_seconds": tolerance,
        "basis": "faster-whisper Silero VAD; source seconds; no forced alignment"}


def finish_timing(words, media_path, info):
    """Use the decoder's bundled VAD for an independent edge-only pass.

faster-whisper does not expose its speech chunks in TranscriptionInfo. This
uses the same bundled VAD, tightening silence and padding only after decoding.
It does not monkeypatch globals or mistake ASR segment bounds for VAD regions.
"""
    options = getattr(info, "vad_options", None)
    if options is None:
        return words, {"version": 1, "status": "unavailable", "reason": "decoder returned no VAD options"}
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import get_speech_timestamps
        samples = decode_audio(str(media_path), sampling_rate=16000)
        edge_options = replace(options, **EDGE_VAD_PARAMETERS)
        chunks = get_speech_timestamps(samples, edge_options, sampling_rate=16000)
        adjusted, timing = clamp_words(words, [(s["start"] / 16000, s["end"] / 16000) for s in chunks])
        from dataclasses import asdict
        timing["decoder_vad_options"] = asdict(options)
        timing["vad_options"] = asdict(edge_options)
        # Infinity is an upstream default, but provenance must be strict JSON.
        for key in ("vad_options", "decoder_vad_options"):
            timing[key] = {k: None if isinstance(v, float) and not math.isfinite(v) else v
                           for k, v in timing[key].items()}
        return adjusted, timing
    except Exception as exc:
        return words, {"version": 1, "status": "unavailable", "reason": str(exc),
                       "original": [{"text": w.text, "start": w.start, "end": w.end} for w in words]}
