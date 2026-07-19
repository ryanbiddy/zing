"""Local text-to-speech providers for scripted voiceover tracks.

Heavy runtimes and model files are deliberately loaded only when synthesis is
requested. The base Zing install stays network-free and does not pull
``espeakng-loader`` through ``kokoro-onnx``.
"""

from __future__ import annotations

import importlib
import math
import os
import sys
import tempfile
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


DEFAULT_VOICE = "af_sarah"
DEFAULT_LANGUAGE = "en-us"
MODEL_FILENAME = "kokoro-v1.0.onnx"
VOICES_FILENAME = "voices-v1.0.bin"


class TTSUnavailableError(RuntimeError):
    """A requested local TTS runtime or model is not available."""


class TTSGenerationError(RuntimeError):
    """A TTS provider failed to produce valid audio."""


@dataclass(frozen=True)
class SynthesisRequest:
    text: str
    voice: str = DEFAULT_VOICE
    speed: float = 1.0
    language: str = DEFAULT_LANGUAGE

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("voiceover text must not be empty")
        if not isinstance(self.voice, str) or not self.voice.strip():
            raise ValueError("voice must not be empty")
        if not isinstance(self.language, str) or not self.language.strip():
            raise ValueError("language must not be empty")
        if (
            isinstance(self.speed, bool)
            or not isinstance(self.speed, (int, float))
            or not math.isfinite(float(self.speed))
            or float(self.speed) <= 0
        ):
            raise ValueError("voice speed must be a positive finite number")


@dataclass(frozen=True)
class SynthesisResult:
    path: Path
    provider: str
    voice: str
    sample_rate: int
    duration: float


@runtime_checkable
class TTSProvider(Protocol):
    name: str

    def synthesize(
        self,
        request: SynthesisRequest,
        output_path: Path,
    ) -> SynthesisResult:
        """Synthesize one request to a local audio file."""


def _pcm16(value: object) -> int:
    try:
        sample = float(value)
    except (TypeError, ValueError) as exc:
        raise TTSGenerationError("Kokoro returned a non-numeric audio sample") from exc
    if not math.isfinite(sample):
        raise TTSGenerationError("Kokoro returned a non-finite audio sample")
    sample = max(-1.0, min(1.0, sample))
    if sample <= -1.0:
        return -32768
    return round(sample * 32767)


def _resolve_wav_output_path(output_path: Path) -> Path:
    resolved = output_path.expanduser().resolve()
    if resolved.suffix.lower() != ".wav":
        raise TTSGenerationError("voiceover output must use the .wav extension")
    return resolved


def _write_pcm16_wav(
    samples: object,
    sample_rate: object,
    output_path: Path,
) -> tuple[int, float]:
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, (int, float))
        or not math.isfinite(float(sample_rate))
        or int(sample_rate) <= 0
    ):
        raise TTSGenerationError("Kokoro returned an invalid sample rate")
    rate = int(sample_rate)
    try:
        pcm = array("h", (_pcm16(sample) for sample in samples))  # type: ignore[arg-type]
    except TypeError as exc:
        raise TTSGenerationError("Kokoro returned invalid audio samples") from exc
    if not pcm:
        raise TTSGenerationError("Kokoro returned an empty audio buffer")
    if sys.byteorder != "little":
        pcm.byteswap()

    output_path = _resolve_wav_output_path(output_path)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.stem}-",
            suffix=".wav",
            dir=output_path.parent,
        )
        os.close(handle)
    except OSError as exc:
        raise TTSGenerationError(
            f"could not create voiceover output directory: {exc}"
        ) from exc

    temporary_path = Path(temporary_name)
    try:
        with wave.open(str(temporary_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(rate)
            audio.writeframes(pcm.tobytes())
        os.replace(temporary_path, output_path)
    except (OSError, wave.Error) as exc:
        temporary_path.unlink(missing_ok=True)
        raise TTSGenerationError(f"could not write voiceover WAV: {exc}") from exc
    return rate, len(pcm) / rate


class KokoroOnnxProvider:
    """The local default provider, backed by user-supplied Kokoro model files."""

    name = "kokoro-onnx"

    def __init__(self, model_path: Path, voices_path: Path) -> None:
        self.model_path = model_path.expanduser().resolve()
        self.voices_path = voices_path.expanduser().resolve()
        self._engine: object | None = None

    def _load_engine(self) -> object:
        missing = [
            path
            for path in (self.model_path, self.voices_path)
            if not path.is_file()
        ]
        if missing:
            joined = ", ".join(str(path) for path in missing)
            raise TTSUnavailableError(
                "Kokoro model assets are missing: "
                f"{joined}. Place {MODEL_FILENAME} and {VOICES_FILENAME} in "
                "the configured model directory; Zing never downloads models "
                "during a render."
            )
        if self._engine is not None:
            return self._engine
        try:
            module = importlib.import_module("kokoro_onnx")
        except ImportError as exc:
            raise TTSUnavailableError(
                "kokoro-onnx is not installed. It is intentionally excluded "
                "from the default install because its runtime pulls "
                "espeakng-loader; install it separately on a supported Python "
                "3.10-3.13 environment."
            ) from exc
        try:
            self._engine = module.Kokoro(
                str(self.model_path),
                str(self.voices_path),
            )
        except Exception as exc:
            raise TTSGenerationError(
                f"could not initialize kokoro-onnx: {exc}"
            ) from exc
        return self._engine

    def synthesize(
        self,
        request: SynthesisRequest,
        output_path: Path,
    ) -> SynthesisResult:
        output_path = _resolve_wav_output_path(output_path)
        engine = self._load_engine()
        try:
            samples, sample_rate = engine.create(  # type: ignore[attr-defined]
                request.text,
                voice=request.voice,
                speed=float(request.speed),
                lang=request.language,
            )
        except Exception as exc:
            raise TTSGenerationError(f"kokoro-onnx synthesis failed: {exc}") from exc
        rate, duration = _write_pcm16_wav(samples, sample_rate, output_path)
        return SynthesisResult(
            path=output_path,
            provider=self.name,
            voice=request.voice,
            sample_rate=rate,
            duration=duration,
        )


def default_tts_provider(model_dir: Path | None = None) -> KokoroOnnxProvider:
    """Resolve the local Kokoro default without importing or downloading it."""
    if model_dir is None:
        root = Path(
            os.environ.get(
                "ZING_KOKORO_HOME",
                Path.home() / ".cache" / "myzing" / "kokoro",
            )
        )
    else:
        root = model_dir
    model_path = Path(os.environ.get("ZING_KOKORO_MODEL", root / MODEL_FILENAME))
    voices_path = Path(
        os.environ.get("ZING_KOKORO_VOICES", root / VOICES_FILENAME)
    )
    return KokoroOnnxProvider(model_path, voices_path)
