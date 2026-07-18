"""Validate the binding Sprint 1 EDL contract before invoking FFmpeg."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from myzing.schemas import AudioTrack, CaptionSpec, Clip, EDL


TIME_EPSILON = 0.000001
SOURCE_DURATION_EPSILON = 0.05
CAPTION_MAX_CHARS_PER_LINE = 42
CAPTION_MAX_LINES = 2
CAPTION_MAX_CPS = 20.0
CAPTION_POSITIONS = {"top", "center", "lower", "bottom"}
AUDIO_KINDS = {"voiceover", "music"}
OUTPUT_PRESETS = {
    "vertical": (9, 16),
    "landscape": (16, 9),
    "square": (1, 1),
}


class EDLValidationError(ValueError):
    """The EDL asks the renderer to guess or execute invalid media."""


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    has_video: bool
    has_audio: bool


@dataclass(frozen=True)
class ResolvedClip:
    spec: Clip
    path: Path
    media: MediaInfo


@dataclass(frozen=True)
class ResolvedAudioTrack:
    spec: AudioTrack
    path: Path
    media: MediaInfo


@dataclass(frozen=True)
class ValidatedEDL:
    edl: EDL
    clips: tuple[ResolvedClip, ...]
    audio_tracks: tuple[ResolvedAudioTrack, ...]
    duration: float
    warnings: tuple[str, ...]
    output_preset: str = "vertical"


Probe = Callable[[Path], MediaInfo]


def output_preset(width: int, height: int) -> str:
    for name, (ratio_width, ratio_height) in OUTPUT_PRESETS.items():
        if width * ratio_height == height * ratio_width:
            return name
    raise EDLValidationError(
        "output aspect ratio must match a 9:16, 16:9, or 1:1 preset"
    )


def _finite(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EDLValidationError(f"{field} must be a number")
    value = float(value)
    if not math.isfinite(value):
        raise EDLValidationError(f"{field} must be finite")
    return value


def _resolve_media(raw_path: str, base_dir: Path, field: str) -> Path:
    if not isinstance(raw_path, str):
        raise EDLValidationError(f"{field} must be a string path")
    if not raw_path.strip():
        raise EDLValidationError(f"{field} is empty")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    path = path.resolve()
    if not path.is_file():
        raise EDLValidationError(f"{field} does not exist: {path}")
    return path


def _validate_caption(
    caption: CaptionSpec,
    index: int,
    duration: float,
    warnings: list[str],
) -> None:
    label = f"captions[{index}]"
    start = _finite(caption.start, f"{label}.start")
    end = _finite(caption.end, f"{label}.end")
    if start < 0 or end <= start:
        raise EDLValidationError(f"{label} must have 0 <= start < end")
    if end > duration + TIME_EPSILON:
        raise EDLValidationError(
            f"{label}.end {end:.3f}s exceeds output duration {duration:.3f}s"
        )
    if not isinstance(caption.text, str) or not caption.text.strip():
        raise EDLValidationError(f"{label}.text is empty")
    if (
        not isinstance(caption.position, str)
        or caption.position not in CAPTION_POSITIONS
    ):
        allowed = ", ".join(sorted(CAPTION_POSITIONS))
        raise EDLValidationError(
            f"{label}.position must be one of {allowed}; got {caption.position!r}"
        )

    lines = caption.text.splitlines() or [caption.text]
    if len(lines) > CAPTION_MAX_LINES:
        warnings.append(
            f"{label} has {len(lines)} lines; readability guidance allows "
            f"{CAPTION_MAX_LINES}"
        )
    for line_index, line in enumerate(lines):
        if len(line) > CAPTION_MAX_CHARS_PER_LINE:
            warnings.append(
                f"{label} line {line_index + 1} has {len(line)} characters; "
                f"guidance allows {CAPTION_MAX_CHARS_PER_LINE}"
            )
    characters_per_second = len(caption.text.replace("\n", "")) / (end - start)
    if characters_per_second > CAPTION_MAX_CPS:
        warnings.append(
            f"{label} reads at {characters_per_second:.1f} characters/second; "
            f"guidance allows {CAPTION_MAX_CPS:.0f}"
        )

    if not isinstance(caption.word_timed, bool):
        raise EDLValidationError(f"{label}.word_timed must be a boolean")
    if not isinstance(caption.all_caps, bool):
        raise EDLValidationError(f"{label}.all_caps must be a boolean")
    if caption.word_timed and not caption.words:
        raise EDLValidationError(
            f"{label}.word_timed is true but no word timings were provided"
        )
    previous_end = start
    for word_index, word in enumerate(caption.words):
        word_label = f"{label}.words[{word_index}]"
        word_start = _finite(word.start, f"{word_label}.start")
        word_end = _finite(word.end, f"{word_label}.end")
        if not isinstance(word.text, str) or not word.text.strip():
            raise EDLValidationError(f"{word_label}.text is empty")
        if word_end <= word_start:
            raise EDLValidationError(f"{word_label} must have start < end")
        if word_start < start - TIME_EPSILON or word_end > end + TIME_EPSILON:
            raise EDLValidationError(
                f"{word_label} ({word_start:.3f}-{word_end:.3f}s) falls outside "
                f"its caption window ({start:.3f}-{end:.3f}s)"
            )
        if word_start < previous_end - TIME_EPSILON:
            raise EDLValidationError(
                f"{word_label} overlaps or precedes the previous word"
            )
        previous_end = word_end


def validate_edl(edl: EDL, base_dir: Path, probe: Probe) -> ValidatedEDL:
    """Resolve media and reject every malformed Sprint 1 timeline."""
    if edl.schema_version != 1:
        raise EDLValidationError(
            f"unsupported EDL schema_version {edl.schema_version}; expected 1"
        )
    if not edl.clips:
        raise EDLValidationError("EDL must contain at least one clip")
    if (
        isinstance(edl.width, bool)
        or not isinstance(edl.width, int)
        or isinstance(edl.height, bool)
        or not isinstance(edl.height, int)
    ):
        raise EDLValidationError("output width and height must be integers")
    if edl.width <= 0 or edl.height <= 0:
        raise EDLValidationError("output width and height must be positive")
    if edl.width % 2 or edl.height % 2:
        raise EDLValidationError("output width and height must be even for yuv420p")
    preset = output_preset(edl.width, edl.height)
    fps = _finite(edl.fps, "fps")
    if fps <= 0:
        raise EDLValidationError("fps must be greater than zero")

    base_dir = base_dir.resolve()
    cache: dict[Path, MediaInfo] = {}

    def inspect(path: Path) -> MediaInfo:
        if path not in cache:
            cache[path] = probe(path)
        return cache[path]

    resolved_clips = []
    expected_start = 0.0
    for original_index, clip in sorted(
        enumerate(edl.clips),
        key=lambda item: (item[1].timeline_start, item[0]),
    ):
        label = f"clips[{original_index}]"
        src_in = _finite(clip.src_in, f"{label}.src_in")
        src_out = _finite(clip.src_out, f"{label}.src_out")
        timeline_start = _finite(
            clip.timeline_start, f"{label}.timeline_start"
        )
        if src_in < 0 or src_out <= src_in:
            raise EDLValidationError(f"{label} must have 0 <= src_in < src_out")
        if timeline_start < 0:
            raise EDLValidationError(f"{label}.timeline_start must be non-negative")
        if timeline_start < expected_start - TIME_EPSILON:
            raise EDLValidationError(
                f"{label} overlaps the previous clip at {timeline_start:.3f}s"
            )
        if timeline_start > expected_start + TIME_EPSILON:
            raise EDLValidationError(
                f"{label} leaves a timeline gap from {expected_start:.3f}s "
                f"to {timeline_start:.3f}s"
            )

        path = _resolve_media(clip.src, base_dir, f"{label}.src")
        media = inspect(path)
        if not media.has_video:
            raise EDLValidationError(f"{label}.src has no video stream: {path}")
        if src_out > media.duration + SOURCE_DURATION_EPSILON:
            raise EDLValidationError(
                f"{label}.src_out {src_out:.3f}s exceeds source duration "
                f"{media.duration:.3f}s"
            )
        resolved_clips.append(ResolvedClip(clip, path, media))
        expected_start = timeline_start + (src_out - src_in)

    duration = expected_start
    warnings: list[str] = []
    for index, caption in enumerate(edl.captions):
        _validate_caption(caption, index, duration, warnings)

    resolved_audio = []
    voiceover_count = sum(track.kind == "voiceover" for track in edl.audio)
    for index, track in enumerate(edl.audio):
        label = f"audio[{index}]"
        if not isinstance(track.kind, str) or track.kind not in AUDIO_KINDS:
            allowed = ", ".join(sorted(AUDIO_KINDS))
            raise EDLValidationError(
                f"{label}.kind must be one of {allowed}; got {track.kind!r}"
            )
        timeline_start = _finite(
            track.timeline_start, f"{label}.timeline_start"
        )
        _finite(track.gain_db, f"{label}.gain_db")
        if timeline_start < 0:
            raise EDLValidationError(f"{label}.timeline_start must be non-negative")
        if not isinstance(track.duck_under_speech, bool):
            raise EDLValidationError(
                f"{label}.duck_under_speech must be a boolean"
            )
        if track.duck_under_speech and track.kind != "music":
            raise EDLValidationError(
                f"{label}.duck_under_speech is only valid for music tracks"
            )

        path = _resolve_media(track.src, base_dir, f"{label}.src")
        media = inspect(path)
        if not media.has_audio:
            raise EDLValidationError(f"{label}.src has no audio stream: {path}")
        if timeline_start >= duration:
            warnings.append(
                f"{label} starts at {timeline_start:.3f}s, at or after the "
                f"{duration:.3f}s output end, so it will be inaudible"
            )
        if track.duck_under_speech and not voiceover_count:
            warnings.append(
                f"{label} requests ducking but the EDL has no voiceover track"
            )
        resolved_audio.append(ResolvedAudioTrack(track, path, media))

    return ValidatedEDL(
        edl=edl,
        clips=tuple(resolved_clips),
        audio_tracks=tuple(resolved_audio),
        duration=duration,
        warnings=tuple(warnings),
        output_preset=preset,
    )
