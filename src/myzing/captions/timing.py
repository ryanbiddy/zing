"""Caption-only VAD clamp; study measurements remain immutable.

The clamp follows AUD1's study-level edge snap (feat/aud1,
myzing.study.asr_hygiene.clamp_words) exactly: the same Silero options
(200 ms minimum silence, 80 ms pad), shrink-only edges, the first word's end
and last word's start in each speech region protected, a 100 ms minimum word,
a 20 ms tolerance and no reordering. Applying it to words AUD1 already
clamped therefore changes nothing, and words whose provenance records either
clamp are skipped, so the two layers never double-shift a word.
"""

from functools import lru_cache
import math
from pathlib import Path

from myzing.timing import transform_word


METHOD = "caption_vad_clamp"
STUDY_METHODS = frozenset({"vad_edge_snap"})  # AUD1's study-level method name.
VAD_PARAMETERS = {"min_silence_duration_ms": 200, "speech_pad_ms": 80}  # AUD1 EDGE_VAD_PARAMETERS.


def already_clamped(word):
    timing = word.timing or {}
    methods = {timing.get("method")} | {a.get("method") for a in timing.get("adjustments", [])}
    return bool(methods & (STUDY_METHODS | {METHOD}))



def mark_study_clamp(words, provenance):
    """Carry AUD1's transcript-level flag through selection/timeline mapping.

    AUD1 records the complete adjusted sequence, including unchanged words.
    Only a successful edge-snap record marks the caption layer as satisfied.
    """
    record = (provenance or {}).get("timing", {})
    if (record.get("method") not in STUDY_METHODS or record.get("status") == "unavailable"
            or not isinstance(record.get("adjusted"), list)):
        return words
    adjusted = record["adjusted"]
    if len(adjusted) != len(words) or any(
        row.get("text") != w.text or row.get("start") != w.start or row.get("end") != w.end
        for w, row in zip(words, adjusted)
    ):
        return words
    return [w if already_clamped(w) else transform_word(
        w, w.start, w.end, "vad_edge_snap", corrected=False, study_clamped=True
    ) for w in words]


def clamp_words(words, intervals, *, min_word_duration=.1, tolerance=.02):
    """Shrink word edges into speech; never move a word wholly in silence."""
    spans = []
    for start, end in sorted(intervals):
        if not all(math.isfinite(v) for v in (start, end)) or not start < end:
            raise ValueError("VAD regions require finite start < end")
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(end, spans[-1][1])
        else:
            spans.append([start, end])
    first, last = set(), set()
    for a, b in spans:
        inside = [i for i, w in enumerate(words) if max(w.start, a) < min(w.end, b)]
        if inside:
            first.add(inside[0])
            last.add(inside[-1])
    result, notes = [], []
    for i, word in enumerate(words):
        if already_clamped(word):
            result.append(word)
            continue
        hits = [(max(word.start, a), min(word.end, b)) for a, b in spans if max(word.start, a) < min(word.end, b)]
        if not hits:
            result.append(word)
            notes.append(f"VAD has no speech overlap for {word.text!r}; original timing retained for review.")
            continue
        start, end = word.start, word.end
        a, b = hits[0][0], hits[-1][1]
        if (i not in last or i in first) and a - start > tolerance:
            start = a
        if (i not in first or i in last) and end - b > tolerance:
            end = b
        if end - start < min_word_duration - 1e-9:
            start, end = word.start, word.end
            notes.append(f"VAD speech for {word.text!r} is shorter than {min_word_duration:g}s; original timing retained.")
        start = max(word.start, round(start, 3)) if start != word.start else word.start
        end = min(word.end, round(end, 3)) if end != word.end else word.end
        if i + 1 < len(words) and start > words[i+1].start:
            start = word.start  # Never reorder overlapping native words.
        if (start, end) != (word.start, word.end):
            result.append(transform_word(word, start, end, METHOD, corrected=True, speech_interval=[a, b]))
        else:
            result.append(word)
    return result, notes


@lru_cache(maxsize=32)
def _speech(path, size, modified):
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    audio = decode_audio(path, sampling_rate=16000)
    spans = get_speech_timestamps(audio, VadOptions(**VAD_PARAMETERS), sampling_rate=16000)
    return tuple((s["start"]/16000, s["end"]/16000) for s in spans)


def speech_intervals(path):
    """Only faster-whisper's installed Silero asset; never fetch a model."""
    value = str(path)
    if value.startswith(("\\\\", "//")) or "://" in value:
        return None, "Caption VAD requires a local file; network sources are not opened."
    path = Path(path)
    if not path.is_absolute():
        return None, "Caption VAD needs a resolved local source path; source word times retained."
    if not path.is_file():
        return None, "Caption VAD unavailable: local source file is missing."
    try:
        stat = path.stat()
        return _speech(str(path.resolve()), stat.st_size, stat.st_mtime_ns), None
    except ImportError:
        return None, 'Caption VAD unavailable; install "myzing[study]" to clamp to detected speech.'
    except Exception as exc:
        return None, f"Caption VAD unavailable ({type(exc).__name__}); source word times retained."
