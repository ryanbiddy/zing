"""Real-cv2 tests for the frame-decode seam (_iter_frames/_changed).

Separate from test_study_captions.py, whose contract is mocked seams
only. These use cv2's own VideoWriter for a tiny synthetic clip — no
ffmpeg binary, no network, still offline. cv2+numpy are hard deps of
the study extra (shots.py), so requiring them here adds nothing new.
"""

from __future__ import annotations

import pytest

from myzing.study import captions


@pytest.fixture(scope="module")
def real_cv2_dependencies():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    return np, cv2


@pytest.fixture(scope="module")
def tiny_clip(tmp_path_factory, real_cv2_dependencies):
    """1.0s @ 30fps, 64x48: frame index painted as a brightness ramp."""
    np, cv2 = real_cv2_dependencies
    path = tmp_path_factory.mktemp("clip") / "tiny.avi"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 48)
    )
    assert writer.isOpened()
    for i in range(30):
        frame = np.full((48, 64, 3), min(8 * i, 255), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


def test_iter_frames_follows_sampling_schedule(tiny_clip):
    got = list(captions._iter_frames(tiny_clip, duration=1.0))

    schedule = captions.sample_schedule(1.0)
    assert [(t, step) for t, step, _ in got] == schedule
    assert all(frame.shape == (48, 64, 3) for _, _, frame in got)
    # Later samples come from later frames (brightness ramps upward).
    assert got[-1][2].mean() > got[0][2].mean()


def test_iter_frames_stops_at_stream_end_without_error(tiny_clip):
    # Ask for more than the clip holds: schedule for 3s against a 1s file.
    got = list(captions._iter_frames(tiny_clip, duration=3.0))
    assert 0 < len(got) < len(captions.sample_schedule(3.0))


def test_iter_frames_unopenable_path_raises(tmp_path, real_cv2_dependencies):
    with pytest.raises(RuntimeError, match="could not open"):
        list(captions._iter_frames(tmp_path / "missing.mp4", duration=1.0))


def test_changed_gate_on_real_arrays(real_cv2_dependencies):
    np, _ = real_cv2_dependencies
    base = np.zeros((480, 270, 3), dtype=np.uint8)
    same = base.copy()
    moved = base.copy()
    moved[100:200, 50:150] = 255                # a caption-sized flip

    assert captions._changed(base, same) is False
    assert captions._changed(base, moved) is True
