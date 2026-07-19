from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.render import tts
from myzing.render.tts import (
    KokoroOnnxProvider,
    SynthesisRequest,
    TTSGenerationError,
    TTSUnavailableError,
    default_tts_provider,
)


def test_kokoro_provider_writes_deterministic_pcm_voiceover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    calls: dict[str, object] = {}

    class FakeKokoro:
        def __init__(self, model_path: str, voices_path: str) -> None:
            calls["paths"] = (model_path, voices_path)

        def create(
            self,
            text: str,
            *,
            voice: str,
            speed: float,
            lang: str,
        ) -> tuple[list[float], int]:
            calls["request"] = (text, voice, speed, lang)
            return ([0.0, 0.5, -0.5, 1.0, -1.0] * 4_800, 24_000)

    monkeypatch.setattr(
        tts.importlib,
        "import_module",
        lambda name: SimpleNamespace(Kokoro=FakeKokoro),
    )
    output = tmp_path / "voice over.wav"
    provider = KokoroOnnxProvider(model, voices)

    result = provider.synthesize(
        SynthesisRequest(
            text="Say the result first.",
            voice="af_sarah",
            speed=1.1,
            language="en-us",
        ),
        output,
    )

    assert calls["paths"] == (str(model), str(voices))
    assert calls["request"] == (
        "Say the result first.",
        "af_sarah",
        1.1,
        "en-us",
    )
    assert result.path == output.resolve()
    assert result.provider == "kokoro-onnx"
    assert result.sample_rate == 24_000
    assert result.duration == pytest.approx(1.0)
    with wave.open(str(output), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 24_000
        assert audio.getnframes() == 24_000


def test_kokoro_provider_fails_honestly_when_optional_runtime_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")

    def missing(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(tts.importlib, "import_module", missing)

    with pytest.raises(
        TTSUnavailableError,
        match="intentionally excluded from the default install",
    ):
        KokoroOnnxProvider(model, voices).synthesize(
            SynthesisRequest("Hello from Zing."),
            tmp_path / "voice.wav",
        )


def test_kokoro_provider_reuses_loaded_engine_across_syntheses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    calls: list[str] = []

    class FakeKokoro:
        def __init__(self, model_path: str, voices_path: str) -> None:
            calls.append("init")

        def create(self, text: str, **kwargs) -> tuple[list[float], int]:
            calls.append(text)
            return ([0.0, 0.25], 24_000)

    monkeypatch.setattr(
        tts.importlib,
        "import_module",
        lambda name: SimpleNamespace(Kokoro=FakeKokoro),
    )
    provider = KokoroOnnxProvider(model, voices)

    first = provider.synthesize(
        SynthesisRequest("First result."),
        tmp_path / "first.wav",
    )
    second = provider.synthesize(
        SynthesisRequest("Second result."),
        tmp_path / "second.wav",
    )

    assert calls == ["init", "First result.", "Second result."]
    assert first.path.is_file()
    assert second.path.is_file()


def test_kokoro_provider_rejects_non_wav_output_before_loading_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    calls: list[str] = []

    class FakeKokoro:
        def __init__(self, model_path: str, voices_path: str) -> None:
            calls.append("init")

        def create(self, text: str, **kwargs) -> tuple[list[float], int]:
            calls.append("create")
            return ([0.0], 24_000)

    monkeypatch.setattr(
        tts.importlib,
        "import_module",
        lambda name: SimpleNamespace(Kokoro=FakeKokoro),
    )

    with pytest.raises(TTSGenerationError, match=r"must use the \.wav extension"):
        KokoroOnnxProvider(model, voices).synthesize(
            SynthesisRequest("Do not synthesize this."),
            tmp_path / "voice.mp3",
        )

    assert calls == []


def test_default_provider_uses_explicit_local_model_directory(
    tmp_path: Path,
) -> None:
    provider = default_tts_provider(tmp_path)

    assert provider.model_path == (tmp_path / "kokoro-v1.0.onnx").resolve()
    assert provider.voices_path == (tmp_path / "voices-v1.0.bin").resolve()
