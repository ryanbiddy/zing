"""Review regressions with local fixtures and fake probes."""

import json
import socket
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from myzing import storage
from myzing.composition import AssetRef, Composition, CompositionAudio, CompositionClip
from myzing.explain.models import Section, StyleCard
from myzing.explain.presentation import markdown
from myzing.explain.sections import audio_section
from myzing.inspect import timeline
from myzing.inspect.timing import build_time_map
from myzing.schemas import Breakdown, Clip, EDL, VideoMeta, Word
from myzing.screen.models import ScreenPlan
from myzing.screen.planner import camera
from myzing.screen.render import graph


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unexpected network access")
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, refuse)


@pytest.mark.parametrize("warning", [
    "Learned audio tagging unavailable; heuristic fallback",
    "Audio loudness unavailable",
    "Speech transcription unavailable",
])
def test_unrelated_audio_warnings_keep_measured_speech(warning):
    b = {"audio": {"speech_ratio": .65}, "provenance": {"vad": "silero"}, "warnings": [warning]}
    section = audio_section(b, None)
    assert section.facts["speech_share"] == .65
    assert section.lines[0] == "Speech for about 65% of the clip (voice activity detection)."


@pytest.mark.parametrize("warning", [
    "speech ratio skipped: VAD failed",
    "Speech detection unavailable",
    "Voice activity detection not installed",
    "no audio stream: transcription and audio measurements will be skipped",
])
def test_failed_speech_detection_stays_unknown(warning):
    b = {"audio": {"speech_ratio": 0}, "provenance": {"vad": "silero"}, "warnings": [warning]}
    assert audio_section(b, None).facts["speech_share"] is None


@pytest.mark.parametrize("source,escaped", [
    ("<b>x</b>.mp4", r"b&gt;\.mp4"),
    ("<b>x.mp4", r"&lt;b&gt;x\.mp4"),
    ("`[*x*]`&.mp4", r"\`\[\*x\*\]\`&amp;\.mp4"),
])
def test_card_escapes_names_and_titles_only_in_markdown(source, escaped):
    title = '<b>[*`x`*]</b> & "title"\n# heading'
    card = StyleCard(source, "a" * 64, 10, {"framing": Section(title, {"width": 640, "height": 360})},
                     "recipe.json", [], ["one", "two", "three"])
    md = markdown(card)
    assert md.splitlines()[0] == f"# Style card: {escaped}"
    assert r'## &lt;b&gt;\[\*\`x\`\*\]&lt;/b&gt; &amp; &quot;title&quot; \# heading' in md
    assert card.to_dict()["source"] == source
    assert card.to_dict()["sections"]["framing"]["title"] == title


@pytest.mark.parametrize("sidecar", [[], None, "not an object", 1])
def test_non_object_music_sidecar_is_unreadable(tmp_path, monkeypatch, sidecar):
    pytest.importorskip("PIL.Image")
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    video.with_suffix(".music.json").write_text(json.dumps(sidecar), encoding="utf-8")

    class Decoder:
        def probe(self, path):
            return {"duration": 4., "fps": 30., "has_audio": False}

        def frame(self, path, time, width, height):
            return bytes(width * height * 3)

    monkeypatch.setattr(timeline, "Decoder", Decoder)
    result = timeline.inspect_timeline(video, tmp_path / "timeline.png", frames=3, width=960)
    assert "Music measurement sidecar is unreadable." in result.warnings
    assert result.audio_measurements is None
    assert Path(result.path).is_file()


def transcript(tmp_path, monkeypatch, selection):
    source, video = tmp_path / "source.mp4", tmp_path / "edit.mp4"
    b = Breakdown(VideoMeta(str(source), "file", duration=10), words=[Word("hello", 1, 2, .9)],
                  provenance={"reference_range": selection})
    monkeypatch.setattr(storage, "load_breakdown", lambda slug: b)
    edl = EDL(clips=[Clip(str(source), 30, 40, 0), Clip(str(source), 31.5, 32, 10)])
    return b, edl, build_time_map(edl, tmp_path), video


def test_trimmed_transcript_maps_from_selected_source_start(tmp_path, monkeypatch):
    b, edl, spans, video = transcript(tmp_path, monkeypatch, {"start": 30., "end": 40., "requested_start": 29.99})
    words, origin, warnings = timeline._transcript(edl, spans, "trimmed", video, 10.5)
    assert [(w.text, w.start, w.end, w.confidence) for w in words] == [
        ("hello", 1., 2., .9), ("hello", 10., 10.5, .9)]
    assert origin.endswith(":source-to-output")
    assert any("clipped" in w for w in warnings)
    assert (b.words[0].start, b.words[0].end) == (1, 2)


@pytest.mark.parametrize("selection", [None, [], {}, {"start": None}, {"start": "bad"},
                                      {"start": True}, {"start": -1}, {"start": float("nan")}])
def test_unreadable_selection_keeps_transcript_unmapped(tmp_path, monkeypatch, selection):
    _, edl, spans, video = transcript(tmp_path, monkeypatch, selection)
    words, origin, warnings = timeline._transcript(edl, spans, "trimmed", video, 10.5)
    assert words == [] and origin == "none"
    assert "Breakdown reference range start is unreadable; transcript words were not mapped." in warnings


def test_selected_media_keeps_its_own_transcript_clock(tmp_path, monkeypatch):
    b, _, _, video = transcript(tmp_path, monkeypatch, {"start": 30., "end": 40.})
    selected = tmp_path / "reference-selection.mp4"
    b.meta.media_path = "media.mp4"
    monkeypatch.setattr(storage, "resolve_relpath", lambda slug, path: selected)
    edl = EDL(clips=[Clip(str(selected), 0, 10, 0)])
    for plan, spans, media in [(edl, build_time_map(edl, tmp_path), video), (None, [], selected)]:
        words, _, _ = timeline._transcript(plan, spans, "trimmed", media, 10)
        assert [(w.start, w.end) for w in words] == [(1, 2)]


def test_screen_audio_is_aligned_before_splitting():
    plan = ScreenPlan("screen.mp4", "a" * 64, 960, 540, 10, idle=[{"start": 2., "end": 6.}])
    cam = camera(plan, 640, 360)
    script = graph(plan, cam, 640, 360, True)
    count = len(cam["time_map"])
    assert count > 1
    assert f"[0:a]aresample=async=1:first_pts=0,asplit={count}" in script
    assert script.index("first_pts=0") < script.index("asplit=") < script.index("atrim=")
    assert "[0:a]" not in graph(plan, cam, 640, 360, False)


@pytest.mark.parametrize("video_duration,container_duration", [(10., 10.5), (None, 10.)])
def test_screen_render_uses_planning_duration(tmp_path, monkeypatch, video_duration, container_duration):
    from myzing.project import probe
    from myzing.render import framing, pipeline
    from myzing.render.validation import MediaInfo
    from myzing.screen import api, render

    source = tmp_path / "screen.mp4"
    source.write_bytes(b"screen")
    stream = {"codec_type": "video", "width": 960, "height": 540, "avg_frame_rate": "30/1"}
    if video_duration is not None:
        stream["duration"] = str(video_duration)
    info = probe.parse_probe({"streams": [stream, {"codec_type": "audio"}],
                              "format": {"duration": str(container_duration)}})
    monkeypatch.setattr(probe, "probe_file", lambda path: info)
    monkeypatch.setattr(api.analysis, "freezes", lambda *args: [])
    monkeypatch.setattr(api.analysis, "activity", lambda *args: [])
    plan = api.plan_screen(source, caption_preset="none")
    assert plan.duration == 10.
    monkeypatch.setattr(framing, "probe_dimensions", lambda *args: (960, 540))
    monkeypatch.setattr(pipeline, "probe_media", lambda path, ffprobe: (
        MediaInfo(container_duration, True, True, video_duration=video_duration) if path == source
        else MediaInfo(10., True, True, video_duration=10.)))
    monkeypatch.setattr(pipeline, "filter_script_args", lambda ffmpeg, script: ["-filter_complex_script", str(script)])

    def encode(command, **kwargs):
        Path(command[-1]).write_bytes(b"render")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(render.subprocess, "run", encode)
    with pytest.raises(ValueError, match="replan"):
        render.render_screen(replace(plan, duration=9.), tmp_path / "bad.mp4")
    result = render.render_screen(plan, tmp_path / "out.mp4", short_side=180)
    assert result["duration"] == 10.
    assert Path(result["video"]).read_bytes() == b"render"


@pytest.fixture
def transparent_still(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    from myzing.layout.detector import LayoutError
    from myzing.memes import render
    from myzing.still import api, inventory

    def absent(*args, **kwargs):
        raise LayoutError("test detector unavailable")

    monkeypatch.setattr(inventory, "YuNetDetector", absent)
    monkeypatch.setattr(inventory, "_ocr_engine", lambda: None)
    monkeypatch.setattr(inventory, "photo_detections", lambda image: ([], []))
    monkeypatch.setattr(render, "photo_detections", lambda image: ([], []))
    photos = tmp_path / "photos"
    photos.mkdir()
    image = Image.new("RGBA", (320, 180), (255, 0, 0, 0))
    image.paste((0, 200, 0, 128), (80, 60, 240, 120))
    image.save(photos / "transparent.png")
    out = tmp_path / "stills"
    made = api.create_stills(photos, "one more fix", out, n=1, aspect="16:9", layout="caption", fit="contain")
    return out, made["summary"][0]["id"]


def test_still_animation_composites_before_encoding(transparent_still, monkeypatch):
    from PIL import Image
    from myzing.memes import video
    from myzing.still import api

    def encode(texts, *, image, out, **kwargs):
        with Image.open(image) as source:
            assert source.getpixel((0, 0)) == (24, 24, 24)
            assert source.getpixel((160, 90)) == (12, 112, 12)
        target = Path(out)
        target.write_bytes(b"mp4")
        target.with_suffix(".gif").write_bytes(b"gif")
        return {"path": out, "width": 1200, "height": 676,
                "gif": {"path": str(target.with_suffix(".gif")), "width": 640, "height": 360}}

    monkeypatch.setattr(video, "render_meme_video", encode)
    result = api.pick_still(*transparent_still, gif=True)
    assert Path(result["video"]["path"]).read_bytes() == b"mp4"
    assert Path(result["gif"]["path"]).read_bytes() == b"gif"


@pytest.mark.ffmpeg
def test_transparent_still_video_and_gif_match_background(transparent_still):
    from PIL import Image
    from myzing.still import api

    result = api.pick_still(*transparent_still, gif=True)
    with Image.open(result["path"]) as still:
        expected = still.getpixel((still.width // 4, still.height * 3 // 4))
    assert expected == (24, 24, 24)
    width, height = result["video"]["width"], result["video"]["height"]
    decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", result["video"]["path"],
                              "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                             capture_output=True, timeout=30)
    assert decoded.returncode == 0, decoded.stderr
    frame = Image.frombytes("RGB", (width, height), decoded.stdout)
    pixels = [frame.getpixel((width // 4, height * 3 // 4))]
    with Image.open(result["gif"]["path"]) as gif:
        pixels.append(gif.convert("RGB").getpixel((gif.width // 4, gif.height * 3 // 4)))
    assert all(abs(a - b) <= 10 for pixel in pixels for a, b in zip(pixel, expected))


@pytest.mark.parametrize("start", [10., 10.01])
def test_composition_rejects_clips_starting_at_or_after_source_end(start):
    clip = CompositionClip("source.mp4", start, 10.04, 0, id="clip", asset_id="source")
    with pytest.raises(ValueError, match="source.*duration"):
        Composition(assets=[AssetRef("source", "source.mp4", None, 10)], clips=[clip])


@pytest.mark.parametrize("end", [None, 10.04])
def test_composition_rejects_audio_starting_after_source_end(end):
    audio = CompositionAudio(id="audio", asset_id="source", src="source.mp4", kind="music",
                             role="music", src_in=10.01, src_out=end)
    with pytest.raises(ValueError, match="source.*duration"):
        Composition(assets=[AssetRef("source", "source.mp4", None, 10)], audio=[audio])


def test_composition_keeps_outpoint_tolerance_and_unknown_duration():
    for start, end, duration in [(9.99, 10.05, 10), (10.01, 10.04, None)]:
        clip = CompositionClip("source.mp4", start, end, 0, id="clip", asset_id="source")
        assert Composition(assets=[AssetRef("source", "source.mp4", None, duration)], clips=[clip]).clips == [clip]
