"""Pure scoring for exact-by-construction eval fixtures."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from myzing.schemas import Breakdown


MANIFEST_PATH = Path(__file__).with_name("manifest.json")
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def normalize_caption(text: str) -> str:
    """Normalize OCR text exactly as declared in the eval manifest."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    without_punctuation = "".join(
        " " if unicodedata.category(char).startswith("P") else char
        for char in normalized
    )
    return re.sub(r"\s+", " ", without_punctuation).strip()


def levenshtein_similarity(left: str, right: str) -> float:
    """Return edit similarity in [0, 1] after manifest normalization."""
    left = normalize_caption(left)
    right = normalize_caption(right)
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return 1.0 - previous[-1] / max(len(left), len(right))


def _best_monotonic_pairs(
    truth_count: int,
    predicted_count: int,
    allowed: Callable[[int, int], bool],
    quality: Callable[[int, int], float],
) -> tuple[tuple[int, int], ...]:
    """Find a deterministic maximum-cardinality chronological matching."""

    def rank(pairs: tuple[tuple[int, int], ...]) -> tuple[int, float, tuple]:
        return (
            len(pairs),
            round(sum(quality(i, j) for i, j in pairs), 12),
            tuple((-i, -j) for i, j in pairs),
        )

    @lru_cache(maxsize=None)
    def visit(i: int, j: int) -> tuple[tuple[int, int], ...]:
        if i >= truth_count or j >= predicted_count:
            return ()
        choices = [visit(i + 1, j), visit(i, j + 1)]
        if allowed(i, j):
            choices.append(((i, j),) + visit(i + 1, j + 1))
        return max(choices, key=rank)

    return visit(0, 0)


def _score_cuts(truth: dict[str, Any], breakdown: Breakdown) -> dict[str, Any]:
    tolerance = float(MANIFEST["cuts"]["time_tolerance_seconds"])
    truth_cuts = sorted(float(value) for value in truth.get("cuts", []))
    ordered_shots = sorted(
        breakdown.shots, key=lambda shot: (shot.start, shot.end, shot.index)
    )
    predicted_cuts = [float(shot.start) for shot in ordered_shots[1:]]

    in_tolerance = _best_monotonic_pairs(
        len(truth_cuts),
        len(predicted_cuts),
        lambda i, j: abs(truth_cuts[i] - predicted_cuts[j]) <= tolerance,
        lambda i, j: -abs(truth_cuts[i] - predicted_cuts[j]),
    )
    used_truth = {i for i, _ in in_tolerance}
    used_predicted = {j for _, j in in_tolerance}
    unmatched_truth = [i for i in range(len(truth_cuts)) if i not in used_truth]
    unmatched_predicted = [
        j for j in range(len(predicted_cuts)) if j not in used_predicted
    ]

    out_of_tolerance = list(zip(unmatched_truth, unmatched_predicted))
    paired_truth = used_truth | {i for i, _ in out_of_tolerance}
    paired_predicted = used_predicted | {j for _, j in out_of_tolerance}
    missing = [truth_cuts[i] for i in range(len(truth_cuts)) if i not in paired_truth]
    extra = [
        predicted_cuts[j]
        for j in range(len(predicted_cuts))
        if j not in paired_predicted
    ]

    all_pairs = sorted(
        [(i, j, True) for i, j in in_tolerance]
        + [(i, j, False) for i, j in out_of_tolerance]
    )
    matches = [
        {
            "truth_seconds": truth_cuts[i],
            "predicted_seconds": predicted_cuts[j],
            "delta_seconds": round(predicted_cuts[j] - truth_cuts[i], 6),
            "within_tolerance": within_tolerance,
        }
        for i, j, within_tolerance in all_pairs
    ]
    count_passed = len(truth_cuts) == len(predicted_cuts)
    timing_passed = (
        not missing
        and not extra
        and all(match["within_tolerance"] for match in matches)
    )
    return {
        "passed": count_passed and timing_passed,
        "count": {
            "passed": count_passed,
            "truth": len(truth_cuts),
            "predicted": len(predicted_cuts),
        },
        "timing": {
            "passed": timing_passed,
            "tolerance_seconds": tolerance,
            "matches": matches,
            "missing_seconds": missing,
            "extra_seconds": extra,
        },
    }


def _positive_overlap(left: dict[str, Any], right: Any) -> float:
    return max(
        0.0,
        min(float(left["end"]), float(right.end))
        - max(float(left["start"]), float(right.start)),
    )


def _score_captions(truth: dict[str, Any], breakdown: Breakdown) -> dict[str, Any]:
    threshold = float(MANIFEST["captions"]["minimum_text_similarity"])
    truth_captions = sorted(
        truth.get("captions", []),
        key=lambda caption: (caption["start"], caption["end"], caption["text"]),
    )
    predicted_captions = sorted(
        breakdown.captions,
        key=lambda caption: (caption.start, caption.end, caption.text),
    )

    pairs = _best_monotonic_pairs(
        len(truth_captions),
        len(predicted_captions),
        lambda i, j: _positive_overlap(
            truth_captions[i], predicted_captions[j]
        )
        > 0.0,
        lambda i, j: levenshtein_similarity(
            truth_captions[i]["text"], predicted_captions[j].text
        ),
    )
    used_truth = {i for i, _ in pairs}
    used_predicted = {j for _, j in pairs}
    matches = []
    for truth_index, predicted_index in pairs:
        expected = truth_captions[truth_index]
        actual = predicted_captions[predicted_index]
        similarity = levenshtein_similarity(expected["text"], actual.text)
        matches.append(
            {
                "truth_text": expected["text"],
                "predicted_text": actual.text,
                "truth_start": float(expected["start"]),
                "truth_end": float(expected["end"]),
                "predicted_start": float(actual.start),
                "predicted_end": float(actual.end),
                "start_delta_seconds": round(
                    float(actual.start) - float(expected["start"]), 6
                ),
                "end_delta_seconds": round(
                    float(actual.end) - float(expected["end"]), 6
                ),
                "overlap_seconds": round(_positive_overlap(expected, actual), 6),
                "similarity": round(similarity, 6),
                "similarity_passed": similarity >= threshold,
            }
        )

    missed = [
        truth_captions[i]
        for i in range(len(truth_captions))
        if i not in used_truth
    ]
    extras = [
        {
            "text": predicted_captions[j].text,
            "start": predicted_captions[j].start,
            "end": predicted_captions[j].end,
        }
        for j in range(len(predicted_captions))
        if j not in used_predicted
    ]
    recall = len(pairs) / len(truth_captions) if truth_captions else 1.0
    precision = len(pairs) / len(predicted_captions) if predicted_captions else 1.0
    recall_passed = not missed
    similarity_passed = all(match["similarity_passed"] for match in matches)
    extras_passed = not extras
    return {
        "passed": recall_passed and similarity_passed and extras_passed,
        "recall": {
            "passed": recall_passed,
            "value": round(recall, 6),
            "matched": len(pairs),
            "truth": len(truth_captions),
            "missed": missed,
        },
        "similarity": {
            "passed": similarity_passed,
            "minimum": threshold,
            "matches": matches,
        },
        "extras": {
            "passed": extras_passed,
            "precision": round(precision, 6),
            "events": extras,
        },
    }


def _expected_signal(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value in {"signal", "silence"}:
        return value == "signal"
    raise ValueError(f"invalid audio window label: {value!r}")


def _score_audio(truth: dict[str, Any], breakdown: Breakdown) -> dict[str, Any]:
    audio_truth = truth.get("audio", {})
    expected = [_expected_signal(value) for value in audio_truth.get("windows", [])]
    signal_floor = float(MANIFEST["audio"]["signal_floor_dbfs"])
    predicted = [
        math.isfinite(float(value)) and float(value) > signal_floor
        for value in breakdown.audio.loudness_curve
    ]
    window_rows = [
        {
            "index": index,
            "expected": "signal" if expected_value else "silence",
            "predicted_dbfs": (
                float(breakdown.audio.loudness_curve[index])
                if index < len(breakdown.audio.loudness_curve)
                else None
            ),
            "predicted": (
                "signal"
                if index < len(predicted) and predicted[index]
                else "silence"
            ),
            "passed": index < len(predicted)
            and expected_value == predicted[index],
        }
        for index, expected_value in enumerate(expected)
    ]
    window_passed = len(expected) == len(predicted) and all(
        row["passed"] for row in window_rows
    )

    speech_config = MANIFEST["audio"]["speech_ratio"]
    expected_ratio = audio_truth.get("speech_ratio")
    speech_available = bool(speech_config["enabled"] and expected_ratio is not None)
    if speech_available:
        delta = float(breakdown.audio.speech_ratio) - float(expected_ratio)
        speech_passed: bool | None = abs(delta) <= float(speech_config["tolerance"])
    else:
        delta = None
        speech_passed = None

    return {
        "passed": window_passed and (speech_passed is not False),
        "window_pattern": {
            "passed": window_passed,
            "signal_floor_dbfs": signal_floor,
            "expected_count": len(expected),
            "predicted_count": len(predicted),
            "windows": window_rows,
            "extra_dbfs": [
                float(value)
                for value in breakdown.audio.loudness_curve[len(expected) :]
            ],
        },
        "speech_ratio": {
            "available": speech_available,
            "passed": speech_passed,
            "tolerance": float(speech_config["tolerance"]),
            "truth": expected_ratio,
            "predicted": breakdown.audio.speech_ratio,
            "delta": delta,
            "reason": None if speech_available else speech_config["reason"],
        },
    }


def score(truth: dict[str, Any], breakdown: Breakdown) -> dict[str, Any]:
    """Score one truth manifest against one Breakdown without side effects."""
    cuts = _score_cuts(truth, breakdown)
    captions = _score_captions(truth, breakdown)
    audio = _score_audio(truth, breakdown)
    return {
        "scorer_version": MANIFEST["scorer_version"],
        "fixture_id": truth.get("fixture_id", "unknown"),
        "passed": cuts["passed"] and captions["passed"] and audio["passed"],
        "cuts": cuts,
        "captions": captions,
        "audio": audio,
    }
