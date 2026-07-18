"""Offline tests for shot detection and derived pacing. The scenedetect
library is mocked at the single _run_detector seam; no video decoding."""

from __future__ import annotations

from pathlib import Path

import pytest

from myzing.schemas import Shot
from myzing.study import shots


def fake_detector(spans, expected_min_len=None):
    calls = []

    def run(media_path, min_scene_len_frames):
        calls.append((media_path, min_scene_len_frames))
        if expected_min_len is not None:
            assert min_scene_len_frames == expected_min_len
        return list(spans), "0.7"

    run.calls = calls
    return run


# -- detect_shots -----------------------------------------------------------

def test_detect_shots_builds_indexed_shots(monkeypatch):
    monkeypatch.setattr(
        shots, "_run_detector", fake_detector([(0.0, 1.4), (1.4, 3.05), (3.05, 10.0)])
    )
    result = shots.detect_shots(Path("media.mp4"), duration=10.0, fps=30.0)

    assert [s.index for s in result.shots] == [0, 1, 2]
    assert result.shots[0].start == 0.0
    assert result.shots[1].start == 1.4
    assert result.shots[2].end == 10.0
    assert result.warnings == []
    assert result.provenance["shot_detector"] == "scenedetect-0.7 AdaptiveDetector"
    assert result.provenance["min_scene_len_s"] == shots.MIN_SCENE_LEN_S


def test_min_scene_len_scales_with_fps(monkeypatch):
    fake = fake_detector([(0.0, 5.0)], expected_min_len=round(0.3 * 60))
    monkeypatch.setattr(shots, "_run_detector", fake)
    shots.detect_shots(Path("m.mp4"), duration=5.0, fps=60.0)
    assert fake.calls  # the assertion inside fake ran


def test_no_cuts_yields_single_full_shot(monkeypatch):
    monkeypatch.setattr(shots, "_run_detector", fake_detector([]))
    result = shots.detect_shots(Path("m.mp4"), duration=12.5, fps=30.0)
    assert len(result.shots) == 1
    assert (result.shots[0].start, result.shots[0].end) == (0.0, 12.5)


def test_missing_scenedetect_is_honest_skip(monkeypatch):
    def raises(*a):
        raise ImportError("No module named 'scenedetect'")
    monkeypatch.setattr(shots, "_run_detector", raises)
    result = shots.detect_shots(Path("m.mp4"), duration=10.0, fps=30.0)
    assert result.shots == []
    assert any("scenedetect not installed" in w for w in result.warnings)
    assert any("myzing[study]" in w for w in result.warnings)


def test_detector_crash_is_honest_skip(monkeypatch):
    def raises(*a):
        raise RuntimeError("could not decode stream")
    monkeypatch.setattr(shots, "_run_detector", raises)
    result = shots.detect_shots(Path("m.mp4"), duration=10.0, fps=30.0)
    assert result.shots == []
    assert any("shot detection failed" in w for w in result.warnings)


# -- derived pacing ---------------------------------------------------------

def _mk(spans):
    return [Shot(i, s, e) for i, (s, e) in enumerate(spans)]


def test_avg_shot_duration():
    assert shots.avg_shot_duration(_mk([(0, 1.0), (1.0, 4.0)])) == 2.0
    assert shots.avg_shot_duration([]) == 0.0


def test_cuts_per_10s_windows_and_raw_trailing_window():
    # Cuts at 1.4, 3.05, 12.0, 21.0 over 25s -> windows [2, 1, 1] and the
    # trailing 5s window is counted raw, not scaled (pinned definition).
    s = _mk([(0, 1.4), (1.4, 3.05), (3.05, 12.0), (12.0, 21.0), (21.0, 25.0)])
    assert shots.cuts_per_10s(s, duration=25.0) == [2.0, 1.0, 1.0]


def test_cuts_per_10s_no_cuts_is_zeros_not_empty():
    # One full-length shot: real measurement, zero cuts -> zeroed windows.
    assert shots.cuts_per_10s(_mk([(0, 32.0)]), duration=32.0) == [0.0, 0.0, 0.0, 0.0]


def test_cuts_per_10s_skip_is_empty():
    # Skipped measurement (no shots) stays distinguishable from "no cuts".
    assert shots.cuts_per_10s([], duration=30.0) == []


def test_cut_exactly_on_window_boundary_counts_in_later_window():
    s = _mk([(0, 10.0), (10.0, 20.0)])
    assert shots.cuts_per_10s(s, duration=20.0) == [0.0, 1.0]
