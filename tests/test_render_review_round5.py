"""Render review regressions: publication, local inputs and media fidelity."""

import errno
import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from myzing.composition import AssetRef, Composition, CompositionClip
from myzing.render import captions, composition, deliveries, encoding, framing, hyperframes_adapter as hf, pipeline
from myzing.render.validation import EDLValidationError, MediaInfo, validate_edl
from myzing.schemas import CaptionSpec, Clip, EDL, Word


def plan(source, width=640, height=360, end=1):
    return Composition(assets=[AssetRef("a", str(source), None)],
                       clips=[CompositionClip(str(source), 0, end, 0, id="c", asset_id="a")],
                       width=width, height=height)


@pytest.fixture
def fake_render(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(pipeline, "probe_media", lambda *a, **k: MediaInfo(10, True, False))
    monkeypatch.setattr(pipeline.shutil, "which", lambda name: name)
    monkeypatch.setattr(pipeline, "filter_script_args", lambda exe, path: ["-/filter_complex", str(path)])

    def run(command, **kwargs):
        Path(command[-1]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(pipeline.subprocess, "run", run)
    return source


@pytest.mark.parametrize("failure", ["copy", "flush", "replace", None])
def test_cross_volume_publication_preserves_previous_output(tmp_path, monkeypatch, failure):
    staged, output = tmp_path / "staged.mp4", tmp_path / "final.mp4"
    staged.write_bytes(b"new video")
    output.write_bytes(b"previous video")
    replace, copy, fsync = os.replace, pipeline.shutil.copyfileobj, os.fsync
    flushed = []

    def cross_device(src, dst):
        if Path(src) == staged:
            raise OSError(errno.EXDEV, "cross-device link")
        assert Path(src).parent == output.parent
        assert flushed
        assert output.read_bytes() == b"previous video"
        if failure == "replace":
            raise OSError(errno.EACCES, "replacement denied")
        replace(src, dst)

    def copying(src, dst, *args):
        if failure == "copy":
            dst.write(b"partial")
            raise OSError(errno.ENOSPC, "disk full")
        copy(src, dst, *args)

    def flush(fd):
        flushed.append(fd)
        if failure == "flush":
            raise OSError(errno.ENOSPC, "disk full")
        fsync(fd)

    monkeypatch.setattr(pipeline.os, "replace", cross_device)
    monkeypatch.setattr(pipeline.shutil, "copyfileobj", copying)
    monkeypatch.setattr(pipeline.os, "fsync", flush)
    if failure:
        with pytest.raises(pipeline.RenderError):
            pipeline._publish_output(staged, output)
        assert output.read_bytes() == b"previous video"
        assert staged.read_bytes() == b"new video"
    else:
        pipeline._publish_output(staged, output)
        assert output.read_bytes() == b"new video"
        assert not staged.exists()
    assert set(tmp_path.iterdir()) == ({output, staged} if failure else {output})


@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize("previous", [False, True])
def test_failed_delivery_only_quarantines_current_artifact(tmp_path, monkeypatch, published, previous):
    p = plan(tmp_path / "source.mp4")
    video = tmp_path / "out.16x9.mp4"
    failed = video.with_suffix(".mp4.failed")
    failed.write_bytes(b"previous diagnostic")
    if previous:
        video.write_bytes(b"previous video")
    monkeypatch.setattr(deliveries, "delivery_plans", lambda *a, **k: (
        {"16:9": p}, {"resolution": {"16:9": {}}}))

    def render(*args, **kwargs):
        if published:
            staged = tmp_path / "current.mp4"
            staged.write_bytes(b"current video")
            staged.replace(video)
        raise pipeline.RenderError("render failed")

    monkeypatch.setattr(deliveries, "render_composition", render)
    result = deliveries._render_deliveries(p, tmp_path / "out.mp4", tmp_path / "work", ["16:9"],
        tmp_path / "report.json", tmp_path, None, None, None, "ffmpeg", "ffprobe", True)
    row = result["deliveries"]["16:9"]
    assert row["status"] == "failed" and "video" not in row
    assert failed.read_bytes() == b"previous diagnostic"
    if published:
        assert not video.exists()
        assert Path(row["failed_artifact"]).read_bytes() == b"current video"
    else:
        assert "failed_artifact" not in row
        assert video.read_bytes() == b"previous video" if previous else not video.exists()


def test_two_pass_logs_decode_utf8_and_replace_bad_bytes(tmp_path, monkeypatch):
    from myzing.composition.encoding import DeliveryEncoding

    passes = []
    log = "Input: Ё.mp4".encode("utf-8") + b"\xff"

    def run(command, **kwargs):
        text = log.decode(kwargs.get("encoding", "cp1252"), errors=kwargs.get("errors", "strict"))
        if "-pass" in command:
            passes.append(command[command.index("-pass") + 1])
            Path(command[-1]).write_bytes(b"video")
            return subprocess.CompletedProcess(command, 0, "", text)
        return subprocess.CompletedProcess(command, 0, "10\n20\n", text)

    monkeypatch.setattr(encoding.subprocess, "run", run)
    command = ["ffmpeg", "-loglevel", "error", "-crf", "20", str(tmp_path / "rendered.mp4")]
    _, _, receipt = encoding.encode(command, DeliveryEncoding(video_bitrate_kbps=1000),
                                    1, 640, 360, 30, tmp_path)
    assert passes == ["1", "2"]
    assert receipt["audio_bytes"] == 30
    assert (tmp_path / "x264-budget.log").read_text(encoding="utf-8") == "Input: Ё.mp4\ufffd"


@pytest.mark.parametrize("position", ["top", "center", "lower", "bottom"])
def test_four_by_five_composition_and_caption_anchor(tmp_path, position):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    prepared = composition.prepare_composition(plan(source, 1080, 1350), tmp_path)
    validated = validate_edl(prepared.edl, tmp_path, lambda _: MediaInfo(1, True, False),
                             resolved_assets=prepared.assets)
    assert validated.output_preset
    x, y = captions.caption_anchor(position, 1080, 1350)
    assert x == 540 and 0 < y < 1350
    target = captions.generate_ass([CaptionSpec("Hello", 0, 1, word_timed=False, position=position)],
                                   1080, 1350, tmp_path / "captions.ass")
    assert rf"\pos({x},{y})" in target.read_text(encoding="utf-8")


@pytest.mark.parametrize("word_timed", [False, True])
def test_legacy_captions_preserve_literal_ass_escapes(tmp_path, word_timed):
    import pysubs2

    text = r"C:\New\name\here\{literal}"
    caption = CaptionSpec(text, 0, 1, word_timed=word_timed, all_caps=False,
                          words=[Word(text, 0, 1)] if word_timed else [])
    output = captions.generate_ass([caption], 640, 360, tmp_path / "captions.ass")
    event = pysubs2.load(output, encoding="utf-8").events[0].text
    assert "C:\\\u2060New\\\u2060name\\\u2060here\\\u2060\\{literal\\}" in event
    assert captions._ass_text("one\ntwo") == r"one\Ntwo"


@pytest.mark.parametrize("version", [1, 2])
def test_long_output_name_does_not_lengthen_scratch_name(fake_render, tmp_path, version):
    output = tmp_path / ("a" * 240 + ".mp4")
    if version == 1:
        pipeline.render_edl(EDL(clips=[Clip(str(fake_render), 0, 1, 0)]), output)
    else:
        composition.render_composition(plan(fake_render), output)
    assert output.read_bytes() == b"rendered"
    assert not [p for p in tmp_path.iterdir() if p.is_dir()]


@pytest.mark.parametrize("include_color", [False, True])
@pytest.mark.parametrize("video", [{"duration": "2"}, {"tags": {"DURATION": "00:00:02.000"}}])
def test_probe_gets_video_duration_for_ordinary_cuts(tmp_path, monkeypatch, include_color, video):
    monkeypatch.setattr(pipeline.shutil, "which", lambda name: name)

    def probe(command, **kwargs):
        entries = command[command.index("stream=codec_type"):] if "stream=codec_type" in command else command
        selected = next(arg for arg in entries if arg.startswith("stream="))
        stream = {"codec_type": "video"}
        if "duration" in selected:
            stream.update(video)
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "format": {"duration": "10"}, "streams": [stream, {"codec_type": "audio"}]}), "")

    monkeypatch.setattr(pipeline.subprocess, "run", probe)
    info = pipeline.probe_media(tmp_path / "source.mp4", include_color=include_color)
    assert info.video_duration == 2
    assert info.duration == 10 and info.has_audio


@pytest.mark.parametrize("version", [1, 2])
def test_ordinary_cuts_cannot_outlast_video(fake_render, tmp_path, monkeypatch, version):
    monkeypatch.setattr(pipeline, "probe_media", lambda *a, **k: MediaInfo(10, True, True, video_duration=2))
    with pytest.raises(EDLValidationError, match="exceeds source duration 2.000"):
        if version == 1:
            pipeline.render_edl(EDL(clips=[Clip(str(fake_render), 0, 8, 0)]), tmp_path / "out.mp4")
        else:
            composition.render_composition(plan(fake_render, end=8), tmp_path / "out.mp4")
    assert not (tmp_path / "out.mp4").exists()


@pytest.mark.parametrize("helper", ["render", "audio", "color"])
@pytest.mark.parametrize("source", [r"\\127.0.0.1\share\clip.mp4", "//127.0.0.1/share/clip.mp4",
                                    r"\\?\UNC\127.0.0.1\share\clip.mp4"])
def test_network_paths_are_rejected_before_filesystem_access(tmp_path, monkeypatch, helper, source):
    from myzing.audio.media import AudioError, local_file
    from myzing.color import ColorError
    from myzing.color.media import local_video
    from myzing.render.validation import _resolve_media

    def unexpected(*args, **kwargs):
        pytest.fail("network path reached the filesystem")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", unexpected)
        patch.setattr(Path, "is_file", unexpected)
        with pytest.raises((EDLValidationError, AudioError, ColorError), match="local|network"):
            if helper == "render":
                _resolve_media(source, tmp_path, "clips[0].src")
            else:
                (local_file if helper == "audio" else local_video)(source)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("name", ["captions.ass", "filter graph.txt", "rendered.mp4"])
@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_work_targets_cannot_alias_inputs(fake_render, tmp_path, monkeypatch, version, name, link):
    work = tmp_path / "work"
    work.mkdir()
    target = work / name
    os.link(fake_render, target)
    if link == "symlink":
        is_symlink = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda p: p == target or is_symlink(p))  # No Windows symlink privilege needed.
    with pytest.raises(pipeline.RenderError, match="work.*(input|symlink)"):
        if version == 1:
            pipeline.render_edl(EDL(clips=[Clip(str(fake_render), 0, 1, 0)]), tmp_path / "out.mp4", work_dir=work)
        else:
            composition.render_composition(plan(fake_render), tmp_path / "out.mp4", work_dir=work)
    assert fake_render.read_bytes() == b"source"
    assert not (tmp_path / "out.mp4").exists()


@pytest.mark.parametrize("error", [KeyboardInterrupt, OSError])
@pytest.mark.parametrize("cleanup_timeout", [False, True])
def test_hyperframes_abnormal_exit_stops_tree_reaps_and_closes_pipes(tmp_path, monkeypatch, error, cleanup_timeout):
    calls, killed, reaped = [], [], []

    class Process:
        pid = 123456
        stdout = io.BytesIO()
        stderr = None
        stdin = None

        def communicate(self, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise error()
            if cleanup_timeout:
                raise subprocess.TimeoutExpired("node", timeout)
            return b"stopped", None

        def kill(self):
            killed.append(self.pid)

        def wait(self, timeout):
            reaped.append(timeout)

    process = Process()
    monkeypatch.setattr(hf.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(hf.subprocess, "run", lambda cmd, **k: killed.append(cmd))
    if os.name != "nt":
        monkeypatch.setattr(hf.os, "killpg", lambda pid, sig: killed.append(pid))
    with pytest.raises(error):
        hf._run_process(["node"], env={}, timeout=1, log=tmp_path / "hyperframes.log")
    assert killed and calls == [1, 15]
    assert process.stdout.closed
    assert reaped == ([15] if cleanup_timeout else [])


def test_cached_network_asset_is_rejected_before_stat(tmp_path, monkeypatch):
    from myzing.render.validation import resolve_assets

    def unexpected(*args, **kwargs):
        pytest.fail("cached network asset reached the filesystem")

    edl = EDL(clips=[Clip("source", 0, 1, 0)])
    with monkeypatch.context() as patch:
        patch.setattr(Path, "is_file", unexpected)
        with pytest.raises(EDLValidationError, match="network"):
            resolve_assets(edl, tmp_path, resolved_assets={"source": Path(r"\\127.0.0.1\share\clip.mp4")})


@pytest.mark.parametrize("probe", ["media", "dimensions", "overlay"])
def test_render_probes_decode_utf8_logs(tmp_path, monkeypatch, probe):
    payload = {"format": {"duration": "1"}, "streams": [{"codec_type": "video", "duration": "1",
        "width": 640, "height": 360, "avg_frame_rate": "30/1", "nb_read_frames": "30"}]}

    def run(command, **kwargs):
        stderr = ("Ё.mp4".encode("utf-8") + b"\xff").decode(
            kwargs.get("encoding", "cp1252"), errors=kwargs.get("errors", "strict"))
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), stderr)

    monkeypatch.setattr(pipeline.subprocess, "run", run)
    monkeypatch.setattr(pipeline.shutil, "which", lambda name: name)
    source = tmp_path / "Ё.mp4"
    if probe == "media":
        assert pipeline.probe_media(source).duration == 1
    elif probe == "dimensions":
        assert framing.probe_dimensions(source) == (640, 360)
    else:
        monkeypatch.setattr(hf, "validate_plan", lambda p: p)
        assert hf.verify_output(source, {"width": 640, "height": 360, "fps": 30, "duration": 1,
                                        "background": {}}) == payload


@pytest.mark.ffmpeg
@pytest.mark.parametrize("version", [1, 2])
def test_default_framing_preserves_anamorphic_display_aspect(tmp_path, version):
    source, output = tmp_path / "anamorphic.mp4", tmp_path / "out.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=white:s=720x576:r=30:d=0.2",
                    "-vf", "setsar=16/15", "-c:v", "libx264", str(source)],
                   check=True, capture_output=True)
    if version == 1:
        pipeline.render_edl(EDL(clips=[Clip(str(source), 0, .2, 0)], width=400, height=400), output)
    else:
        composition.render_composition(plan(source, 400, 400, .2), output)
    pixels = subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1",
                             "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"],
                            check=True, capture_output=True).stdout
    assert len(pixels) == 400 * 400
    assert pixels[45 * 400 + 200] < 10
    assert pixels[60 * 400 + 200] > 240


@pytest.mark.ffmpeg
def test_four_by_five_composition_renders(tmp_path):
    source, output = tmp_path / "source.mp4", tmp_path / "out.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=160x200:r=30:d=0.2",
                    "-c:v", "libx264", str(source)], check=True, capture_output=True)
    result = composition.render_composition(plan(source, 160, 200, .2), output)
    assert framing.probe_dimensions(output) == (160, 200)
    assert result.duration == pytest.approx(.2)
