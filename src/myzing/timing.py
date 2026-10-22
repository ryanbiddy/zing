"""Interval boundary shared by assembly and OCR; corrections are never measurements."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable

from myzing.schemas import Word

MIN_WORD_S = 0.04
RETRY_RADIUS_S = 1.0
MAX_RETRY_WORDS = 3
EPSILON = 1e-9


class TimingReviewError(ValueError):
    """A timestamp needs a human correction before assembly can continue."""


@dataclass
class TimingProvenance:
    status: str
    method: str
    original: dict[str, float]
    adjustments: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1
    repaired: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if not self.repaired:
            result.pop("repaired")
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TimingProvenance":
        return cls(**deepcopy(value))


def finite(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def interval_problem(start: float, end: float, duration: float,
                     *, allow_zero: bool = False) -> str:
    """Return the same interval diagnosis for all timing producers."""
    if not finite(duration) or duration <= 0:
        return "media duration must be finite and positive; re-run zing study"
    if not finite(start) or not finite(end):
        return "non-finite or non-numeric time"
    if start < 0 or end < 0:
        return "negative time"
    if end < start:
        return "negative duration"
    if end == start and not allow_zero:
        return "zero duration"
    if start > duration or end > duration:
        return f"time beyond media duration {duration:.3f}s"
    return ""


def clamp_interval(start: float, end: float, duration: float) -> tuple[float, float]:
    """Clamp an OCR observation to media; reject empty/non-finite results."""
    if not finite(start) or not finite(end):
        raise TimingReviewError("non-finite or non-numeric OCR interval")
    bounded = (max(0.0, start), min(end, duration))
    problem = interval_problem(*bounded, duration)
    if problem:
        raise TimingReviewError(problem)
    return bounded


def _review(word: Word, reason: str) -> TimingReviewError:
    def stamp(value: Any) -> str:
        return f"{value:.3f}" if finite(value) else repr(value)
    return TimingReviewError(
        f"timing review required: word {word.text!r} at "
        f"{stamp(word.start)}-{stamp(word.end)}s: {reason}. "
        "Review the audio and correct this word's source timestamps with "
        "timing.status='corrected', timing.method='user_correction' and the "
        "original measurement retained, then assemble again. For unresolved "
        "zero duration, optionally use --retry-word-timing-model LOCAL_DIRECTORY."
    )


def _provenance(word: Word) -> TimingProvenance:
    if word.timing is not None:
        try:
            timing = TimingProvenance.from_dict(word.timing)
            if timing.version != 1 or timing.status not in {"measured", "corrected"}:
                raise ValueError("unsupported timing provenance")
            if not timing.method or set(timing.original) != {"start", "end"}:
                raise ValueError("timing method/original measurement missing")
            return timing
        except (TypeError, ValueError) as exc:
            raise _review(word, f"invalid timing provenance: {exc}") from exc
    return TimingProvenance("measured", "source_transcript",
                            {"start": word.start, "end": word.end})


def transform_word(word: Word, start: float, end: float, method: str,
                   *, corrected: bool = True, **details: Any) -> Word:
    """Keep source measurements through repair, trim, and timeline mapping."""
    timing = _provenance(word)
    if corrected:
        timing.status = "corrected"
        timing.method = method
    timing.adjustments.append({
        "method": method, "from": {"start": word.start, "end": word.end},
        "to": {"start": start, "end": end}, **details,
    })
    return replace(word, start=start, end=end, timing=timing.to_dict())


# Retry returns source-coordinate words, never a replacement transcript.
WordRetry = Callable[[Word, float, float], list[Word]]


def prepare_words(words: list[Word], duration: float, *, repair: bool = True,
                  retry: WordRetry | None = None) -> tuple[list[Word], list[str]]:
    """Validate all words before selection; repair only isolated zero durations.

    Prefer a centered 40 ms interval, shifting it into adjacent unoccupied
    time when needed. Neither endpoint moves more than 40 ms. Never alter
    a neighbor, reorder the transcript, or remove a word. A retry is limited
    to one <=2s span per unresolved word, at most three spans per assembly.
    """
    problem = interval_problem(0, duration, duration)
    if problem:
        raise TimingReviewError(f"timing review required: {problem}")
    for index, word in enumerate(words):
        problem = interval_problem(word.start, word.end, duration, allow_zero=repair)
        if problem:
            raise _review(word, problem)
        if not isinstance(word.text, str) or not word.text.strip():
            raise _review(word, "empty word text")
        if index and word.start < words[index - 1].end - EPSILON:
            raise _review(word, f"out-of-order or overlapping word after {words[index - 1].text!r}")
    out = [replace(w, timing=_provenance(w).to_dict()) for w in words]
    notes: list[str] = []
    attempts = 0
    for index, word in enumerate(out):
        if word.end != word.start:
            continue
        previous_end = out[index - 1].end if index else 0.0
        next_start = out[index + 1].start if index + 1 < len(out) else duration
        low = max(previous_end, word.start - MIN_WORD_S)
        high = min(next_start, word.start + MIN_WORD_S)
        if high - low >= MIN_WORD_S - EPSILON:
            start = max(low, min(word.start - MIN_WORD_S / 2, high - MIN_WORD_S))
            out[index] = transform_word(word, start, min(high, start + MIN_WORD_S),
                                        "adjacent_silence_40ms")
        elif retry is not None and attempts < MAX_RETRY_WORDS:
            attempts += 1
            span_start = max(0.0, word.start - RETRY_RADIUS_S)
            span_end = min(duration, word.end + RETRY_RADIUS_S)
            try:
                candidates = retry(word, span_start, span_end)
            except Exception as exc:
                raise _review(word, f"bounded transcription retry failed: {exc}") from exc
            matches = [w for w in candidates if w.text.strip().casefold() == word.text.strip().casefold()]
            if len(matches) != 1:
                raise _review(word, "bounded retry did not return exactly one matching word; text retained")
            candidate = matches[0]
            problem = interval_problem(candidate.start, candidate.end, duration)
            if (problem or candidate.start < max(span_start, previous_end)
                    or candidate.end > min(span_end, next_start)):
                raise _review(word, "bounded retry returned invalid/overlapping timing; neighbors retained")
            out[index] = transform_word(word, candidate.start, candidate.end,
                                        "bounded_retranscription",
                                        span={"start": span_start, "end": span_end},
                                        retry_timing=deepcopy(candidate.timing))
        else:
            raise _review(word, "zero duration; no room for 40 ms without moving neighbors"
                          + ("; retry budget exhausted" if retry else ""))
        fixed = out[index]
        notes.append(f"corrected timing for {word.text!r}: {word.start:.3f}-{word.end:.3f}s "
                     f"-> {fixed.start:.3f}-{fixed.end:.3f}s ({fixed.timing['method']}); "
                     "original measurement retained")
    return out, notes
