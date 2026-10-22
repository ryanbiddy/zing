"""Real rendered pixels, audio alignment, text geometry and offline CLI/MCP acceptance."""

from __future__ import annotations

import json
import socket
import subprocess
import urllib.request
from pathlib import Path

import pytest

from myzing import storage
from myzing.inspect import InspectionError
from myzing.inspect.media import Decoder
from myzing.inspect.timeline import WORD, inspect_timeline
from myzing.render.pipeline import render_edl
from myzing.schemas import Breakdown, CaptionSpec, Clip, EDL, VideoMeta, Word

pytestmark = pytest.mark.ffmpeg


def ffmpeg(*args):
    result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def make_video(path, color="red", audio=False):
    args = ["-f", "lavfi", "-i", f"color={color}:s=160x90:r=30:d=4"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000:duration=4",
                 "-af", "volume=4", "-c:a", "aac"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    ffmpeg(*args)


@pytest.fixture
def offline(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Inspection attempted network access")
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    for key in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")


@pytest.fixture
def two_cut(tmp_path):
    pytest.importorskip("PIL.Image")
    # Spaces/apostrophes/Unicode exercise argument-list and portable EDL paths.
    root = tmp_path / "editor's clips é"
    root.mkdir()
    for color in ("red", "green", "blue"):
        make_video(root / f"{color}.mp4", color, audio=True)
    edl = EDL(clips=[Clip("red.mp4", .5, 1.5, 0), Clip("green.mp4", 1, 2, 1),
                     Clip("blue.mp4", .75, 2.75, 2)], width=160, height=90, fps=30)
    output = root / "rendered.mp4"
    # Render actual Zing output, then attach review captions without burning them
    # over the known-color pixels used as the independent cut oracle.
    render_edl(edl, output, base_dir=root)
    edl.captions = [CaptionSpec("first next", .8, 2.2, words=[
        Word("first", .8, 1.2), Word("next", 1.8, 2.2)])]
    edl_path = root / "draft-edl.json"
    edl_path.write_text(edl.to_json(), encoding="utf-8")
    return output, edl_path, edl


def test_rendered_two_cuts_and_transcript_pixels(two_cut, offline):
    from PIL import Image, ImageColor
    video, edl_path, _ = two_cut
    result = inspect_timeline(video, video.with_suffix(".png"), edl=edl_path)
    assert [r["center"] for r in result.rows] == [1, 2]
    assert result.cuts[0]["left"]["source_time"] == 1.5
    assert result.cuts[0]["right"]["source_time"] == 1
    assert result.cuts[1]["left"]["source_time"] == 2
    assert result.cuts[1]["right"]["source_time"] == .75
    with Image.open(result.path) as png:
        assert png.size == (result.width, result.height)
        for row in result.rows:
            assert row["frames"][2]["output_time"] == row["center"]
            assert row["frames"][2]["x"] == result.width // 2
            for frame in row["frames"]:
                left, top, width, height = frame["rect"]
                # Avoid the amber cut line through the central thumbnail.
                rgb = png.getpixel((left + width // 2 + 10, top + height // 2))
                dominant = max(range(3), key=lambda i: rgb[i])
                expected = 0 if frame["output_time"] < 1 else 1 if frame["output_time"] < 2 else 2
                assert dominant == expected, (frame, rgb)
                assert rgb[expected] > 100
            for word in row["words"]:
                # Independently compute the projection. Tolerance: one PNG pixel.
                for field, t in [("x_start", max(row["start"], word["start"])),
                                  ("x_end", min(row["end"], word["end"]))]:
                    expected_x = 40 + (t - row["start"]) / (row["end"] - row["start"]) * (result.width - 80)
                    assert abs(word[field] - expected_x) <= 1
                    assert png.getpixel((word[field], word["bar_y"])) == ImageColor.getrgb(WORD)
                left, top, width, height = word["text_box"]
                assert abs(left + width / 2 - word["x_center"]) <= 1
                # Check the actual glyph pixels too; font side bearings may
                # differ from the interval anchor by up to three pixels.
                # Include antialiased edges: exact foreground equality selects
                # only the heaviest stems and biases thin glyphs' bounding boxes.
                ink = [px for px in range(left, left + width)
                       if any(min(png.getpixel((px, py))) > 60
                              for py in range(top, top + height))]
                assert ink
                assert abs((min(ink) + max(ink)) / 2 - word["x_center"]) <= 3
        assert all(r["waveform"]["peak_rms"] > .1 for r in result.rows)


def test_breakdown_source_words_translate_into_rendered_output(two_cut, offline, zing_workspace):
    video, edl_path, edl = two_cut
    source = video.parent / "green.mp4"
    breakdown = Breakdown(VideoMeta(str(source), "file", duration=4, media_path=str(source)),
                          words=[Word("before", .1, .3), Word("green", 1.1, 1.4), Word("edge", 1.9, 2.2)])
    storage.save_breakdown(breakdown, slug="green")
    result = inspect_timeline(video, video.parent / "source-words.png", edl=edl_path,
                              breakdown="green", start=.5, end=2.5)
    assert result.transcript_origin == "breakdown:green:source-to-output"
    words = result.rows[0]["words"]
    assert [w["text"] for w in words] == ["green", "edge"]
    assert words[0]["start"] == pytest.approx(1.1)
    assert words[1]["end"] == pytest.approx(2)
    assert words[0]["x_start"] == pytest.approx(40 + .6 / 2 * 1520, abs=1)


def test_no_audio_range_overwrite_and_end_guard(tmp_path, offline):
    pytest.importorskip("PIL.Image")
    video = tmp_path / "silent.mp4"
    make_video(video)
    out = tmp_path / "review.png"
    result = inspect_timeline(video, out, start=3, end=4, frames=5)
    assert result.rows[0]["waveform"]["has_audio"] is False
    assert result.rows[0]["frames"][-1]["output_time"] < 4
    before = out.read_bytes()
    with pytest.raises(InspectionError, match="already exists"):
        inspect_timeline(video, out)
    assert out.read_bytes() == before
    inspect_timeline(video, out, around=1, overwrite=True)
    assert out.read_bytes() != before


def test_waveform_uses_same_time_axis_as_frames(tmp_path, offline):
    pytest.importorskip("PIL.Image")
    from PIL import Image, ImageColor
    from myzing.inspect.timeline import WAVE
    video = tmp_path / "pulse.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=red:s=160x90:r=30:d=3", "-f", "lavfi", "-i",
           "aevalsrc=if(between(t\\,1.4\\,1.6)\\,0.8*sin(2*PI*440*t)\\,0):s=8000:d=3",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(video))
    result = inspect_timeline(video, tmp_path / "pulse.png", start=1, end=2)
    row = result.rows[0]
    x0, y, width, height = row["waveform"]["rect"]
    with Image.open(result.path) as png:
        # The loud pulse is at 1.5s: exactly the middle of this zoomed row.
        hits = [x for x in range(x0, x0 + width) if png.getpixel((x, y + height // 2 - 8)) == ImageColor.getrgb(WAVE)]
    assert hits
    assert abs((min(hits) + max(hits)) / 2 - 800) <= 12  # 8 ms including AAC ringing
    assert 40 + .35 * 1520 < min(hits) < 40 + .45 * 1520
    assert row["frames"][2]["output_time"] == 1.5


def test_real_ffmpeg_failure_is_clear_and_leaves_no_png(tmp_path, monkeypatch):
    pytest.importorskip("PIL.Image")
    video = tmp_path / "input.mp4"
    make_video(video, audio=True)
    # A real failing FFmpeg call after successful ffprobe and frame decoding.
    original_run = Decoder.run
    def run(self, command, operation):
        if "waveform" in operation:
            at = command.index("-f")
            command[at:at] = ["-af", "zing_filter_does_not_exist"]
        return original_run(self, command, operation)
    monkeypatch.setattr(Decoder, "run", run)
    out = tmp_path / "failed.png"
    with pytest.raises(InspectionError, match="ffmpeg failed during waveform.*") as error:
        inspect_timeline(video, out, start=0, end=1)
    assert "zing_filter_does_not_exist" in str(error.value)
    assert not out.exists()


def test_cli_and_mcp_inspect_offline(tmp_path, offline, capsys, zing_workspace):
    pytest.importorskip("PIL.Image")
    from myzing.cli import main
    from myzing.mcp_server import h_inspect_timeline
    video = tmp_path / "video.mp4"
    make_video(video)
    storage.save_breakdown(Breakdown(VideoMeta(str(video), "file", duration=4),
                                    words=[Word("visible", .8, 1.2)]), slug="sample")
    assert main(["inspect", "timeline", str(video), "--around", "1", "--out", str(tmp_path / "cli.png"),
                 "--breakdown", "sample", "--json"]) == 0
    cli_result = json.loads(capsys.readouterr().out)
    assert cli_result["rows"][0]["words"][0]["text"] == "visible"
    mcp_result = h_inspect_timeline(str(video), str(tmp_path / "mcp.png"), around=1, breakdown="sample")
    assert mcp_result["ok"]
    assert Path(mcp_result["path"]).is_file()
    assert mcp_result["rows"] == cli_result["rows"]
    json.dumps(mcp_result)
