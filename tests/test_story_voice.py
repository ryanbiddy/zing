"""Recorded line narration works without a speech model or audio packages."""
from __future__ import annotations

import json
import struct
import sys
import wave
from types import SimpleNamespace

import pytest

from myzing.story import StoryError, voice


def write_wav(path, frames, *, rate=1000, channels=1, width=2):
    data = bytes([140]) * frames * channels if width == 1 else struct.pack("<h", 1200) * frames * channels
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(data)
    return data


@pytest.fixture
def recorded(tmp_path):
    story = {"beats": [
        {"id": "hook", "tail": 0.2, "lines": [{"text": "A paper town opens.", "gap": 0.075},
                                                 {"text": "A bell rings."}]},
        {"id": "turn", "lines": [{"text": "Mira finds the key."}]},
        {"id": "answer", "tail": 0, "lines": [{"text": "It fits.", "gap": 0}]},
        {"id": "kicker", "lines": [{"text": "The bakery opens."}]},
    ], "outro": 1.2}
    lines = tmp_path / "lines"
    lines.mkdir()
    for name, frames in [("hook-0", 1001), ("hook-1", 503), ("turn-0", 250), ("answer-0", 400), ("kicker-0", 300)]:
        write_wav(lines / f"{name}.wav", frames)
    return story, lines


def test_recorded_lines_have_exact_millisecond_timings_and_audio(tmp_path, recorded, monkeypatch):
    story, lines = recorded
    monkeypatch.setitem(sys.modules, "kokoro_onnx", None)
    monkeypatch.setattr(voice.importlib, "import_module", lambda name: pytest.fail(f"optional import: {name}"))
    timings = voice.generate(tmp_path, story, lines_dir=lines)
    assert timings["provider"] == "lines" and timings["voice"] is None
    assert timings["beats"] == [
        {"id": "hook", "start": 0.35, "end": 2.289, "lines": [
            {"text": "A paper town opens.", "start": 0.35, "end": 1.351},
            {"text": "A bell rings.", "start": 1.426, "end": 1.929}]},
        {"id": "turn", "start": 2.289, "end": 2.999, "lines": [
            {"text": "Mira finds the key.", "start": 2.289, "end": 2.539}]},
        {"id": "answer", "start": 2.999, "end": 3.399, "lines": [
            {"text": "It fits.", "start": 2.999, "end": 3.399}]},
        {"id": "kicker", "start": 3.399, "end": 4.159, "lines": [
            {"text": "The bakery opens.", "start": 3.399, "end": 3.699}]},
    ]
    assert timings["outro_start"] == 4.159
    assert timings["duration"] == 5.359
    assert json.loads((tmp_path / "timings.json").read_text(encoding="utf-8")) == timings
    with wave.open(str(tmp_path / "narration.wav")) as audio:
        assert audio.getnframes() == 5359
        assert audio.getnframes() / audio.getframerate() == timings["duration"]
        pcm = audio.readframes(audio.getnframes())
    assert pcm[:700] == bytes(700)
    assert pcm[700:2702] == struct.pack("<h", 1200) * 1001
    assert pcm[-2400:] == bytes(2400)


def test_default_pauses_and_unsigned_pcm_silence(tmp_path):
    write_wav(tmp_path / "hook-0.wav", 1000, width=1, channels=2)
    timings = voice.generate(tmp_path, {"beats": [{"id": "hook", "lines": [{"text": "Hello."}]}]},
                             lines_dir=tmp_path)
    assert timings["beats"][0]["start"] == 0.35
    assert timings["outro_start"] == 1.81
    assert timings["duration"] == 5.01
    with wave.open(str(tmp_path / "narration.wav")) as audio:
        assert (audio.getnchannels(), audio.getsampwidth()) == (2, 1)
        assert audio.readframes(350) == bytes([128]) * 700
        assert audio.readframes(1000) == bytes([140]) * 2000


def test_missing_line_names_the_required_file(tmp_path, recorded):
    story, lines = recorded
    (lines / "hook-1.wav").unlink()
    with pytest.raises(StoryError, match="hook-1.wav"):
        voice.generate(tmp_path, story, lines_dir=lines)
    assert not (tmp_path / "narration.wav").exists()


@pytest.mark.parametrize("settings", [{"rate": 2000}, {"channels": 2}, {"width": 1}])
def test_mixed_wav_formats_are_refused(tmp_path, recorded, settings):
    story, lines = recorded
    write_wav(lines / "hook-1.wav", 100, **settings)
    with pytest.raises(StoryError, match="same sample rate, channel count and bit depth"):
        voice.generate(tmp_path, story, lines_dir=lines)


@pytest.mark.parametrize("data", [b"not a wav", b"RIFF\x00\x00\x00\x00WAVE"])
def test_invalid_wav_has_a_plain_error(tmp_path, recorded, data):
    story, lines = recorded
    (lines / "hook-0.wav").write_bytes(data)
    with pytest.raises(StoryError, match="Cannot read hook-0.wav"):
        voice.generate(tmp_path, story, lines_dir=lines)


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf"), True])
def test_invalid_speed_is_refused(tmp_path, recorded, speed):
    story, lines = recorded
    with pytest.raises(StoryError, match="speed"):
        voice.generate(tmp_path, story, speed=speed, lines_dir=lines)


def test_missing_kokoro_import_explains_the_two_files(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "sys", SimpleNamespace(version_info=(3, 13, 0)))
    monkeypatch.setitem(sys.modules, "kokoro_onnx", None)
    with pytest.raises(StoryError) as caught:
        voice.generate(tmp_path, {"beats": []})
    message = str(caught.value)
    assert "kokoro-onnx" in message and "ZING_KOKORO_MODEL" in message and "ZING_KOKORO_VOICES" in message
    assert ".onnx" in message and ".bin" in message


def test_unsupported_python_names_recordings_without_trying_import(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "sys", SimpleNamespace(version_info=(3, 14, 0)))
    monkeypatch.setattr(voice.importlib, "import_module", lambda name: pytest.fail(f"optional import: {name}"))
    with pytest.raises(StoryError, match="Use --lines-dir or Python 3.11-3.13"):
        voice.generate(tmp_path, {"beats": []})


def test_missing_model_files_explain_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "sys", SimpleNamespace(version_info=(3, 13, 0)))
    monkeypatch.setitem(sys.modules, "kokoro_onnx", SimpleNamespace())
    monkeypatch.delenv("ZING_KOKORO_MODEL", raising=False)
    monkeypatch.delenv("ZING_KOKORO_VOICES", raising=False)
    with pytest.raises(StoryError, match="model files are missing") as caught:
        voice.generate(tmp_path, {"beats": []})
    assert "ZING_KOKORO_MODEL" in str(caught.value) and "ZING_KOKORO_VOICES" in str(caught.value)


def test_kokoro_uses_say_voice_speed_and_records_metadata(tmp_path, monkeypatch):
    import numpy as np

    monkeypatch.setattr(voice, "sys", SimpleNamespace(version_info=(3, 13, 0)))
    calls = []

    class Kokoro:
        def __init__(self, model, voices):
            assert model.endswith("model.onnx") and voices.endswith("voices.bin")

        def create(self, text, **kwargs):
            calls.append((text, kwargs))
            return np.concatenate([np.zeros(100), np.full(1000, 0.5), np.zeros(100)]), 1000

    for variable, filename in [("ZING_KOKORO_MODEL", "model.onnx"), ("ZING_KOKORO_VOICES", "voices.bin")]:
        (tmp_path / filename).touch()
        monkeypatch.setenv(variable, str(tmp_path / filename))
    monkeypatch.setitem(sys.modules, "kokoro_onnx", SimpleNamespace(Kokoro=Kokoro))
    story = {"beats": [{"id": "hook", "lines": [{"text": "1993", "say": "nineteen ninety three"}]}]}
    result = voice.generate(tmp_path, story, voice="am_michael", speed=1.06)
    assert calls == [("nineteen ninety three", {"voice": "am_michael", "speed": 1.06, "lang": "en-us"})]
    assert result["provider"] == "kokoro" and result["voice"] == "am_michael"
    assert result["beats"][0]["lines"][0] == {"text": "1993", "start": 0.35, "end": 1.449}


def test_unsafe_beat_id_cannot_read_outside_lines_directory(tmp_path):
    with pytest.raises(StoryError, match="Beat ids"):
        voice.generate(tmp_path, {"beats": [{"id": "../outside", "lines": [{"text": "Hello."}]}]},
                       lines_dir=tmp_path)


def test_supplied_synthetic_recordings_keep_the_ai_voice_credit():
    from myzing.story.outro import credit_lines

    story = {"sources": [{"title": "Example", "url": "https://example.org"}]}
    human = {"provider": "lines", "voice": None, "synthetic": False}
    assert "narration is an AI voice" not in credit_lines(story, human)
    assert "narration is an AI voice" in credit_lines(story, {**human, "synthetic": True})
    assert "narration is an AI voice" in credit_lines(story, {"provider": "kokoro", "voice": "af_heart"})
