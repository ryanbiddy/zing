"""Clip-split evaluation must not turn unavailable data or abstentions into success."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from tools.eval.real import run_transition_eval as r


def example():
    manifest = {"clips": [{"id": "c", "fps": 30, "sha256": "pin"}]}
    labels = {
        "clips": {
            "c": {
                "transition_windows": [[1, 4]],
                "transition_events": [
                    {"signature": "hard_cut", "start_seconds": 2, "end_seconds": 2}
                ],
            }
        },
        "thresholds": {
            "confidence": 0.8,
            "cut_tolerance_frames": 2,
            "interval_iou": 0.5,
        },
    }
    observations = {
        "clips": {
            "c": {
                "media_sha256": "pin",
                "breakdown": {
                    "provenance": {
                        "transition_evidence": [
                            {
                                "signature": "unknown",
                                "start_seconds": 0,
                                "end_seconds": 5,
                                "confidence": 0,
                            }
                        ]
                    }
                },
            }
        }
    }
    return manifest, labels, observations


def test_unknown_crossing_review_edges_covers_truth_but_stays_false_negative():
    result = r.score_split(*example(), ["c"])
    stats = result["signatures"]["hard_cut"]
    assert (stats["tp"], stats["fn"], stats["unknown"]) == (0, 1, 1)
    assert result["unknown_count"] == 1
    assert stats["precision"] is None and stats["recall"] == 0


def test_missing_prediction_is_not_an_invented_unknown():
    manifest, labels, observations = example()
    observations["clips"]["c"]["breakdown"]["provenance"]["transition_evidence"] = []
    result = r.score_split(manifest, labels, observations, ["c"])
    assert result["signatures"]["hard_cut"]["fn"] == 1
    assert result["signatures"]["hard_cut"]["unknown"] == 0
    assert result["unknown_count"] == 0


@pytest.mark.parametrize("fault", ["hash", "missing_evidence", "missing_clip"])
def test_incomplete_or_changed_observation_cannot_score(fault):
    manifest, labels, observations = example()
    if fault == "hash":
        observations["clips"]["c"]["media_sha256"] = "changed"
    elif fault == "missing_evidence":
        observations["clips"]["c"]["breakdown"]["provenance"].clear()
    else:
        observations["clips"].clear()
    with pytest.raises(ValueError):
        r.score_split(manifest, labels, observations, ["c"])


def test_split_rejects_overlap(tmp_path):
    split, _, _ = r.load_split()
    split["held_out"][0] = split["calibration"][0]
    path = tmp_path / "split.json"
    r.write_json(path, split)
    with pytest.raises(ValueError, match="partition"):
        r.load_split(path)


@pytest.mark.parametrize(
    "lock_state", ["absent", "changed_decisions", "changed_inputs"]
)
def test_held_out_requires_unchanged_lock_before_any_inference(
    tmp_path, monkeypatch, lock_state
):
    monkeypatch.setattr(
        r.transitions,
        "detect_transitions",
        lambda *a, **k: pytest.fail("held-out inference attempted"),
    )
    args = [
        "--root",
        str(tmp_path),
        "--out",
        str(tmp_path / "out"),
        "--split",
        "held_out",
    ]
    if lock_state != "absent":
        inputs = {
            name: r.sha256(r.HERE / name)
            for name in (
                "manifest.json",
                "labels.json",
                "transition-split.json",
                "scoring.py",
                "run_transition_eval.py",
            )
        }
        lock = {**r.fingerprint(), "inputs": inputs}
        if lock_state == "changed_decisions":
            lock["decision_sha256"] = "stale"
        else:
            lock["inputs"]["labels.json"] = "stale"
        path = tmp_path / "lock.json"
        r.write_json(path, lock)
        args += ["--lock", str(path)]
    with pytest.raises(SystemExit) as exc:
        r.main(args)
    assert exc.value.code == 2


def test_only_selected_clips_contribute_to_metrics():
    manifest, labels, observations = example()
    manifest["clips"].append({"id": "held", "fps": 30, "sha256": "another"})
    labels["clips"]["held"] = copy.deepcopy(labels["clips"]["c"])
    result = r.score_split(manifest, labels, observations, ["c"])
    assert result["signatures"]["hard_cut"]["truth_count"] == 1
    assert result["reviewed_seconds"] == 3


def test_published_validation_matches_frozen_held_out_measurement():
    report = r.read_json(r.HERE / "transitions-v6-results.json")
    lock = r.read_json(r.HERE / "transition-v6-lock.json")
    assert r.fingerprint()["decision_sha256"] == lock["decision_sha256"]
    assert report["decision_freeze"] == lock
    measured = report["real"]["held_out"]["v6"]
    published = r.transitions.VALIDATION_STATUS["real_video_held_out"]
    assert published["event_count"] == sum(s["truth_count"] for s in measured["signatures"].values())
    assert published["reviewed_seconds"] == measured["reviewed_seconds"]
    for kind in ("hard_cut", "dissolve"):
        assert published[kind] == {k: measured["signatures"][kind][k] for k in published[kind]}
    assert report["remaining_misses"][0]["clip"] == "duck-titles"
    assert report["real"]["held_out"]["v5"]["matches_current_detector"] is False
