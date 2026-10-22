"""Bounded offline animated memes: Pillow text once, FFmpeg motion/compositing."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import warnings
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from myzing import storage
from myzing.render.pipeline import filter_script_args
from . import MemeError
from .render import (ASPECT_ALIASES, MAX_PIXELS, Rect, _draw_layer, fit_rect,
                     layout_boxes, output_size, require_pillow, resolve_font, text_layers)
from .templates import fetch_blank, get_template
from .validate import check_texts

MAX_BYTES = 500 * 1024 * 1024
MAX_SECONDS = 30
# Exclude playlists, concat, devices and other demuxers that open nested resources.
FORMATS = "mov,matroska,webm,avi,mpeg,mpegts,gif,png_pipe,jpeg_pipe,mjpeg,webp_pipe,image2"
PROBE_TIMEOUT = 20
RENDER_TIMEOUT = 180


@dataclass(frozen=True)
class MemeVideoResult:
    """Versioned package-local contract, independent of the shared schemas."""

    path: str
    source_path: str
    width: int
    height: int
    duration: float
    requested_duration: float
    fps: int
    size_bytes: int
    has_audio: bool
    gif: dict | None
    layout: str
    aspect: str
    fit: str
    boxes: list[dict]
    validation: dict
    warnings: list[str]
    version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> MemeVideoResult:
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise MemeError("Unsupported animated meme result version; expected version 1.")
        try:
            return cls(**data)
        except TypeError as exc:
            raise MemeError(f"Invalid animated meme result: {exc}") from exc


def _number(name: str, value: float, low: float, high: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise MemeError(f"{name} must be a finite number from {low} to {high}.")
    return value


def _integer(name: str, value: int, low: int, high: int) -> int:
    _number(name, value, low, high)
    if type(value) is not int:
        raise MemeError(f"{name} must be an integer.")
    return value


def _run(command: list[str], *, timeout: int) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MemeError(f"{Path(command[0]).stem} timed out after {timeout}s; trim or resize the input.") from exc
    except OSError as exc:
        raise MemeError(f"Could not run {Path(command[0]).stem}: {exc}; install FFmpeg and ffprobe on PATH.") from exc
    if result.returncode:
        raise MemeError(f"{Path(command[0]).stem} could not process this media; use a local MP4, GIF, or still image. "
                        f"{result.stderr[-1800:].strip()}")
    return result.stdout


def _local_path(value: str) -> Path:
    if not isinstance(value, str) or "://" in value or value.startswith(("\\\\", "//")):
        raise MemeError("Use a local file path; animated rendering does not access network sources.")
    path = Path(value).expanduser().resolve()
    if str(path).startswith(("\\\\", "//")):
        raise MemeError("Use a local file path, not a network share.")
    return path


def _probe(path: Path, ffprobe: str) -> dict:
    try:
        data = json.loads(_run([
            ffprobe, "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", FORMATS,
            "-show_streams", "-show_format", "-of", "json", str(path),
        ], timeout=PROBE_TIMEOUT))
        streams = data.get("streams", [])
        video = next(s for s in streams if s.get("codec_type") == "video"
                     and not s.get("disposition", {}).get("attached_pic"))
        width, height = int(video["width"]), int(video["height"])
        if min(width, height) <= 0 or max(width, height) > 8192 or width * height > MAX_PIXELS:
            raise MemeError("Source exceeds the 8192px / 40 megapixel limit; resize it first.")
        sar = video.get("sample_aspect_ratio", "1:1")
        ratio = Fraction(sar.replace(":", "/")) if sar not in ("N/A", "0:1") else Fraction(1)
        width = round(width * ratio)
        rotation = next((float(s["rotation"]) for s in video.get("side_data_list", []) if "rotation" in s), 0)
        if not math.isfinite(rotation) or rotation % 90:
            raise MemeError("Unsupported display rotation; normalize the source to a multiple of 90 degrees first.")
        if rotation % 180:
            width, height = height, width
        if min(width, height) <= 0 or max(width, height) > 8192 or width * height > MAX_PIXELS:
            raise MemeError("Source display dimensions exceed the 8192px / 40 megapixel limit; resize it first.")
        raw_duration = video.get("duration", data.get("format", {}).get("duration"))
        duration = float(raw_duration) if raw_duration not in (None, "N/A") else None
        if duration is not None and (not math.isfinite(duration) or duration <= 0):
            raise MemeError("Source has an invalid duration; re-encode it before rendering.")
        return {"width": width, "height": height, "duration": duration, "stream": video["index"],
                "format": data.get("format", {}).get("format_name", ""),
                "has_audio": any(s.get("codec_type") == "audio" for s in streams)}
    except (ValueError, KeyError, TypeError, StopIteration, ZeroDivisionError) as exc:
        if isinstance(exc, MemeError):
            raise
        raise MemeError("Unsupported or unreadable media; provide a decodable local video, GIF, or still image.") from exc


def _windows(count: int, duration: float, at: list[float] | None,
             until: list[float] | None) -> list[tuple[float, float]]:
    for name, values in (("at", at), ("until", until)):
        if values is not None and (not isinstance(values, (list, tuple)) or len(values) != count):
            raise MemeError(f"Provide exactly one {name} value per text, including empty slots.")
    starts = at if at is not None else [0] * count
    ends = until if until is not None else [duration] * count
    result = []
    for a, b in zip(starts, ends):
        _number("at", a, 0, duration)
        _number("until", b, 0, duration)
        if a >= b:
            raise MemeError("Each text window must have at < until within the trimmed output duration.")
        result.append((a, b))
    return result


def _fit_filter(source: tuple[int, int], viewport: Rect, size: tuple[int, int], fit: str) -> str:
    """Crop before scaling, as Pillow does, to bound intermediate allocations."""
    sw, sh = source
    vw, vh = round(viewport.width), round(viewport.height)
    rect = fit_rect(source, viewport, fit)
    if fit == "cover":
        scale = rect.width / sw
        cw, ch = min(sw, round(vw / scale)), min(sh, round(vh / scale))
        fitted = f"crop={max(1, cw)}:{max(1, ch)}:exact=1,scale={vw}:{vh}:flags=lanczos"
    else:
        rw, rh = max(1, round(rect.width)), max(1, round(rect.height))
        fitted = (f"scale={rw}:{rh}:flags=lanczos,"
                  f"pad={vw}:{vh}:{round(rect.x - viewport.x)}:{round(rect.y - viewport.y)}:color=0x181818")
    w, h = size
    if viewport.y:
        fitted += f",pad={w}:{h}:0:{round(viewport.y)}:color=white"
    return fitted


def _publish(staged: Path, target: Path, overwrite: bool) -> None:
    if overwrite:
        os.replace(staged, target)
    else:
        # Same filesystem: hard-link publication is atomic and refuses a file
        # created by another process after the initial existence check.
        try:
            os.link(staged, target)
        except FileExistsError as exc:
            raise MemeError(f"{target} already exists; choose another --out or pass overwrite.") from exc
        except OSError as exc:
            raise MemeError(f"Could not publish {target} without overwriting: {exc}. "
                            "Choose a writable local destination with hard-link support (such as NTFS, APFS, or ext4).") from exc


def render_meme_video(texts: list[str], *, video: str = "", image: str = "", template: str = "",
                      layout: str = "", aspect: str = "1:1", out: str = "", fit: str = "",
                      font: str = "", regions: list[list[float]] | None = None,
                      plate: bool = False, shadow: bool = False, rotation: float = 0,
                      start: float = 0, end: float | None = None, max_duration: float = 30,
                      duration: float = 5, zoom: float = 0, fps: int = 30, width: int | None = None,
                      gif: bool = False, gif_fps: int = 10, gif_width: int = 640,
                      gif_duration: float = 8, at: list[float] | None = None,
                      until: list[float] | None = None, overwrite: bool = False) -> dict:
    """Return paths and measured metadata. All text times use output seconds.

    ``duration`` and ``zoom`` apply to stills; video trims use source start/end.
    GIF limits can be lowered but never exceed 8s, 10fps, or 640px width.
    """
    if sum(bool(v) for v in (video, image, template)) != 1:
        raise MemeError("Provide exactly one of video, image, or a cached template.")
    for name, value in (("plate", plate), ("shadow", shadow), ("gif", gif), ("overwrite", overwrite)):
        if type(value) is not bool:
            raise MemeError(f"{name} must be boolean")
    _number("rotation", rotation, -180, 180)
    _number("start", start, 0, 86400)
    _number("max_duration", max_duration, .1, MAX_SECONDS)
    _number("duration", duration, .1, MAX_SECONDS if video else max_duration)
    _number("zoom", zoom, 0, .25)
    _integer("fps", fps, 1, 60)
    _integer("gif_fps", gif_fps, 1, 10)
    _integer("gif_width", gif_width, 16, 640)
    _number("gif_duration", gif_duration, .1, 8)
    if end is not None:
        _number("end", end, 0, 86400)
    if width is not None:
        _integer("width", width, 64, 1920)
        if width % 2:
            raise MemeError("width must be even for H.264 output.")
    if not video and (start or end is not None):
        raise MemeError("Use duration for still motion; start/end trim a video or GIF.")
    if video and zoom:
        raise MemeError("zoom applies to still images/templates; omit it for video/GIF inputs.")
    selected = get_template(template) if template else None
    layout = layout or ("labels" if selected else "classic")
    fit = fit or ("contain" if selected else "cover")
    aspect = ASPECT_ALIASES.get(aspect, aspect)
    output_size(aspect, (1200, 675))
    if fit not in ("cover", "contain"):
        raise MemeError("fit must be cover or contain")
    count = selected["box_count"] if selected else (len(regions) if isinstance(regions, list) else None)
    validation = check_texts(texts, box_count=count)
    if not validation["valid"]:
        raise MemeError(" ".join(p["message"] for p in validation["problems"]))
    texts = list(validation["texts"])
    windows_count = len(texts)
    if selected and layout == "labels" and regions is None:
        texts += [""] * (selected["box_count"] - len(texts))
        regions = selected["box_layout"]
    layout_boxes(layout, len(texts), (1080, 1080), regions=regions)
    font = resolve_font(font or ("sans" if layout == "caption" else "anton"))
    Image, _, _, _, ImageOps = require_pillow()
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise MemeError("Animated memes require FFmpeg and ffprobe on PATH; install FFmpeg and run zing doctor.")
    if selected:
        try:
            source = _local_path(str(fetch_blank(template, allow_download=False)))
        except MemeError as exc:
            raise MemeError("Animated templates must already be cached; use a local --image or cache the blank with zing meme render first.") from exc
    else:
        source = _local_path(video or image)
    if not source.is_file():
        raise MemeError(f"Source is not a local file: {source}")
    if not 0 < source.stat().st_size <= MAX_BYTES:
        raise MemeError("Source is empty or exceeds the 500 MiB limit; trim or compress it first.")
    target = _local_path(out or str(storage.workspace_root() / "memes/renders" / f"meme-{uuid4().hex[:12]}.mp4"))
    gif_target = target.with_suffix(".gif") if gif else None
    for dest in (target, gif_target):
        if dest is None:
            continue
        if dest == source or (dest.exists() and os.path.samefile(dest, source)):
            raise MemeError("Output must differ from the source path.")
        if dest.exists() and not overwrite:
            raise MemeError(f"{dest} already exists; choose another --out or pass overwrite.")
    if target.suffix.lower() != ".mp4":
        raise MemeError("Animated output must end in .mp4; use gif=true / --gif for a companion GIF.")
    info = _probe(source, ffprobe)
    source_size = (info["width"], info["height"])
    still = None
    if not video:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as opened:
                    if getattr(opened, "n_frames", 1) != 1:
                        raise MemeError("Animated image supplied as a still; use --video for GIF motion.")
                    if opened.width * opened.height > MAX_PIXELS or max(opened.size) > 8192:
                        raise MemeError("Source exceeds the 8192px / 40 megapixel limit; resize it first.")
                    still = ImageOps.exif_transpose(opened).convert("RGB")
            source_size = still.size
        except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise MemeError(f"Could not decode still image: {exc}; resize or re-encode it.") from exc
    if video:
        if info["duration"] is None:
            raise MemeError("Video/GIF has no finite duration; re-encode it before rendering.")
        stop = info["duration"] if end is None else end
        if start >= stop or stop > info["duration"] + .001:
            raise MemeError("Require 0 <= start < end <= source duration.")
        duration = stop - start
        if duration > max_duration + .000001:
            raise MemeError(f"Selected input is {duration:.3f}s; limit is {max_duration:g}s. Trim with --start/--end.")
    windows = _windows(windows_count, duration, at, until)
    windows += [(0, duration)] * (len(texts) - windows_count)
    w, h = output_size(aspect, source_size)
    if width is not None:
        w, h = width, max(2, round(h * width / w))
    w, h = w + w % 2, h + h % 2
    if h > 4096 or w * h > 8_000_000:
        raise MemeError("Output exceeds 4096px height / 8 megapixels; choose an aspect preset or smaller width.")
    if duration * fps < 1:
        raise MemeError("Selected duration must include at least one output frame; increase duration or fps.")
    viewport, layers = text_layers(texts, source_size=source_size, size=(w, h), layout=layout,
                                  fit=fit, font=font, regions=regions, plate=plate,
                                  shadow=shadow, rotation=rotation)
    target.parent.mkdir(parents=True, exist_ok=True)
    reports = []
    with tempfile.TemporaryDirectory(prefix=".meme-", dir=target.parent) as directory:
        work = Path(directory)
        input_path = source
        if still is not None:
            input_path = work / "source.png"
            still.save(input_path)
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                   "-filter_complex_threads", "1", "-protocol_whitelist", "file", "-format_whitelist", FORMATS]
        if video:
            command += ["-ss", str(start)]
            if "gif" in info.get("format", "").split(","):
                command += ["-ignore_loop", "1"]
        else:
            command += ["-loop", "1", "-framerate", str(fps)]
        command += ["-i", str(input_path)]
        sw, sh = source_size
        chain = f"setpts=PTS-STARTPTS,fps={fps},scale={sw}:{sh},setsar=1,format=rgba"
        if zoom:
            # A single still goes through FFmpeg zoompan; text remains stationary.
            frames = max(1, math.ceil(duration * fps) - 1)
            chain += (f",zoompan=z='1+{zoom}*min(on/{frames},1)':"
                      f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={sw}x{sh}:fps={fps}")
        chain += "," + _fit_filter(source_size, viewport, (w, h), fit)
        graph = [f"[0:{info['stream'] if video else 0}]{chain}[base]"]
        previous = "base"
        for index, (layer, (a, b)) in enumerate(zip(layers, windows)):
            if not layer.text.strip():
                continue
            canvas = Image.new("RGBA", (w, h))
            reports.append({"index": index, **_draw_layer(canvas, layer), "at": a, "until": b})
            png = work / f"text-{index}.png"
            canvas.save(png)
            command += ["-protocol_whitelist", "file", "-i", str(png)]
            label = f"text{index}"
            graph.append(f"[{previous}][{len(reports)}:v]overlay=0:0:format=auto:"
                         f"enable='between(t,{a:.9f},{b:.9f})'[{label}]")
            previous = label
        graph.append(f"[{previous}]format=yuv420p[outv]")
        script = work / "composition.ffgraph"
        script.write_text(";\n".join(graph), encoding="utf-8")
        staged = work / "render.mp4"
        command += filter_script_args(ffmpeg, script) + ["-map", "[outv]"]
        if video and info["has_audio"]:
            command += ["-map", "0:a:0", "-af", "apad", "-c:a", "aac", "-b:a", "192k"]
        else:
            command += ["-an"]
        command += ["-t", str(duration), "-r", str(fps), "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-threads", "2", "-movflags", "+faststart", str(staged)]
        _run(command, timeout=RENDER_TIMEOUT)
        measured = _probe(staged, ffprobe)
        gif_report = None
        if gif_target:
            gf, gw, gd = min(fps, gif_fps), min(w, gif_width), min(duration, gif_duration)
            # GIF timestamps have centisecond precision. Quantize down so the
            # final frame cannot push the animation beyond the requested cap.
            gd = math.floor(gd * 100 + 1e-7) / 100
            if gd < 1 / gf:
                raise MemeError("GIF duration must include at least one GIF frame; increase duration or gif_fps.")
            gif_script = work / "palette.ffgraph"
            gif_script.write_text(
                f"[0:v]fps={gf},scale={gw}:-1:flags=lanczos,split[a][b];"
                "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a[outg]",
                encoding="utf-8")
            staged_gif = work / "render.gif"
            frames = math.floor(gd * gf + 1e-7)
            last_delay = math.floor(gd * 100) - round((frames - 1) * 100 / gf)
            _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                  "-filter_complex_threads", "1", "-protocol_whitelist", "file", "-t", str(gd), "-i", str(staged),
                  *filter_script_args(ffmpeg, gif_script), "-map", "[outg]", "-an", "-frames:v", str(frames),
                  "-loop", "0", "-final_delay", str(last_delay), str(staged_gif)], timeout=RENDER_TIMEOUT)
            gp = _probe(staged_gif, ffprobe)
            gif_report = {"path": str(gif_target), "width": gp["width"], "height": gp["height"],
                          "duration": gp["duration"], "fps": gf, "frames": frames,
                          "size_bytes": staged_gif.stat().st_size}
        size_bytes = staged.stat().st_size
        # Both encodes must finish before publishing either output.
        _publish(staged, target, overwrite)
        if gif_target:
            _publish(staged_gif, gif_target, overwrite)
    return MemeVideoResult(
        path=str(target), source_path=str(source), width=w, height=h,
        duration=measured["duration"], requested_duration=duration, fps=fps,
        size_bytes=size_bytes, has_audio=measured["has_audio"], gif=gif_report,
        layout=layout, aspect=aspect, fit=fit, boxes=reports, validation=validation,
        warnings=(["Generic catalog regions: inspect placement or supply custom regions."]
                  if selected and selected["layout_kind"] == "generic_rows" else []),
    ).to_dict()
