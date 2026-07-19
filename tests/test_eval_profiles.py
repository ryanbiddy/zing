"""Sprint 2 profile evaluation: exact aggregates and isolated mutations."""

from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from myzing.schemas import Breakdown, StatSummary, StyleProfile
from tools.eval.profile_scoring import (
    PROFILE_DIMENSIONS,
    evaluate_profile_cases,
    score_profile,
)
from tools.eval.run import (
    SAMPLE_DIRECTORY,
    evaluate,
    profile_builder_adapter,
)

PROFILE_CASE = (
    ROOT / "tools" / "eval" / "profiles" / "synthetic-constructed"
)
PROFILE_CASES = ROOT / "tools" / "eval" / "profiles"


def _stat(
    median: float = 20.0,
    p25: float = 10.0,
    p75: float = 30.0,
    n: int = 5,
) -> StatSummary:
    return StatSummary(median=median, p25=p25, p75=p75, n=n)


def _profile() -> StyleProfile:
    return StyleProfile(
        name="constructed-taste",
        source_slugs=[f"synthetic-{index}" for index in range(5)],
        genre="talking-head",
        platform="youtube",
        duration=_stat(30.0, 20.0, 40.0),
        shot_duration=_stat(2.0, 1.5, 2.5),
        cuts_per_10s_curve=[
            _stat(4.0, 3.0, 5.0),
            _stat(2.0, 1.0, 3.0, n=4),
        ],
        time_to_first_cut=_stat(1.0, 0.5, 1.5),
        time_to_first_word=_stat(0.4, 0.2, 0.6),
        time_to_first_caption=_stat(0.7, 0.5, 0.9, n=4),
        caption_all_caps_rate=0.6,
        caption_words_visible_mode=2,
        speech_ratio=_stat(0.55, 0.4, 0.7),
        music_present_rate=0.4,
        transition_kind_counts={"hard_cut": 8, "dissolve": 2},
        judged={"study": {"hook_type": "question"}},
        unjudged_source_slugs=["synthetic-4"],
        warnings=["synthetic-4: captions unavailable"],
        provenance={"builder_version": "test"},
    )


def _constructed_summary(values: list[float]) -> StatSummary:
    """Quartiles are unambiguous for the fixture's duplicated outer ranks."""
    ordered = sorted(values)
    assert len(ordered) == 5
    return StatSummary(
        median=ordered[2],
        p25=ordered[1],
        p75=ordered[3],
        n=5,
    )


def test_synthetic_breakdowns_have_exact_hand_constructed_aggregates() -> None:
    expected = StyleProfile.from_json(
        (PROFILE_CASE / "expected-profile.json").read_text(encoding="utf-8")
    )
    breakdowns = [
        Breakdown.from_json(
            (
                PROFILE_CASE / "breakdowns" / slug / "breakdown.json"
            ).read_text(encoding="utf-8")
        )
        for slug in expected.source_slugs
    ]

    assert expected.duration == _constructed_summary(
        [breakdown.meta.duration for breakdown in breakdowns]
    )
    assert expected.shot_duration == _constructed_summary(
        [breakdown.avg_shot_duration for breakdown in breakdowns]
    )
    assert expected.time_to_first_cut == _constructed_summary(
        [breakdown.shots[1].start for breakdown in breakdowns]
    )
    assert expected.time_to_first_word == _constructed_summary(
        [breakdown.words[0].start for breakdown in breakdowns]
    )
    assert expected.time_to_first_caption == _constructed_summary(
        [breakdown.captions[0].start for breakdown in breakdowns]
    )
    assert expected.speech_ratio == _constructed_summary(
        [breakdown.audio.speech_ratio for breakdown in breakdowns]
    )
    captions = [
        caption for breakdown in breakdowns for caption in breakdown.captions
    ]
    assert expected.caption_all_caps_rate == (
        sum(caption.all_caps for caption in captions) / len(captions)
    )
    assert expected.caption_words_visible_mode == 2
    assert expected.music_present_rate == (
        sum(breakdown.audio.has_music for breakdown in breakdowns)
        / len(breakdowns)
    )
    assert expected.transition_kind_counts == dict(
        Counter(
            transition.kind
            for breakdown in breakdowns
            for transition in breakdown.transitions
        )
    )

    normalized_curves = []
    for breakdown in breakdowns:
        buckets = [0.0] * 10
        for shot in breakdown.shots[1:]:
            bucket = min(
                int(shot.start / breakdown.meta.duration * 10),
                9,
            )
            buckets[bucket] += 1.0
        normalized_curves.append(buckets)
    assert expected.cuts_per_10s_curve == [
        _constructed_summary([curve[index] for curve in normalized_curves])
        for index in range(10)
    ]


def test_lane_a_builder_matches_synthetic_and_real_frozen_profiles() -> None:
    cases = sorted(
        path
        for path in PROFILE_CASES.iterdir()
        if (path / "expected-profile.json").is_file()
    )

    result = evaluate_profile_cases(cases, builder=profile_builder_adapter)

    assert result["available"] is True
    assert result["passed"] is True
    assert result["case_count"] == 2
    by_id = {case["fixture_id"]: case for case in result["cases"]}
    assert set(by_id) == {"synthetic-constructed", "real-frozen"}
    assert len(by_id["real-frozen"]["fixture_hashes"]) == 7
    assert all(
        case["score"]["failed_dimensions"] == [] for case in result["cases"]
    )


def _mutate_stat(
    profile: StyleProfile,
    field: str,
    component: str,
) -> None:
    stat = getattr(profile, field)
    setattr(stat, component, getattr(stat, component) + 1)


@pytest.mark.parametrize(
    ("dimension", "mutate"),
    [
        (
            "duration",
            lambda profile: _mutate_stat(profile, "duration", "median"),
        ),
        (
            "shot_duration",
            lambda profile: _mutate_stat(
                profile,
                "shot_duration",
                "p25",
            ),
        ),
        (
            "cuts_per_10s_curve",
            lambda profile: setattr(
                profile.cuts_per_10s_curve[1],
                "n",
                profile.cuts_per_10s_curve[1].n + 1,
            ),
        ),
        (
            "time_to_first_cut",
            lambda profile: _mutate_stat(
                profile,
                "time_to_first_cut",
                "p75",
            ),
        ),
        (
            "time_to_first_word",
            lambda profile: _mutate_stat(
                profile,
                "time_to_first_word",
                "n",
            ),
        ),
        (
            "time_to_first_caption",
            lambda profile: _mutate_stat(
                profile,
                "time_to_first_caption",
                "median",
            ),
        ),
        (
            "caption_all_caps_rate",
            lambda profile: setattr(profile, "caption_all_caps_rate", 0.2),
        ),
        (
            "caption_words_visible_mode",
            lambda profile: setattr(profile, "caption_words_visible_mode", 3),
        ),
        (
            "speech_ratio",
            lambda profile: _mutate_stat(
                profile,
                "speech_ratio",
                "p25",
            ),
        ),
        (
            "music_present_rate",
            lambda profile: setattr(profile, "music_present_rate", 0.8),
        ),
        (
            "transition_kind_counts",
            lambda profile: profile.transition_kind_counts.update(wipe=1),
        ),
    ],
)
def test_profile_mutation_matrix_is_sensitive_and_per_dimension(
    dimension: str,
    mutate,
) -> None:
    expected = _profile()
    actual = copy.deepcopy(expected)
    mutate(actual)

    result = score_profile(expected, actual, fixture_id="constructed")

    assert tuple(result["dimensions"]) == PROFILE_DIMENSIONS
    assert result["passed"] is False
    assert result["failed_dimensions"] == [dimension]
    assert result["dimensions"][dimension]["passed"] is False
    assert [
        name
        for name, detail in result["dimensions"].items()
        if detail["passed"]
    ] == [name for name in PROFILE_DIMENSIONS if name != dimension]


def test_profile_scorer_does_not_score_judged_or_provenance_fields() -> None:
    expected = _profile()
    actual = copy.deepcopy(expected)
    actual.judged = {"study": {"hook_type": "cold-open"}}
    actual.warnings.append("different coverage wording")
    actual.provenance = {"builder_version": "other"}

    result = score_profile(expected, actual, fixture_id="measured-only")

    assert result["passed"] is True
    assert result["not_scored"] == [
        "name",
        "source_slugs",
        "genre",
        "platform",
        "judged",
        "unjudged_source_slugs",
        "warnings",
        "provenance",
        "schema_version",
    ]


def test_eval_report_includes_profile_results(tmp_path: Path) -> None:
    profile_case = tmp_path / "profile-case"
    profile_case.mkdir()
    expected = _profile()
    (profile_case / "expected-profile.json").write_text(
        expected.to_json(indent=2) + "\n",
        encoding="utf-8",
    )
    for slug in expected.source_slugs:
        breakdown_path = (
            profile_case / "breakdowns" / slug / "breakdown.json"
        )
        breakdown_path.parent.mkdir(parents=True)
        breakdown_path.write_text("{}\n", encoding="utf-8")

    def builder(
        name: str,
        slugs: list[str],
        workspace: Path,
    ) -> StyleProfile:
        assert name == expected.name
        assert slugs == expected.source_slugs
        assert workspace != profile_case
        assert workspace.name.startswith("zing-profile-eval-profile-case-")
        return copy.deepcopy(expected)

    report_path = tmp_path / "eval-report.json"
    report = evaluate(
        [SAMPLE_DIRECTORY],
        report_path,
        ffmpeg="not-installed-ffmpeg",
        profile_case_directories=[profile_case],
        profile_builder=builder,
    )

    assert report["report_schema_version"] == 6
    assert report["passed"] is True
    assert report["profile_eval"]["available"] is True
    assert report["profile_eval"]["passed"] is True
    assert report["profile_eval"]["case_count"] == 1
    case = report["profile_eval"]["cases"][0]
    assert case["fixture_id"] == "profile-case"
    assert case["score"]["failed_dimensions"] == []
    assert len(case["fixture_hashes"]["expected-profile.json"]) == 64
    assert (
        json.loads(report_path.read_text(encoding="utf-8"))["profile_eval"]
        == report["profile_eval"]
    )


def test_profile_failure_gates_report_without_cross_failing_breakdown(
    tmp_path: Path,
) -> None:
    profile_case = tmp_path / "mutated-profile"
    profile_case.mkdir()
    expected = _profile()
    (profile_case / "expected-profile.json").write_text(
        expected.to_json(indent=2) + "\n",
        encoding="utf-8",
    )
    for slug in expected.source_slugs:
        breakdown_path = (
            profile_case / "breakdowns" / slug / "breakdown.json"
        )
        breakdown_path.parent.mkdir(parents=True)
        breakdown_path.write_text("{}\n", encoding="utf-8")

    def mutated_builder(
        name: str,
        slugs: list[str],
        workspace: Path,
    ) -> StyleProfile:
        actual = copy.deepcopy(expected)
        actual.duration.median += 1.0
        return actual

    report = evaluate(
        [SAMPLE_DIRECTORY],
        tmp_path / "mutated-report.json",
        ffmpeg="not-installed-ffmpeg",
        profile_case_directories=[profile_case],
        profile_builder=mutated_builder,
    )

    assert report["passed"] is False
    assert report["cases"][0]["score"]["passed"] is True
    assert report["profile_eval"]["passed"] is False
    profile_score = report["profile_eval"]["cases"][0]["score"]
    assert profile_score["failed_dimensions"] == ["duration"]
