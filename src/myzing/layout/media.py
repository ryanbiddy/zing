"""Bounded local FFmpeg sampling. No network inputs and no implicit download."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

from myzing.study import proc

from .detector import LayoutError
from .types import number


def probe_duration(video: Path) -> float:
    if not video.is_file():
        raise LayoutError(f"Video does not exist: {video}; supply a local video file")
    result = proc.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                       "-select_streams", "v:0", "-show_entries",
                       "stream=width,height,duration:format=duration", "-of", "json", str(video)], timeout=30)
    if result.returncode:
        raise LayoutError(f"Cannot probe video: {proc.tail(result.stderr)}")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = float(stream.get("duration", payload.get("format", {}).get("duration")))
        number(duration, "video duration", 1e-6)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise LayoutError("Video has no usable video stream/duration; remux it with FFmpeg and retry") from exc
    return duration


def sample_frames(video: Path, directory: Path, *, duration: float, sample_rate: float = 2.0,
                  max_samples: int = 600) -> list[tuple[float, Path]]:
    """At most 8 fps / 600 images, at most 640px on either axis.

    Record selected frames' actual PTS (also for VFR), relative to the first
    video frame. FFmpeg applies rotation; scaling normalizes pixel aspect.
    """
    number(sample_rate, "sample_rate", 0.1, 8)
    number(duration, "duration", 1e-6)
    if type(max_samples) is not int or not 1 <= max_samples <= 600:
        raise ValueError("max_samples must be an integer from 1 to 600")
    count = math.ceil(duration * sample_rate)
    if count > max_samples:
        raise LayoutError(f"Sampling needs {count} frames; limit is {max_samples}. "
                          "Trim the video or lower --sample-rate; no interval was silently dropped.")
    if not video.is_file():
        raise LayoutError(f"Video does not exist: {video}")
    directory.mkdir(parents=True, exist_ok=True)
    factor = "min(1,min(640/(iw*sar),640/ih))"
    filters = (f"setpts=PTS-STARTPTS,select='isnan(prev_selected_t)+gte(t-prev_selected_t,{1 / sample_rate:.12f})',"
               f"scale=w='max(1,round(iw*sar*{factor}))':h='max(1,round(ih*{factor}))',setsar=1,showinfo")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-nostdin", "-y",
               "-protocol_whitelist", "file,pipe", "-i", str(video.resolve()), "-map", "0:v:0", "-vf", filters,
               "-fps_mode", "vfr", "-frames:v", str(max_samples + 1), "-an", "-sn",
               str(directory / "frame-%04d.png")]
    try:
        result = proc.run(command, timeout=max(30, duration * 3))
    except subprocess.TimeoutExpired as exc:
        raise LayoutError("FFmpeg sampling timed out; trim or remux the video") from exc
    if result.returncode:
        raise LayoutError(f"FFmpeg sampling failed: {proc.tail(result.stderr)}")
    times = [float(t) for t in re.findall(r"\bn:\s*\d+\s+pts:.*?\bpts_time:([\d.eE+-]+)", result.stderr)]
    files = sorted(directory.glob("frame-*.png"))
    if not times or len(times) != len(files) or len(times) > max_samples:
        raise LayoutError("FFmpeg sample count/PTS mismatch or sample limit reached; trim the video and retry")
    if any(t < 0 or t >= duration for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise LayoutError("FFmpeg returned invalid sample timestamps; remux the video and retry")
    return list(zip(times, files))
