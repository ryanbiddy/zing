from __future__ import annotations

import errno
import subprocess
from pathlib import Path

import pytest

from myzing.render import pipeline
from myzing.render.pipeline import RenderError, probe_media, render_edl
from myzing.render.validation import MediaInfo
from myzing.schemas import Clip, EDL


def test_renderer_refuses_to_overwrite_input_media(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        pipeline,
        "probe_media",
        lambda path, ffprobe: MediaInfo(1.0, True, False),
    )
    edl = EDL(clips=[Clip(str(source), 0.0, 1.0, 0.0)])

    with pytest.raises(RenderError, match="must not overwrite"):
        render_edl(edl, source, base_dir=tmp_path)


def test_probe_wraps_subprocess_timeout(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(pipeline.shutil, "which", lambda binary: binary)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffprobe", 30)

    monkeypatch.setattr(pipeline.subprocess, "run", timeout)

    with pytest.raises(RenderError, match="could not run ffprobe"):
        probe_media(source)


def test_publish_falls_back_for_cross_device_work_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    staged = tmp_path / "work" / "rendered.mp4"
    staged.parent.mkdir()
    staged.write_bytes(b"rendered")
    output = tmp_path / "output" / "final.mp4"

    def cross_device(source: Path, destination: Path) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    def move(source: Path, destination: Path) -> None:
        destination.write_bytes(source.read_bytes())
        source.unlink()

    monkeypatch.setattr(pipeline.os, "replace", cross_device)
    monkeypatch.setattr(pipeline.shutil, "move", move)

    pipeline._publish_output(staged, output)

    assert output.read_bytes() == b"rendered"
    assert not staged.exists()
