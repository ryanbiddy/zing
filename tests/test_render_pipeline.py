from __future__ import annotations

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
