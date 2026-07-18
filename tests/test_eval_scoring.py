from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from myzing.schemas import Breakdown
from tools.eval.scoring import levenshtein_similarity, normalize_caption, score


SAMPLE = Path(__file__).parents[1] / "tools" / "eval" / "sample"


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


def test_checked_in_sample_passes_and_speech_is_unavailable(
    truth: dict, breakdown: dict
) -> None:
    result = score_dict(truth, breakdown)

    assert result["passed"]
    assert result["audio"]["speech_ratio"]["available"] is False
    assert result["audio"]["speech_ratio"]["passed"] is None
    assert "tone is not speech" in result["audio"]["speech_ratio"]["reason"]


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
    ],
    ids=[
        "missing-cut",
        "shifted-cut",
        "missing-caption",
        "caption-outside-truth-window",
        "wrong-caption-text",
        "extra-caption",
        "wrong-audio-window",
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
