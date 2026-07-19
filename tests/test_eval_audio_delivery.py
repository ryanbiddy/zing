from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from tools.eval import audio_delivery


def test_measure_audio_delivery_returns_complete_finite_measurement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "voice.wav"
    media_path.write_bytes(b"fixture")
    monkeypatch.setattr(audio_delivery.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(
        audio_delivery.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stderr="I: -14.2 LUFS\nPeak: -1.3 dBFS\n",
        ),
    )

    result = audio_delivery.measure_audio_delivery(media_path)

    assert result == {
        "available": True,
        "integrated_lufs": -14.2,
        "true_peak_dbtp": -1.3,
        "warnings": [],
        "reason": None,
    }


def test_measure_audio_delivery_rejects_incomplete_finite_measurement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "voice.wav"
    media_path.write_bytes(b"fixture")
    monkeypatch.setattr(audio_delivery.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(
        audio_delivery.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stderr="I: -14.2 LUFS\nPeak: -inf dBFS\n",
        ),
    )

    result = audio_delivery.measure_audio_delivery(media_path)

    assert result["available"] is False
    assert result["integrated_lufs"] is None
    assert result["true_peak_dbtp"] is None
    assert result["warnings"] == []
    assert result["reason"] == (
        "ffmpeg ebur128 returned an incomplete finite loudness measurement: "
        "missing true peak"
    )
