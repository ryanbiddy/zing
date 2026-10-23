"""Caption-only VAD clamp; study measurements remain immutable (AUD1-safe)."""

from functools import lru_cache
from pathlib import Path

from myzing.timing import transform_word


def clamp_words(words, intervals):
    result, notes = [], []
    for word in words:
        overlaps = [(max(word.start, a), min(word.end, b)) for a, b in intervals
                    if a < word.end and b > word.start]
        if not overlaps:
            result.append(word)
            notes.append(f"VAD has no speech overlap for {word.text!r}; original timing retained for review.")
            continue
        # Largest overlap avoids pulling a word across a real silent interval.
        start, end = max(overlaps, key=lambda ab: ab[1]-ab[0])
        if end-start < .001:
            result.append(word)  # Leave zero-duration repair to the shared timing layer.
        elif (start, end) != (word.start, word.end):
            result.append(transform_word(word, start, end, "caption_vad_clamp", corrected=True,
                                         speech_interval=[start, end]))
        else:
            result.append(word)
    return result, notes


@lru_cache(maxsize=32)
def _speech(path, size, modified):
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    audio = decode_audio(path, sampling_rate=16000)
    spans = get_speech_timestamps(audio, VadOptions(speech_pad_ms=30))
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
