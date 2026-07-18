"""Offline tests for keyframe extraction (ffmpeg mocked at proc.run)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from myzing.schemas import Shot
from myzing.study import keyframes
from myzing.study.proc import ToolMissing


def grabbing_ffmpeg(calls):
    def run(cmd, timeout=None):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"jpg")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def test_extracts_shot_and_hook_frames(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr("myzing.study.keyframes.proc.run", grabbing_ffmpeg(calls))
    shots = [Shot(0, 0.0, 1.4), Shot(1, 1.4, 5.0)]
    warnings: list[str] = []

    keyframes.extract_keyframes(
        Path("media.mp4"), tmp_path, shots, duration=5.0, warnings=warnings
    )

    assert shots[0].keyframe == "frames/shot_000.jpg"
    assert shots[1].keyframe == "frames/shot_001.jpg"
    assert (tmp_path / "frames" / "shot_001.jpg").is_file()
    # hook frames at 0,1,2s
    for s in (0, 1, 2):
        assert (tmp_path / "frames" / f"hook_{s}s.jpg").is_file()
    assert warnings == []
    # seek time appears before -i (fast input seeking)
    first = calls[0]
    assert first.index("-ss") < first.index("-i")


def test_short_video_gets_fewer_hook_frames(tmp_path, monkeypatch):
    monkeypatch.setattr("myzing.study.keyframes.proc.run", grabbing_ffmpeg([]))
    warnings: list[str] = []

    keyframes.extract_keyframes(
        Path("m.mp4"), tmp_path, [Shot(0, 0.0, 1.5)], duration=1.5,
        warnings=warnings,
    )

    frames = sorted(p.name for p in (tmp_path / "frames").iterdir())
    assert frames == ["hook_0s.jpg", "hook_1s.jpg", "shot_000.jpg"]


# -- F-07: stale keyframe cache across re-studies ----------------------------

def test_restudy_regrabs_frames_at_new_boundaries(tmp_path, monkeypatch):
    """A leftover shot_000.jpg from a previous study (old boundary) must be
    re-extracted at the CURRENT shot start, not silently reused."""
    calls: list = []
    monkeypatch.setattr("myzing.study.keyframes.proc.run", grabbing_ffmpeg(calls))
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "shot_000.jpg").write_bytes(b"old-frame-from-4.2s")
    shots = [Shot(0, 2.0, 5.0)]                # detector now says 2.0s

    keyframes.extract_keyframes(Path("m.mp4"), tmp_path, shots, 5.0, [])

    shot_cmds = [c for c in calls if "shot_000" in c[-1]]
    assert shot_cmds, "stale shot_000.jpg reused instead of re-grabbed"
    assert shot_cmds[0][shot_cmds[0].index("-ss") + 1] == "2.000"
    assert (frames / "shot_000.jpg").read_bytes() == b"jpg"
    assert shots[0].keyframe == "frames/shot_000.jpg"


def test_restudy_clears_stale_leftover_frames(tmp_path, monkeypatch):
    """Fewer shots on re-study: frames from the old, longer shot list (and
    old hook frames) must not linger next to the fresh ones."""
    monkeypatch.setattr("myzing.study.keyframes.proc.run", grabbing_ffmpeg([]))
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "shot_007.jpg").write_bytes(b"old")
    (frames / "hook_9s.jpg").write_bytes(b"old")

    keyframes.extract_keyframes(
        Path("m.mp4"), tmp_path, [Shot(0, 0.0, 1.5)], duration=1.5, warnings=[]
    )

    names = sorted(p.name for p in frames.iterdir())
    assert names == ["hook_0s.jpg", "hook_1s.jpg", "shot_000.jpg"]


def test_ffmpeg_missing_degrades_with_warning(tmp_path, monkeypatch):
    def missing(cmd, timeout=None):
        raise ToolMissing("ffmpeg")
    monkeypatch.setattr("myzing.study.keyframes.proc.run", missing)
    shots = [Shot(0, 0.0, 2.0)]
    warnings: list[str] = []

    keyframes.extract_keyframes(Path("m.mp4"), tmp_path, shots, 2.0, warnings)

    assert shots[0].keyframe == ""
    assert any("could not be extracted" in w for w in warnings)
