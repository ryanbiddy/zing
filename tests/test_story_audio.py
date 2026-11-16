"""Paper sound and music tests use generated PCM, with no remote assets."""
from __future__ import annotations

import json
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from myzing.story import StoryError, audio, data_path, render
from test_story_render import story_folder


def tone(path: Path, *, duration=2.0, rate=8000, volume=.3, channels=1, width=2):
    frames = round(duration * rate)
    data = bytearray()
    for index in range(frames):
        value = volume * math.sin(2 * math.pi * 220 * index / rate)
        pcm = (bytes([round(128 + 120 * value)]) if width == 1
               else round(value * (2 ** (8 * width - 1) - 1)).to_bytes(width, "little", signed=True))
        data.extend(pcm * channels)
    with wave.open(str(path), "wb") as output:
        output.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        output.writeframes(data)


@pytest.fixture
def sound_story(tmp_path):
    story = {"panels": [
        {"from": "hook", "props": [{"prop": "star"}, {"prop": "cup", "at": "hook:0:0.5"}],
         "cards": [{"at": "hook+0.1"}]},
        {"from": "turn", "props": [{"prop": "tree"}],
         "cards": [{"at": "turn+0.1", "anim": "stamp"}]},
    ]}
    timings = {"duration": 2.0, "outro_start": 1.8, "beats": [
        {"id": "hook", "start": .35, "end": 1.0,
         "lines": [{"start": .35, "end": .85}]},
        {"id": "turn", "start": 1.2, "end": 1.8,
         "lines": [{"start": 1.2, "end": 1.7}]},
    ]}
    tone(tmp_path / "narration.wav")
    (tmp_path / "timings.json").write_text(json.dumps(timings), encoding="utf-8")
    return story, timings


def test_effect_times_follow_camera_slides_and_item_cues(sound_story):
    story, timings = sound_story
    events = audio.effect_events(story, timings)
    assert [event["kind"] for event in events] == ["pop", "pop", "pop", "whoosh", "pop", "stamp"]
    assert [event["at"] for event in events] == pytest.approx([0, .45, .6, .78, 1.2, 1.3])
    page = data_path("cutout.html").read_text(encoding="utf-8")
    assert "CAM[i] - .42" in page and ") / .8) * W" in page
    assert audio.SLIDE_LEAD == .42 and audio.SLIDE_DURATION == .8


def test_hidden_and_out_of_range_effects_are_omitted(sound_story):
    story, timings = sound_story
    story["panels"] = [{"from": "hook", "cards": [
        {"at": 3}, {"at": -1}, {"at": 1, "until": .9}, {"at": .5, "until": 1.0},
    ], "props": [{"at": 1, "until": 1}]}]
    assert audio.effect_events(story, timings) == [{"kind": "pop", "at": .5}]


@pytest.mark.parametrize("item,expected", [
    ({"at": .35, "until": .55}, None),  # Gone before its panel reaches the frame.
    ({"at": .35, "until": 1.58}, None),
    ({"at": 4.5}, None),  # Its panel has already left the frame.
    ({"at": 4.38}, None),
    ({"at": .35}, 1.58),  # Earlier animation is first seen during the incoming slide.
    ({"at": 1.7, "until": 2.1}, 1.7),
    ({"at": 4.2}, 4.2),  # Outgoing-slide cues remain visible and keep their time.
])
@pytest.mark.parametrize("collection", ["cards", "props"])
def test_item_effects_follow_their_panels_visible_interval(item, expected, collection):
    story = {"panels": [{"from": "hook"}, {"from": "turn", collection: [item]}, {"from": "end"}]}
    timings = {"duration": 6.0, "outro_start": 5.0, "beats": [
        {"id": "hook", "start": .35}, {"id": "turn", "start": 2.0}, {"id": "end", "start": 4.0},
    ]}
    pops = [event["at"] for event in audio.effect_events(story, timings) if event["kind"] == "pop"]
    assert pops == pytest.approx([] if expected is None else [expected])


@pytest.mark.parametrize("until,expected", [(1.5, None), (1.7, 1.58), (2.5, 2.0)])
def test_static_prop_effect_is_heard_only_while_its_panel_and_prop_are_visible(until, expected):
    story = {"panels": [{"from": "hook"}, {"from": "turn", "props": [{"until": until}]}]}
    timings = {"duration": 4.0, "outro_start": 3.0, "beats": [
        {"id": "hook", "start": .35}, {"id": "turn", "start": 2.0},
    ]}
    pops = [event["at"] for event in audio.effect_events(story, timings) if event["kind"] == "pop"]
    assert pops == pytest.approx([] if expected is None else [expected])


def test_sfx_mix_is_byte_identical_and_keeps_narration_and_timings(tmp_path, sound_story):
    story, timings = sound_story
    before = [(tmp_path / name).read_bytes() for name in ("narration.wav", "timings.json")]
    first = audio.mix(tmp_path, story, timings, tmp_path).read_bytes()
    second = audio.mix(tmp_path, story, timings, tmp_path).read_bytes()
    assert first == second and first != before[0]
    assert [(tmp_path / name).read_bytes() for name in ("narration.wav", "timings.json")] == before
    with wave.open(str(tmp_path / "mixed.wav"), "rb") as output:
        assert (output.getnframes(), output.getframerate(), output.getnchannels()) == (16000, 8000, 1)


def test_effect_has_no_samples_before_its_cue_and_is_quiet():
    bus = audio.synthesize_effects([{"kind": "pop", "at": .2}], rate=8000, frames=8000, voice_rms=.25)
    assert all(value == 0 for value in bus[:1600])
    active = bus[1600:2560]
    assert any(value != 0 for value in active)
    rms = math.sqrt(sum(value * value for value in active) / len(active))
    assert -22 < 20 * math.log10(rms / .25) < -17
    assert all(value == 0 for value in bus[2560:])


def test_mix_keeps_headroom_for_loud_supplied_voice(tmp_path, sound_story):
    story, timings = sound_story
    tone(tmp_path / "narration.wav", volume=.999)
    mixed = audio.mix(tmp_path, story, timings, tmp_path)
    with wave.open(str(mixed), "rb") as output:
        values = struct.unpack("<16000h", output.readframes(output.getnframes()))
    assert max(abs(value) for value in values) <= math.ceil(.98 * 32768)


@pytest.mark.parametrize("settings", [{"no_sfx": True}, {"story_sfx": False}])
def test_disabling_sfx_returns_original_narration(tmp_path, sound_story, monkeypatch, settings):
    story, timings = sound_story
    if "story_sfx" in settings:
        story["sfx"] = settings["story_sfx"]
    monkeypatch.setattr(audio, "synthesize_effects", lambda *a, **kw: pytest.fail("effects were synthesized"))
    assert audio.mix(tmp_path, story, timings, tmp_path, no_sfx=settings.get("no_sfx", False)) == tmp_path / "narration.wav"
    assert not (tmp_path / "mixed.wav").exists()


def test_render_no_sfx_muxes_only_original_voice(tmp_path, monkeypatch):
    directory = story_folder(tmp_path)
    observed = []
    monkeypatch.setattr(render, "capture", lambda *args: None)
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")

    def encode(*args, **kwargs):
        observed.extend(args)
        Path(args[-1]).write_bytes(b"encoded test video")

    monkeypatch.setattr(render, "run", encode)
    render.render(directory, no_sfx=True)
    inputs = [observed[index + 1] for index, value in enumerate(observed) if value == "-i"]
    assert inputs[1:] == [directory / "narration.wav"]


@pytest.mark.parametrize("width,channels", [(1, 1), (2, 2), (3, 1), (4, 2)])
def test_sfx_accepts_every_supplied_pcm_format(tmp_path, sound_story, width, channels):
    story, timings = sound_story
    tone(tmp_path / "narration.wav", width=width, channels=channels)
    mixed = audio.mix(tmp_path, story, timings, tmp_path)
    with wave.open(str(mixed), "rb") as output:
        assert output.getnchannels() == channels
        assert output.getnframes() == 16000


def music_metadata(license="CC0 1.0"):
    return {"path": "tone.wav", "credit": "Test tone", "license": license,
            "source_url": "https://example.org/test-tone"}


@pytest.mark.parametrize("license", ["CC BY-NC 4.0", "CC BY-ND 4.0", "unknown", "All rights reserved"])
def test_music_refuses_uncleared_licenses_before_decoding(tmp_path, sound_story, monkeypatch, license):
    story, timings = sound_story
    story["music"] = music_metadata(license)
    monkeypatch.setattr(audio, "run", lambda *a, **kw: pytest.fail("decoder ran before rights check"))
    with pytest.raises(StoryError, match="NC, ND and unknown licenses are refused"):
        audio.mix(tmp_path, story, timings, tmp_path, no_sfx=True)


def test_music_fades_and_ducks_during_spoken_lines():
    timings = {"duration": 4.0, "beats": [{"lines": [{"start": 1.0, "end": 2.0}]}]}
    assert audio.music_gain(0, timings) == 0
    assert audio.music_gain(4, timings) == 0
    assert audio.music_gain(.7, timings) == pytest.approx(.25)
    assert audio.music_gain(1.5, timings) == pytest.approx(.10)
    assert audio.music_gain(.94, timings) == pytest.approx(.175)
    assert audio.music_gain(2.125, timings) == pytest.approx(.175)
    assert audio.music_gain(3, timings) == pytest.approx(.25)


def test_music_is_looped_trimmed_and_mixed_without_changing_voice(tmp_path, sound_story):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    story, timings = sound_story
    story["music"] = music_metadata()
    tone(tmp_path / "tone.wav", duration=.13, volume=.4)
    before = (tmp_path / "narration.wav").read_bytes()
    mixed = audio.mix(tmp_path, story, timings, tmp_path, no_sfx=True)
    assert mixed.read_bytes() != before
    assert (tmp_path / "narration.wav").read_bytes() == before
    with wave.open(str(mixed), "rb") as output:
        assert output.getnframes() / output.getframerate() == pytest.approx(2)
        data = struct.unpack("<16000h", output.readframes(output.getnframes()))
    # A short source repeats past its first loop and remains under the voice.
    assert any(data[4000:8000])
    assert max(abs(value) for value in data) < 16000
