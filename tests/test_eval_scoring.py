from __future__ import annotations

import copy
import itertools
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from myzing.schemas import Breakdown, CaptionEvent, Shot, VideoMeta
from tools.eval.scoring import (
    _best_monotonic_pairs,
    levenshtein_similarity,
    normalize_caption,
    score,
)


SAMPLE = ROOT / "tools" / "eval" / "sample"


def _truth_for_cuts(cuts: list[float]) -> dict:
    return {
        "fixture_id": "synthetic-cuts",
        "cuts": cuts,
        "captions": [],
        "audio": {"windows": []},
    }


def _breakdown_for_cuts(predicted_cuts: list[float]) -> Breakdown:
    bounds = [0.0] + list(predicted_cuts) + [predicted_cuts[-1] + 1.0]
    return Breakdown(
        meta=VideoMeta(source_url="synthetic://cuts", platform="file"),
        shots=[
            Shot(index=index, start=bounds[index], end=bounds[index + 1])
            for index in range(len(bounds) - 1)
        ],
    )


@pytest.fixture
def truth() -> dict:
    return json.loads((SAMPLE / "truth.json").read_text(encoding="utf-8"))


@pytest.fixture
def breakdown() -> dict:
    return json.loads((SAMPLE / "breakdown.json").read_text(encoding="utf-8"))


def score_dict(truth: dict, breakdown: dict) -> dict:
    return score(truth, Breakdown.from_dict(breakdown))


def test_caption_normalization_is_explicit() -> None:
    assert normalize_caption("  HéLLo，\tZING!!! ") == "héllo zing"
    assert levenshtein_similarity("Hello, Zing!", "hello zing") == 1.0


def test_checked_in_sample_passes_with_speech_ratio_scoring(
    truth: dict, breakdown: dict
) -> None:
    result = score_dict(truth, breakdown)

    assert result["passed"]
    assert result["audio"]["speech_ratio"]["available"] is True
    assert result["audio"]["speech_ratio"]["passed"] is True
    assert result["audio"]["speech_ratio"]["truth"] == pytest.approx(2 / 3, abs=0.001)


@pytest.mark.parametrize(
    ("mutation", "target", "healthy"),
    [
        (
            lambda value: value["shots"].pop(),
            ("cuts", "count"),
            ("captions", "audio"),
        ),
        (
            lambda value: value["shots"][1].update(start=1.2),
            ("cuts", "timing"),
            ("captions", "audio"),
        ),
        (
            lambda value: value["captions"].clear(),
            ("captions", "recall"),
            ("cuts", "audio"),
        ),
        (
            lambda value: value["captions"][0].update(start=2.0, end=2.5),
            ("captions", "recall"),
            ("cuts", "audio"),
        ),
        (
            lambda value: value["captions"][0].update(text="unrelated words"),
            ("captions", "similarity"),
            ("cuts", "audio"),
        ),
        (
            lambda value: value["captions"].append(
                {
                    "text": "extra",
                    "start": 0.5,
                    "end": 1.0,
                    "position": "center",
                    "all_caps": False,
                    "words_visible": 1,
                    "confidence": 1.0,
                }
            ),
            ("captions", "extras"),
            ("cuts", "audio"),
        ),
        (
            lambda value: value["audio"]["loudness_curve"].__setitem__(1, -10.0),
            ("audio", "window_pattern"),
            ("cuts", "captions"),
        ),
        (
            lambda value: value["audio"].update(speech_ratio=0.3),
            ("audio", "speech_ratio"),
            ("cuts", "captions"),
        ),
    ],
    ids=[
        "missing-cut",
        "shifted-cut",
        "missing-caption",
        "caption-outside-truth-window",
        "wrong-caption-text",
        "extra-caption",
        "wrong-audio-window",
        "wrong-speech-ratio",
    ],
)
def test_fault_matrix_is_sensitive_and_isolated(
    truth: dict,
    breakdown: dict,
    mutation,
    target: tuple[str, str],
    healthy: tuple[str, ...],
) -> None:
    broken = copy.deepcopy(breakdown)
    mutation(broken)

    result = score_dict(truth, broken)

    assert result["passed"] is False
    assert result[target[0]][target[1]]["passed"] is False
    for family in healthy:
        assert result[family]["passed"] is True


def test_cut_matching_does_not_reuse_truth_event(
    truth: dict, breakdown: dict
) -> None:
    breakdown["shots"].insert(
        2,
        {
            "index": 99,
            "start": 1.04,
            "end": 1.2,
            "keyframe": "",
        },
    )

    result = score_dict(truth, breakdown)

    assert result["cuts"]["count"]["passed"] is False
    assert result["cuts"]["timing"]["extra_seconds"] == [1.04]


def test_caption_below_similarity_threshold_fails(
    truth: dict, breakdown: dict
) -> None:
    breakdown["captions"][0]["text"] = "hello sing"

    result = score_dict(truth, breakdown)

    assert result["captions"]["similarity"]["matches"][0]["similarity"] == 0.9
    assert result["captions"]["similarity"]["passed"] is True

    breakdown["captions"][0]["text"] = "goodbye"
    result = score_dict(truth, breakdown)
    assert result["captions"]["similarity"]["passed"] is False


# --- F-09: missing/extra/out-of-tolerance reported strictly separately ----


def test_leftover_cuts_report_missing_and_extra_never_fabricated_pairs() -> None:
    """F-09 (C#3): unrelated leftovers must never be zipped into 'matches'.

    Truth [1.0, 2.0] vs predicted [1.0, 5.0]: truth 2.0 is MISSING and
    predicted 5.0 is EXTRA — the report must never claim truth 2.0 was
    "matched" to predicted 5.0 with a 3-second delta.
    """
    result = score(_truth_for_cuts([1.0, 2.0]), _breakdown_for_cuts([1.0, 5.0]))

    timing = result["cuts"]["timing"]
    assert result["cuts"]["count"]["passed"] is True
    assert timing["passed"] is False
    assert timing["missing_seconds"] == [2.0]
    assert timing["extra_seconds"] == [5.0]
    assert [
        (match["truth_seconds"], match["predicted_seconds"], match["within_tolerance"])
        for match in timing["matches"]
    ] == [(1.0, 1.0, True)]


def test_near_miss_cut_is_a_real_out_of_tolerance_match() -> None:
    """A prediction just past the tolerance window is still a related event:
    it stays a (single) out-of-tolerance match inside the declared pairing
    window, not a missing+extra split."""
    result = score(_truth_for_cuts([1.0, 2.0]), _breakdown_for_cuts([1.0, 2.2]))

    timing = result["cuts"]["timing"]
    assert timing["pairing_window_seconds"] == pytest.approx(0.3)
    assert timing["passed"] is False
    assert timing["missing_seconds"] == []
    assert timing["extra_seconds"] == []
    assert [
        (match["truth_seconds"], match["predicted_seconds"], match["within_tolerance"])
        for match in timing["matches"]
    ] == [(1.0, 1.0, True), (2.0, 2.2, False)]
    assert timing["matches"][1]["delta_seconds"] == pytest.approx(0.2)


def test_out_of_tolerance_pairing_never_crosses_in_tolerance_matches() -> None:
    """Near-miss pairing must stay chronologically consistent with the
    in-tolerance matching — no crossed pairs in the per-event report."""
    result = score(_truth_for_cuts([1.0, 1.2]), _breakdown_for_cuts([1.18, 1.3]))

    timing = result["cuts"]["timing"]
    assert timing["missing_seconds"] == []
    assert timing["extra_seconds"] == []
    assert [
        (match["truth_seconds"], match["predicted_seconds"], match["within_tolerance"])
        for match in timing["matches"]
    ] == [(1.0, 1.18, False), (1.2, 1.3, True)]


def test_scorer_version_bumped_for_pairing_semantics_change() -> None:
    result = score(_truth_for_cuts([1.0]), _breakdown_for_cuts([1.0]))

    assert result["scorer_version"] == "1.3.0"


# --- F-12: matcher must survive real-video event counts (iterative) -------


def test_cut_scoring_survives_real_video_scale() -> None:
    """F-12: 5000 truth + 5000 predicted cuts (10000 events) must score
    without hitting Python's recursion limit."""
    truth_cuts = [float(second) for second in range(1, 5001)]
    predicted_cuts = [second + 0.05 for second in truth_cuts]

    result = score(_truth_for_cuts(truth_cuts), _breakdown_for_cuts(predicted_cuts))

    assert result["cuts"]["passed"] is True
    assert len(result["cuts"]["timing"]["matches"]) == 5000
    assert all(
        match["within_tolerance"] for match in result["cuts"]["timing"]["matches"]
    )


def test_cut_scoring_at_scale_still_reports_leftovers_honestly() -> None:
    truth_cuts = [float(second) for second in range(1, 601)]
    predicted_cuts = [
        second + 0.05 for second in truth_cuts if second != 300.0
    ] + [650.5]

    result = score(_truth_for_cuts(truth_cuts), _breakdown_for_cuts(predicted_cuts))

    timing = result["cuts"]["timing"]
    assert result["cuts"]["count"]["passed"] is True
    assert timing["passed"] is False
    assert timing["missing_seconds"] == [300.0]
    assert timing["extra_seconds"] == [650.5]
    assert len(timing["matches"]) == 599


def test_caption_scoring_survives_real_video_scale() -> None:
    """F-12: caption-per-word density (2500 truth + 2500 predicted events)."""
    truth = {
        "fixture_id": "synthetic-captions",
        "cuts": [],
        "captions": [
            {"text": f"caption {index}", "start": float(index), "end": index + 0.8}
            for index in range(2500)
        ],
        "audio": {"windows": []},
    }
    breakdown = Breakdown(
        meta=VideoMeta(source_url="synthetic://captions", platform="file"),
        captions=[
            CaptionEvent(
                text=f"caption {index}",
                start=index + 0.05,
                end=index + 0.85,
            )
            for index in range(2500)
        ],
    )

    result = score(truth, breakdown)

    assert result["captions"]["passed"] is True
    assert result["captions"]["recall"]["matched"] == 2500


def test_iterative_matcher_agrees_with_brute_force_on_random_cases() -> None:
    """The Fenwick-table matcher must achieve exactly the brute-force-optimal
    summed weight over strictly-increasing chains, deterministically."""
    rng = random.Random(20260718)
    for _ in range(30):
        truth_count = rng.randint(1, 4)
        predicted_count = rng.randint(1, 4)
        candidates = [
            (i, j)
            for i in range(truth_count)
            for j in range(predicted_count)
            if rng.random() < 0.6
        ]
        qualities = {pair: round(rng.uniform(-1.0, 1.0), 3) for pair in candidates}

        def weight(i: int, j: int) -> tuple[float, ...]:
            return (1.0, qualities[(i, j)])

        chain = _best_monotonic_pairs(candidates, weight)

        assert all(pair in candidates for pair in chain)
        assert all(
            a[0] < b[0] and a[1] < b[1] for a, b in zip(chain, chain[1:])
        )
        achieved = (
            tuple(sum(column) for column in zip(*(weight(i, j) for i, j in chain)))
            if chain
            else None
        )
        best = None
        max_len = min(truth_count, predicted_count)
        for size in range(1, max_len + 1):
            for combo in itertools.combinations(candidates, size):
                if any(
                    a[0] >= b[0] or a[1] >= b[1]
                    for a, b in zip(combo, combo[1:])
                ):
                    continue
                value = tuple(
                    sum(column)
                    for column in zip(*(weight(i, j) for i, j in combo))
                )
                if best is None or value > best:
                    best = value
        assert achieved == best
