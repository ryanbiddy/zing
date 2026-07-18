from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

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
