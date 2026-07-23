"""Real-scenedetect test for the _run_detector seam (mirrors the
real-cv2 pattern of test_study_captions_frames.py): a synthetic clip
with one unmistakable hard cut, written by cv2.VideoWriter — offline,
no ffmpeg binary."""

from __future__ import annotations

import pytest

from myzing.study import shots


@pytest.fixture(scope="module")
def real_detector_dependencies():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("scenedetect")
    return np, cv2


@pytest.fixture(scope="module")
def two_scene_clip(tmp_path_factory, real_detector_dependencies):
    """2s @ 30fps: 1s black, then 1s white — one hard cut at t=1.0."""
    np, cv2 = real_detector_dependencies
    path = tmp_path_factory.mktemp("clip") / "cut.avi"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (320, 240)
    )
    assert writer.isOpened()
    for i in range(60):
        value = 0 if i < 30 else 255
        writer.write(np.full((240, 320, 3), value, dtype=np.uint8))
    writer.release()
    return path


def test_run_detector_real_seam_finds_the_cut(two_scene_clip):
    spans, version = shots._run_detector(
        str(two_scene_clip), min_scene_len_frames=9
    )

    assert isinstance(version, str) and version
    assert len(spans) == 2
    (s0, e0), (s1, e1) = spans
    assert s0 == 0.0
    assert e0 == pytest.approx(1.0, abs=0.2)   # the cut
    assert s1 == pytest.approx(e0, abs=1e-6)   # contiguous
    assert e1 == pytest.approx(2.0, abs=0.2)
