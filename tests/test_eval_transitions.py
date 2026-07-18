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
    SIGNATURES,
    evaluate_transition_goldens,
    summarize_signature_precision,
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
    assert result.provenance["transition_detector_version"] == 2
    assert result.provenance["transition_feature_summary"]["frame_count"] == 90


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
    assert report["macro_precision"] == 1.0
    assert report["limitations"]["prototype_only"] is True
    assert "match_cut" in report["limitations"]["not_detected"]
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
