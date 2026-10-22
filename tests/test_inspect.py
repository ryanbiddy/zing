"""Coordinate, limits and API failure contracts; no media or network required."""

from __future__ import annotations

import builtins
import json
import subprocess
from pathlib import Path

import pytest

from myzing.inspect import InspectionError
from myzing.inspect.media import Decoder
from myzing.inspect.timeline import InspectionResult, _pillow, plan_ranges, time_to_x
from myzing.inspect.timing import (TimeSpan, build_time_map, cut_points,
                                  output_to_source, source_words_to_output, validate_words)
from myzing.schemas import Clip, EDL, Word


def test_mapping_reordered_and_repeated_source(tmp_path):
    edl = EDL(clips=[Clip("a.mp4", 8, 10, 3), Clip("a.mp4", 4, 7, 0)])
    spans = build_time_map(edl, tmp_path)
    assert output_to_source(spans, 2.75)["source_time"] == 6.75
    assert output_to_source(spans, 3)["source_time"] == 8
    assert output_to_source(spans, 3)["clip_index"] == 0
    assert cut_points(spans) == [{"output_time": 3, "left": {
        "clip_index": 1, "source": str(tmp_path / "a.mp4"), "source_time": 7},
        "right": {"clip_index": 0, "source": str(tmp_path / "a.mp4"), "source_time": 8}}]
    for t in (-1, 5, float("nan")):
        with pytest.raises(InspectionError):
            output_to_source(spans, t)
    assert TimeSpan.from_dict(spans[0].to_dict()) == spans[0]
    with pytest.raises(InspectionError, match="version"):
        TimeSpan.from_dict({"version": 2})


def test_source_word_clipping_and_repetition(tmp_path):
    spans = build_time_map(EDL(clips=[Clip("a", 4, 6, 0), Clip("a", 4, 6, 2)]), tmp_path)
    mapped = source_words_to_output([Word("edge", 3.8, 4.2), Word("end", 5.8, 6.2),
                                     Word("gone", 7, 8)], tmp_path / "a", spans)
    assert [(w.text, round(w.start, 3), round(w.end, 3)) for w in mapped] == [
        ("edge", 0, .2), ("end", 1.8, 2), ("edge", 2, 2.2), ("end", 3.8, 4)]


@pytest.mark.parametrize("clips", [[], [Clip("a", 0, 1, 1)],
    [Clip("a", 0, 1, 0), Clip("b", 0, 1, .5)], [Clip("a", 1, 0, 0)],
    [Clip("a", 0, float("inf"), 0)], [Clip("https://example.com/a", 0, 1, 0)]])
def test_bad_mapping_rejected(tmp_path, clips):
    with pytest.raises(InspectionError):
        build_time_map(EDL(clips=clips), tmp_path)


def test_future_edl_rejected(tmp_path):
    with pytest.raises(InspectionError, match="schema_version"):
        build_time_map(EDL(schema_version=2), tmp_path)


@pytest.mark.parametrize("start,end", [(1, 1), (-1, 2), (2, 1), (0, float("nan")), (True, 2), (0, 4)])
def test_bad_word_timing_is_visible(start, end):
    with pytest.raises(InspectionError, match="Word|word"):
        validate_words([Word("text", start, end)], 3)


@pytest.mark.parametrize("kwargs", [
    {"frames": 100}, {"frames": True}, {"width": 5000}, {"width": 960, "frames": 15},
    {"start": -1}, {"start": 2, "end": 1}, {"end": float("inf")},
    {"around": 1, "start": 0}, {"around": 0}, {"around": 2, "frames": 4},
    {"radius": 0}, {"radius": 61}, {"around": float("nan")},
])
def test_request_limits(kwargs):
    with pytest.raises(InspectionError):
        plan_ranges(10, [], **kwargs)


def test_cut_count_duration_and_pixel_caps():
    with pytest.raises(InspectionError, match="60 total frames"):
        plan_ranges(100, [{"output_time": i} for i in range(1, 14)])
    with pytest.raises(InspectionError, match="120 seconds"):
        plan_ranges(121, [])
    with pytest.raises(InspectionError, match="600 total"):
        plan_ranges(1000, [{"output_time": i} for i in range(100, 700, 100)], radius=60)
    with pytest.raises(InspectionError, match="megapixels"):
        plan_ranges(20, [{"output_time": i} for i in range(1, 13)], width=2400)


def test_center_stays_centered_at_edges():
    rows, _ = plan_ranges(5, [], around=.1)
    assert rows[0] == {"start": 0, "end": .2, "center": .1}
    assert time_to_x(.1, 0, .2, 40, 1560) == 800


@pytest.mark.parametrize("failure,match", [
    (FileNotFoundError(), "install FFmpeg"),
    (subprocess.TimeoutExpired("ffmpeg", 20), "timed out"),
    (OSError("permission denied"), "Could not run"),
])
def test_decoder_actionable_errors(monkeypatch, failure, match):
    def fail(*args, **kwargs):
        assert isinstance(args[0], list)
        assert 0 < kwargs["timeout"] <= 20
        raise failure
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(InspectionError, match=match):
        Decoder().run(["ffmpeg"], "waveform")


def test_decoder_failure_does_not_turn_into_silence(monkeypatch, tmp_path):
    def fail(command, **kwargs):
        assert command[command.index("-protocol_whitelist") + 1] == "file,pipe"
        return subprocess.CompletedProcess(command, 1, b"", b"bad audio codec")
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(InspectionError, match="waveform.*bad audio codec"):
        Decoder().envelope(tmp_path / "audio.mp4", 1, 2, 100)


def test_total_decode_deadline(monkeypatch):
    decoder = Decoder()
    decoder.deadline = 0
    with pytest.raises(InspectionError, match="50 seconds"):
        decoder.run(["ffmpeg"], "probe")


def test_missing_pillow_hint(monkeypatch):
    original = builtins.__import__
    def no_pillow(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_pillow)
    with pytest.raises(InspectionError, match=r'myzing\[memes\]'):
        _pillow()


def test_cli_mcp_metadata_and_errors(monkeypatch, tmp_path, capsys, zing_workspace):
    from myzing import cli, mcp_server
    from myzing.inspect import command, timeline
    result = InspectionResult(str(tmp_path / "out.png"), 1600, 510, "video.mp4", 2,
                              [], [], [], [], "none")
    assert InspectionResult.from_dict(result.to_dict()) == result
    def inspect(*args, **kwargs):
        assert kwargs["around"] == 1
        return result
    monkeypatch.setattr(command, "inspect_timeline", inspect)
    monkeypatch.setattr(timeline, "inspect_timeline", inspect)
    assert cli.main(["inspect", "timeline", "video.mp4", "--around", "1", "--out", "out.png", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["path"].endswith("out.png")
    payload = mcp_server.h_inspect_timeline("video.mp4", "out.png", around=1)
    assert payload == {"ok": True, **result.to_dict()}
    json.dumps(payload)  # No image bytes can be serialized here.
    def fail(*args, **kwargs):
        raise InspectionError("ffmpeg failed during frame extraction: broken codec")
    monkeypatch.setattr(timeline, "inspect_timeline", fail)
    monkeypatch.setattr(command, "inspect_timeline", fail)
    assert not mcp_server.h_inspect_timeline("video.mp4", "out.png")["ok"]
    assert cli.main(["inspect", "timeline", "video.mp4", "--out", "out.png", "--json"]) == 1
    assert "broken codec" in json.loads(capsys.readouterr().out)["error"]


def test_publish_race_and_overwrite(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    from myzing.inspect.timeline import _publish
    out = tmp_path / "existing.png"
    out.write_bytes(b"keep me")
    canvas = Image.new("RGB", (1, 1), "red")
    with pytest.raises(InspectionError, match="already exists"):
        _publish(canvas, out, False)
    assert out.read_bytes() == b"keep me"
    assert not list(tmp_path.glob(".zing-inspect-*"))
    _publish(canvas, out, True)
    with Image.open(out) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0)
