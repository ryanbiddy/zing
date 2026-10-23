"""Build one path-safe FFmpeg filtergraph from a validated EDL."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myzing.composition import Transition

from .validation import ValidatedEDL
from .framing import framing_filter


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
    music_label: str | None = None
    source_label: str | None = None


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
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    extra: tuple[str, ...] = (),
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
    filters.extend(extra)
    if fade_in:
        filters.append(f"afade=t=in:st=0:d={_number(fade_in)}")
    if fade_out and trim_start is not None and trim_end is not None:
        filters.append(f"afade=t=out:st={_number(trim_end - trim_start - fade_out)}:d={_number(fade_out)}")
    # Count decoded/resampled samples, independent of decoder timestamps.
    filters.append("asetpts=N/SR/TB")
    source = f"[{input_index}:a:0]" + ",".join(filters)
    start_samples = round(start * 48000)
    if start_samples:
        # Materialize the offset as samples. A subsequent timestamp reset
        # cannot erase this silence; rounding to milliseconds loses precision.
        source += (
            f"[{label}_content];\n"
            "anullsrc=r=48000:cl=stereo,"
            f"atrim=end_sample={start_samples},"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"asetpts=N/SR/TB[{label}_silence];\n"
            f"[{label}_silence][{label}_content]concat=n=2:v=0:a=1,"
            "asetpts=N/SR/TB"
        )
    return (
        source + f",apad=whole_dur={_number(duration)},"
        f"atrim=duration={_number(duration)}[{label}]"
    )


def build_graph(
    validated: ValidatedEDL,
    include_captions: bool,
    *,
    caption_filter: str = "ass",
    fonts_dir: bool = False,
    fps_rate: str | None = None,
    clip_luts: tuple[str | None, ...] = (),
    transitions: tuple[Transition | None, ...] = (),
    caption_overlay: Path | None = None,
    clip_framings: tuple = (),
    clip_audio_filters: tuple = (),
    composition_audio: tuple = (),
    music_fades: dict | None = None,
    measure_stems: bool = False,
    duck_envelope: Path | None = None,
) -> GraphPlan:
    edl = validated.edl
    duration = validated.duration
    lines: list[str] = []
    input_paths: list[Path] = []

    video_labels = []
    clip_audio_labels = []
    if transitions and len(transitions) != len(validated.clips) - 1:
        raise ValueError("transitions must match the validated timeline boundaries")
    rate = fps_rate or _number(edl.fps)
    if transitions:
        from . import transitions as effects
    if clip_luts and len(clip_luts) != len(validated.clips):
        raise ValueError("clip LUTs must match the validated timeline order")
    if clip_framings and len(clip_framings) != len(validated.clips):
        raise ValueError("clip framings must match the validated timeline order")
    if clip_audio_filters and len(clip_audio_filters) != len(validated.clips):
        raise ValueError("clip audio filters must match the validated timeline order")
    for input_index, resolved in enumerate(validated.clips):
        input_paths.append(resolved.path)
        clip = resolved.spec
        label = f"clipv{input_index}"
        video_labels.append(label)
        lut = clip_luts[input_index] if clip_luts else None
        from myzing.color.media import input_matrix
        matrix = input_matrix(resolved.media.color_metadata)
        grade = (
            f"scale=in_color_matrix={matrix},format=rgb24,"
            f"lut3d=file='{lut}':interp=trilinear,"
            "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
            "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709,"
        ) if lut else (
            # When any clip is graded, convert ungraded clips with the same
            # explicit Rec.709 limited-range matrix and tags. FFmpeg's default
            # matrix for untagged input differs across versions (bt601 on 6.x),
            # which shifted ungraded segments by ~2.5 dE next to graded ones.
            ("scale=in_color_matrix=bt601,format=rgb24,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
             if matrix == "bt601" else
             "scale=in_color_matrix=bt709:out_color_matrix=bt709:out_range=tv,format=yuv420p,") +
            "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709,"
        ) if any(clip_luts) or (fps_rate is not None and matrix == "bt601") else ""
        edge = ""
        if transitions:
            following = transitions[input_index] if input_index < len(transitions) else None
            edge = effects.video_edge(clip, following, edl.width, edl.height, rate)
        elif fps_rate is not None:
            from .transitions import video_frame
            # Round absolute timeline endpoints, not each source trim's length.
            # Otherwise fractional trims accumulate drift against audio/captions.
            frames = video_frame(clip.timeline_start + clip.src_out - clip.src_in, rate) - video_frame(clip.timeline_start, rate)
            edge = (f",tpad=stop_mode=clone:stop_duration=1,trim=end_frame={frames},"
                    f"settb=expr=1/({rate}),setpts=N")
        framing = clip_framings[input_index] if clip_framings else None
        framing_clock = ""
        if framing is not None and framing.mode != "fit" and not transitions and edge:
            # Allocate the final frames before crop evaluation: even a cloned
            # source frame gets the window for its own output-frame index.
            framing_clock, edge = edge.removeprefix(",") + ",", ""
        lines.append(
            f"[{input_index}:v:0]"
            f"trim=start={_number(clip.src_in)}:end={_number(clip.src_out)},"
            "setpts=PTS-STARTPTS,"
            f"fps={fps_rate or _number(edl.fps)},"
            + grade + framing_clock + framing_filter(framing, edl.width, edl.height, rate, label)
            + edge + f"[{label}]"
        )
        audio_extra = tuple(clip_audio_filters[input_index]) if clip_audio_filters else ()
        if transitions:
            lines.append(effects.clip_audio(input_index, resolved, f"clipa{input_index}", extra=audio_extra))
        elif resolved.media.has_audio:
            audio_label = f"clipa{input_index}"
            clip_audio_labels.append(audio_label)
            fade_in = fade_out = 0.0
            if fps_rate is not None:
                # Five milliseconds suppresses discontinuity clicks without
                # moving speech, changing duration or crossfading words.
                fade = min(.005, (clip.src_out - clip.src_in) / 2)
                previous = validated.clips[input_index - 1] if input_index else None
                following = validated.clips[input_index + 1] if input_index + 1 < len(validated.clips) else None
                if previous is None or previous.path != resolved.path or abs(previous.spec.src_out - clip.src_in) > 1e-8:
                    fade_in = fade
                if following is None or following.path != resolved.path or abs(clip.src_out - following.spec.src_in) > 1e-8:
                    fade_out = fade
            lines.append(
                _audio_leg(
                    input_index,
                    clip.timeline_start,
                    duration,
                    audio_label,
                    trim_start=clip.src_in,
                    trim_end=clip.src_out,
                    fade_in=fade_in,
                    fade_out=fade_out,
                    extra=audio_extra,
                )
            )

    if transitions:
        effects.join_streams(lines, transitions, rate, duration)
        clip_audio_labels = ["clip_audio"]
    else:
        joined_video = "".join(f"[{label}]" for label in video_labels)
        lines.append(
            f"{joined_video}concat=n={len(video_labels)}:v=1:a=0,"
            f"trim=duration={_number(duration)}"
            # V2 captions must see the output CFR grid, including across cuts.
            + (f",fps={fps_rate}" if fps_rate is not None else "")
            + "[video_concat]"
        )
    caption_base = "video_concat"
    if caption_overlay is not None:
        overlay_index = len(validated.clips) + len(validated.audio_tracks)
        # PNG capture -> ProRes 4444 carries straight alpha. Convert both legs
        # explicitly to full-range RGB; multiply alpha exactly once in overlay.
        # Transition legs use AVTB, which truncates some rational frame times.
        # Put both CFR streams on the exact frame clock before framesync, or an
        # overlay boundary can select the previous frame (e.g. frame 7 at NTSC).
        clock = f"settb=expr=1/({rate}),setpts=N"
        lines.extend([
            f"[video_concat]{clock},scale=in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24[hf_cut]",
            f"[{overlay_index}:v:0]{clock},"
            "scale=in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgba[hf_captions]",
            "[hf_cut][hf_captions]overlay=alpha=straight:format=rgb:eof_action=pass:repeatlast=0,"
            "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
            "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709[video_hyperframes]",
        ])
        caption_base = "video_hyperframes"
    if include_captions:
        if caption_filter not in {"ass", "subtitles"}:
            raise ValueError(f"unsupported caption filter: {caption_filter}")
        lines.append(
            f"[{caption_base}]{caption_filter}=filename='captions.ass':"
            + ("fontsdir='fonts':" if fonts_dir else "")
            + f"original_size={edl.width}x{edl.height}[video_out]"
        )
    else:
        lines.append(f"[{caption_base}]null[video_out]")

    # Stems exist only for a music mix that will be measured.
    measure_stems = measure_stems and any(t.spec.kind == "music" for t in validated.audio_tracks)
    source_measure = None
    if clip_audio_labels and measure_stems:
        joined = "".join(f"[{label}]" for label in clip_audio_labels)
        lines.append(joined + (f"amix=inputs={len(clip_audio_labels)}:normalize=0:duration=longest" if len(clip_audio_labels) > 1 else "anull") + "[source_bus]")
        lines.append("[source_bus]asplit=2[source_audible][source_measure]")
        source_measure = "source_measure"
        clip_audio_labels = ["source_audible"]
    scoped = [a for a in composition_audio if a.duck_under_speech and a.duck_scope == "source_speech"]
    if scoped:
        if duck_envelope is None:
            raise ValueError("source_speech ducking needs a known-speech gain envelope")
        # Director speech passages drive a precomputed gain envelope (1 kHz
        # control rate, raised-cosine ramps). It holds through clause gaps
        # and has no per-sample expression, so it scales with span count.
        envelope_index = len(validated.clips) + len(validated.audio_tracks) + (caption_overlay is not None)
        envelope = (f"[{envelope_index}:a:0]aresample=48000,pan=stereo|c0=c0|c1=c0,"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB,"
                    f"apad=whole_dur={_number(duration)},atrim=duration={_number(duration)}")
        if len(scoped) == 1:
            lines.append(envelope + "[duck_env0]")
        else:
            lines.append(envelope + f",asplit={len(scoped)}" + "".join(f"[duck_env{i}]" for i in range(len(scoped))))
    voice_labels = []
    music: list[tuple[str, bool]] = []
    first_track_input = len(validated.clips)
    for track_offset, resolved in enumerate(validated.audio_tracks):
        input_index = first_track_input + track_offset
        input_paths.append(resolved.path)
        label = f"tracka{track_offset}"
        spec = composition_audio[track_offset] if composition_audio else None
        fades = (music_fades or {}).get(spec.id, {}) if spec else {}
        lines.append(
            _audio_leg(
                input_index,
                resolved.spec.timeline_start,
                duration,
                label,
                gain_db=resolved.spec.gain_db,
                trim_start=spec.src_in if spec else None,
                trim_end=(spec.src_out if spec.src_out is not None else resolved.media.duration) if spec else None,
                fade_in=fades.get("fade_in", 0), fade_out=fades.get("fade_out", 0),
            )
        )
        if resolved.spec.kind == "voiceover":
            voice_labels.append(label)
        else:
            music.append((label, resolved.spec.duck_under_speech and (not spec or spec.duck_scope == "voiceover")))
            index = next((i for i, a in enumerate(scoped) if a is spec), None)
            if index is not None:
                lines.append(f"[{label}][duck_env{index}]amultiply[{label}_source_ducked]")
                music[-1] = (label + "_source_ducked", False)

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
    music_outputs = []
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
            music_outputs.append(output_label)
        else:
            final_audio_labels.append(label)
            music_outputs.append(label)

    music_measure = None
    if measure_stems and music_outputs:
        final_audio_labels = [v for v in final_audio_labels if v not in music_outputs]
        joined = "".join(f"[{label}]" for label in music_outputs)
        lines.append(joined + (f"amix=inputs={len(music_outputs)}:normalize=0:duration=longest" if len(music_outputs) > 1 else "anull") + "[music_bus]")
        lines.append("[music_bus]asplit=2[music_audible][music_measure]")
        final_audio_labels.append("music_audible")
        music_measure = "music_measure"

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

    if caption_overlay is not None:
        input_paths.append(caption_overlay)
    if scoped:
        input_paths.append(duck_envelope)
    if fps_rate is not None and final_audio_labels:
        # Reserve AAC headroom without lifting quiet material or adding latency.
        # Oversampling also catches peaks between the original 48 kHz samples.
        lines[-1] = lines[-1].removesuffix("[audio_out]") + "[audio_unlimited]"
        lines.append("[audio_unlimited]aresample=192000,"
                     "alimiter=limit=0.794328:level=false:latency=true,"
                     "aresample=48000[audio_out]")
    return GraphPlan(
        graph=";\n".join(lines) + "\n",
        input_paths=tuple(input_paths),
        video_label="video_out",
        audio_label="audio_out",
        music_label=music_measure,
        source_label=source_measure,
    )
