"""Transcription -> `Word[]` with per-word confidence.

Choices are evidence-based (R1-A pick 2):
- faster-whisper, default model **large-v2**: hallucination is the worst
  failure mode for a measurement tool, large-v3's regression is multiply
  attested, and distil-* models never trained their word-alignment heads.
  Override via ZING_WHISPER_MODEL for experiments; the model used is
  recorded in provenance either way.
- vad_filter=True (the single biggest hallucination mitigation) and
  condition_on_previous_text=False (stops cross-window error propagation).
- Per-word probability lands in Word.confidence — downstream consumers get
  to know which timings to distrust.

Native word timestamps are ±0.1–0.2s typical, which meets the S1 bar;
whisperX forced alignment is the S2 upgrade if the eval harness shows
misses. faster-whisper is an optional [study] dependency, imported lazily;
absence or model-load failure is an honest skip with a warning.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from myzing.schemas import Word

DEFAULT_MODEL = "large-v2"
ENV_MODEL = "ZING_WHISPER_MODEL"


@dataclass
class TranscribeResult:
    words: list[Word] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def transcribe(media_path: Path, model_name: str | None = None) -> TranscribeResult:
    result = TranscribeResult()
    name = model_name or os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODEL
    try:
        model, device, compute_type, version = _load_model(name)
    except ImportError:
        result.warnings.append(
            "transcription skipped: faster-whisper not installed "
            "(pip install myzing[study])"
        )
        return result
    except Exception as e:  # model download/load failure — skip, don't guess
        result.warnings.append(
            f"transcription skipped: whisper model '{name}' could not be "
            f"loaded: {e}"
        )
        return result

    try:
        words, language, language_probability = _run_model(model, media_path)
    except Exception as e:
        result.warnings.append(f"transcription failed: {e}")
        return result

    result.words = words
    result.provenance = {
        "whisper_model": name,
        "device": device,
        "compute_type": compute_type,
        "faster_whisper": version,
        "language": language,
        "language_probability": round(language_probability, 3),
        "vad_filter": True,
        "condition_on_previous_text": False,
    }
    return result


def _load_model(name: str):
    """Import + construct the model (tests mock this). GPU with int8_float16
    when available, plain int8 otherwise — the R1-A compute picks."""
    import faster_whisper

    version = getattr(faster_whisper, "__version__", "unknown")
    try:
        model = faster_whisper.WhisperModel(
            name, device="auto", compute_type="int8_float16"
        )
        return model, "auto", "int8_float16", version
    except (ValueError, RuntimeError):
        model = faster_whisper.WhisperModel(name, device="cpu", compute_type="int8")
        return model, "cpu", "int8", version


def _run_model(model, media_path: Path):
    """Run transcription (tests mock this). Segments are a generator — the
    full iteration IS the transcription work."""
    segments, info = model.transcribe(
        str(media_path),
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    words: list[Word] = []
    for segment in segments:
        for w in segment.words or []:
            text = w.word.strip()
            if not text:
                continue
            words.append(
                Word(
                    text=text,
                    start=round(w.start, 3),
                    end=round(w.end, 3),
                    confidence=round(w.probability, 3),
                )
            )
    return words, info.language, info.language_probability
