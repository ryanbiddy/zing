"""Generated-media acceptance oracles for animated memes; no remote fixtures."""

from __future__ import annotations

import io
import json
import math
import struct
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:
    Image = ImageChops = ImageDraw = None

from myzing import cli, mcp_server, storage
from myzing.memes import MemeError
from myzing.memes import video as motion

pytestmark = pytest.mark.skipif(Image is None, reason="install myzing[memes] for render tests")


def run(*args):
    result = subprocess.run(list(map(str, args)), capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def probe(path):
    return json.loads(run("ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path))


def clip(path, *, seconds=3, audio=False, pattern=False, fps=10):
    command = ["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
               f"{'testsrc2=' if pattern else 'color=c=0x315779:'}s=320x180:r={fps}:d={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}", "-c:a", "aac"]
    run(*command, "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", path)
    return path


def frame(path, time):
    return Image.open(io.BytesIO(run("ffmpeg", "-v", "error", "-ss", time, "-i", path,
                                    "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"))).convert("RGB")


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr("myzing.memes.templates.build_opener", lambda *a: pytest.fail("render used network"))


@pytest.mark.ffmpeg
@pytest.mark.parametrize("layout", ["classic", "caption", "labels"])
@pytest.mark.parametrize("fit", ["cover", "contain"])
def test_timed_text_pixels_in_shared_layout_boxes(tmp_path, offline, monkeypatch, layout, fit):
    source = clip(tmp_path / "source.mp4")
    calls = []
    draw = motion._draw_layer

    def counted(*args):
        calls.append(1)
        return draw(*args)

    monkeypatch.setattr(motion, "_draw_layer", counted)
    options = {"regions": [[.25, .05, .5, .3], [.25, .65, .5, .3]]} if layout == "labels" else {}
    result = motion.render_meme_video(
        ["alpha", "beta"], video=str(source), layout=layout, fit=fit, width=320,
        fps=10, end=2, at=[0, .8], until=[.5, 1.5], out=str(tmp_path / "timed.mp4"), **options)
    assert len(calls) == 2  # one Pillow raster per text, regardless of frame count
    assert (result["width"], result["height"]) == (320, 320)
    # Classic boxes hug the top/bottom edges and caption beats stack at one
    # shared size in a bar that fits the text (meme E2E fix 4), so the boxes
    # are the text blocks, not the former fixed 23% bands / 26% bar halves.
    expected_boxes = {
        "classic": [[13, 10, 307, 45], [13, 275, 307, 310]],
        "caption": [[13, 7, 307, 38], [13, 40, 307, 71]],
        "labels": ([[80, 79, 240, 133], [80, 187, 240, 241]] if fit == "contain"
                   else [[18, 16, 302, 112], [18, 208, 302, 304]]),
    }
    assert [box["box"] for box in result["boxes"]] == expected_boxes[layout]
    samples = {t: frame(result["path"], t) for t in (.2, .6, 1, 1.8)}
    for box, active in zip(result["boxes"], (.2, 1)):
        ink = box["text_bbox"]
        x0, y0, x1, y1 = box["box"]
        assert x0 <= ink[0] < ink[2] <= x1 and y0 <= ink[1] < ink[3] <= y1
        if layout == "caption":
            assert ink[3] < 320 * .26
        for t, image in samples.items():
            colors = image.crop(tuple(ink)).getcolors(320 * 320)
            pixels = sum(n for n, rgb in colors if (max(rgb) < 65 if layout == "caption" else min(rgb) > 190))
            assert (pixels > 25) == (t == active), (layout, fit, t, box, pixels)
    if layout == "classic":
        assert result["boxes"][0]["wrapped_lines"] == ["ALPHA"]
        # Contain preserves the landscape source with dark padding; cover fills.
        corner = samples[.6].getpixel((2, 2))
        assert (max(corner) < 35) == (fit == "contain")
    if layout == "caption":
        assert min(samples[.6].getpixel((2, 2))) > 240
        assert max(samples[.6].getpixel((160, 230))) - min(samples[.6].getpixel((160, 230))) > 30
    assert not list(tmp_path.glob(".meme-*"))


@pytest.mark.ffmpeg
def test_cli_trim_dimensions_fps_and_audio(tmp_path, capsys, offline):
    directory = tmp_path / "a space's [clip]"
    directory.mkdir()
    source = clip(directory / "source.mp4", audio=True, pattern=True)
    target = directory / "result.mp4"
    assert cli.main(["meme", "render-video", "--video", str(source), "--text", "ready",
                     "--start", "1", "--end", "2.5", "--at", ".5", "--until", "1",
                     "--fps", "20", "--aspect", "16:9", "--width", "320", "--out", str(target), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    data = probe(target)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    a = next(s for s in data["streams"] if s["codec_type"] == "audio")
    assert v["codec_name"] == "h264" and a["codec_name"] == "aac"
    assert (v["width"], v["height"]) == (320, 180)
    assert Fraction(v["avg_frame_rate"]) == 20
    assert float(v["duration"]) == pytest.approx(1.5, abs=.05)
    assert float(a["duration"]) == pytest.approx(1.5, abs=.05)
    raw = run("ffmpeg", "-v", "error", "-i", target, "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-")
    samples = struct.unpack(f"<{len(raw) // 4}f", raw)
    assert math.sqrt(sum(v * v for v in samples) / len(samples)) > .04
    # Away from text, the trimmed first frame matches source t=1, not source t=0.
    actual = frame(target, .1).crop((0, 90, 320, 180))
    expected = frame(source, 1.1).crop((0, 90, 320, 180))
    wrong = frame(source, .1).crop((0, 90, 320, 180))
    difference = lambda im: sum(ImageChops.difference(actual, im).tobytes())
    assert difference(expected) < difference(wrong) * .25
    assert result["size_bytes"] == target.stat().st_size and result["has_audio"]
    assert "base64" not in json.dumps(result)
    assert motion.MemeVideoResult.from_dict({k: v for k, v in result.items() if k != "ok"}).to_dict() == {
        k: v for k, v in result.items() if k != "ok"}
    before = target.read_bytes()
    assert not mcp_server.h_meme_render_video(["replacement"], video=str(source), out=str(target))["ok"]
    assert target.read_bytes() == before
    assert mcp_server.h_meme_render_video(["replacement"], video=str(source), out=str(target),
                                        overwrite=True, width=320, end=1)["ok"]
    assert target.read_bytes() != before


@pytest.mark.ffmpeg
def test_gif_default_limits_palette_and_size_report(tmp_path, offline):
    source = clip(tmp_path / "moving.mp4", seconds=9, pattern=True)
    result = motion.render_meme_video(["motion"], video=str(source), aspect="16:9", width=800,
                                      fps=12, gif=True, out=str(tmp_path / "result.mp4"))
    gif = result["gif"]
    assert gif["width"] == 640 and gif["fps"] == 10 and gif["frames"] == 80
    assert gif["size_bytes"] == Path(gif["path"]).stat().st_size > 1000
    with Image.open(gif["path"]) as image:
        assert image.n_frames == 80 and image.width == 640
        durations = []
        first = image.convert("RGB")
        for i in range(image.n_frames):
            image.seek(i)
            durations.append(image.info["duration"])
        assert set(durations) == {100}
        assert sum(durations) == 8000
        assert ImageChops.difference(first, image.convert("RGB")).getbbox()
    assert result["duration"] == pytest.approx(9, abs=1 / 12)
    assert gif["duration"] <= 8


@pytest.mark.ffmpeg
def test_gif_input_ignores_loop_and_custom_gif_limits(tmp_path, offline):
    source = tmp_path / "source.dat"  # content detection, not a filename extension
    frames = [Image.new("RGB", (160, 100), (20 + i * 15, 60, 80)) for i in range(10)]
    frames[0].save(source, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    result = mcp_server.h_meme_render_video(["gif"], video=str(source), fps=10, width=320,
                                           gif=True, gif_width=160, gif_fps=4, gif_duration=.75,
                                           out=str(tmp_path / "gif-input.mp4"))
    assert result["ok"], result
    assert result["duration"] == pytest.approx(1, abs=.1)
    assert not result["has_audio"]
    with Image.open(result["gif"]["path"]) as gif:
        assert gif.width == 160 and gif.n_frames == 3
        delays = []
        for i in range(gif.n_frames):
            gif.seek(i)
            delays.append(gif.info["duration"])
        assert sum(delays) <= 750 and min(delays) >= 250
    early, late = frame(result["path"], .1), frame(result["path"], .8)
    assert late.getpixel((160, 200))[0] > early.getpixel((160, 200))[0] + 70


@pytest.mark.ffmpeg
def test_too_long_refused_and_explicit_trim_allowed(tmp_path, offline):
    source = clip(tmp_path / "long.mp4", seconds=31, fps=1)
    with pytest.raises(MemeError, match="Trim with --start/--end"):
        motion.render_meme_video(["long"], video=str(source), out=str(tmp_path / "no.mp4"))
    assert not (tmp_path / "no.mp4").exists()
    result = motion.render_meme_video(["short"], video=str(source), start=29, end=31,
                                      max_duration=2, fps=10, width=320, out=str(tmp_path / "short.mp4"))
    assert result["duration"] == pytest.approx(2, abs=.1)
    with pytest.raises(MemeError, match="source duration"):
        motion.render_meme_video(["bad"], video=str(source), end=32)


@pytest.mark.ffmpeg
def test_still_zoom_moves_image_but_text_stays_fixed(tmp_path, offline):
    source = tmp_path / "grid.png"
    image = Image.new("RGB", (640, 480), "#305070")
    draw = ImageDraw.Draw(image)
    for x in range(0, 640, 40):
        draw.rectangle((x, 160, x + 8, 400), fill="#a05040")
    image.save(source)
    result = motion.render_meme_video(["steady"], image=str(source), duration=2, zoom=.2, fps=10,
                                      width=320, out=str(tmp_path / "zoom.mp4"))
    early, late = frame(result["path"], 0), frame(result["path"], 1.9)
    area = (0, 100, 320, 250)
    assert ImageChops.difference(early.crop(area), late.crop(area)).getbbox()
    ink = tuple(result["boxes"][0]["text_bbox"])
    # Text masks stay put over a uniform area while the grid zooms.
    mask = lambda im: im.crop(ink).convert("L").point(lambda p: 255 if p > 200 else 0)
    changed = ImageChops.difference(mask(early), mask(late)).histogram()[255]
    assert changed < 10  # tolerate H.264 ringing at a few glyph-edge pixels
    assert not result["has_audio"] and result["duration"] == pytest.approx(2, abs=.1)


@pytest.mark.ffmpeg
def test_cached_template_and_oriented_still(tmp_path, zing_workspace, offline):
    blank = storage.workspace_root() / "memes/templates/drake.jpg"
    blank.parent.mkdir(parents=True)
    Image.new("RGB", (600, 600), "#345678").save(blank)
    result = motion.render_meme_video(["reject", "prefer"], template="drake", width=320,
                                      duration=.5, fps=10, out=str(tmp_path / "template.mp4"))
    assert result["layout"] == "labels" and result["fit"] == "contain"
    assert all(b["box"][0] >= 160 for b in result["boxes"])
    source = tmp_path / "portrait.jpg"
    image = Image.new("RGB", (400, 200), "#345678")
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, exif=exif)
    result = motion.render_meme_video(["upright"], image=str(source), aspect="original", width=320,
                                      duration=.5, fps=10, out=str(tmp_path / "portrait.mp4"))
    assert (result["width"], result["height"]) == (320, 640)


@pytest.mark.parametrize("options", [
    {"fps": 0}, {"fps": 61}, {"fps": 2.5}, {"width": 321}, {"width": 2000},
    {"start": -1}, {"start": float("nan")}, {"end": float("inf")}, {"max_duration": 31},
    {"duration": 31}, {"zoom": .3}, {"zoom": .1}, {"gif_fps": 11}, {"gif_width": 641},
    {"gif_duration": 9}, {"gif": "yes"}, {"overwrite": "yes"}, {"rotation": float("nan")},
    {"fit": "stretch"}, {"layout": "bad"}, {"regions": [[0, 0, 1, 1]]}, {"aspect": "bad"},
])
def test_invalid_options_are_actionable_data(options):
    result = mcp_server.h_meme_render_video(["hello"], video="missing.mp4", **options)
    assert not result["ok"] and result["error"]


def test_windows_validate_finite_order_and_count():
    for data in ({}, {"version": 2}, {"version": True}, {"version": 1}):
        with pytest.raises(MemeError):
            motion.MemeVideoResult.from_dict(data)
    for at, until in [([0], [1, 2]), ([float("nan"), 0], None), ([0, 3], None),
                      ([1, 0], [.5, 2]), ("bad", None), (None, [float("inf"), 2])]:
        with pytest.raises(MemeError):
            motion._windows(2, 2, at, until)
    assert motion._windows(2, 2, [0, 1.5], None) == [(0, 2), (1.5, 2)]


def test_source_and_destination_guards_before_ffprobe(tmp_path, monkeypatch, offline):
    monkeypatch.setattr(motion.shutil, "which", lambda name: name)
    monkeypatch.setattr(motion, "_run", lambda *a, **k: pytest.fail("unsafe request reached ffprobe"))
    source = tmp_path / "source.gif"
    source.write_bytes(b"source")
    for options, message in [
        ({"out": str(source)}, "differ"),
        ({"out": str(tmp_path / "source.mp4"), "gif": True, "overwrite": True}, "differ"),
        ({"video": "https://example.com/video.mp4"}, "local file"),
        ({"video": "//server/share/video.mp4"}, "local file"),
    ]:
        args = {"video": str(source), **options}
        with pytest.raises(MemeError, match=message):
            motion.render_meme_video(["hello"], **args)
    existing = tmp_path / "existing.mp4"
    existing.write_bytes(b"keep")
    with pytest.raises(MemeError, match="already exists"):
        motion.render_meme_video(["hello"], video=str(source), out=str(existing))
    assert existing.read_bytes() == b"keep"
    monkeypatch.setattr(motion, "MAX_BYTES", 2)
    with pytest.raises(MemeError, match="500 MiB"):
        motion.render_meme_video(["hello"], video=str(source))


def test_probe_rejects_oversized_unknown_and_invalid_duration(tmp_path, monkeypatch):
    for streams in [[], [{"codec_type": "video", "width": 10000, "height": 10000}],
                    [{"codec_type": "video", "width": 100, "height": 100, "duration": "nan"}]]:
        monkeypatch.setattr(motion, "_run", lambda *a, **k: json.dumps({"streams": streams}))
        with pytest.raises(MemeError):
            motion._probe(tmp_path / "input.mp4", "ffprobe")


def test_timeout_and_missing_dependencies_are_errors(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 20
        raise subprocess.TimeoutExpired(args[0], 20)

    monkeypatch.setattr(motion.subprocess, "run", timeout)
    with pytest.raises(MemeError, match="timed out after 20s"):
        motion._run(["ffprobe", "file"], timeout=20)
    monkeypatch.setattr(motion.shutil, "which", lambda name: None)
    result = mcp_server.h_meme_render_video(["hello"], video="input.mp4")
    assert not result["ok"] and "install FFmpeg" in result["error"]


def test_no_network_template_miss(tmp_path, zing_workspace, offline, monkeypatch):
    monkeypatch.setattr(motion.shutil, "which", lambda name: name)
    result = mcp_server.h_meme_render_video(["hello"], template="drake")
    assert not result["ok"] and "already be cached" in result["error"]


def test_atomic_publication_refuses_race(tmp_path):
    staged, target = tmp_path / "stage", tmp_path / "out"
    staged.write_bytes(b"new")
    target.write_bytes(b"keep")
    with pytest.raises(MemeError, match="already exists"):
        motion._publish(staged, target, False)
    assert target.read_bytes() == b"keep"


def test_failed_encode_preserves_existing_outputs_and_cleans_temp(tmp_path, monkeypatch):
    source, target = tmp_path / "source.mp4", tmp_path / "result.mp4"
    source.write_bytes(b"source")
    target.write_bytes(b"previous mp4")
    target.with_suffix(".gif").write_bytes(b"previous gif")
    monkeypatch.setattr(motion.shutil, "which", lambda name: name)
    monkeypatch.setattr(motion, "_probe", lambda *a: {
        "width": 320, "height": 180, "stream": 0, "duration": 1, "has_audio": False})
    monkeypatch.setattr(motion, "filter_script_args", lambda *a: ["-filter_complex", "unused"])

    def failed(command, **kwargs):
        Path(command[-1]).write_bytes(b"partial")
        raise MemeError("encoder failed")

    monkeypatch.setattr(motion, "_run", failed)
    with pytest.raises(MemeError, match="encoder failed"):
        motion.render_meme_video(["hello"], video=str(source), out=str(target), width=320,
                                 overwrite=True, gif=True)
    assert target.read_bytes() == b"previous mp4"
    assert target.with_suffix(".gif").read_bytes() == b"previous gif"
    assert not list(tmp_path.glob(".meme-*"))


@pytest.mark.parametrize("texts", [["x" * 71], ["x" * 60, "y" * 60], ["that moment when"]])
def test_animated_text_uses_same_caps_and_validators(texts):
    result = mcp_server.h_meme_render_video(texts, video="missing.mp4")
    assert not result["ok"] and "Source is not" not in result["error"]
