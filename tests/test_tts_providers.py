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


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


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