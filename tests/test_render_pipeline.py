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


def test_directory_creation_translates_os_error_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    directory = tmp_path / "render-output"

    def full_disk(path: Path, *args, **kwargs) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "mkdir", full_disk)

    with pytest.raises(
        RenderError,
        match="could not create scratch directory:.*No space left on device",
    ):
        pipeline._create_directory(
            directory,
            "could not create scratch directory",
        )


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


@pytest.mark.parametrize(
    "banner,expected",
    [
        ("ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023", ["-filter_complex_script", "g.txt"]),
        ("ffmpeg version 7.0.2-static https://johnvansickle.com", ["-/filter_complex", "g.txt"]),
        ("ffmpeg version 9.0.2-essentials_build-www.gyan.dev Copyright", ["-/filter_complex", "g.txt"]),
        ("ffmpeg version n8.1.2 Copyright (c) 2000-2026", ["-/filter_complex", "g.txt"]),
        ("ffmpeg version N-118000-gabcdef Copyright", ["-/filter_complex", "g.txt"]),
        ("", ["-/filter_complex", "g.txt"]),
    ],
)
def test_filter_script_args_follow_ffmpeg_major_version(monkeypatch, banner, expected):
    import subprocess as _subprocess

    from myzing.render import pipeline

    pipeline.ffmpeg_major_version.cache_clear()
    monkeypatch.setattr(
        pipeline.subprocess, "run",
        lambda *a, **k: _subprocess.CompletedProcess(a[0], 0, stdout=banner, stderr=""),
    )
    try:
        assert pipeline.filter_script_args("ffmpeg-under-test", Path("g.txt")) == expected
    finally:
        pipeline.ffmpeg_major_version.cache_clear()
