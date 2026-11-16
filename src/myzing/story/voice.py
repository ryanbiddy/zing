"""Line-by-line narration with sample-counted pauses and cue times."""
from __future__ import annotations

import importlib
import json
import math
import os
import re
import sys
import wave
from pathlib import Path

from . import StoryError

INTRO_GAP = 0.35
LINE_GAP = 0.16
BEAT_GAP = 0.3
OUTRO_GAP = 3.2
KOKORO_SETUP = (
    "Install kokoro-onnx on Python 3.11-3.13 (pip install kokoro-onnx; it is not part of any Zing extra). "
    "Set ZING_KOKORO_MODEL to the Kokoro .onnx model file and "
    "ZING_KOKORO_VOICES to the voices .bin file. Both files must already be on disk."
)


def _seconds(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise StoryError(f"{label} must be a finite number of seconds, zero or greater.")
    return float(value)


def _read_line(path: Path) -> tuple[bytes, tuple[int, int, int]]:
    try:
        with wave.open(str(path), "rb") as audio:
            fmt = (audio.getframerate(), audio.getnchannels(), audio.getsampwidth())
            if audio.getcomptype() != "NONE" or fmt[1] not in (1, 2) or fmt[2] not in (1, 2, 3, 4):
                raise StoryError(f"{path.name}: use a mono or stereo PCM WAV file (8, 16, 24 or 32 bit).")
            frames = audio.readframes(audio.getnframes())
            if len(frames) != audio.getnframes() * fmt[1] * fmt[2]:
                raise StoryError(f"{path.name}: the WAV file is incomplete.")
    except (OSError, wave.Error, EOFError) as exc:
        raise StoryError(f"Cannot read {path.name}. Supply one PCM WAV per line in --lines-dir.") from exc
    if not frames:
        raise StoryError(f"{path.name}: the WAV file has no audio frames.")
    return frames, fmt


def _kokoro(voice: str, speed: float):
    if sys.version_info >= (3, 14):
        raise StoryError(f"Kokoro does not support Python 3.14 or newer. Use --lines-dir or Python 3.11-3.13. {KOKORO_SETUP}")
    try:
        module = importlib.import_module("kokoro_onnx")
        np = importlib.import_module("numpy")
    except (ImportError, OSError) as exc:
        raise StoryError(f"Kokoro is unavailable. {KOKORO_SETUP}") from exc
    model, voices = os.environ.get("ZING_KOKORO_MODEL"), os.environ.get("ZING_KOKORO_VOICES")
    if not model or not voices or not Path(model).expanduser().is_file() or not Path(voices).expanduser().is_file():
        raise StoryError(f"Kokoro model files are missing. {KOKORO_SETUP}")
    try:
        engine = module.Kokoro(str(Path(model).expanduser()), str(Path(voices).expanduser()))
    except Exception as exc:
        raise StoryError(f"Cannot open the Kokoro model and voices files. {KOKORO_SETUP}") from exc

    def synthesize(line: dict, label: str):
        try:
            samples, rate = engine.create(line.get("say", line["text"]), voice=voice, speed=speed, lang="en-us")
            samples = np.asarray(samples, dtype=np.float32)
            if samples.ndim != 1 or not np.isfinite(samples).all() or not isinstance(rate, int) or rate <= 0:
                raise ValueError("invalid samples or sample rate")
            loud = np.flatnonzero(np.abs(samples) > 0.01)
            if not len(loud):
                raise ValueError("the voice returned only silence")
            # Keep the prototype's small breaths around each spoken line.
            samples = samples[max(0, loud[0] - int(rate * 0.025)):loud[-1] + int(rate * 0.075)]
            return samples, (rate, 1, 2)
        except Exception as exc:
            raise StoryError(f"Kokoro could not narrate {label}. Check the voice name and model files: {exc}") from exc

    return synthesize, np


def generate(directory: Path, story: dict, *, voice: str = "af_heart", speed: float = 1.0,
             lines_dir: Path | None = None, synthetic: bool = False) -> dict:
    """Write narration.wav and timings.json; supplied WAVs retain their exact audio."""
    speed = _seconds(speed, "speed")
    if speed == 0:
        raise StoryError("speed must be greater than zero.")
    provider = "lines" if lines_dir is not None else "kokoro"
    synthesize, np = (None, None) if lines_dir is not None else _kokoro(voice, speed)
    clips, fmt = [], None
    for beat in story["beats"]:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", beat["id"]):
            raise StoryError("Beat ids must start with a letter and use only letters, numbers, '_' or '-'.")
        for index, line in enumerate(beat["lines"]):
            label = f"{beat['id']}-{index}"
            data, current = (_read_line(Path(lines_dir) / f"{label}.wav") if lines_dir is not None
                             else synthesize(line, label))
            if fmt is not None and current != fmt:
                raise StoryError(f"{label}: all line WAVs must use the same sample rate, channel count and bit depth.")
            fmt = current
            clips.append(data)
    if fmt is None:
        raise StoryError("The story has no lines to narrate.")
    rate, channels, width = fmt
    if np is not None:
        peak = max(float(np.max(np.abs(clip))) for clip in clips)
        clips = [(clip * (0.89 / peak) * 32767).astype("<i2").tobytes() for clip in clips]

    frame_size = channels * width
    silence = bytes([128]) * frame_size if width == 1 else bytes(frame_size)
    chunks, beats, cursor, clip_index = [], [], 0, 0

    def pause(seconds, label):
        nonlocal cursor
        count = int(_seconds(seconds, label) * rate)
        chunks.append(silence * count)
        cursor += count

    def timestamp():
        return round(cursor / rate, 3)

    pause(INTRO_GAP, "intro")
    for beat in story["beats"]:
        start, lines = timestamp(), []
        for line in beat["lines"]:
            line_start = timestamp()
            clip = clips[clip_index]
            clip_index += 1
            chunks.append(clip)
            cursor += len(clip) // frame_size
            lines.append({"text": line["text"], "start": line_start, "end": timestamp()})
            pause(line.get("gap", LINE_GAP), "line gap")
        pause(beat.get("tail", BEAT_GAP), "beat tail")
        beats.append({"id": beat["id"], "start": start, "end": timestamp(), "lines": lines})
    outro_start = timestamp()
    pause(story.get("outro", OUTRO_GAP), "outro")
    timings = {"duration": timestamp(), "outro_start": outro_start, "beats": beats,
               "provider": provider, "voice": voice if provider == "kokoro" else None,
               "synthetic": provider == "kokoro" or bool(synthetic)}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    wav_tmp, json_tmp = directory / "narration.wav.tmp", directory / "timings.json.tmp"
    try:
        with wave.open(str(wav_tmp), "wb") as audio:
            audio.setnchannels(channels)
            audio.setsampwidth(width)
            audio.setframerate(rate)
            for chunk in chunks:
                audio.writeframesraw(chunk)
        json_tmp.write_text(json.dumps(timings, indent=1, ensure_ascii=False), encoding="utf-8")
        wav_tmp.replace(directory / "narration.wav")
        json_tmp.replace(directory / "timings.json")
    except OSError as exc:
        raise StoryError(f"Cannot write narration.wav and timings.json: {exc}") from exc
    finally:
        wav_tmp.unlink(missing_ok=True)
        json_tmp.unlink(missing_ok=True)
    return timings
