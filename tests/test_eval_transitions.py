from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from myzing.study import transitions as study_transitions
from tools.eval.make_goldens import generate_transition_goldens
from tools.eval.transitions import (
    DEFAULT_REAL_RECALL_AUDIT,
    SIGNATURES,
    evaluate_transition_goldens,
    summarize_real_dissolve_calibration,
    summarize_real_transition_recall,
    summarize_signature_precision,
    summarize_signature_recall,
)


def test_signature_precision_counts_false_positives() -> None:
    cases = [
        {
            "truth": ["hard_cut"],
            "predicted": ["hard_cut"],
        },
        {
            "truth": ["dissolve"],
            "predicted": ["hard_cut", "dissolve"],
        },
    ]

    summary = summarize_signature_precision(cases)

    assert summary["hard_cut"] == {
        "true_positives": 1,
        "false_positives": 1,
        "predicted_count": 2,
        "precision": 0.5,
    }
    assert summary["dissolve"]["precision"] == 1.0


def test_signature_recall_counts_false_negatives() -> None:
    cases = [
        {
            "truth": ["hard_cut"],
            "predicted": ["hard_cut"],
        },
        {
            "truth": ["dissolve"],
            "predicted": [],
        },
    ]

    summary = summarize_signature_recall(cases)

    assert summary["hard_cut"] == {
        "available": True,
        "true_positives": 1,
        "false_negatives": 0,
        "truth_count": 1,
        "recall": 1.0,
    }
    assert summary["dissolve"] == {
        "available": True,
        "true_positives": 0,
        "false_negatives": 1,
        "truth_count": 1,
        "recall": 0.0,
    }
    assert summary["wipe"]["available"] is False
    assert summary["wipe"]["recall"] is None


def test_real_recall_audit_covers_both_requested_corpora() -> None:
    result = summarize_real_transition_recall()

    assert DEFAULT_REAL_RECALL_AUDIT.is_file()
    assert result["source_count"] == 8
    assert result["corpora"] == {
        "frozen-real-video-set": 5,
        "sprint-2-gate-pack": 3,
    }
    assert result["exhaustively_labeled_source_count"] == 0
    assert result["recall"]["available"] is False
    assert result["recall"]["value"] is None
    assert result["production_disposition"] == "experimental-warning"
    assert result["detector_execution"] == {
        "available": True,
        "accuracy_status": "unjudged",
        "detector_version": 4,
        "source_count": 3,
        "predicted_event_counts": {
            "hard_cut": 5,
            "dissolve": 0,
            "wipe": 3,
            "zoom_punch": 1,
            "audio_aligned_cut": 0,
        },
    }
    assert all(
        signature["available"] is False
        and signature["value"] is None
        for signature in result["recall"]["by_signature"].values()
    )
    assert {
        source["annotation_status"] for source in result["sources"]
    } == {"coarse-only", "unjudged"}


def test_real_recall_audit_source_identities_match_frozen_provenance() -> None:
    audit = json.loads(
        DEFAULT_REAL_RECALL_AUDIT.read_text(encoding="utf-8")
    )
    audited = {
        (
            source["fixture_id"],
            source["source_url"],
            source["media_sha256"],
        )
        for corpus in audit["corpora"]
        for source in corpus["sources"]
    }
    real_sources = set()
    for case_directory in (
        ROOT / "tools" / "eval" / "real_videos"
    ).iterdir():
        provenance_path = case_directory / "provenance.json"
        if not provenance_path.is_file():
            continue
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        real_sources.add(
            (
                provenance["fixture_id"],
                provenance["source"]["url"],
                provenance["source_media"]["sha256"],
            )
        )
    gate_calibration = json.loads(
        (
            ROOT
            / "tools"
            / "eval"
            / "fixtures"
            / "transitions"
            / "real-gate-candidates.json"
        ).read_text(encoding="utf-8")
    )
    gate_sources = {
        (
            source["fixture_id"],
            source["source_url"],
            source["media_sha256"],
        )
        for source in gate_calibration["sources"]
    }

    assert audited == real_sources | gate_sources


def test_real_recall_audit_rejects_stale_detector_measurements(
    tmp_path: Path,
) -> None:
    audit = json.loads(
        DEFAULT_REAL_RECALL_AUDIT.read_text(encoding="utf-8")
    )
    gate_source = audit["corpora"][1]["sources"][0]
    gate_source["detector_measurement"]["detector_version"] = 3
    audit_path = tmp_path / "stale-recall-audit.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")

    with pytest.raises(ValueError, match="measurements are stale"):
        summarize_real_transition_recall(audit_path)


def test_production_detector_returns_typed_audio_aligned_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        study_transitions,
        "detect_transition_signatures",
        lambda media_path, ffmpeg, ffprobe: {
            "events": [
                {
                    "signature": "hard_cut",
                    "start_seconds": 1.0,
                    "end_seconds": 1.0,
                    "frame_pair_count": 1,
                },
                {
                    "signature": "dissolve",
                    "start_seconds": 2.0,
                    "end_seconds": 2.4,
                    "frame_pair_count": 12,
                },
            ],
            "audio_aligned_pairs": [
                {
                    "cut_seconds": 1.0,
                    "onset_seconds": 0.98,
                    "delta_seconds": -0.02,
                }
            ],
            "feature_summary": {
                "frame_count": 90,
                "active_run_count": 2,
            },
        },
    )

    result = study_transitions.detect_transitions(tmp_path / "clip.mp4")

    assert [transition.kind for transition in result.transitions] == [
        "hard_cut",
        "dissolve",
    ]
    assert result.transitions[0].audio_aligned is True
    assert result.transitions[0].audio_onset_delta == -0.02
    assert result.transitions[1].audio_aligned is False
    assert result.provenance["transition_detector_version"] == 4
    assert result.provenance["transition_feature_summary"]["frame_count"] == 90
    assert result.provenance["transition_validation"] == {
        "status": "experimental",
        "synthetic_recall_available": True,
        "real_video_recall_available": False,
    }
    assert len(result.warnings) == 1
    assert "real-video recall is unavailable" in result.warnings[0]


def test_non_monotonic_gradual_motion_is_not_a_dissolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame_size = (
        study_transitions.FRAME_WIDTH * study_transitions.FRAME_HEIGHT
    )
    frames = [
        bytes([value]) * frame_size
        for value in (0, 10, 0, 10, 0)
    ]
    monkeypatch.setattr(
        study_transitions,
        "_probe_video",
        lambda media_path, ffprobe: (30.0, 96, 96),
    )
    monkeypatch.setattr(
        study_transitions,
        "_read_gray_frames",
        lambda media_path, ffmpeg, width, height: frames,
    )
    monkeypatch.setattr(
        study_transitions,
        "_audio_onsets",
        lambda media_path, ffmpeg: ([], True),
    )

    measurement = study_transitions.detect_transition_signatures(
        tmp_path / "motion.mp4"
    )

    assert "dissolve" not in measurement["predicted"]
    assert measurement["events"] == []
    assert measurement["feature_summary"]["suppressed_dissolve_candidates"] == 1


def test_real_dissolve_calibration_keeps_precision_unavailable() -> None:
    calibration = summarize_real_dissolve_calibration()

    assert calibration["source_count"] == 3
    assert calibration["prior_dissolve_candidates"] == 29
    assert calibration["retained_by_current_gate"] == 0
    assert calibration["suppressed_by_current_gate"] == 29
    assert calibration["candidate_rejection_rate"] == 1.0
    assert calibration["precision"] == {
        "available": False,
        "value": None,
        "annotation_status": "unjudged",
        "reason": (
            "The gate pack froze detector measurements, not frame-level human "
            "transition truth. Candidate rejection is a calibration diagnostic "
            "and must not be reported as real-video precision."
        ),
    }


@pytest.mark.ffmpeg
def test_transition_goldens_report_per_signature_precision(
    tmp_path: Path,
) -> None:
    directories = generate_transition_goldens(tmp_path / "transition goldens")

    assert [directory.name for directory in directories] == [
        "01 hard cut",
        "02 dissolve",
        "03 wipe",
        "04 zoom punch",
        "05 audio-aligned cut",
    ]
    report_path = tmp_path / "transition report.json"
    report = evaluate_transition_goldens(directories, report_path)

    assert set(report["signatures"]) == set(SIGNATURES)
    for signature in SIGNATURES:
        assert report["signatures"][signature]["true_positives"] >= 1
        assert report["signatures"][signature]["precision"] == 1.0
        assert report["signatures"][signature]["recall"] == 1.0
    assert report["macro_precision"] == 1.0
    assert report["macro_recall"] == 1.0
    assert report["prototype_schema_version"] == 3
    assert report["real_video_calibration"]["precision"]["value"] is None
    assert report["real_video_calibration"]["retained_by_current_gate"] == 0
    assert report["real_video_recall"]["recall"]["value"] is None
    assert (
        report["real_video_recall"]["production_disposition"]
        == "experimental-warning"
    )
    assert report["limitations"]["prototype_only"] is True
    assert "match_cut" in report["limitations"]["not_detected"]
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_failed_audio_probe_is_distinguishable_from_no_onsets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-Q10 finding closed: audio decode failure must not read as
    measured-empty (the skipped-vs-empty conflation the contract bans)."""
    frame_size = (
        study_transitions.FRAME_WIDTH * study_transitions.FRAME_HEIGHT
    )
    frames = [bytes([0]) * frame_size, bytes([255]) * frame_size]
    monkeypatch.setattr(
        study_transitions,
        "_probe_video",
        lambda media_path, ffprobe: (30.0, 96, 96),
    )
    monkeypatch.setattr(
        study_transitions,
        "_read_gray_frames",
        lambda media_path, ffmpeg, width, height: frames,
    )
    monkeypatch.setattr(
        study_transitions,
        "_audio_onsets",
        lambda media_path, ffmpeg: ([], False),
    )

    measurement = study_transitions.detect_transition_signatures(
        tmp_path / "silent-failure.mp4"
    )

    assert measurement["audio_probe_ok"] is False
    assert measurement["audio_onsets_seconds"] == []
