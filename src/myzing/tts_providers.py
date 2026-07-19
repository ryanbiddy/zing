"""TTS provider plugin surface (S4 Track 1, Lane B).

Lane C owns the provider protocol and the local default
(``render.tts.TTSProvider`` / ``KokoroOnnxProvider``); this module owns
how providers are CHOSEN and how optional paid providers plug in:

- ``resolve_tts_provider(name=None)`` — named registry resolution:
  explicit arg beats the ``ZING_TTS_PROVIDER`` env var beats the local
  default ("kokoro"). Unknown names fail with the available list.
- ``ElevenLabsProvider`` — the optional premium plugin. Key-gated via
  ``ELEVENLABS_API_KEY``; NEVER required, never imported into a render
  unless selected. Absence degrades honestly (doctor and zing_status
  report the state; errors name the exact env var).

The plugin calls the ElevenLabs HTTP API with stdlib urllib only — no
SDK dependency. Requests ask for raw PCM and the WAV container is
written locally, so the output is bit-identical in shape to the local
provider's (mono PCM16 .wav) and the renderer never cares which
provider produced a track.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any, Callable

from myzing.render.tts import (
    SynthesisRequest,
    SynthesisResult,
    TTSGenerationError,
    TTSProvider,
    TTSUnavailableError,
    default_tts_provider,
)

PROVIDER_ENV = "ZING_TTS_PROVIDER"
ELEVENLABS_KEY_ENV = "ELEVENLABS_API_KEY"
ELEVENLABS_VOICE_ENV = "ZING_ELEVENLABS_VOICE"

_ELEVENLABS_SAMPLE_RATE = 22050
_ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class ElevenLabsProvider:
    """Optional premium TTS via the ElevenLabs API. Key-gated, never
    required — construction is cheap and offline; the key is checked at
    synthesis time so doctor/status can describe the state honestly."""

    name = "elevenlabs"

    def __init__(self, api_key: str | None = None, timeout: float = 120.0):
        self._api_key = api_key
        self._timeout = timeout

    def _key(self) -> str:
        key = self._api_key or os.environ.get(ELEVENLABS_KEY_ENV, "").strip()
        if not key:
            raise TTSUnavailableError(
                "ElevenLabs is key-gated: set the ELEVENLABS_API_KEY env var "
                "(from elevenlabs.io -> Profile -> API keys). Zing never "
                "requires it — the local kokoro provider is the default."
            )
        return key

    def synthesize(
        self, request: SynthesisRequest, output_path: Path
    ) -> SynthesisResult:
        key = self._key()
        voice_id = request.voice
        if voice_id in ("", "af_sarah"):  # the local default voice isn't an
            # ElevenLabs id — fall back to the configured one honestly
            voice_id = os.environ.get(ELEVENLABS_VOICE_ENV, "").strip()
            if not voice_id:
                raise TTSUnavailableError(
                    "no ElevenLabs voice configured: pass an ElevenLabs "
                    f"voice id or set {ELEVENLABS_VOICE_ENV} (ids are in "
                    "your ElevenLabs VoiceLab)"
                )
        # Lane C SG-1 (#206 review): reject a bad local output path BEFORE
        # the network call — the API request is billable, and a wrong
        # suffix used to spend quota just to fail locally afterwards.
        output_path = output_path.expanduser().resolve()
        if output_path.suffix.lower() != ".wav":
            raise TTSGenerationError("voiceover output must use the .wav extension")
        payload = json.dumps({
            "text": request.text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"speed": request.speed},
        }).encode("utf-8")
        http_request = urllib.request.Request(
            _ELEVENLABS_URL.format(voice_id=voice_id)
            + f"?output_format=pcm_{_ELEVENLABS_SAMPLE_RATE}",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "xi-api-key": key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout) as resp:
                pcm = resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise TTSUnavailableError(
                    "ElevenLabs rejected the API key (HTTP "
                    f"{e.code}) — check ELEVENLABS_API_KEY"
                ) from e
            if e.code == 429:
                raise TTSGenerationError(
                    "ElevenLabs rate/quota limit hit (HTTP 429) — retry "
                    "later or check your plan"
                ) from e
            raise TTSGenerationError(
                f"ElevenLabs API error HTTP {e.code}: "
                f"{e.read()[:200].decode(errors='replace')}"
            ) from e
        except (urllib.error.URLError, OSError) as e:
            raise TTSGenerationError(
                f"could not reach ElevenLabs: {e} — voiceover needs the "
                "network for this provider; the local kokoro provider "
                "works offline"
            ) from e
        if len(pcm) < 2:
            raise TTSGenerationError("ElevenLabs returned an empty audio body")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with wave.open(str(output_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(_ELEVENLABS_SAMPLE_RATE)
                audio.writeframes(pcm[: len(pcm) - (len(pcm) % 2)])
        except (OSError, wave.Error) as e:
            raise TTSGenerationError(f"could not write voiceover WAV: {e}") from e
        duration = (len(pcm) // 2) / _ELEVENLABS_SAMPLE_RATE
        return SynthesisResult(
            path=output_path,
            provider=self.name,
            voice=voice_id,
            sample_rate=_ELEVENLABS_SAMPLE_RATE,
            duration=duration,
        )


_REGISTRY: dict[str, Callable[[], TTSProvider]] = {
    "kokoro": default_tts_provider,
    "elevenlabs": ElevenLabsProvider,
}

DEFAULT_PROVIDER = "kokoro"


def available_tts_providers() -> list[str]:
    return sorted(_REGISTRY)


def resolve_tts_provider(name: str | None = None) -> TTSProvider:
    """Pick a provider: explicit ``name`` > ZING_TTS_PROVIDER > kokoro.

    Unknown names raise TTSUnavailableError listing what exists —
    selection errors must be as honest as synthesis errors.
    """
    chosen = (name or os.environ.get(PROVIDER_ENV, "") or DEFAULT_PROVIDER)
    chosen = chosen.strip().lower()
    factory = _REGISTRY.get(chosen)
    if factory is None:
        raise TTSUnavailableError(
            f"unknown TTS provider '{chosen}' — available: "
            f"{', '.join(available_tts_providers())} (set {PROVIDER_ENV} or "
            "pass a provider name)"
        )
    return factory()


def tts_status() -> dict[str, Any]:
    """Honest provider state for doctor / zing_status: what synthesis
    would do RIGHT NOW on this machine, per provider."""
    from myzing.render.tts import MODEL_FILENAME, VOICES_FILENAME  # noqa: F401

    kokoro = default_tts_provider()
    kokoro_ready = kokoro.model_path.is_file() and kokoro.voices_path.is_file()
    key_set = bool(os.environ.get(ELEVENLABS_KEY_ENV, "").strip())
    selected = (
        os.environ.get(PROVIDER_ENV, "").strip().lower() or DEFAULT_PROVIDER
    )
    return {
        "selected": selected,
        "providers": {
            "kokoro": {
                "ready": kokoro_ready,
                "detail": (
                    "model files present"
                    if kokoro_ready
                    else f"model files missing (looked at {kokoro.model_path})"
                ),
            },
            "elevenlabs": {
                "ready": key_set,
                "detail": (
                    "API key set"
                    if key_set
                    else f"optional; enable with {ELEVENLABS_KEY_ENV}"
                ),
            },
        },
    }
