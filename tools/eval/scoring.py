"""Pure scoring for exact-by-construction eval fixtures."""

from __future__ import annotations

import bisect
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Sequence

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
    candidates: Sequence[tuple[int, int]],
    weight: Callable[[int, int], tuple[float, ...]],
) -> tuple[tuple[int, int], ...]:
    """Find a deterministic maximum-weight chronological matching.

    ``candidates`` lists every (truth_index, predicted_index) pair that is
    allowed to match, sorted by (truth_index, predicted_index). The result
    is the chain with strictly increasing indices on both sides whose
    componentwise sum of ``weight(i, j)`` tuples is lexicographically
    largest; every ``weight`` tuple must beat the empty tuple so a longer
    chain never loses to an empty one. Ties prefer the earliest candidates,
    keeping the matching deterministic.

    Iterative by design (F-12): an explicit choice table plus a Fenwick
    tree of prefix maxima over the predicted index, so real-video event
    counts can never hit Python's recursion limit. O(len(candidates) *
    log(predicted_count)) instead of the previous O(n * m) recursion.
    """
    if not candidates:
        return ()
    total = len(candidates)
    weights = [weight(i, j) for i, j in candidates]
    size = max(j for _, j in candidates) + 1
    # tree[position] covers a Fenwick range of predicted indices and holds
    # the best (chain value, candidate index) seen there; querying position
    # p returns the best chain ending at any predicted index < p.
    tree: list[tuple[tuple[float, ...], int] | None] = [None] * (size + 1)

    def push(position: int, value: tuple[float, ...], index: int) -> None:
        while position <= size:
            entry = tree[position]
            if entry is None or value > entry[0]:
                tree[position] = (value, index)
            position += position & -position

    def prefix_best(position: int) -> tuple[tuple[float, ...], int] | None:
        best: tuple[tuple[float, ...], int] | None = None
        while position > 0:
            entry = tree[position]
            if entry is not None and (
                best is None
                or entry[0] > best[0]
                or (entry[0] == best[0] and entry[1] < best[1])
            ):
                best = entry
            position -= position & -position
        return best

    values: list[tuple[float, ...]] = [()] * total
    parents = [-1] * total
    group_start = 0
    while group_start < total:
        # Process all candidates sharing one truth index as a group: they
        # query the tree before any of them is inserted, so a chain can
        # never reuse a truth event.
        group_end = group_start
        truth_index = candidates[group_start][0]
        while group_end < total and candidates[group_end][0] == truth_index:
            group_end += 1
        for index in range(group_start, group_end):
            predecessor = prefix_best(candidates[index][1])
            if predecessor is None:
                values[index] = weights[index]
            else:
                values[index] = tuple(
                    previous + step
                    for previous, step in zip(predecessor[0], weights[index])
                )
                parents[index] = predecessor[1]
        for index in range(group_start, group_end):
            push(candidates[index][1] + 1, values[index], index)
        group_start = group_end

    best_index = 0
    for index in range(1, total):
        if values[index] > values[best_index]:
            best_index = index
    chain: list[tuple[int, int]] = []
    index = best_index
    while index != -1:
        chain.append(candidates[index])
        index = parents[index]
    chain.reverse()
    return tuple(chain)


def _score_cuts(truth: dict[str, Any], breakdown: Breakdown) -> dict[str, Any]:
    tolerance = float(MANIFEST["cuts"]["time_tolerance_seconds"])
    pairing_window = float(
        MANIFEST["cuts"]["out_of_tolerance_pairing_window_seconds"]
    )
    truth_cuts = sorted(float(value) for value in truth.get("cuts", []))
    ordered_shots = sorted(
        breakdown.shots, key=lambda shot: (shot.start, shot.end, shot.index)
    )
    predicted_cuts = [float(shot.start) for shot in ordered_shots[1:]]

    # F-09 (C#3): a truth event may only ever pair with a RELATED prediction
    # — one inside the declared pairing window. One matching pass maximizes
    # (in-tolerance matches, then total related pairs, then closeness), so
    # near-miss pairs stay chronologically consistent with real matches and
    # everything unrelated is reported as missing/extra, never as a pair.
    candidates = [
        (i, j)
        for i, cut in enumerate(truth_cuts)
        for j in range(
            bisect.bisect_left(predicted_cuts, cut - pairing_window),
            bisect.bisect_right(predicted_cuts, cut + pairing_window),
        )
    ]
    pairs = _best_monotonic_pairs(
        candidates,
        lambda i, j: (
            1.0 if abs(truth_cuts[i] - predicted_cuts[j]) <= tolerance else 0.0,
            1.0,
            -abs(truth_cuts[i] - predicted_cuts[j]),
        ),
    )
    used_truth = {i for i, _ in pairs}
    used_predicted = {j for _, j in pairs}
    missing = [
        truth_cuts[i] for i in range(len(truth_cuts)) if i not in used_truth
    ]
    extra = [
        predicted_cuts[j]
        for j in range(len(predicted_cuts))
        if j not in used_predicted
    ]

    matches = [
        {
            "truth_seconds": truth_cuts[i],
            "predicted_seconds": predicted_cuts[j],
            "delta_seconds": round(predicted_cuts[j] - truth_cuts[i], 6),
            "within_tolerance": abs(truth_cuts[i] - predicted_cuts[j])
            <= tolerance,
        }
        for i, j in pairs
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
            "pairing_window_seconds": pairing_window,
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

    # Candidate pairs are exactly the temporally overlapping ones. The
    # running prefix maximum of predicted end times is monotone, so both
    # window edges can be found by bisection; candidates stay sorted by
    # (truth_index, predicted_index) as _best_monotonic_pairs requires.
    predicted_starts = [float(caption.start) for caption in predicted_captions]
    prefix_max_end: list[float] = []
    running_end = -math.inf
    for caption in predicted_captions:
        running_end = max(running_end, float(caption.end))
        prefix_max_end.append(running_end)
    candidates = [
        (i, j)
        for i, expected in enumerate(truth_captions)
        for j in range(
            bisect.bisect_right(prefix_max_end, float(expected["start"])),
            bisect.bisect_left(predicted_starts, float(expected["end"])),
        )
        if _positive_overlap(expected, predicted_captions[j]) > 0.0
    ]
    pairs = _best_monotonic_pairs(
        candidates,
        lambda i, j: (
            1.0,
            levenshtein_similarity(
                truth_captions[i]["text"], predicted_captions[j].text
            ),
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
