from __future__ import annotations

import errno
import subprocess
from pathlib import Path

import pytest

from myzing.render import pipeline
from myzing.ffmpeg_capabilities import FFmpegCapabilityError
from myzing.render.pipeline import RenderError, probe_media, render_edl
from myzing.render.validation import MediaInfo
from myzing.schemas import CaptionSpec, Clip, EDL


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


def test_caption_preflight_fails_before_media_or_files(tmp_path, monkeypatch):
    output = tmp_path / "new-output" / "video.mp4"
    work = tmp_path / "new-work"
    edl = EDL(
        clips=[Clip("missing.mp4", 0.0, 1.0, 0.0)],
        captions=[CaptionSpec("hello", 0.0, 1.0, word_timed=False)],
    )
    selected = []

    def missing(ffmpeg):
        selected.append(ffmpeg)
        raise FFmpegCapabilityError("this FFmpeg build has no libass support")

    def unexpected(*args, **kwargs):
        pytest.fail("caption preflight must precede media probes and ASS authoring")

    monkeypatch.setattr(pipeline, "caption_filter", missing)
    monkeypatch.setattr(pipeline, "probe_media", unexpected)
    monkeypatch.setattr(pipeline, "generate_ass", unexpected)
    with pytest.raises(RenderError, match="no libass"):
        render_edl(edl, output, work_dir=work, ffmpeg="chosen-ffmpeg")
    assert selected == ["chosen-ffmpeg"]
    assert not output.parent.exists()
    assert not work.exists()


def test_uncaptioned_render_does_not_probe_caption_filters(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("uncaptioned renders do not need libass")

    monkeypatch.setattr(pipeline, "caption_filter", unexpected)
    edl = EDL(clips=[Clip("missing.mp4", 0.0, 1.0, 0.0)])
    assert pipeline.preflight_captions(edl, "ffmpeg") == "ass"


def test_subtitles_fallback_reaches_executed_graph(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    edl = EDL(
        clips=[Clip(str(source), 0.0, 1.0, 0.0)],
        captions=[CaptionSpec("hello", 0.0, 1.0, word_timed=False)],
    )
    monkeypatch.setattr(pipeline, "caption_filter", lambda _: "subtitles")
    monkeypatch.setattr(pipeline, "probe_media", lambda *a: MediaInfo(1.0, True, False))
    monkeypatch.setattr(pipeline.shutil, "which", lambda name: name)
    monkeypatch.setattr(pipeline, "generate_ass", lambda *a: None)
    monkeypatch.setattr(pipeline, "filter_script_args", lambda exe, path: ["-/filter_complex", str(path)])

    def run(command, **kwargs):
        Path(command[-1]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(pipeline.subprocess, "run", run)
    result = render_edl(edl, tmp_path / "out.mp4", work_dir=tmp_path / "work")
    assert "[video_concat]subtitles=filename='captions.ass':" in result.filtergraph
    assert result.output_path.read_bytes() == b"rendered"


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
