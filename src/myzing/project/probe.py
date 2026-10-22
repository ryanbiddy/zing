"""Read local ffprobe metadata without normalizing or downloading media."""

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path

from myzing.study import proc
from .models import Probe, Rational


def _number(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _rate(value) -> Fraction | None:
    try:
        rate = Fraction(str(value))
        return rate if rate > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def parse_probe(data: dict) -> Probe:
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), {})
    width, height = video.get("width"), video.get("height")
    rotation = _number(video.get("tags", {}).get("rotate")) or 0.0
    for side in video.get("side_data_list", []):
        angle = _number(side.get("rotation"))
        if angle is not None:
            rotation = angle
            break
    display_width, display_height = width, height
    if abs(rotation) % 180 == 90:
        display_width, display_height = height, width
    orientation = None
    if display_width and display_height:
        orientation = ("square" if display_width == display_height else
                       "landscape" if display_width > display_height else "portrait")
    avg = _rate(video.get("avg_frame_rate"))
    nominal = _rate(video.get("r_frame_rate"))
    rate = avg or nominal
    duration = _number(fmt.get("duration"))
    if duration is None:
        duration = _number(video.get("duration"))
    flags, notes = [], []
    if not video or not width or not height:
        flags.append("no_video")
    if duration is None or duration <= 0:
        flags.append("unknown_duration")
    if rate is None:
        flags.append("unknown_fps")
    if avg and nominal and abs(avg - nominal) / nominal > Fraction(1, 100):
        flags.append("vfr_suspected")
        notes.append("Average and nominal frame rates differ; frame timestamps have not been checked.")
    else:
        notes.append("Stream metadata alone does not establish constant frame rate.")
    # Inspect every video stream; a secondary HDR stream must not disappear.
    for stream in streams:
        if stream.get("codec_type") != "video":
            continue
        transfer = str(stream.get("color_transfer", "")).lower()
        side_types = " ".join(str(s.get("side_data_type", "")).lower()
                              for s in stream.get("side_data_list", []))
        if (transfer in {"smpte2084", "arib-std-b67"}
                or any(s in side_types for s in ("mastering display", "content light", "dovi"))):
            flags.append("hdr")
        tags = {**fmt.get("tags", {}), **stream.get("tags", {})}
        # Only explicit metadata, never a guess from the image or bit depth.
        profiles = " ".join(str(v).lower() for k, v in tags.items()
                            if any(word in k.lower() for word in ("gamma", "transfer", "profile", "log")))
        if transfer in {"log", "log_sqrt"} or "log" in profiles:
            flags.append("log")
    if not any(flag in flags for flag in ("hdr", "log")):
        notes.append("No explicit LOG/HDR tag found; untagged camera profiles remain unknown.")
    # ffprobe's input filename is redundant and would defeat project portability.
    fmt = {k: v for k, v in fmt.items() if k != "filename"}
    return Probe(
        duration=duration, streams=streams, format=fmt, width=width, height=height,
        rotation=rotation, fps=Rational(rate.numerator, rate.denominator) if rate else None,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        orientation=orientation, flags=sorted(set(flags)), notes=notes,
    )


def probe_file(path: Path) -> Probe:
    result = proc.run([
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_streams", "-show_format", "-of", "json", str(path),
    ], timeout=120)
    if result.returncode:
        raise proc.MediaError(f"Cannot probe {path}: {proc.tail(result.stderr)}")
    try:
        return parse_probe(json.loads(result.stdout))
    except (ValueError, TypeError, AttributeError) as exc:
        raise proc.MediaError(f"Invalid ffprobe metadata for {path}: {exc}") from exc
