"""Transcription -> `Word[]` with per-word confidence.

Choices are evidence-based (R1-A pick 2):
- faster-whisper, preferring cached **large-v2** absent a saved choice: hallucination is the worst
  failure mode for a measurement tool, large-v3's regression is multiply
  attested, and distil-* models never trained their word-alignment heads.
  Setup saves the selected model; ZING_WHISPER_MODEL overrides it. The model is
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
    local_files_only: bool = False,
    vocabulary=(),
) -> TranscribeResult:
    result = TranscribeResult()
    from .speech_models import resolve_name, missing_message
    name = resolve_name(model_name, require_cached=False)
    if name == "skip":
        from .speech_models import SKIP_NOTE
        result.warnings.append(SKIP_NOTE)
        result.provenance = {"speech_setup": "skipped", "captions": "unavailable", "continuity": "unavailable"}
        return result
    try:
        model, device, compute_type, version = (
            _load_model(name, local_files_only=True) if local_files_only else _load_model(name)
        )
    except ImportError:
        result.warnings.append(
            "transcription skipped: faster-whisper not installed "
            "(pip install myzing[study])"
        )
        return result
    except Exception as e:  # model download/load failure — skip, don't guess
        result.warnings.append(
            f"transcription skipped: whisper model '{name}' could not be "
            f"loaded: {e}. {missing_message(name)}"
        )
        return result

    from .asr_hygiene import vocabulary_context
    context = vocabulary_context(vocabulary)
    options = {"vocabulary": context["terms"]} if context["terms"] else {}
    use_batched = duration > formats.SHORT_FORM_MAX_S

    def decode(options):
        if use_batched:
            try:
                return _run_model_batched(model, media_path, **options), f"batched(batch_size={BATCH_SIZE})"
            except Exception as e:
                result.warnings.append(
                    f"batched transcription failed ({e}); fell back to "
                    "sequential"
                )
        return _run_model(model, media_path, **options), "sequential"

    try:
        run, pipeline = decode(options)
    except Exception as e:
        result.warnings.append(f"transcription failed: {e}")
        return result

    vocabulary_check = None
    if options:
        # Hints must not cost recall. A prompt can end a chunk early or skip a
        # window (measured: a quarter of a file's words), leaving VAD speech
        # without words. Only then decode again without hints and keep
        # whichever transcript covers the detected speech better.
        from .asr_hygiene import coverage_margin, speech_coverage
        regions = (run[3] if len(run) > 3 else {}).get("speech_regions")
        if regions is None:
            vocabulary_check = {"status": "unchecked", "reason": "no VAD speech regions"}
        else:
            hinted = speech_coverage(run[0], regions)
            margin = coverage_margin(hinted["speech_seconds"])
            vocabulary_check = {"status": "kept hinted", "hinted": hinted, "margin_seconds": round(margin, 3)}
            if hinted["uncovered_seconds"] > margin:
                try:
                    plain, plain_pipeline = decode({})
                except Exception as e:
                    vocabulary_check.update(status="kept hinted", unhinted_error=str(e))
                else:
                    unhinted = speech_coverage(plain[0], regions)
                    vocabulary_check["unhinted"] = unhinted
                    if unhinted["uncovered_seconds"] + margin < hinted["uncovered_seconds"]:
                        run, pipeline = plain, plain_pipeline
                        vocabulary_check["status"] = "kept unhinted"
                        result.warnings.append(
                            f"Vocabulary hints left {hinted['uncovered_seconds']:.1f} s of detected speech without "
                            f"words ({unhinted['uncovered_seconds']:.1f} s without hints); kept the unhinted transcript. "
                            "Limit the vocabulary to names spoken in this clip.")

    words, language, language_probability = run[:3]
    timing = run[3] if len(run) > 3 else {}
    prompt = run[4] if len(run) > 4 else {}
    if vocabulary_check and vocabulary_check["status"] == "kept unhinted":
        prompt = {**prompt, "applied": False}
    if timing.get("status") == "unavailable":
        result.warnings.append("VAD word-edge clamp unavailable; raw word times retained: " + timing["reason"])
    result.words = words
    result.provenance = {
        "asr_vocabulary": context,
        "asr_prompt": prompt,
        "vocabulary_check": vocabulary_check,
        "timing": timing,
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


def _load_model(name: str, *, local_files_only: bool = True):
    """Import + construct the model (tests mock this). GPU with int8_float16
    when available, plain int8 otherwise — the R1-A compute picks.

    Loading never downloads, whatever ``local_files_only`` says (kept for
    callers): weights come from Zing's verified cache, a local folder or an
    existing hub snapshot. The only download path is the consented, pinned
    fetch in zing studio / zing doctor / zing setup --speech-model.
    """
    import faster_whisper

    from .speech_models import local_path
    # Load exactly the folder inventory reported (Zing's verified cache, a local
    # directory, or an existing hub snapshot). A bare name makes faster-whisper
    # resolve its own repo id, which misses snapshots from other publishers.
    requested = name
    path = local_path(name)
    version = getattr(faster_whisper, "__version__", "unknown")
    options = {"local_files_only": True}
    if path is None:
        from .speech_models import missing_message
        raise FileNotFoundError(missing_message(requested))
    # local_files_only only covers the weights: a model directory without
    # tokenizer.json makes faster-whisper fetch the tokenizer from the hub.
    if not (path / "tokenizer.json").is_file():
        raise FileNotFoundError(
            f"local model '{name}' has no tokenizer.json; loading it would download one")
    name = str(path)
    try:
        model = faster_whisper.WhisperModel(
            name, device="auto", compute_type="int8_float16", **options
        )
        return model, "auto", "int8_float16", version
    except (ValueError, RuntimeError):
        model = faster_whisper.WhisperModel(name, device="cpu", compute_type="int8", **options)
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
                    start=round(float(w.start), 3),
                    end=round(float(w.end), 3),
                    confidence=round(float(w.probability), 3),
                )
            )
    words.sort(key=lambda w: (w.start, w.end))
    return words


def _run_model(model, media_path: Path, *, vocabulary=()):
    """Sequential transcription (tests mock this)."""
    from .asr_hygiene import vocabulary_context, finish_timing, fit_prompt
    prompt = fit_prompt(vocabulary_context(vocabulary)["terms"], getattr(model, "hf_tokenizer", None))
    segments, info = model.transcribe(
        str(media_path),
        word_timestamps=True,
        vad_filter=True,
        hotwords=prompt["hotwords"],
        initial_prompt=prompt["initial_prompt"],
        condition_on_previous_text=False,
    )
    words, timing = finish_timing(_collect_words(segments), media_path, info)
    return words, info.language, info.language_probability, timing, prompt


def _run_model_batched(model, media_path: Path, *, vocabulary=()):
    """Batched long-form transcription (tests mock this): VAD-segmented
    batches through the same model — same weights, better utilization."""
    from faster_whisper import BatchedInferencePipeline

    pipeline = BatchedInferencePipeline(model)
    from .asr_hygiene import vocabulary_context, finish_timing, fit_prompt
    prompt = fit_prompt(vocabulary_context(vocabulary)["terms"], getattr(model, "hf_tokenizer", None),
                        initial_prompt=False)
    segments, info = pipeline.transcribe(
        str(media_path),
        word_timestamps=True,
        vad_filter=True,
        hotwords=prompt["hotwords"],
        initial_prompt=prompt["initial_prompt"],
        batch_size=BATCH_SIZE,
        condition_on_previous_text=False,
    )
    words, timing = finish_timing(_collect_words(segments), media_path, info)
    return words, info.language, info.language_probability, timing, prompt
