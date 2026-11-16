"""Line-by-line narration with sample-counted pauses and cue times."""
from __future__ import annotations

import json
import math
import re
import tempfile
import wave
from pathlib import Path

from myzing.render.tts import DEFAULT_VOICE, SynthesisRequest, TTSUnavailableError
from myzing.tts_providers import resolve_tts_provider

from . import StoryError

INTRO_GAP = 0.35
LINE_GAP = 0.16
BEAT_GAP = 0.3
OUTRO_GAP = 3.2
KOKORO_SETUP = (
    "Install kokoro-onnx on Python 3.11-3.13 (pip install kokoro-onnx; it is not part of any Zing extra). "
    "Place kokoro-v1.0.onnx and voices-v1.0.bin in ZING_KOKORO_HOME, or set "
    "ZING_KOKORO_MODEL and ZING_KOKORO_VOICES to override those files. "
    "Both files must already be on disk."
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


def generate(directory: Path, story: dict, *, provider: str | None = None,
             voice: str | None = None, speed: float = 1.0,
             lines_dir: Path | None = None, synthetic: bool = False) -> dict:
    """Write narration.wav and timings.json; supplied WAVs retain their exact audio."""
    speed = _seconds(speed, "speed")
    if speed == 0:
        raise StoryError("speed must be greater than zero.")
    chosen = provider.strip().lower() if provider is not None else None
    if lines_dir is not None:
        if chosen not in (None, "lines"):
            raise StoryError("--lines-dir requires --provider lines; omit --lines-dir to synthesize speech.")
        chosen = "lines"
    if chosen == "lines" and lines_dir is None:
        raise StoryError("--provider lines requires --lines-dir with one WAV per line.")
    engine, used_voice = None, None
    if chosen != "lines":
        try:
            engine = resolve_tts_provider(chosen)
        except TTSUnavailableError:
            raise StoryError("Cannot select the narration provider. Use kokoro, elevenlabs or lines; "
                             "check ZING_TTS_PROVIDER if --provider is omitted.") from None
        chosen = "kokoro" if engine.name == "kokoro-onnx" else engine.name
        used_voice = voice if voice is not None else DEFAULT_VOICE
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    clips, fmt = [], None
    with tempfile.TemporaryDirectory(prefix=".story-voice-", dir=directory) as temporary:
        for beat in story["beats"]:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", beat["id"]):
                raise StoryError("Beat ids must start with a letter and use only letters, numbers, '_' or '-'.")
            for index, line in enumerate(beat["lines"]):
                label = f"{beat['id']}-{index}"
                if engine is None:
                    line_path = Path(lines_dir) / f"{label}.wav"
                else:
                    line_path = Path(temporary) / f"{label}.wav"
                    request = SynthesisRequest(text=line.get("say", line["text"]),
                                               voice=voice if voice is not None else DEFAULT_VOICE,
                                               speed=speed)
                    try:
                        result = engine.synthesize(request, line_path)
                    except Exception:
                        # Provider errors can contain HTTP response bodies. Never echo them or keys.
                        setup = (KOKORO_SETUP if chosen == "kokoro" else
                                 "Check ELEVENLABS_API_KEY, ZING_ELEVENLABS_VOICE, the voice ID and service access.")
                        raise StoryError(f"{chosen} could not narrate {label}. {setup}") from None
                    used_voice = result.voice
                data, current = _read_line(line_path)
                if fmt is not None and current != fmt:
                    raise StoryError(f"{label}: all line WAVs must use the same sample rate, channel count and bit depth.")
                fmt = current
                clips.append(data)
    if fmt is None:
        raise StoryError("The story has no lines to narrate.")
    rate, channels, width = fmt
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
               "provider": chosen, "voice": used_voice,
               "synthetic": chosen != "lines" or bool(synthetic)}
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
