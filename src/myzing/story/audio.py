"""Deterministic paper sounds and a quiet music bed, mixed after narration."""
from __future__ import annotations

import math
import random
import re
import struct
import sys
import unicodedata
import wave
from array import array
from pathlib import Path

from myzing.factory.tools import ffmpeg, run

from . import StoryError
from .contract import cue_time, local_photo

SLIDE_LEAD = .42
SLIDE_DURATION = .8
SFX_LEVEL = 10 ** (-18 / 20)
EFFECT_LENGTHS = {"whoosh": SLIDE_DURATION, "pop": .12, "stamp": .22}


def _headline_tokens(text: str) -> list[str]:
    value = unicodedata.normalize("NFKC", text).lower()
    return "".join(char if unicodedata.category(char)[0] in "LN" else " " for char in value).split()


def _mention(text: str, phrase: str, *, plural: bool = False) -> int | None:
    """Match the page's normalized words and its optional one-letter plural."""
    words, wanted = _headline_tokens(text), _headline_tokens(phrase)
    if not wanted:
        return None
    for index in range(len(words) - len(wanted) + 1):
        if all(word == part or plural and (word == part + "s" or part == word + "s")
               for word, part in zip(words[index:index + len(wanted)], wanted)):
            return index
    return None


def _headline_events(story: dict, timings: dict) -> list[dict]:
    events = []
    for index, beat in enumerate(timings["beats"]):
        if index:
            events.append({"kind": "whoosh", "at": beat["start"]})
        people, picture = set(), None
        for line in beat["lines"]:
            text = line.get("text", "")
            for ident, member in story.get("cast", {}).items():
                name = member["name"].strip()
                parts = name.split()
                names = [name, *parts[:1], *parts[-1:]]
                if ident not in people and any(_mention(text, name) is not None for name in names):
                    people.add(ident)
                    events.append({"kind": "pop", "at": line["start"]})
            matches = []
            for ident, image in story.get("images", {}).items():
                keywords = image.get("keywords", [word for word in re.split("[-_]", ident) if len(word) >= 3])
                positions = [position for word in keywords
                             if (position := _mention(text, word.lower(), plural=True)) is not None]
                if positions:
                    matches.append((min(positions), ident))
            if matches:
                # Stable order agrees with the page when two image keywords share a position.
                latest = sorted(matches, key=lambda item: item[0])[-1][1]
                if latest != picture:
                    events.append({"kind": "pop", "at": line["start"]})
                    picture = latest
    if timings.get("outro_start", timings["duration"]) < timings["duration"]:
        start = timings["outro_start"]
        events.append({"kind": "whoosh", "at": start})
        if any(member.get("photos") for member in story.get("cast", {}).values()):
            events.append({"kind": "pop", "at": start})
    return sorted((event for event in events if 0 <= event["at"] < timings["duration"]),
                  key=lambda event: event["at"])


def effect_events(story: dict, timings: dict) -> list[dict]:
    """Resolve the same panel starts and item cues that the page uses."""
    if story.get("look", "cutout") == "headline":
        return _headline_events(story, timings)
    events = []
    panels = story["panels"]
    for index, panel in enumerate(panels):
        start = cue_time(panel["from"], timings)
        visible_start = max(0.0, start - SLIDE_LEAD) if index else 0.0
        visible_end = min(timings["duration"], cue_time(panels[index + 1]["from"], timings)
                          + SLIDE_DURATION - SLIDE_LEAD) if index + 1 < len(panels) else timings["duration"]
        if index:
            events.append({"kind": "whoosh", "at": start - SLIDE_LEAD})

        def arrival(item, *, static=False):
            at = cue_time(item["at"], timings) if "at" in item else start if index else 0.0
            until = min(visible_end, cue_time(item["until"], timings)) if "until" in item else visible_end
            first_seen = max(visible_start, at) if not static else visible_start
            if first_seen >= until:
                return None
            # Earlier cues can animate offscreen. Their sound starts when the panel
            # enters, while cues during either camera slide keep their exact time.
            result = max(visible_start, at) if index else at
            # A static prop may disappear before the slide reaches the panel center.
            return first_seen if static and result >= until else result

        for prop in panel.get("props", []):
            at = arrival(prop, static="at" not in prop)
            if at is not None:
                events.append({"kind": "pop", "at": at})
        for card in panel.get("cards", []):
            at = arrival(card)
            if at is not None:
                events.append({"kind": "stamp" if card.get("anim") == "stamp" else "pop", "at": at})
    return sorted((event for event in events if event["at"] < timings["duration"]
                   and event["at"] + EFFECT_LENGTHS[event["kind"]] > 0), key=lambda event: event["at"])


def _effect(kind: str, rate: int, seed: int) -> array:
    """Make filtered paper noise, a small pitch drop, or a low damped impact."""
    duration = EFFECT_LENGTHS[kind]
    count = max(2, round(duration * rate))
    noise, values, low = random.Random(seed), array("f"), 0.0
    for index in range(count):
        t, phase = index / rate, index / (count - 1)
        white = noise.uniform(-1, 1)
        low += .14 * (white - low)
        if kind == "whoosh":
            value = low * math.sin(math.pi * phase) ** 2
        elif kind == "pop":
            value = (math.sin(2 * math.pi * (720 * t - 1800 * t * t)) + .12 * low) * math.exp(-36 * t)
            value *= min(1, t / .004)
        else:
            value = (.8 * math.sin(2 * math.pi * 76 * t) + .35 * low) * math.exp(-23 * t)
            value *= min(1, t / .003)
        values.append(value * min(1, (duration - t) / .008))
    return values


def synthesize_effects(events: list[dict], *, rate: int, frames: int, voice_rms: float) -> array:
    """Make one mono bus; every effect is about 18 dB below spoken-line RMS."""
    bus = array("f", [0]) * frames
    target = voice_rms * SFX_LEVEL
    for index, event in enumerate(events):
        samples = _effect(event["kind"], rate, 731 + index)
        rms = math.sqrt(sum(value * value for value in samples) / len(samples))
        gain = target / rms if rms else 0
        start = round(event["at"] * rate)
        for offset in range(max(0, -start), min(len(samples), frames - start)):
            bus[start + offset] += samples[offset] * gain
    # A set can introduce several props at once. Keep that combined hit quiet.
    peak = max((abs(value) for value in bus), default=0)
    if peak > voice_rms * .5:
        gain = voice_rms * .5 / peak
        bus = array("f", (value * gain for value in bus))
    return bus


def _read_pcm(path: Path) -> tuple[array, int, int]:
    try:
        with wave.open(str(path), "rb") as source:
            rate, channels, width, count = (source.getframerate(), source.getnchannels(),
                                            source.getsampwidth(), source.getnframes())
            if source.getcomptype() != "NONE" or channels not in (1, 2) or width not in (1, 2, 3, 4):
                raise StoryError(f"{path.name}: use a mono or stereo PCM WAV file.")
            data = source.readframes(count)
            if len(data) != count * channels * width:
                raise StoryError(f"{path.name}: the WAV file is incomplete.")
    except (OSError, EOFError, wave.Error) as exc:
        raise StoryError(f"Cannot read {path.name} for the story mix.") from exc
    if width == 1:
        samples = array("f", ((value - 128) / 128 for value in data))
    elif width == 3:
        samples = array("f", (int.from_bytes(data[i:i + 3], "little", signed=True) / 8388608
                              for i in range(0, len(data), 3)))
    else:
        fmt, scale = ("<h", 32768) if width == 2 else ("<i", 2147483648)
        samples = array("f", (value[0] / scale for value in struct.iter_unpack(fmt, data)))
    return samples, rate, channels


def _voice_rms(samples: array, rate: int, channels: int, timings: dict) -> float:
    total, count = 0.0, 0
    for beat in timings["beats"]:
        for line in beat["lines"]:
            start = max(0, round(line["start"] * rate) * channels)
            end = min(len(samples), round(line["end"] * rate) * channels)
            for index in range(start, end):
                total += samples[index] ** 2
            count += max(0, end - start)
    # A silent supplied track still gets a restrained sound bed.
    return math.sqrt(total / count) if total and count else .05


def music_gain(t: float, timings: dict) -> float:
    """Fade the bed at both ends and duck from 0.25 to 0.10 of voice RMS."""
    duration = timings["duration"]
    fade = min(.6, duration / 2)
    edge = max(0, min(1, t / fade, (duration - t) / fade))
    speech = 0.0
    for beat in timings["beats"]:
        for line in beat["lines"]:
            attack = (t - line["start"] + .12) / .12
            release = (line["end"] + .25 - t) / .25
            speech = max(speech, max(0, min(1, attack, release)))
    return edge * (.25 - .15 * speech)


def _music_samples(directory: Path, music: dict, timings: dict, scratch: Path,
                   rate: int, channels: int) -> array:
    # Also enforce rights here for direct callers of the mixer.
    from .heads import photo_errors

    errors = photo_errors(music)
    if errors:
        raise StoryError("\n".join(error.replace("photo", "music") for error in errors))
    source = local_photo(directory, music["path"])
    if not source.is_file():
        raise StoryError("music file is missing")
    decoded = scratch / "music.wav"
    run(ffmpeg(), "-v", "error", "-y", "-protocol_whitelist", "file,pipe",
        "-stream_loop", "-1", "-i", source,
        "-t", timings["duration"], "-vn", "-ac", channels, "-ar", rate,
        "-c:a", "pcm_s16le", "-threads", 1, decoded, capture_output=True,
        timeout=60 + timings["duration"] * 2)
    samples, _, _ = _read_pcm(decoded)
    if not samples:
        raise StoryError("The music file has no audio frames.")
    return samples


def mix(directory: Path, story: dict, timings: dict, scratch: Path, *, no_sfx: bool = False) -> Path:
    """Write a temporary mix, leaving narration.wav and timings.json untouched."""
    narration = Path(directory) / "narration.wav"
    effects = not no_sfx and story.get("sfx", True)
    music = story.get("music")
    if not effects and not music:
        return narration
    samples, rate, channels = _read_pcm(narration)
    frames = len(samples) // channels
    voice_rms = _voice_rms(samples, rate, channels, timings)
    sounds = synthesize_effects(effect_events(story, timings), rate=rate, frames=frames,
                                voice_rms=voice_rms) if effects else None
    bed, bed_scale, envelope = None, 0.0, None
    if music:
        bed = _music_samples(directory, music, timings, scratch, rate, channels)
        rms = math.sqrt(sum(value * value for value in bed) / len(bed))
        bed_scale = voice_rms / rms if rms else 0
        # Interpolate a 100 Hz envelope instead of scanning every line per sample.
        envelope = [music_gain(index / 100, timings) for index in range(math.ceil(frames / rate * 100) + 2)]
    peak = 0.0
    for frame in range(frames):
        sound = sounds[frame] if sounds is not None else 0
        gain = 0.0
        if envelope is not None:
            position = frame * 100 / rate
            index = int(position)
            gain = (envelope[index] + (envelope[index + 1] - envelope[index]) * (position - index)) * bed_scale
        for channel in range(channels):
            index = frame * channels + channel
            value = samples[index] + sound
            if bed is not None:
                value += bed[index % len(bed)] * gain
            samples[index] = value
            peak = max(peak, abs(value))
    # Keep headroom when supplied recordings already peak near full scale.
    master = min(1, .98 / peak) if peak else 1
    output = array("h", (max(-32768, min(32767, round(value * master * 32768))) for value in samples))
    if sys.byteorder != "little":
        output.byteswap()
    target = Path(scratch) / "mixed.wav"
    with wave.open(str(target), "wb") as destination:
        destination.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        destination.writeframes(output.tobytes())
    return target
