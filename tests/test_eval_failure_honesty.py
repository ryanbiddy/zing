from __future__ import annotations

import errno
import os
import subprocess
from pathlib import Path

import pytest

from myzing import mcp_server, storage
from myzing.render import pipeline
from myzing.render.pipeline import RenderError, probe_media, render_edl
from myzing.render.validation import MediaInfo
from myzing.schemas import Clip, EDL


def test_missing_study_binary_names_tool_and_recovery(
    zing_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_server.shutil, "which", lambda binary: None)

    result = mcp_server.h_study_video("https://example.invalid/video")

    assert result["ok"] is False
    assert "ffmpeg not found" in result["error"]
    assert "zing doctor" in result["error"]


def test_missing_render_probe_binary_names_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(pipeline.shutil, "which", lambda binary: None)

    with pytest.raises(
        RenderError,
        match="ffprobe executable not found: absent-probe",
    ):
        probe_media(source, ffprobe="absent-probe")


def test_interrupted_study_becomes_terminal_and_restartable(
    zing_workspace: Path,
) -> None:
    slug = "failure-honesty-interrupted"
    storage.write_status(
        slug,
        state="running",
        phase="audio",
        pid=os.getpid(),
        heartbeat_at=mcp_server._now(),
        started_at=mcp_server._now(),
    )

    result = mcp_server.h_get_breakdown(slug)

    assert result["ok"] is False
    assert result["state"] == "failed"
    assert "study interrupted" in result["error"]
    assert "worker thread" in result["error"]
    assert "study_video again" in result["error"]
    assert storage.read_status(slug)["state"] == "failed"


def test_corrupt_media_names_probe_input_and_decoder_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "corrupt.mp4"
    source.write_bytes(b"not a video")
    monkeypatch.setattr(pipeline.shutil, "which", lambda binary: binary)
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stdout="",
            stderr="Invalid data found when processing input",
        ),
    )

    with pytest.raises(RenderError) as failure:
        probe_media(source)

    message = str(failure.value)
    assert str(source) in message
    assert "Invalid data found when processing input" in message


def test_full_output_disk_names_directory_and_preserves_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output_dir = tmp_path / "full-disk"
    output = output_dir / "draft.mp4"
    edl = EDL(clips=[Clip(str(source), 0.0, 1.0, 0.0)])
    monkeypatch.setattr(
        pipeline,
        "probe_media",
        lambda path, ffprobe: MediaInfo(1.0, True, False),
    )
    real_mkdir = Path.mkdir

    def full_disk(directory: Path, *args, **kwargs) -> None:
        if directory == output_dir:
            raise OSError(errno.ENOSPC, "No space left on device")
        real_mkdir(directory, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", full_disk)

    with pytest.raises(RenderError) as failure:
        render_edl(edl, output, base_dir=tmp_path)

    message = str(failure.value)
    assert str(output_dir) in message
    assert "No space left on device" in message
