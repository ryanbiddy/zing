"""Opt-in local re-transcription of a bounded audio crop. Never downloads a model."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from myzing.schemas import Word
from myzing.study.proc import MediaError, run, tail
from myzing.timing import RETRY_RADIUS_S, TimingProvenance, WordRetry, interval_problem


def local_word_retry(media_path: Path, model_directory: Path) -> WordRetry:
    """Load a user-supplied CTranslate2 model only if a 40ms repair fails."""
    model = None
    model_path = model_directory.expanduser().resolve()

    def retry(word: Word, start: float, end: float) -> list[Word]:
        nonlocal model
        if interval_problem(start, end, end) or end - start > 2 * RETRY_RADIUS_S + 1e-9:
            raise ValueError("word retry requires a positive span of at most 2 seconds")
        if not model_path.is_dir():
            raise ValueError(f"local whisper model directory missing: {model_path}; supply an existing model")
        if model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("word retry needs faster-whisper; install myzing[study]") from exc
            model = WhisperModel(str(model_path), device="cpu", compute_type="int8",
                                 local_files_only=True)
        with TemporaryDirectory(prefix="zing-word-") as work:
            crop = Path(work) / "span.wav"
            result = run([
                "ffmpeg", "-v", "error", "-nostdin", "-ss", str(start),
                "-i", str(media_path), "-t", str(end - start),
                "-vn", "-ac", "1", "-ar", "16000", str(crop),
            ], timeout=30)
            if result.returncode:
                raise MediaError(f"word retry audio crop failed: {tail(result.stderr)}")
            from myzing.study.transcribe import _run_model

            words, _, _ = _run_model(model, crop)
        out: list[Word] = []
        for measured in words:
            timing = TimingProvenance(
                "measured", "local_span_transcription",
                {"start": measured.start, "end": measured.end},
                adjustments=[{"method": "source_mapping", "offset": start,
                              "model_directory": str(model_path)}],
            )
            out.append(replace(measured, start=measured.start + start,
                               end=measured.end + start, timing=timing.to_dict()))
        return out

    return retry
