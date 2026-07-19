"""Artifact-pinned content probes for a real Kokoro voiceover render."""

from __future__ import annotations

import hashlib
import math
import re
import subprocess
import sys
import wave
from array import array
from collections.abc import Callable
from pathlib import Path
from typing import Any

from myzing.render.tts import SynthesisResult


PROBE_VERSION = "1.0.0"
MODEL_SHA256 = "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"
VOICES_SHA256 = "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
MODEL_SOURCE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx"
)
VOICES_SOURCE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin"
)
MIN_VOICE_RMS_DBFS = -60.0
MIN_RENDER_GAIN_DB = 20.0
EXPECTED_SAMPLE_RATE = 24_000

RunFunction = Callable[..., subprocess.CompletedProcess[str]]


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dbfs(value: float) -> float:
    return 20.0 * math.log10(value) if value > 0 else -math.inf


def _probe_wav(synthesis: SynthesisResult) -> dict[str, Any]:
    path = synthesis.path.expanduser().resolve()
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frame_count = audio.getnframes()
            frames = audio.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        return {
            "passed": False,
            "available": False,
            "path": str(path),
            "reason": f"could not read synthesized WAV: {exc}",
        }

    samples = array("h")
    if sample_width == 2:
        samples.frombytes(frames)
        if sys.byteorder != "little":
            samples.byteswap()
    peak = max((abs(sample) for sample in samples), default=0) / 32768.0
    rms = (
        math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        / 32768.0
        if samples
        else 0.0
    )
    duration = frame_count / sample_rate if sample_rate > 0 else 0.0
    checks = {
        "provider": synthesis.provider == "kokoro-onnx",
        "voice": synthesis.voice == "af_sarah",
        "channels": channels == 1,
        "sample_width": sample_width == 2,
        "sample_rate": (
            sample_rate == EXPECTED_SAMPLE_RATE
            and synthesis.sample_rate == EXPECTED_SAMPLE_RATE
        ),
        "duration": (
            frame_count > 0
            and abs(duration - synthesis.duration) <= 0.02
        ),
        "non_silent": _dbfs(rms) >= MIN_VOICE_RMS_DBFS,
    }
    return {
        "passed": all(checks.values()),
        "available": True,
        "path": str(path),
        "provider": synthesis.provider,
        "voice": synthesis.voice,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate": sample_rate,
        "frame_count": frame_count,
        "duration_seconds": round(duration, 6),
        "rms_dbfs": round(_dbfs(rms), 3),
        "peak_dbfs": round(_dbfs(peak), 3),
        "checks": checks,
    }


def _mean_volume(
    path: Path,
    window: tuple[float, float],
    *,
    ffmpeg: str,
    run: RunFunction,
) -> tuple[float | None, str | None]:
    start, duration = window
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-ss",
        f"{start:.6f}",
        "-t",
        f"{duration:.6f}",
        "-i",
        str(path),
        "-vn",
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    try:
        result = run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not run ffmpeg volume probe: {exc}"
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        reason = detail[-1] if detail else "unknown FFmpeg error"
        return None, f"ffmpeg volume probe failed: {reason}"
    matches = re.findall(
        r"mean_volume:\s*(-?(?:\d+(?:\.\d+)?|inf))\s+dB",
        result.stderr,
        flags=re.IGNORECASE,
    )
    if not matches:
        return None, "ffmpeg volume probe returned no mean_volume"
    value = matches[-1].lower()
    return (-math.inf if value == "-inf" else float(value)), None


def _probe_render(
    path: Path,
    baseline_window: tuple[float, float],
    active_window: tuple[float, float],
    *,
    ffmpeg: str,
    run: RunFunction,
) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        return {
            "passed": False,
            "available": False,
            "path": str(path),
            "reason": "rendered media is not present",
        }
    baseline, baseline_error = _mean_volume(
        path,
        baseline_window,
        ffmpeg=ffmpeg,
        run=run,
    )
    active, active_error = _mean_volume(
        path,
        active_window,
        ffmpeg=ffmpeg,
        run=run,
    )
    if baseline_error or active_error or baseline is None or active is None:
        return {
            "passed": False,
            "available": False,
            "path": str(path),
            "reason": baseline_error or active_error,
        }

    baseline_silent = math.isinf(baseline) and baseline < 0
    gain = None if baseline_silent else active - baseline
    passed = (
        math.isfinite(active)
        and active >= MIN_VOICE_RMS_DBFS
        and (baseline_silent or (gain is not None and gain >= MIN_RENDER_GAIN_DB))
    )
    return {
        "passed": passed,
        "available": True,
        "path": str(path),
        "baseline_window_seconds": list(baseline_window),
        "active_window_seconds": list(active_window),
        "baseline_mean_dbfs": None if baseline_silent else baseline,
        "baseline_silent": baseline_silent,
        "active_mean_dbfs": active,
        "voice_gain_over_baseline_db": (
            None if gain is None else round(gain, 3)
        ),
        "minimum_gain_db": MIN_RENDER_GAIN_DB,
    }


def evaluate_real_voiceover(
    model_path: Path,
    voices_path: Path,
    synthesis: SynthesisResult,
    render_path: Path,
    *,
    expected_model_sha256: str = MODEL_SHA256,
    expected_voices_sha256: str = VOICES_SHA256,
    baseline_window: tuple[float, float],
    active_window: tuple[float, float],
    ffmpeg: str = "ffmpeg",
    run: RunFunction = subprocess.run,
) -> dict[str, Any]:
    """Probe exact model assets, synthesized PCM, and audible render placement."""
    model_path = model_path.expanduser().resolve()
    voices_path = voices_path.expanduser().resolve()
    model_sha256 = _sha256(model_path)
    voices_sha256 = _sha256(voices_path)
    assets = {
        "passed": (
            model_sha256 == expected_model_sha256
            and voices_sha256 == expected_voices_sha256
        ),
        "license": "Apache-2.0",
        "model": str(model_path),
        "model_source": MODEL_SOURCE,
        "model_sha256": model_sha256,
        "model_sha256_passed": model_sha256 == expected_model_sha256,
        "voices": str(voices_path),
        "voices_source": VOICES_SOURCE,
        "voices_sha256": voices_sha256,
        "voices_sha256_passed": voices_sha256 == expected_voices_sha256,
    }
    wav = _probe_wav(synthesis)
    render = _probe_render(
        render_path,
        baseline_window,
        active_window,
        ffmpeg=ffmpeg,
        run=run,
    )
    return {
        "report_schema_version": 1,
        "probe_version": PROBE_VERSION,
        "passed": assets["passed"] and wav["passed"] and render["passed"],
        "assets": assets,
        "wav": wav,
        "render": render,
    }
