"""Shared local reference selection. Half-open ranges use decoded frame times."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

LIMIT_SECONDS = 60


def seconds(value):
    if isinstance(value, bool):
        raise ValueError("Reference time must be seconds or mm:ss.")
    try:
        parts = str(value).strip().split(":")
        if len(parts) == 2:
            minutes, tail = int(parts[0]), float(parts[1])
            if minutes < 0 or not 0 <= tail < 60:
                raise ValueError
            result = minutes * 60 + tail
        elif len(parts) == 1:
            result = float(parts[0])
        else:
            raise ValueError
        if not math.isfinite(result) or result < 0:
            raise ValueError
        return result
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Reference time must be nonnegative seconds or mm:ss (for example 30 or 0:30).") from None


def parse(ref_start=None, ref_end=None, reference_range=None):
    if reference_range is not None:
        if ref_start is not None or ref_end is not None:
            raise ValueError("Use --reference-range or --ref-start/--ref-end, not both.")
        if reference_range == "all":
            return None, None
        parts = str(reference_range).split("-")
        if len(parts) != 2:
            raise ValueError("Reference range must look like 0:30-1:20, or all.")
        ref_start, ref_end = parts
    start = seconds(ref_start) if ref_start is not None else None
    end = seconds(ref_end) if ref_end is not None else None
    if end is not None and end <= (start or 0):
        raise ValueError("Reference range must satisfy 0 <= start < end.")
    return start, end


def add_options(parser):
    parser.add_argument("--ref-start", help="reference start in seconds or mm:ss (inclusive)")
    parser.add_argument("--ref-end", help="reference end in seconds or mm:ss (exclusive)")
    parser.add_argument("--reference-range", help="reference interval, e.g. 0:30-1:20")


def options(args):
    return {k: getattr(args, k) for k in ("ref_start", "ref_end", "reference_range")
            if getattr(args, k, None) is not None}


def slug(source, ref_start=None, ref_end=None, reference_range=None, *, analysis_seconds=None, analysis_max_side=None):
    from myzing.storage import slug_for
    start, end = parse(ref_start, ref_end, reference_range)
    key = source if start is None and end is None else f"{source}#reference={start or 0:g}-{end}"
    if analysis_seconds is not None or analysis_max_side is not None:
        key += f"#analysis={analysis_seconds};max-side={analysis_max_side}"
    return slug_for(key)


def validate_duration(duration, ref_start=None, ref_end=None, reference_range=None, *, limit=LIMIT_SECONDS):
    start, end = parse(ref_start, ref_end, reference_range)
    start, end = start or 0., duration if end is None else end
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Reference duration is unknown; supply a readable video before study.")
    if start >= duration or end > duration + 1e-6:
        raise ValueError(f"Reference range is outside the {duration:g}s video.")
    if limit is not None and end - start > limit + 1e-6:
        raise ValueError(f"Reference is {end-start:g}s; the supported limit is {limit:g}s. "
                         "Choose a trim before study, e.g. --ref-start 0:30 --ref-end 1:20 "
                         "or --reference-range 0:30-1:20.")
    return start, end


@dataclass
class Selection:
    source: str
    source_sha256: str
    source_duration: float
    requested_start: float
    requested_end: float
    start_frame: int | None
    end_frame: int | None
    fps: str
    start: float
    end: float
    analysis_limited: bool = False
    max_side: int | None = None
    version: int = 1

    def to_dict(self):
        return {**asdict(self), "interval": "half-open; first frame at or after each boundary",
                "encoding": "only selected interval encoded; accurate input seek; H.264 CRF 18/AAC"}

    @classmethod
    def from_dict(cls, value):
        if value.get("version") != 1:
            raise ValueError("Unsupported reference selection version")
        return cls(**{k: v for k, v in value.items() if k in cls.__dataclass_fields__})


def _vfr_window(source, start, end, origin=0.):
    """Stream decoded timestamps for the selected interval, never the full clip.

    Input seeking starts at the preceding keyframe. Only scalar counts and the
    two boundary timestamps are retained, even on high-frame-rate footage.
    """
    import subprocess
    import tempfile
    import threading
    from myzing.study.proc import MediaError
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-read_intervals", f"{start+origin}%{end+origin+1}",
               "-show_entries", "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(source)]
    first, last, count = None, None, 0
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True,
                              encoding="utf-8", errors="replace") as process:
            timer = threading.Timer(120, process.kill)
            timer.start()
            try:
                for line in process.stdout:
                    try:
                        t = float(line.strip().split(",")[0]) - origin
                    except ValueError:
                        continue
                    if start-1e-7 <= t < end-1e-7:
                        first = t if first is None else first
                        last, count = t, count+1
                code = process.wait()
            finally:
                timer.cancel()
            if code:
                raise MediaError("Could not read reference frame timestamps; choose a readable reference.")
    if first is None:
        raise ValueError("Reference range contains no video frames; choose a longer range.")
    return first, last, count


def select_local(source, folder, ref_start=None, ref_end=None, reference_range=None, *,
                 limit=None, analysis_seconds=None, max_side=None):
    """Probe before decoding, then encode only the requested (bounded) interval.

    CFR boundaries are rounded up to frame timestamps. VFR input is selected by
    time and normalized only inside this interval, as recorded in the receipt.
    No stream-copy keyframe trim can silently include earlier reference frames.
    """
    from myzing.project.probe import probe_file
    from myzing.project.api import hash_file
    from myzing.study import proc
    source, folder = Path(source).resolve(), Path(folder)
    probe = probe_file(source)
    start, end = validate_duration(probe.duration, ref_start, ref_end, reference_range, limit=limit)
    requested_end = end
    if analysis_seconds is not None:
        end = min(end, start + analysis_seconds)
    parsed = parse(ref_start, ref_end, reference_range)
    resize = bool(max_side and max(probe.width or 0, probe.height or 0) > max_side)
    if parsed == (None, None) and end == probe.duration and not resize:
        return source, None
    if not probe.fps or not probe.width or not probe.height:
        raise ValueError("Reference trim requires a video stream with a known frame rate.")
    rate = Fraction(probe.fps.numerator, probe.fps.denominator)
    stream = next(s for s in probe.streams if s.get("codec_type") == "video")
    origin = float(stream.get("start_time") or 0)
    container_origin = float(probe.format.get("start_time") or 0)
    first = math.ceil(Fraction(str(start)) * rate - Fraction(1, 1000000))
    last = math.ceil(Fraction(str(end)) * rate - Fraction(1, 1000000))
    if last <= first:
        raise ValueError("Reference range contains no video frames; choose a longer range.")
    begin, finish = float(first / rate), float(last / rate)
    vfr = None
    if "vfr_suspected" in probe.flags:
        begin, final_source_frame, count = _vfr_window(source, start, end, origin)
        finish = end
        first, last = None, None
        vfr = {"first_frame_time": begin, "last_frame_time": final_source_frame,
               "selected_source_frames": count, "absolute_frame_indices": "unknown for VFR"}
    receipt = Selection(str(source), hash_file(source), probe.duration, start, requested_end,
                        first, last, str(rate), begin, finish, requested_end > end, max_side if resize else None)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "reference-selection.mp4"
    temporary = folder / "reference-selection.part.mp4"
    # Trim before resampling so fps never borrows a frame beyond the exclusive
    # source boundary. Output -t alone only limits the already-filtered output.
    filters = [f"trim=duration={finish-begin:.12f}", "setpts=PTS-STARTPTS"]
    if resize:
        filters.append(f"scale=w='min({max_side},iw)':h='min({max_side},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2")
    filters.append(f"fps={rate}")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-ss", f"{begin+origin-container_origin:.12f}", "-i", str(source), "-t", f"{finish-begin:.12f}",
               "-map", "0:v:0", "-map", "0:a:0?", "-vf", ",".join(filters),
               *(["-frames:v", str(last-first)] if first is not None else []),
               "-c:v", "libx264", "-threads", "1",
               "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", str(temporary)]
    try:
        result = proc.run(command, timeout=300)
        if result.returncode:
            raise proc.MediaError(f"Reference trim failed: {proc.tail(result.stderr)}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    data = receipt.to_dict()
    data["source_timing"] = "VFR suspected; selected time interval normalized to CFR" if "vfr_suspected" in probe.flags else "CFR frame grid from stream metadata"
    if vfr:
        data["source_frames"] = vfr
    data["selected_sha256"] = hash_file(target)
    return target, data
