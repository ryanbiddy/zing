"""Audio structure -> `AudioLayout`: loudness curve, speech ratio, and an
honest music heuristic.

Pinned definitions implemented here (schemas.py, binding):
- loudness_curve: per-1-second mean RMS in dBFS via ffmpeg astats. The
  stream is resampled to 48kHz and cut into exact 1s frames with
  asetnsamples — without that, "per frame" is whatever the decoder emits.
- speech_ratio: fraction of duration covered by VAD speech. Silero v6 via
  faster-whisper's bundled get_speech_timestamps, called with
  upstream-style parameters (min_silence 100ms, pad 30ms) — NOT the
  transcription defaults (2s merge + 400ms pad), which would inflate the
  metric (R1-A pick 3).

has_music (R1-A pick 5, heuristic v1): compare the loudness floor of
non-speech gaps against speech-segment loudness. A bed that stays loud
through the gaps reads as music; near-silence in gaps reads as no music.
Wall-to-wall speech leaves no evidence either way — reported as
has_music=False with music_confidence 0.0 plus a warning, never a guess.
`music_confidence` is confidence in the reported bool. S2 adds a tagger
anchor (YAMNet/PANNs) for calibrated confidence.

has_voiceover S1 semantics: "a human voice is present" (speech_ratio >=
0.05). Distinguishing voice-over from on-camera speech is judgment, not
measurement, and stays with the AI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

from myzing.schemas import AudioLayout

from . import proc

SILENCE_FLOOR_DB = -99.0          # JSON-safe stand-in for -inf (digital silence)
SPEECH_PRESENT_RATIO = 0.05
VAD_PARAMS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 250,
    "min_silence_duration_ms": 100,
    "speech_pad_ms": 30,
}


@dataclass
class AudioResult:
    audio: AudioLayout = field(default_factory=AudioLayout)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def measure_audio(media_path: Path, duration: float) -> AudioResult:
    result = AudioResult()
    curve = _loudness_curve(media_path, result.warnings)
    segments = _speech_segments(media_path, result.warnings)

    speech_ratio = 0.0
    if segments is not None and duration > 0:
        speech_ratio = round(
            min(1.0, sum(e - s for s, e in segments) / duration), 3
        )

    has_music, music_confidence = _music_heuristic(
        curve, segments, speech_ratio, result.warnings
    )

    result.audio = AudioLayout(
        has_music=has_music,
        music_confidence=music_confidence,
        has_voiceover=speech_ratio >= SPEECH_PRESENT_RATIO,
        speech_ratio=speech_ratio,
        loudness_curve=curve,
    )
    result.provenance = {
        "loudness": "ffmpeg astats mean RMS dBFS, 1s buckets @48kHz",
        "vad": "silero (faster-whisper bundled), upstream-style params",
        "vad_params": dict(VAD_PARAMS),
        "has_music": "gap-floor heuristic v1",
    }
    return result


# -- loudness ---------------------------------------------------------------

def _loudness_curve(media_path: Path, warnings: list[str]) -> list[float]:
    cmd = [
        "ffmpeg", "-hide_banner", "-i", str(media_path), "-vn",
        "-af",
        "aresample=48000,asetnsamples=48000,"
        "astats=metadata=1:reset=1,"
        "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-",
        "-f", "null", "-",
    ]
    try:
        res = proc.run(cmd, timeout=300)
    except proc.ToolMissing as e:
        warnings.append(f"loudness curve skipped: {e}")
        return []
    if res.returncode != 0:
        warnings.append(
            f"loudness curve skipped: ffmpeg failed:\n{proc.tail(res.stderr)}"
        )
        return []
    curve = parse_astats(res.stdout)
    if not curve:
        warnings.append(
            "loudness curve empty: no audio frames measured (missing or "
            "unreadable audio stream)"
        )
    return curve


def parse_astats(stdout: str) -> list[float]:
    curve: list[float] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("lavfi.astats.Overall.RMS_level="):
            continue
        raw = line.split("=", 1)[1].strip()
        if raw in ("-inf", "inf", "nan", ""):
            curve.append(SILENCE_FLOOR_DB)
            continue
        try:
            curve.append(max(SILENCE_FLOOR_DB, round(float(raw), 1)))
        except ValueError:
            curve.append(SILENCE_FLOOR_DB)
    return curve


# -- speech (VAD) -----------------------------------------------------------

def _speech_segments(
    media_path: Path, warnings: list[str]
) -> list[tuple[float, float]] | None:
    """VAD speech spans in seconds, or None when the measurement had to be
    skipped (which is different from [] = measured, no speech)."""
    try:
        return _run_vad(media_path)
    except ImportError:
        warnings.append(
            "speech ratio skipped: faster-whisper not installed "
            "(pip install myzing[study])"
        )
        return None
    except Exception as e:
        warnings.append(f"speech ratio skipped: VAD failed: {e}")
        return None


def _run_vad(media_path: Path) -> list[tuple[float, float]]:
    """The one seam that touches faster-whisper's VAD (tests mock this)."""
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    sampling_rate = 16000
    audio = decode_audio(str(media_path), sampling_rate=sampling_rate)
    spans = get_speech_timestamps(audio, VadOptions(**VAD_PARAMS))
    return [
        (span["start"] / sampling_rate, span["end"] / sampling_rate)
        for span in spans
    ]


# -- music heuristic --------------------------------------------------------

def _music_heuristic(
    curve: list[float],
    segments: list[tuple[float, float]] | None,
    speech_ratio: float,
    warnings: list[str],
) -> tuple[bool, float]:
    if not curve:
        return False, 0.0
    if segments is None:
        # No VAD -> can't partition speech vs gaps; loud sustained audio is
        # weak evidence at best. Stay honest: unknown.
        warnings.append("music detection skipped: needs VAD speech spans")
        return False, 0.0

    speech_buckets, gap_buckets = _partition_buckets(curve, segments)

    if speech_ratio < SPEECH_PRESENT_RATIO:
        # No meaningful speech: sustained audible level suggests music-only
        # content (common in short-form); near-silence suggests no music.
        level = median(curve)
        if level > -35.0:
            return True, 0.6
        return False, 0.4

    if len(gap_buckets) < 2:
        warnings.append(
            "music detection inconclusive: speech is wall-to-wall, no "
            "non-speech gaps to measure a bed in"
        )
        return False, 0.0

    closeness = median(gap_buckets) - median(speech_buckets)  # dB, usually <0
    if closeness > -18.0:
        # Gaps stay nearly as loud as speech: something sustained is playing.
        confidence = min(0.85, 0.45 + (closeness + 18.0) * 0.02)
        return True, round(confidence, 3)
    confidence = min(0.8, 0.35 + (-closeness - 18.0) * 0.02)
    return False, round(confidence, 3)


def _partition_buckets(
    curve: list[float], segments: list[tuple[float, float]]
) -> tuple[list[float], list[float]]:
    """Split 1s loudness buckets into speech-dominated vs gap buckets."""
    speech: list[float] = []
    gaps: list[float] = []
    for i, level in enumerate(curve):
        b_start, b_end = float(i), float(i + 1)
        overlap = sum(
            max(0.0, min(b_end, e) - max(b_start, s)) for s, e in segments
        )
        (speech if overlap > 0.5 else gaps).append(level)
    return speech, gaps
