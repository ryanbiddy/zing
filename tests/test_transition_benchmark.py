from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from myzing.study import transitions
from tools.eval.transition_benchmark import (
    CLASSES, MIN_PRECISION, MIN_RECALL, evaluate_corpus, score_events,
)
from tools.eval.transition_corpus import GeneratedCase, corpus_cases, generate_case, generate_corpus


def event(kind: str, start: float = 1.0, end: float = 1.0) -> dict:
    return {"signature": kind, "start_seconds": start, "end_seconds": end}


def test_event_scoring_penalizes_duplicates_wrong_time_and_wrong_labels() -> None:
    cases = [{"fps": 30, "truth_events": [event("hard_cut"), event("wipe", 2, 2.5)],
              "events": [event("hard_cut"), event("hard_cut"), event("wipe", 0, 0.5),
                         event("dissolve", 2, 2.5)]}]
    result = score_events(cases)
    hard_cut = result["signatures"]["hard_cut"]
    assert hard_cut["precision"] == 0.5 and hard_cut["recall"] == 1.0
    assert result["signatures"]["wipe"]["false_positives"] == 1
    assert result["signatures"]["wipe"]["false_negatives"] == 1
    assert result["signatures"]["dissolve"]["precision"] == 0.0


def test_unknown_and_missing_are_separate_and_empty_precision_is_unavailable() -> None:
    cases = [{"fps": 24, "truth_events": [event("flash", 1, 1.5), event("whip_pan", 2, 2.5)],
              "events": [event("unknown", 1, 1.5)]}]
    result = score_events(cases)
    assert result["unknown_count"] == 1
    flash, whip = (result["signatures"][kind] for kind in ("flash", "whip_pan"))
    assert flash["precision"] is None and flash["recall"] == 0
    assert flash["false_negatives"] == 1 and flash["unknown"] == 1
    assert whip["false_negatives"] == 1 and whip["unknown"] == 0
    assert score_events([])["signatures"]["hard_cut"]["recall"] is None


def test_corpus_split_and_interval_contract() -> None:
    calibration, held_out = corpus_cases("calibration"), corpus_cases("held_out")
    assert {c.seed for c in calibration}.isdisjoint(c.seed for c in held_out)
    assert {c.fps for c in calibration}.isdisjoint(c.fps for c in held_out)
    for split in (calibration, held_out):
        assert {c.variant for c in split if c.kind == "wipe"} == {"up", "down", "left", "right"}
        assert len({c.length for c in split if c.kind == "dissolve"}) == 3
        assert {c.kind for c in split} >= set(CLASSES) - {"audio_aligned_cut"}
        assert len([c for c in split if c.kind == "negative"]) == 8
        for case in split:
            assert GeneratedCase.from_dict(case.to_dict()) == case
            for truth in case.truth_events():
                assert 0 < truth["start_seconds"] <= truth["end_seconds"] < case.duration
                assert abs(truth["end_seconds"] * case.fps - round(truth["end_seconds"] * case.fps)) < 0.0001


def test_evidence_round_trip_and_version_rejection() -> None:
    evidence = transitions.TransitionEvidence("unknown", 1, 1.5, 0.8, 1.7, 0,
                                               transitions.DETECTOR_VERSION, "motion")
    assert transitions.TransitionEvidence.from_dict(evidence.to_dict()) == evidence
    with pytest.raises(ValueError, match="unsupported transition evidence version"):
        transitions.TransitionEvidence.from_dict({**evidence.to_dict(), "version": 99})


@pytest.fixture(scope="module")
def generated_report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("p14-generated")
    directories = generate_corpus(root / "media")
    report_path = root / "report.json"
    report = evaluate_corpus(directories, report_path)
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    return report


@pytest.mark.ffmpeg
def test_generated_transition_precision_recall_and_unknown_gate(generated_report: dict) -> None:
    report = generated_report
    assert report["case_count"] == 48
    assert report["acceptance"] == {"passed": True, "failures": []}
    for split in report["splits"].values():
        for kind in transitions.SUPPORTED_SIGNATURES:
            stats = split["signatures"][kind]
            assert stats["precision"] >= MIN_PRECISION, (kind, stats)
            assert stats["recall"] >= MIN_RECALL, (kind, stats)
        for kind in ("whip_pan", "flash"):
            stats = split["signatures"][kind]
            assert stats["precision"] is None and stats["recall"] == 0
            assert stats["unknown"] == stats["truth_count"] == 2
    for case in report["cases"]:
        assert case["feature_summary"]["frame_count"] == 3 * case["fps"]
        for observation in case["events"]:
            assert observation["detector_version"] == transitions.DETECTOR_VERSION
            assert observation["version"] == 1
            assert 0 <= observation["evidence_start_seconds"] <= observation["start_seconds"]
            assert observation["end_seconds"] <= observation["evidence_end_seconds"] < 3
            assert 0 <= observation["confidence"] <= 1
            assert observation["reason"]


@pytest.mark.ffmpeg
def test_held_out_motion_negatives_have_no_confident_effects(generated_report: dict) -> None:
    negatives = [case for case in generated_report["cases"]
                 if case["split"] == "held_out" and not case["truth_events"]]
    assert len(negatives) == 8
    assert generated_report["splits"]["held_out"]["negative_confident_effects"] == 0
    for case in negatives:
        assert not case["predicted"], case["case_id"]
        assert all(observation["signature"] == "unknown" and observation["confidence"] < 0.8
                   for observation in case["events"])
    # Exercise the production projection too: unknowns stay in evidence, never
    # in the legacy list that profile aggregation treats as editing effects.
    result = transitions.detect_transitions(Path(negatives[-1]["media"]))
    assert result.transitions == []
    assert result.provenance["transition_evidence"]
    assert all(item["observation_index"] is None for item in result.provenance["transition_evidence"])


@pytest.mark.ffmpeg
def test_generated_media_and_truth_are_deterministic(tmp_path: Path) -> None:
    case = next(case for case in corpus_cases("held_out") if case.kind == "whip_pan")
    first = generate_case(case, tmp_path / "first")
    second = generate_case(case, tmp_path / "second")
    left = transitions._read_gray_frames(first / "clip.mp4", "ffmpeg")
    right = transitions._read_gray_frames(second / "clip.mp4", "ffmpeg")
    assert left == right and len(left) == case.fps * case.duration
    assert left[0] != left[-1]  # genuinely two different scenes
    a, b = (json.loads((directory / "truth.json").read_text(encoding="utf-8"))
            for directory in (first, second))
    assert a["case"] == b["case"] == case.to_dict()
    assert a["truth_events"] == b["truth_events"] == case.truth_events()
    assert a["sha256"] == b["sha256"]
