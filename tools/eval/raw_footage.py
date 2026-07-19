"""Pure scoring for exact raw-footage measurement fixtures."""

from __future__ import annotations

from typing import Any, Sequence

from .scoring import MANIFEST, _best_monotonic_pairs, normalize_caption


RAW_CONFIG = MANIFEST["raw_footage"]


def _ordered(
    events: Sequence[dict[str, Any]],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda event: tuple(float(event[field]) for field in fields),
    )


def _match_events(
    expected: list[dict[str, Any]],
    predicted: list[dict[str, Any]],
    fields: Sequence[str],
) -> tuple[tuple[int, int], ...]:
    pairing_window = float(RAW_CONFIG["pairing_window_seconds"])
    candidates = [
        (truth_index, predicted_index)
        for truth_index, truth_event in enumerate(expected)
        for predicted_index, predicted_event in enumerate(predicted)
        if max(
            abs(
                float(predicted_event[field])
                - float(truth_event[field])
            )
            for field in fields
        )
        <= pairing_window
    ]
    return _best_monotonic_pairs(
        candidates,
        lambda truth_index, predicted_index: (
            1.0,
            -sum(
                abs(
                    float(predicted[predicted_index][field])
                    - float(expected[truth_index][field])
                )
                for field in fields
            ),
        ),
    )


def _timing_score(
    expected_events: Sequence[dict[str, Any]],
    predicted_events: Sequence[dict[str, Any]],
    fields: Sequence[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    expected = _ordered(expected_events, fields)
    predicted = _ordered(predicted_events, fields)
    pairs = _match_events(expected, predicted, fields)
    used_expected = {truth_index for truth_index, _ in pairs}
    used_predicted = {predicted_index for _, predicted_index in pairs}
    tolerance = float(RAW_CONFIG["time_tolerance_seconds"])
    matches = []
    for truth_index, predicted_index in pairs:
        truth_event = expected[truth_index]
        predicted_event = predicted[predicted_index]
        deltas = {
            field: round(
                float(predicted_event[field])
                - float(truth_event[field]),
                6,
            )
            for field in fields
        }
        matches.append(
            {
                "truth": truth_event,
                "predicted": predicted_event,
                "deltas_seconds": deltas,
                "within_tolerance": all(
                    abs(delta) <= tolerance for delta in deltas.values()
                ),
            }
        )
    missing = [
        expected[index]
        for index in range(len(expected))
        if index not in used_expected
    ]
    extra = [
        predicted[index]
        for index in range(len(predicted))
        if index not in used_predicted
    ]
    count_passed = len(expected) == len(predicted)
    timing_passed = (
        not missing
        and not extra
        and all(match["within_tolerance"] for match in matches)
    )
    return (
        {
            "passed": count_passed and timing_passed,
            "count": {
                "passed": count_passed,
                "truth": len(expected),
                "predicted": len(predicted),
            },
            "timing": {
                "passed": timing_passed,
                "tolerance_seconds": tolerance,
                "pairing_window_seconds": float(
                    RAW_CONFIG["pairing_window_seconds"]
                ),
                "matches": matches,
                "missing": missing,
                "extra": extra,
            },
        },
        matches,
    )


def _score_dead_air(
    expected: Sequence[dict[str, Any]],
    predicted: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    result, _ = _timing_score(
        expected,
        predicted,
        ("start", "end"),
    )
    return result


def _score_filler_words(
    expected: Sequence[dict[str, Any]],
    predicted: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    result, matches = _timing_score(
        expected,
        predicted,
        ("start",),
    )
    identity_rows = [
        {
            "truth": match["truth"]["word"],
            "predicted": match["predicted"]["word"],
            "passed": normalize_caption(match["truth"]["word"])
            == normalize_caption(match["predicted"]["word"]),
        }
        for match in matches
    ]
    identity_passed = (
        not result["timing"]["missing"]
        and not result["timing"]["extra"]
        and all(row["passed"] for row in identity_rows)
    )
    result["identity"] = {
        "passed": identity_passed,
        "matches": identity_rows,
    }
    result["passed"] = result["passed"] and identity_passed
    return result


def _score_repeated_takes(
    expected: Sequence[dict[str, Any]],
    predicted: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    result, matches = _timing_score(
        expected,
        predicted,
        ("first_start", "first_end", "second_start", "second_end"),
    )
    minimum = float(RAW_CONFIG["repeated_take_minimum_similarity"])
    similarity_rows = [
        {
            "truth": float(match["truth"]["similarity"]),
            "predicted": float(match["predicted"]["similarity"]),
            "minimum": minimum,
            "passed": float(match["predicted"]["similarity"]) >= minimum,
        }
        for match in matches
    ]
    similarity_passed = (
        not result["timing"]["missing"]
        and not result["timing"]["extra"]
        and all(row["passed"] for row in similarity_rows)
    )
    result["similarity"] = {
        "passed": similarity_passed,
        "minimum": minimum,
        "matches": similarity_rows,
    }
    result["passed"] = result["passed"] and similarity_passed
    return result


def score_raw_footage(
    truth: dict[str, Any],
    measurement: dict[str, Any],
) -> dict[str, Any]:
    """Score raw-footage observations without depending on a schema field."""
    expected = truth.get("raw_footage")
    if not isinstance(expected, dict):
        raise ValueError("raw-footage truth is missing raw_footage")
    if not isinstance(measurement, dict):
        raise ValueError("raw-footage measurement must be an object")

    dead_air = _score_dead_air(
        expected.get("dead_air_spans", []),
        measurement.get("dead_air_spans", []),
    )
    filler_words = _score_filler_words(
        expected.get("filler_words", []),
        measurement.get("filler_words", []),
    )
    repeated_takes = _score_repeated_takes(
        expected.get("repeated_takes", []),
        measurement.get("repeated_takes", []),
    )
    return {
        "scorer_version": MANIFEST["scorer_version"],
        "fixture_id": truth.get("fixture_id", "unknown"),
        "passed": (
            dead_air["passed"]
            and filler_words["passed"]
            and repeated_takes["passed"]
        ),
        "dead_air": dead_air,
        "filler_words": filler_words,
        "repeated_takes": repeated_takes,
    }


def measurement_from_raw_result(result: Any) -> dict[str, Any]:
    """Adapt Lane A's internal RawResult without claiming a schema field."""
    return {
        "dead_air_spans": [
            {"start": span.start, "end": span.end}
            for span in result.dead_air
        ],
        "filler_words": [
            {"word": word, "start": start}
            for word, start in result.filler_locations
        ],
        "repeated_takes": [
            {
                "first_start": take.first_start,
                "first_end": take.first_end,
                "second_start": take.second_start,
                "second_end": take.second_end,
                "similarity": take.similarity,
            }
            for take in result.repeated_takes
        ],
    }
