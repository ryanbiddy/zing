"""Speech readiness exercises audio decoding without loading a model."""
import sys
import tomllib
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import doctor
from myzing.study import transcribe
from test_release_packaging import load

ROOT = Path(__file__).resolve().parents[1]
ERROR = "open() got an unexpected keyword argument 'metadata_errors'"


@pytest.mark.parametrize("extra", ["study", "factory", "all"])
def test_speech_extras_bound_pyav_in_metadata_and_lock(extra):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "av>=11,<19" in project["project"]["optional-dependencies"][extra]
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(p for p in lock["package"] if p["name"] == "myzing")
    assert {"name": "av"} in package["optional-dependencies"][extra]
    assert {"name": "av", "marker": f"extra == '{extra}'", "specifier": ">=11,<19"} in package["metadata"]["requires-dist"]
    assert next(p for p in lock["package"] if p["name"] == "av")["version"] == "18.0.0"


@pytest.mark.parametrize("broken", [False, True])
def test_decode_smoke_uses_one_second_wav_and_propagates_failure(monkeypatch, broken):
    calls = []

    def decode(audio, sampling_rate=16000):
        with wave.open(audio) as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (1, 2, 16000, 16000)
        calls.append(sampling_rate)
        if broken:
            raise TypeError(ERROR)
        return [0.0] * 16000

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(decode_audio=decode))
    if broken:
        with pytest.raises(TypeError, match="metadata_errors"):
            transcribe.decode_smoke()
    else:
        transcribe.decode_smoke()
    assert calls == [16000]


def test_doctor_rejects_installed_but_broken_decoder(monkeypatch, zing_workspace, tmp_path):
    monkeypatch.setenv("ZING_WHISPER_MODEL", "small.en")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setattr(doctor, "_has_module", lambda _: True)

    def decode(*args, **kwargs):
        raise TypeError(ERROR)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(decode_audio=decode))
    check = doctor.check_whisper()
    assert not check.ok
    assert ERROR in check.detail
    assert check.fix == doctor._install_command("myzing[study]")
    assert "transcription" in check.degraded_mode.lower()


@pytest.mark.parametrize("extras,expected", [("all", True), ("mcp,render,memes,study", True),
                                            ("mcp,render,memes,factory", True), ("mcp,render,memes", False)])
def test_fresh_install_runs_decode_smoke_for_speech_extras(monkeypatch, tmp_path, extras, expected):
    module = load("fresh_install_check")
    calls = []

    class Recorder:
        def __init__(self, root, *args):
            self.root = root

        def __call__(self, name, command, **kwargs):
            calls.append((name, command))
            return str(self.root) if name == "site" else ""

    monkeypatch.setattr(module, "Recorder", Recorder)
    module.run_check(tmp_path / "fixture.whl", tmp_path / "run", extras, [], lambda: None)
    smoke = [c for name, c in calls if name == "speech-decode"]
    assert bool(smoke) is expected
    if expected:
        assert smoke[0][1:] == ["-c", "from myzing.study.transcribe import decode_smoke; decode_smoke()"]

