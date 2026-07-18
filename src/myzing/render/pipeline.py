"""Probe, validate, author ASS, and execute one deterministic FFmpeg render."""

from __future__ import annotations

import errno
import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from myzing.schemas import EDL

from .captions import CaptionDependencyError, generate_ass
from .graph import GraphPlan, build_graph
from .validation import MediaInfo, ValidatedEDL, validate_edl


class RenderError(RuntimeError):
    """The renderer could not probe or execute the requested EDL."""


@dataclass(frozen=True)
class RenderResult:
    output_path: Path
    duration: float
    warnings: tuple[str, ...]
    command: tuple[str, ...]
    filtergraph: str
    work_dir: Path | None


def _publish_output(staged_output: Path, output_path: Path) -> None:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RenderError(f"could not create output directory: {exc}") from exc
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


def probe_media(path: Path, ffprobe: str = "ffprobe") -> MediaInfo:
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
                "stream=codec_type",
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
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RenderError(f"ffprobe returned malformed metadata for {path}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RenderError(f"ffprobe returned invalid duration for {path}: {duration}")
    return MediaInfo(
        duration=duration,
        has_video="video" in stream_types,
        has_audio="audio" in stream_types,
    )


def _ffmpeg_command(
    ffmpeg: str,
    plan: GraphPlan,
    graph_path: Path,
    output_path: Path,
    validated: ValidatedEDL,
) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for path in plan.input_paths:
        command.extend(["-i", str(path)])
    command.extend(
        [
            "-filter_complex_script",
            str(graph_path),
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
            f"{validated.edl.fps:.6f}",
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
) -> RenderResult:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RenderError(f"could not create render work directory: {exc}") from exc
    if shutil.which(ffmpeg) is None:
        raise RenderError(f"ffmpeg executable not found: {ffmpeg}")

    include_captions = bool(validated.edl.captions)
    if include_captions:
        try:
            generate_ass(
                validated.edl.captions,
                validated.edl.width,
                validated.edl.height,
                directory / "captions.ass",
            )
        except (CaptionDependencyError, OSError) as exc:
            raise RenderError(str(exc)) from exc

    plan = build_graph(validated, include_captions)
    graph_path = directory / "filter graph.txt"
    try:
        graph_path.write_text(plan.graph, encoding="utf-8")
    except OSError as exc:
        raise RenderError(f"could not write FFmpeg filtergraph: {exc}") from exc
    staged_output = directory / "rendered.mp4"
    command = _ffmpeg_command(ffmpeg, plan, graph_path, staged_output, validated)
    try:
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

    _publish_output(staged_output, output_path)
    return RenderResult(
        output_path=output_path,
        duration=validated.duration,
        warnings=validated.warnings,
        command=tuple(command),
        filtergraph=plan.graph,
        work_dir=directory,
    )


def render_edl(
    edl: EDL,
    output_path: Path,
    *,
    base_dir: Path | None = None,
    work_dir: Path | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> RenderResult:
    """Execute one EDL after full validation, replacing output atomically."""
    base_dir = (base_dir or Path.cwd()).resolve()
    output_path = output_path.expanduser().resolve()
    validated = validate_edl(
        edl,
        base_dir,
        lambda path: probe_media(path, ffprobe),
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
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_path.stem}-render-",
        dir=output_path.parent,
    ) as temporary:
        result = _render_in_directory(
            validated,
            output_path,
            Path(temporary),
            ffmpeg,
        )
    return RenderResult(
        output_path=result.output_path,
        duration=result.duration,
        warnings=result.warnings,
        command=result.command,
        filtergraph=result.filtergraph,
        work_dir=None,
    )
