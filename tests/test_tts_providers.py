"""TTS provider plugin surface (S4-B Track 1): registry resolution,
key-gated ElevenLabs plugin, honest degraded states. All network mocked."""

from __future__ import annotations

import io
import urllib.error
import wave

import pytest

from myzing import tts_providers
from myzing.render.tts import (
    KokoroOnnxProvider,
    SynthesisRequest,
    TTSGenerationError,
    TTSUnavailableError,
)


from conftest import FakeHTTPResponse as FakeResponse


# -- registry ----------------------------------------------------------------

def test_default_is_kokoro(monkeypatch):
    monkeypatch.delenv(tts_providers.PROVIDER_ENV, raising=False)
    provider = tts_providers.resolve_tts_provider()
    assert isinstance(provider, KokoroOnnxProvider)


def test_env_selects_elevenlabs(monkeypatch):
    monkeypatch.setenv(tts_providers.PROVIDER_ENV, "elevenlabs")
    provider = tts_providers.resolve_tts_provider()
    assert provider.name == "elevenlabs"


def test_explicit_name_beats_env(monkeypatch):
    monkeypatch.setenv(tts_providers.PROVIDER_ENV, "elevenlabs")
    provider = tts_providers.resolve_tts_provider("kokoro")
    assert isinstance(provider, KokoroOnnxProvider)


def test_unknown_provider_lists_available(monkeypatch):
    with pytest.raises(TTSUnavailableError, match="elevenlabs, kokoro"):
        tts_providers.resolve_tts_provider("polly")


# -- ElevenLabs key gating ---------------------------------------------------

def test_no_key_is_actionable_and_never_required(monkeypatch, tmp_path):
    monkeypatch.delenv(tts_providers.ELEVENLABS_KEY_ENV, raising=False)
    provider = tts_providers.ElevenLabsProvider()
    with pytest.raises(TTSUnavailableError) as e:
        provider.synthesize(
            SynthesisRequest(text="hi", voice="v123"), tmp_path / "vo.wav"
        )
    assert "ELEVENLABS_API_KEY" in str(e.value)
    assert "never requires" in str(e.value)


def test_default_voice_needs_configured_id(monkeypatch, tmp_path):
    monkeypatch.setenv(tts_providers.ELEVENLABS_KEY_ENV, "k")
    monkeypatch.delenv(tts_providers.ELEVENLABS_VOICE_ENV, raising=False)
    provider = tts_providers.ElevenLabsProvider()
    with pytest.raises(TTSUnavailableError, match="ZING_ELEVENLABS_VOICE"):
        provider.synthesize(SynthesisRequest(text="hi"), tmp_path / "vo.wav")


# -- ElevenLabs synthesis (mocked network) -----------------------------------

def test_synthesize_writes_wav(monkeypatch, tmp_path):
    monkeypatch.setenv(tts_providers.ELEVENLABS_KEY_ENV, "secret")
    captured = {}
    pcm = b"\x00\x01" * 22050  # exactly 1s of mono PCM16 at 22050 Hz

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["key"] = request.get_header("Xi-api-key")
        return FakeResponse(pcm)

    monkeypatch.setattr(tts_providers.urllib.request, "urlopen", fake_urlopen)
    result = tts_providers.ElevenLabsProvider().synthesize(
        SynthesisRequest(text="hello world", voice="v123"), tmp_path / "vo.wav"
    )
    assert captured["key"] == "secret"
    assert "v123" in captured["url"] and "pcm_22050" in captured["url"]
    assert result.provider == "elevenlabs"
    assert abs(result.duration - 1.0) < 0.01
    with wave.open(str(result.path)) as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 22050
        assert audio.getnframes() == 22050


def test_auth_rejection_names_the_key(monkeypatch, tmp_path):
    monkeypatch.setenv(tts_providers.ELEVENLABS_KEY_ENV, "bad")

    def forbidden(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 401, "no", {}, io.BytesIO())

    monkeypatch.setattr(tts_providers.urllib.request, "urlopen", forbidden)
    with pytest.raises(TTSUnavailableError, match="ELEVENLABS_API_KEY"):
        tts_providers.ElevenLabsProvider().synthesize(
            SynthesisRequest(text="hi", voice="v1"), tmp_path / "vo.wav"
        )


def test_network_failure_names_the_offline_alternative(monkeypatch, tmp_path):
    monkeypatch.setenv(tts_providers.ELEVENLABS_KEY_ENV, "k")

    def down(request, timeout=0):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(tts_providers.urllib.request, "urlopen", down)
    with pytest.raises(TTSGenerationError, match="kokoro provider"):
        tts_providers.ElevenLabsProvider().synthesize(
            SynthesisRequest(text="hi", voice="v1"), tmp_path / "vo.wav"
        )


# -- honest status -----------------------------------------------------------

def test_tts_status_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("ZING_KOKORO_HOME", str(tmp_path / "nowhere"))
    monkeypatch.delenv(tts_providers.ELEVENLABS_KEY_ENV, raising=False)
    monkeypatch.delenv(tts_providers.PROVIDER_ENV, raising=False)
    status = tts_providers.tts_status()
    assert status["selected"] == "kokoro"
    assert status["providers"]["kokoro"]["ready"] is False
    assert "missing" in status["providers"]["kokoro"]["detail"]
    assert status["providers"]["elevenlabs"]["ready"] is False
    assert "ELEVENLABS_API_KEY" in status["providers"]["elevenlabs"]["detail"]


def test_doctor_reports_tts(monkeypatch, tmp_path):
    from myzing import doctor

    monkeypatch.setenv("ZING_KOKORO_HOME", str(tmp_path / "nowhere"))
    monkeypatch.delenv(tts_providers.ELEVENLABS_KEY_ENV, raising=False)
    check = doctor.check_tts()
    assert check.tier == "optional"
    assert check.ok is False
    assert "without voiceover" in check.degraded_mode
    assert "ELEVENLABS_API_KEY" in check.fix or "kokoro" in check.fix

# -- SG-2: remaining ElevenLabs error paths ----------------------------------

def test_quota_429_names_the_plan(monkeypatch, tmp_path):
    monkeypatch.setenv(tts_providers.ELEVENLABS_KEY_ENV, "k")

    def limited(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 429, "slow down", {}, io.BytesIO())

    monkeypatch.setattr(tts_providers.urllib.request, "urlopen", limited)
    with pytest.raises(TTSGenerationError, match="quota"):
        tts_providers.ElevenLabsProvider().synthesize(
            SynthesisRequest(text="hi", voice="v1"), tmp_path / "vo.wav"
        )


def test_server_error_includes_status_and_body(monkeypatch, tmp_path):
    monkeypatch.setenv(tts_providers.ELEVENLABS_KEY_ENV, "k")

    def boom(request, timeout=0):
        raise urllib.error.HTTPError(
            request.full_url, 500, "oops", {}, io.BytesIO(b"internal fire")
        )

    monkeypatch.setattr(tts_providers.urllib.request, "urlopen", boom)
    with pytest.raises(TTSGenerationError, match="HTTP 500.*internal fire"):
        tts_providers.ElevenLabsProvider().synthesize(
            SynthesisRequest(text="hi", voice="v1"), tmp_path / "vo.wav"
        )


def test_empty_audio_body_is_loud(monkeypatch, tmp_path):
    monkeypatch.setenv(tts_providers.ELEVENLABS_KEY_ENV, "k")
    monkeypatch.setattr(
        tts_providers.urllib.request, "urlopen",
        lambda request, timeout=0: FakeResponse(b""),
    )
    with pytest.raises(TTSGenerationError, match="empty audio"):
        tts_providers.ElevenLabsProvider().synthesize(
            SynthesisRequest(text="hi", voice="v1"), tmp_path / "vo.wav"
        )


def test_non_wav_output_rejected_before_any_network_call(monkeypatch, tmp_path):
    """Lane C SG-1 (#206 review): the first version of this test returned
    fake audio before asserting rejection — proving only that failure
    EVENTUALLY happened, after a billable API call. The suffix check must
    fire before urlopen so a bad local path can never spend quota."""
    monkeypatch.setenv(tts_providers.ELEVENLABS_KEY_ENV, "k")
    calls = {"n": 0}

    def counting(request, timeout=0):
        calls["n"] += 1
        return FakeResponse(b"ok" * 50)

    monkeypatch.setattr(tts_providers.urllib.request, "urlopen", counting)
    with pytest.raises(TTSGenerationError, match=".wav extension"):
        tts_providers.ElevenLabsProvider().synthesize(
            SynthesisRequest(text="hi", voice="v1"), tmp_path / "vo.mp3"
        )
    assert calls["n"] == 0  # rejection is free — ElevenLabs never contacted


# -- CX1-P2-1: the privacy claim must track the provider registry -------------

def test_readme_discloses_every_external_provider():
    """Collateral lens CX1-P2-1: the README claimed 'No API keys, no
    cloud' while this module has shipped an optional key-gated external
    provider since S4-B. Absolute privacy claims are the kind that erode
    trust in every other claim, so pin the disclosure to the REGISTRY:
    adding another external provider without disclosing it fails here."""
    from pathlib import Path

    readme = (
        Path(__file__).resolve().parents[1] / "README.md"
    ).read_text(encoding="utf-8")
    external = set(tts_providers._REGISTRY) - {tts_providers.DEFAULT_PROVIDER}
    for name in external:
        assert name in readme.lower(), (
            f"README does not disclose the optional external provider "
            f"{name!r} — see CX1-P2-1"
        )
    # And the absolute forms the lens struck must not come back.
    lowered = readme.lower()
    for absolute in ("no api keys, no cloud", "nothing leaves your machine"):
        assert absolute not in lowered, (
            f"README carries the absolute claim {absolute!r} again"
        )


# -- SG-4: readiness must test the CAPABILITY, not a proxy for it ------------

def _kokoro_files_present(monkeypatch, tmp_path):
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    monkeypatch.setenv("ZING_KOKORO_MODEL", str(model))
    monkeypatch.setenv("ZING_KOKORO_VOICES", str(voices))


def test_kokoro_not_ready_when_the_runtime_is_missing(monkeypatch, tmp_path):
    """Found live on Python 3.14: the model files sat on disk, kokoro-onnx
    caps at <3.14 and could not be imported, and status reported READY —
    so voiceover failed at render time after doctor said it was fine.
    Model files are a proxy for the capability, not the capability
    (audit #201's lineage)."""
    _kokoro_files_present(monkeypatch, tmp_path)
    monkeypatch.setattr(
        tts_providers.importlib.util, "find_spec", lambda name: None
    )
    kokoro = tts_providers.tts_status()["providers"]["kokoro"]
    assert kokoro["ready"] is False
    assert "not importable" in kokoro["detail"]
    assert "elevenlabs" in kokoro["detail"]  # names the working alternative


def test_kokoro_ready_needs_both_halves(monkeypatch, tmp_path):
    _kokoro_files_present(monkeypatch, tmp_path)
    monkeypatch.setattr(
        tts_providers.importlib.util, "find_spec", lambda name: object()
    )
    kokoro = tts_providers.tts_status()["providers"]["kokoro"]
    assert kokoro["ready"] is True
    assert "importable" in kokoro["detail"]


def test_doctor_prescribes_the_runtime_not_the_download(monkeypatch, tmp_path):
    """D-13's lesson generalized: never prescribe a fix for something
    that is not what is missing. Model files present + no runtime must
    point at the install, not at another download."""
    from myzing import doctor

    _kokoro_files_present(monkeypatch, tmp_path)
    monkeypatch.setattr(
        tts_providers.importlib.util, "find_spec", lambda name: None
    )
    monkeypatch.delenv(tts_providers.ELEVENLABS_KEY_ENV, raising=False)
    check = doctor.check_tts()
    assert check.ok is False
    assert 'myzing[render]' in check.fix
    assert "download the kokoro model files" not in check.fix
