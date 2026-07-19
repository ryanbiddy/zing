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

Long-form strategy (A-Q9): sequential decoding scales linearly with
duration, so videos past the short-form boundary use faster-whisper's
BatchedInferencePipeline (VAD-segmented, batched inference) instead —
several times faster on the same model and hardware. Short-form keeps the
sequential path: its word timestamps feed caption-sync judgment, and the
batched pipeline's timestamp remapping has a documented bug history
(R1-A). A batched failure falls back to sequential with a warning; the
pipeline used is always recorded in provenance.

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

from . import formats

DEFAULT_MODEL = "large-v2"
ENV_MODEL = "ZING_WHISPER_MODEL"
BATCH_SIZE = 8


@dataclass
class TranscribeResult:
    words: list[Word] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def transcribe(
    media_path: Path,
    model_name: str | None = None,
    duration: float = 0.0,
) -> TranscribeResult:
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

    pipeline = "sequential"
    use_batched = duration > formats.SHORT_FORM_MAX_S
    try:
        if use_batched:
            try:
                words, language, language_probability = _run_model_batched(
                    model, media_path
                )
                pipeline = f"batched(batch_size={BATCH_SIZE})"
            except Exception as e:
                result.warnings.append(
                    f"batched transcription failed ({e}); fell back to "
                    "sequential"
                )
                words, language, language_probability = _run_model(
                    model, media_path
                )
        else:
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
        "pipeline": pipeline,
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


def _collect_words(segments) -> list[Word]:
    """Drain a segment generator into Words — the iteration IS the work.

    SW-4: the batched pipeline's segment seams can overlap by a fraction
    of a second, emitting out-of-order word timestamps (2 inversions in
    10,088 words on a 62-min study). The timestamps are whisper's own;
    sorting is a faithful normalization, not a fabrication — downstream
    consumers (caption windows, keeper evidence) assume monotonic order.
    """
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
    words.sort(key=lambda w: (w.start, w.end))
    return words


def _run_model(model, media_path: Path):
    """Sequential transcription (tests mock this)."""
    segments, info = model.transcribe(
        str(media_path),
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return _collect_words(segments), info.language, info.language_probability


def _run_model_batched(model, media_path: Path):
    """Batched long-form transcription (tests mock this): VAD-segmented
    batches through the same model — same weights, better utilization."""
    from faster_whisper import BatchedInferencePipeline

    pipeline = BatchedInferencePipeline(model)
    segments, info = pipeline.transcribe(
        str(media_path),
        word_timestamps=True,
        vad_filter=True,
        batch_size=BATCH_SIZE,
    )
    return _collect_words(segments), info.language, info.language_probability
