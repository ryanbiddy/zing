"""Probe, validate, author ASS, and execute one deterministic FFmpeg render."""

from __future__ import annotations

import errno
import functools
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from myzing.composition import Transition

from myzing.ffmpeg_capabilities import FFmpegCapabilityError, caption_filter
from myzing.schemas import EDL

from .captions import CaptionDependencyError, generate_ass
from .graph import GraphPlan, build_graph
from .validation import MediaInfo, ValidatedEDL, validate_edl


class RenderError(RuntimeError):
    """The renderer could not probe or execute the requested EDL."""


def preflight_captions(edl: EDL, ffmpeg: str) -> str:
    """Fail before probing media, authoring files, or synthesizing voiceovers."""
    if not edl.captions:
        return "ass"
    try:
        return caption_filter(ffmpeg)
    except FFmpegCapabilityError as exc:
        raise RenderError(str(exc)) from exc


@dataclass(frozen=True)
class RenderResult:
    output_path: Path
    duration: float
    warnings: tuple[str, ...]
    command: tuple[str, ...]
    filtergraph: str
    work_dir: Path | None
    audio_measurements: dict | None = None
    delivery_measurements: dict | None = None


def _create_directory(directory: Path, error: str) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RenderError(f"{error}: {exc}") from exc


def _publish_output(staged_output: Path, output_path: Path) -> None:
    _create_directory(output_path.parent, "could not create output directory")
    try:
        os.replace(staged_output, output_path)
        return
    except OSError as exc:
        cross_device = (
            exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == 17
        )
        if not cross_device:
            raise RenderError(f"could not publish rendered output: {exc}") from exc
    try:
        shutil.move(staged_output, output_path)
    except OSError as exc:
        raise RenderError(
            f"could not publish rendered output across filesystems: {exc}"
        ) from exc


def probe_media(path: Path, ffprobe: str = "ffprobe", *, include_color: bool = False) -> MediaInfo:
    if shutil.which(ffprobe) is None:
        raise RenderError(f"ffprobe executable not found: {ffprobe}")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-show_entries",
                ("stream=codec_type,duration,color_space,color_transfer,color_primaries,color_range,pix_fmt:stream_tags:format_tags"
                 if include_color else "stream=codec_type"),
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RenderError(f"could not run ffprobe for {path}: {exc}") from exc
    if result.returncode:
        raise RenderError(
            f"ffprobe failed for {path}: {result.stderr.strip() or 'unknown error'}"
        )
    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
        stream_types = {
            stream.get("codec_type") for stream in payload.get("streams", [])
        }
        metadata = {}
        video_duration = None
        if include_color:
            video = next((s for s in payload.get("streams", []) if s.get("codec_type") == "video"), {})
            metadata = {key: str(video.get(key, "unknown")) for key in (
                "color_space", "color_transfer", "color_primaries", "color_range", "pix_fmt",
            )}
            tags = {**payload.get("format", {}).get("tags", {}), **video.get("tags", {})}
            metadata["profile_tags"] = json.dumps({k: v for k, v in tags.items()
                if any(term in k.lower() for term in ("color", "gamma", "transfer", "profile"))}, sort_keys=True)
            # Container duration can include audio that outlasts the video.
            # Matroska commonly stores this as a DURATION stream tag instead.
            stream_duration = video.get("duration")
            try:
                if stream_duration not in (None, "N/A"):
                    video_duration = float(stream_duration)
                else:
                    stamp = video.get("tags", {}).get("DURATION", "")
                    if re.fullmatch(r"\d+:\d{2}:\d{2}(?:\.\d+)?", stamp):
                        hours, minutes, seconds = map(float, stamp.split(":"))
                        video_duration = hours * 3600 + minutes * 60 + seconds
                if video_duration is not None and (not math.isfinite(video_duration) or video_duration <= 0):
                    video_duration = None
            except (TypeError, ValueError):
                video_duration = None
    except (KeyError, TypeError, ValueError) as exc:
        raise RenderError(f"ffprobe returned malformed metadata for {path}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RenderError(f"ffprobe returned invalid duration for {path}: {duration}")
    return MediaInfo(
        duration=duration,
        has_video="video" in stream_types,
        has_audio="audio" in stream_types,
        color_metadata=metadata,
        video_duration=video_duration,
    )


@functools.lru_cache(maxsize=8)
def ffmpeg_major_version(ffmpeg: str) -> int | None:
    """FFmpeg's major version, or None for git builds and unreadable output."""
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r"ffmpeg version n?(\d+)\.", result.stdout)
    return int(match.group(1)) if match else None


def filter_script_args(ffmpeg: str, script: Path) -> list[str]:
    """Arguments that load a filtergraph from a file on this FFmpeg.

    FFmpeg 7 added ``-/filter_complex <file>`` and FFmpeg 9 removed
    ``-filter_complex_script``. Git builds are treated as current.
    """
    major = ffmpeg_major_version(ffmpeg)
    if major is not None and major < 7:
        return ["-filter_complex_script", str(script)]
    return ["-/filter_complex", str(script)]


def _ffmpeg_command(
    ffmpeg: str,
    plan: GraphPlan,
    graph_path: Path,
    output_path: Path,
    validated: ValidatedEDL,
    fps_rate: str | None = None,
) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for path in plan.input_paths:
        command.extend(["-i", str(path)])
    command.extend(filter_script_args(ffmpeg, graph_path))
    command.extend(
        [
            "-map",
            f"[{plan.video_label}]",
            "-map",
            f"[{plan.audio_label}]",
            "-t",
            f"{validated.duration:.6f}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            fps_rate or f"{validated.edl.fps:.6f}",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-movflags",
            "+faststart",
            "-metadata",
            "creation_time=1970-01-01T00:00:00Z",
            "-f",
            "mp4",
            str(output_path),
        ]
    )
    return command


def _render_in_directory(
    validated: ValidatedEDL,
    output_path: Path,
    directory: Path,
    ffmpeg: str,
    caption_filter_name: str = "ass",
    *,
    caption_writer: Callable[[Path], None] | None = None,
    fps_rate: str | None = None,
    clip_luts: tuple[str | None, ...] = (),
    transitions: tuple[Transition | None, ...] = (),
    caption_overlay: Path | None = None,
    clip_framings: tuple = (),
    clip_audio_filters: tuple = (),
    composition_audio: tuple = (),
    speech_spans: tuple = (),
    music_fades: dict | None = None,
    music_metadata: dict | None = None,
    duck: dict | None = None,
    measure_music: bool = False,
    delivery=None,
    ffprobe: str = "ffprobe",
) -> RenderResult:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RenderError(f"could not create render work directory: {exc}") from exc
    if shutil.which(ffmpeg) is None:
        raise RenderError(f"ffmpeg executable not found: {ffmpeg}")

    include_captions = bool(validated.edl.captions)
    if caption_writer is not None:
        try:
            caption_writer(directory)
        except OSError as exc:
            raise RenderError(f"could not prepare composition captions: {exc}") from exc
    elif include_captions:
        try:
            generate_ass(
                validated.edl.captions,
                validated.edl.width,
                validated.edl.height,
                directory / "captions.ass",
            )
        except (CaptionDependencyError, OSError) as exc:
            raise RenderError(str(exc)) from exc

    duck_envelope = None
    duck_passages: list[list[float]] = []
    if any(a.duck_under_speech and a.duck_scope == "source_speech" for a in composition_audio):
        from myzing.music import ducking
        settings = duck or {}
        attack, release = settings.get("attack", ducking.DEFAULT_ATTACK_SECONDS), settings.get("release", ducking.DEFAULT_RELEASE_SECONDS)
        duck_passages = ducking.duck_passages(speech_spans, validated.duration,
                                              hold=settings.get("hold", ducking.DEFAULT_HOLD_SECONDS), attack=attack,
                                              release=release, plateau=settings.get("plateau", ducking.DEFAULT_PLATEAU_SECONDS))
        duck_envelope = directory / "music-duck.wav"
        try:
            ducking.write_envelope(duck_envelope, duck_passages, validated.duration,
                                   depth_db=settings.get("depth_db", ducking.DEFAULT_DEPTH_DB), attack=attack,
                                   release=release, gain_points=settings.get("gain_points"))
        except OSError as exc:
            raise RenderError(f"could not write the music ducking envelope: {exc}") from exc
    plan = build_graph(
        validated, include_captions, caption_filter=caption_filter_name,
        fonts_dir=caption_writer is not None, fps_rate=fps_rate,
        clip_luts=clip_luts,
        transitions=transitions,
        caption_overlay=caption_overlay,
        clip_framings=clip_framings,
        clip_audio_filters=clip_audio_filters,
        composition_audio=composition_audio,
        music_fades=music_fades, measure_stems=measure_music,
        duck_envelope=duck_envelope,
    )
    graph_path = directory / "filter graph.txt"
    try:
        graph_path.write_text(plan.graph, encoding="utf-8")
    except OSError as exc:
        raise RenderError(f"could not write FFmpeg filtergraph: {exc}") from exc
    staged_output = directory / "rendered.mp4"
    command = _ffmpeg_command(ffmpeg, plan, graph_path, staged_output, validated, fps_rate)
    for label, name in ((plan.music_label, "music-stem.wav"), (plan.source_label, "source-stem.wav")):
        if label:
            command += ["-map", f"[{label}]", "-t", f"{validated.duration:.6f}", "-c:a", "pcm_f32le", str(directory / name)]
    delivery_receipt = None
    try:
        if delivery is not None:
            from .encoding import encode
            result, command, delivery_receipt = encode(command, delivery, validated.duration,
                validated.edl.width, validated.edl.height, validated.edl.fps, directory, ffprobe=ffprobe)
        else:
            result = subprocess.run(
                command,
                cwd=directory,
                check=False,
                capture_output=True,
                text=True,
                timeout=900,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RenderError(f"could not run ffmpeg: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or "unknown FFmpeg error"
        raise RenderError(f"ffmpeg render failed: {detail[-4000:]}")
    if not staged_output.is_file() or staged_output.stat().st_size == 0:
        raise RenderError("ffmpeg reported success but produced no output")

    measurements = None
    if plan.music_label:
        from myzing.music.measurement import measure_mix
        from myzing.audio.media import AudioError
        from myzing.music.ducking import SpanLimitError
        try:
            measurements = measure_mix(staged_output, directory / "music-stem.wav",
                directory / "source-stem.wav" if plan.source_label else None, speech_spans, validated.duration,
                passages=duck_passages or None,
                ramps=ducking.ramp_windows((duck or {}).get("gain_points")) if duck_passages else ())
            if duck_passages:
                measurements["duck"] = {**(duck or {}), "passages": len(duck_passages),
                                        "method": "known-speech gain envelope: raised-cosine pre-duck before each passage, "
                                                  "held through gaps shorter than max(hold, attack + release + plateau) "
                                                  "and at close edit edges, slow raised-cosine recovery"}
        except (AudioError, SpanLimitError) as exc:
            raise RenderError(f"could not measure music mix: {exc}") from exc
        from myzing.project.api import hash_file
        measurements.update(render_sha256=hash_file(staged_output), music_plan=music_metadata)
        (directory / "music-measurements.json").write_text(json.dumps(measurements, indent=2, allow_nan=False), encoding="utf-8")
    _publish_output(staged_output, output_path)
    if delivery_receipt is not None:
        _publish_output(directory / "delivery-encoding.json", output_path.with_suffix(".encoding.json"))
    if measurements is not None:
        _publish_output(directory / "music-measurements.json", output_path.with_suffix(".music.json"))
    return RenderResult(
        output_path=output_path,
        duration=validated.duration,
        warnings=validated.warnings + tuple((measurements or {}).get("warnings", ()))
                 + tuple((delivery_receipt or {}).get("warnings", ())),
        command=tuple(command),
        filtergraph=plan.graph,
        work_dir=directory,
        audio_measurements=measurements,
        delivery_measurements=delivery_receipt,
    )


def render_edl(
    edl: EDL,
    output_path: Path,
    *,
    base_dir: Path | None = None,
    work_dir: Path | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    resolved_assets: dict[str, Path] | None = None,
) -> RenderResult:
    """Execute one EDL after full validation, replacing output atomically.

    resolved_assets, when supplied, is the result of resolve_assets() for
    this EDL, captured before dispatch or voiceover synthesis.
    """
    caption_filter_name = preflight_captions(edl, ffmpeg)
    base_dir = base_dir or Path.cwd()
    output_path = output_path.expanduser().resolve()
    validated = validate_edl(
        edl,
        base_dir,
        lambda path: probe_media(path, ffprobe),
        resolved_assets=resolved_assets,
    )
    input_paths = {
        resolved.path for resolved in (*validated.clips, *validated.audio_tracks)
    }
    if output_path in input_paths:
        raise RenderError("output path must not overwrite an input media file")
    if work_dir is not None:
        return _render_in_directory(
            validated,
            output_path,
            work_dir.expanduser().resolve(),
            ffmpeg,
            caption_filter_name,
        )

    _create_directory(
        output_path.parent,
        f"could not create output directory {output_path.parent}",
    )
    with tempfile.TemporaryDirectory(
        prefix=f".{output_path.stem}-render-",
        dir=output_path.parent,
    ) as temporary:
        result = _render_in_directory(
            validated,
            output_path,
            Path(temporary),
            ffmpeg,
            caption_filter_name,
        )
    return RenderResult(
        output_path=result.output_path,
        duration=result.duration,
        warnings=result.warnings,
        command=result.command,
        filtergraph=result.filtergraph,
        work_dir=None,
    )
