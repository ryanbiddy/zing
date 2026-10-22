"""Feature and decision checks independent of real calibration timestamps."""

from __future__ import annotations

import os
import random
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from myzing.study import transition_models as m
from myzing.study import transitions as t
from tools.eval.real.run_real_eval import verified
from tools.eval.real.run_transition_eval import load_split, score_split


def scenes():
    a = [
        40.0 + (100 if (x < 8 and y < 16) or (x >= 16 and y >= 16) else 0)
        for y in range(24)
        for x in range(24)
    ]
    b = [
        40.0 + (100 if (x >= 16 and y < 16) or (x < 8 and y >= 16) else 0)
        for y in range(24)
        for x in range(24)
    ]
    return a, b


def pairs(frames, fps=30):
    return [
        t.PairFeatures(
            (i + 1) / fps,
            m.distance(a, b),
            t._histogram_distance(
                bytes(round(max(0, min(255, v))) for v in a),
                bytes(round(max(0, min(255, v))) for v in b),
            ),
            0.5,
            m.structure_change(a, b, 24),
            m.edge_change(a, b, 24),
        )
        for i, (a, b) in enumerate(zip(frames, frames[1:]))
    ]


def test_pool_averages_grain_instead_of_aliasing():
    frame = bytes([0, 80, 0, 80, 80, 0, 80, 0] * 8)
    assert m.pool(frame, 8, 8) == [40] * 4


def test_block_structure_separates_exposure_from_replacement():
    a, b = scenes()
    assert m.structure_change(a, a, 24) == 0
    assert m.structure_change(a, [v + 35 for v in a], 24) == pytest.approx(0)
    assert m.structure_change(a, b, 24) > 0.18
    assert m.exposure_residual(a, [v + 35 for v in a]) < 0.01


def test_edge_change_tolerates_small_translation():
    a, b = scenes()
    shifted = [a[y * 24 + max(0, x - 1)] for y in range(24) for x in range(24)]
    assert m.edge_change(a, shifted, 24) < 0.05
    assert m.edge_change(a, b, 24) > 0.1


def test_translation_null_model_recognizes_motion():
    a, b = scenes()
    shifted = [a[y * 24 + max(0, x - 3)] + 7 for y in range(24) for x in range(24)]
    assert m.translation_error(a, shifted, 24) < 0.01
    assert m.translation_error(a, b, 24) > 0.55


def test_blend_fit_reconstructs_mixture_and_preserves_fraction_order():
    a, b = scenes()
    frames = [
        [x * (1 - fraction) + y * fraction for x, y in zip(a, b)]
        for fraction in (0.2, 0.5, 0.8)
    ]
    error, alpha = m.blend_fit(a, b, frames)
    assert error < 1e-12
    assert alpha == pytest.approx([0.2, 0.5, 0.8])
    assert m.blend_fit(a, b, frames[::-1])[1] == pytest.approx([0.8, 0.5, 0.2])


def test_optical_window_accepts_grain_without_quiet_handles():
    a, b = scenes()
    rng = random.Random(802)
    frames = []
    for i in range(75):
        fraction = min(1, max(0, (i - 20) / 24))
        frames.append(
            [
                x * (1 - fraction) + y * fraction + rng.uniform(-2, 2)
                for x, y in zip(a, b)
            ]
        )
    found = t._optical_dissolves(frames, pairs(frames), 30, [])
    assert len(found) == 1
    first, last, error, anchor_first, anchor_last = found[0]
    assert anchor_first <= first < last <= anchor_last
    assert abs(first - 20) <= 4 and abs(last - 44) <= 4
    assert error < t.OPTICAL_MAX_ERROR
    assert t._optical_dissolves(frames, pairs(frames), 30, [(19, 45)]) == []


@pytest.mark.parametrize("mode", ["lighting", "overlay", "pan"])
def test_optical_window_rejects_continuous_scene_changes(mode):
    a, _ = scenes()
    frames = []
    for i in range(75):
        alpha = min(1, max(0, (i - 20) / 24))
        if mode == "lighting":
            frame = [v + 50 * alpha for v in a]
        elif mode == "overlay":
            frame = [v + 70 * alpha * (j % 24 < 8) for j, v in enumerate(a)]
        else:
            shift = round(alpha * 8)
            frame = [a[y * 24 + (x + shift) % 24] for y in range(24) for x in range(24)]
        frames.append(frame)
    assert t._optical_dissolves(frames, pairs(frames), 30, []) == []


def test_adaptive_cut_handles_two_frame_blend():
    rng = random.Random(80)
    a = [rng.uniform(30, 130) for _ in range(576)]
    b = [rng.uniform(80, 180) for _ in range(576)]
    frames = [a] * 8 + [[(x + y) / 2 for x, y in zip(a, b)]] + [b] * 9
    features = pairs(frames)
    assert len(t._hard_cuts(features, frames, 30)) == 1
    assert t._hard_cuts(features, frames, 30)[0] in (7, 8)


def test_low_contrast_cut_has_structural_evidence():
    rng = random.Random(81)
    a = [rng.uniform(70, 100) for _ in range(576)]
    b = [rng.uniform(80, 110) for _ in range(576)]
    frames = [a] * 8 + [b] * 9
    assert 8 < m.distance(a, b) < t.HARD_CUT_DIFFERENCE
    assert t._hard_cuts(pairs(frames), frames, 30) == [7]


@pytest.mark.parametrize("black", [0.0, 16.0])
def test_persistent_black_accepts_full_and_limited_range(black):
    rng = random.Random(82)
    a = [rng.uniform(30, 180) for _ in range(576)]
    frames = [a] * 8 + [[black] * len(a)] * 9
    assert t._hard_cuts(pairs(frames), frames, 30) == [7]
    frames[9:] = [a] * 8
    assert t._hard_cuts(pairs(frames), frames, 30) == []


def test_real_split_is_complete_disjoint_and_keeps_one_dissolve_each():
    split, manifest, labels = load_split()
    assert split["frozen_before_tuning"]
    for part in ("calibration", "held_out"):
        assert (
            sum(
                e["signature"] == "dissolve"
                for id in split[part]
                for e in labels["clips"][id]["transition_events"]
            )
            == 1
        )
    assert len(manifest["clips"]) == 10


@pytest.mark.real_media
def test_pinned_real_classroom_transition_regression():
    if os.environ.get("ZING_REAL_TRANSITIONS") != "1":
        pytest.skip(
            "opt in with ZING_REAL_TRANSITIONS=1 and ZING_REAL_EVAL_ROOT pointing to pinned media"
        )
    root = Path(os.environ.get("ZING_REAL_EVAL_ROOT", "zing-workspace/real-eval"))
    _, manifest, labels = load_split()
    clip = next(c for c in manifest["clips"] if c["id"] == "duck-classroom")
    media = root / clip["file"]
    if not media.is_file():
        pytest.skip("pinned real classroom clip absent; no automatic download")
    assert verified(media, clip["sha256"])
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")):
        pytest.skip("real-media test needs ffmpeg and ffprobe")
    result = t.detect_transitions(media)
    observations = {
        "clips": {
            clip["id"]: {
                "media_sha256": clip["sha256"],
                "breakdown": {"provenance": result.provenance},
            }
        }
    }
    scores = score_split(manifest, labels, observations, [clip["id"]])["signatures"]
    assert (scores["hard_cut"]["tp"], scores["hard_cut"]["fp"]) == (2, 0)
    assert (scores["dissolve"]["tp"], scores["dissolve"]["fp"]) == (1, 0)
    assert all(s["fp"] == 0 for s in scores.values())
