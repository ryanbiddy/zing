"""Build one path-safe FFmpeg filtergraph from a validated EDL."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .validation import ValidatedEDL


DUCK_THRESHOLD = 0.03
DUCK_RATIO = 4.0
DUCK_ATTACK_MS = 20
DUCK_RELEASE_MS = 250


@dataclass(frozen=True)
class GraphPlan:
    graph: str
    input_paths: tuple[Path, ...]
    video_label: str
    audio_label: str


def _number(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def _audio_leg(
    input_index: int,
    start: float,
    duration: float,
    label: str,
    *,
    trim_start: float | None = None,
    trim_end: float | None = None,
    gain_db: float = 0.0,
) -> str:
    filters = []
    if trim_start is not None and trim_end is not None:
        filters.append(
            f"atrim=start={_number(trim_start)}:end={_number(trim_end)}"
        )
    filters.extend(
        [
            "asetpts=PTS-STARTPTS",
            "aresample=48000",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
        ]
    )
    if gain_db:
        filters.append(f"volume={_number(gain_db)}dB")
    if start:
        filters.extend(
            [
                f"adelay={round(start * 1000)}:all=1",
                "asetpts=PTS-STARTPTS",
            ]
        )
    filters.extend(
        [
            f"apad=whole_dur={_number(duration)}",
            f"atrim=duration={_number(duration)}",
        ]
    )
    return f"[{input_index}:a:0]" + ",".join(filters) + f"[{label}]"


def build_graph(validated: ValidatedEDL, include_captions: bool) -> GraphPlan:
    edl = validated.edl
    duration = validated.duration
    lines: list[str] = []
    input_paths: list[Path] = []

    video_labels = []
    clip_audio_labels = []
    for input_index, resolved in enumerate(validated.clips):
        input_paths.append(resolved.path)
        clip = resolved.spec
        label = f"clipv{input_index}"
        video_labels.append(label)
        lines.append(
            f"[{input_index}:v:0]"
            f"trim=start={_number(clip.src_in)}:end={_number(clip.src_out)},"
            "setpts=PTS-STARTPTS,"
            f"fps={_number(edl.fps)},"
            f"scale={edl.width}:{edl.height}:"
            "force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={edl.width}:{edl.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "setsar=1,format=yuv420p"
            f"[{label}]"
        )
        if resolved.media.has_audio:
            audio_label = f"clipa{input_index}"
            clip_audio_labels.append(audio_label)
            lines.append(
                _audio_leg(
                    input_index,
                    clip.timeline_start,
                    duration,
                    audio_label,
                    trim_start=clip.src_in,
                    trim_end=clip.src_out,
                )
            )

    joined_video = "".join(f"[{label}]" for label in video_labels)
    lines.append(
        f"{joined_video}concat=n={len(video_labels)}:v=1:a=0,"
        f"trim=duration={_number(duration)}[video_concat]"
    )
    if include_captions:
        lines.append(
            "[video_concat]ass=filename='captions.ass':"
            f"original_size={edl.width}x{edl.height}[video_out]"
        )
    else:
        lines.append("[video_concat]null[video_out]")

    voice_labels = []
    music: list[tuple[str, bool]] = []
    first_track_input = len(validated.clips)
    for track_offset, resolved in enumerate(validated.audio_tracks):
        input_index = first_track_input + track_offset
        input_paths.append(resolved.path)
        label = f"tracka{track_offset}"
        lines.append(
            _audio_leg(
                input_index,
                resolved.spec.timeline_start,
                duration,
                label,
                gain_db=resolved.spec.gain_db,
            )
        )
        if resolved.spec.kind == "voiceover":
            voice_labels.append(label)
        else:
            music.append((label, resolved.spec.duck_under_speech))

    final_audio_labels = list(clip_audio_labels)
    voice_audible_label: str | None = None
    ducked_music_count = sum(duck and bool(voice_labels) for _, duck in music)
    if voice_labels:
        if len(voice_labels) == 1:
            lines.append(f"[{voice_labels[0]}]anull[voice_bus]")
        else:
            joined_voice = "".join(f"[{label}]" for label in voice_labels)
            lines.append(
                f"{joined_voice}amix=inputs={len(voice_labels)}:"
                "duration=longest:normalize=0[voice_bus]"
            )
        if ducked_music_count:
            split_labels = ["voice_audible"] + [
                f"voice_sidechain{index}" for index in range(ducked_music_count)
            ]
            lines.append(
                f"[voice_bus]asplit={len(split_labels)}"
                + "".join(f"[{label}]" for label in split_labels)
            )
            voice_audible_label = "voice_audible"
        else:
            voice_audible_label = "voice_bus"
        final_audio_labels.append(voice_audible_label)

    sidechain_index = 0
    for music_index, (label, duck) in enumerate(music):
        if duck and voice_labels:
            output_label = f"music_ducked{music_index}"
            lines.append(
                f"[{label}][voice_sidechain{sidechain_index}]"
                "sidechaincompress="
                f"threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}:"
                f"attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}:"
                "knee=2.828:detection=rms:link=maximum:makeup=1:mix=1"
                f"[{output_label}]"
            )
            sidechain_index += 1
            final_audio_labels.append(output_label)
        else:
            final_audio_labels.append(label)

    if not final_audio_labels:
        lines.append(
            f"anullsrc=r=48000:cl=stereo:d={_number(duration)}[audio_out]"
        )
    elif len(final_audio_labels) == 1:
        lines.append(
            f"[{final_audio_labels[0]}]"
            "aresample=48000,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo"
            "[audio_out]"
        )
    else:
        joined_audio = "".join(f"[{label}]" for label in final_audio_labels)
        lines.append(
            f"{joined_audio}amix=inputs={len(final_audio_labels)}:"
            "duration=longest:normalize=0,"
            f"atrim=duration={_number(duration)},"
            "aresample=48000,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo"
            "[audio_out]"
        )

    return GraphPlan(
        graph=";\n".join(lines) + "\n",
        input_paths=tuple(input_paths),
        video_label="video_out",
        audio_label="audio_out",
    )
