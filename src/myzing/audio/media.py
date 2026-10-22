"""Bounded local FFmpeg decoding. No downloads or model loading."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

SAMPLE_RATE = 22050
MAX_SECONDS = 600.0


class AudioError(RuntimeError):
    """An actionable analysis failure."""


def numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise AudioError('Audio analysis needs NumPy; install: python -m pip install "myzing[audio]"') from exc
    return np


def duration_limit(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= MAX_SECONDS:
        raise ValueError(f"max_seconds must be finite and between 0 (exclusive) and {MAX_SECONDS:g}")
    if value * SAMPLE_RATE < 1:
        raise ValueError("max_seconds must cover at least one PCM sample")
    return value


def local_file(path: str | Path) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise AudioError(f"Audio input is not a local file: {path}. Supply a local audio or video file.")
    return path


def ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise AudioError("FFmpeg is missing from PATH; install FFmpeg, then run zing doctor.")
    return executable


def run_ffmpeg(args: list[str], *, timeout: float = 120) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            [ffmpeg(), "-nostdin", "-hide_banner", *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioError("FFmpeg audio analysis timed out; try a shorter local excerpt.") from exc
    except OSError as exc:
        raise AudioError(f"Could not run FFmpeg; check zing doctor: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace")[-2000:].strip()
        raise AudioError(f"FFmpeg could not analyze the audio; check that the file has a decodable audio stream. {detail}")
    return result


def input_args(path: Path, seconds: float) -> list[str]:
    # Input -t bounds work; atrim in the loudness path bounds meter coverage.
    # The whitelist prevents playlists or containers from fetching remote media.
    return ["-protocol_whitelist", "file,pipe", "-t", f"{seconds:.9f}",
            "-i", str(path), "-map", "0:a:0", "-vn", "-sn", "-dn"]


def decode_mono(path: str | Path, *, max_seconds: float = MAX_SECONDS):
    """Return (float32 samples, truncated). At most 600 s / 53 MB of PCM.

    Decode one extra sample to distinguish a full excerpt from an exact-length
    file. The rate and first-stream selection are fixed for reproducibility.
    """
    np = numpy()
    duration_limit(max_seconds)
    path = local_file(path)
    limit = int(max_seconds * SAMPLE_RATE)
    result = run_ffmpeg([
        "-loglevel", "error", *input_args(path, (limit + 1) / SAMPLE_RATE),
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_f32le",
        "-f", "f32le", "pipe:1",
    ], timeout=max(30, max_seconds * 2))
    samples = np.frombuffer(result.stdout, dtype="<f4")
    if not samples.size:
        raise AudioError("The audio stream is empty; supply a file with audio samples.")
    if not np.isfinite(samples).all():
        raise AudioError("Decoded audio contains non-finite samples; repair or re-export the source.")
    return samples[:limit], bool(samples.size > limit)


def ffmpeg_version() -> str:
    output = run_ffmpeg(["-version"], timeout=10).stdout.decode("utf-8", errors="replace")
    return output.splitlines()[0]
