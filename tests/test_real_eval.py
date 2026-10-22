"""The audit must not reward duplicates, unreviewed time or changed media."""

import importlib.util
from pathlib import Path

import pytest


def load(name):
    path = Path(__file__).resolve().parents[1] / "tools/eval/real" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scoring = load("scoring")
runner = load("run_real_eval")
acquire, inside, sha256, verified = (
    runner.acquire,
    runner.inside,
    runner.sha256,
    runner.verified,
)


def test_undefined_metrics_are_not_perfect():
    assert scoring.pr(0, 0, 0)["precision"] is None
    assert scoring.pr(0, 0, 2)["recall"] == 0


def test_matching_does_not_count_duplicate_predictions_twice():
    pairs = scoring.assign([1], [1, 1], lambda a, b: 1 if a == b else -1)
    assert len(pairs) == 1
    assert scoring.pr(len(pairs), 2 - len(pairs), 0)["precision"] == 0.5


def test_matching_does_not_lose_overlapping_eligible_event():
    pairs = scoring.assign(
        ["flexible", "only-a"],
        ["a", "b"],
        lambda t, p: (
            (2 if p == "a" else 1) if t == "flexible" else (2 if p == "a" else -1)
        ),
    )
    assert pairs == [(0, 1), (1, 0)]


def test_unreviewed_event_and_cross_boundary_interval_excluded():
    assert scoring.inside({"start_seconds": 5, "end_seconds": 5}, [[3, 7]])
    assert not scoring.inside({"start_seconds": 8, "end_seconds": 8}, [[3, 7]])
    assert not scoring.inside({"start_seconds": 6, "end_seconds": 8}, [[3, 7]])
    assert not scoring.inside({"start_seconds": 7, "end_seconds": 7}, [[3, 7]])


def test_cuts_match_two_frames_but_not_wrong_time_or_duplicate():
    clips = {"c": {"fps": 30}}
    labels = {
        "c": {
            "transition_windows": [[0, 5]],
            "transition_events": [
                {"signature": "hard_cut", "start_seconds": 1, "end_seconds": 1}
            ],
        }
    }
    obs = {
        "c": {
            "breakdown": {
                "provenance": {
                    "transition_evidence": [
                        {
                            "signature": "hard_cut",
                            "start_seconds": t,
                            "end_seconds": t,
                            "confidence": 0.9,
                        }
                        for t in [1 + 2 / 30, 1 + 2 / 30, 2, 8]
                    ]
                }
            }
        }
    }
    result = scoring.transition_score(
        clips, labels, obs, "hard_cut", {"confidence": 0.8, "cut_tolerance_frames": 2}
    )
    assert (result["tp"], result["fp"], result["fn"]) == (1, 2, 0)


def test_abstention_does_not_raise_recall():
    clips = {"c": {"fps": 30}}
    labels = {
        "c": {
            "transition_windows": [[0, 5]],
            "transition_events": [
                {"signature": "dissolve", "start_seconds": 1, "end_seconds": 2}
            ],
        }
    }
    obs = {
        "c": {
            "breakdown": {
                "provenance": {
                    "transition_evidence": [
                        {
                            "signature": "unknown",
                            "start_seconds": 1,
                            "end_seconds": 2,
                            "confidence": 0,
                        }
                    ]
                }
            }
        }
    }
    result = scoring.transition_score(
        clips, labels, obs, "dissolve", {"confidence": 0.8, "interval_iou": 0.5}
    )
    assert result["fn"] == 1 and result["recall"] == 0
    assert result["per_clip"][0]["abstentions"] == 1


def test_download_is_explicit_and_cached_hash_is_enforced(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("network attempted without authorization")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    p = tmp_path / "media.mp4"
    with pytest.raises(ValueError, match="--download"):
        acquire("https://example.org/media.mp4", p, "0" * 64, False)
    p.write_bytes(b"known asset")
    digest = sha256(p)
    acquire("https://example.org/media.mp4", p, digest, False)
    p.write_bytes(b"changed asset")
    with pytest.raises(ValueError, match="SHA-256"):
        verified(p, digest)


def test_workspace_paths_cannot_escape(tmp_path):
    assert inside(tmp_path, "clips/a.mp4") == tmp_path / "clips/a.mp4"
    with pytest.raises(ValueError, match="escapes"):
        inside(tmp_path, "../outside.mp4")


def test_audio_unknown_is_not_negative_and_face_missing_is_unavailable():
    result = scoring.face_score(
        {"c": {"face_frames": [{"t": 1, "present": None}, {"t": 2, "present": True}]}},
        {},
        {"face_sample_tolerance_seconds": 0.01},
    )
    assert result["unknown"] == [["c", 1]] and result["unavailable"] == [["c", 2]]
    assert result["recall"] is None and result["frames_scored"] == 0


def test_labels_and_observations_are_bound_to_media_hash():
    manifest = {"clips": [{"id": "c", "sha256": "expected"}]}
    labels = {"version": 1, "clips": {"c": {"media_sha256": "wrong"}}, "thresholds": {}}
    with pytest.raises(ValueError, match="Label/media"):
        scoring.score(manifest, labels, {"clips": {}})
    labels["clips"]["c"]["media_sha256"] = "expected"
    with pytest.raises(ValueError, match="Observation/media"):
        scoring.score(manifest, labels, {"clips": {"c": {"media_sha256": "wrong"}}})
