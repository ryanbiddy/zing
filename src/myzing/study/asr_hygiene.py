"""Bounded supplied vocabulary and conservative VAD edge suppression.

The silence-suppression idea follows stable-ts (MIT); this implementation is
stdlib-only and consumes faster-whisper's Silero regions on the source clock.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from collections.abc import Iterable, Mapping

MAX_TERMS = 64
MAX_TERM_CHARS = 80
MAX_VOCABULARY_CHARS = 500
METHOD = "vad_edge_snap"
EDGE_VAD_PARAMETERS = {"min_silence_duration_ms": 200, "speech_pad_ms": 80}


def vocabulary_context(vocabulary=(), *, brief=None, metadata=None) -> dict:
    """Use supplied text only. Explicit vocabulary precedes brief, then metadata.

    No name extraction, spelling inference, or external lookup. Whitespace is
    normalized; duplicate terms are removed; oversize terms are omitted whole.
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
    for key in ("topic", "purpose"):
        value = brief.get(key)
        if isinstance(value, str):
            candidates.append((value, "brief." + key))
    if isinstance(metadata, Mapping):
        for key in ("title", "topic", "names", "tags"):
            value = metadata.get(key)
            values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
            candidates.extend((v, "reference." + key) for v in values)
    terms, sources, seen, omitted = [], [], set(), 0
    for value, source in candidates:
        if not isinstance(value, str):
            raise ValueError("vocabulary entries must be strings")
        value = " ".join(value.split())
        if not value or value.casefold() in seen:
            continue
        if (len(value) > MAX_TERM_CHARS or len(terms) >= MAX_TERMS
                or len(", ".join(terms + [value]).encode("utf-8")) > MAX_VOCABULARY_CHARS):
            omitted += 1
            continue
        terms.append(value)
        sources.append(source)
        seen.add(value.casefold())
    hotwords = ", ".join(terms)
    data = {"version": 1, "terms": terms, "sources": sources, "hotwords": hotwords,
            "initial_prompt": hotwords, "omitted_terms": omitted,
            "limits": {"terms": MAX_TERMS, "term_characters": MAX_TERM_CHARS,
                       "total_utf8_bytes": MAX_VOCABULARY_CHARS}}
    data["cache_key"] = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return data


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
