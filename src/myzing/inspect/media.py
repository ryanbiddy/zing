"""Bounded FFmpeg decoding. Local protocols only; failures never become silence."""

from __future__ import annotations

import array
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from . import InspectionError

PROCESS_TIMEOUT = 20
TOTAL_TIMEOUT = 50
SAMPLE_RATE = 8000


class Decoder:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + TOTAL_TIMEOUT

    def run(self, command: list[str], operation: str) -> bytes:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise InspectionError("Inspection exceeded 50 seconds; request fewer frames or a shorter range.")
        try:
            result = subprocess.run(command, capture_output=True, check=False,
                                    timeout=min(PROCESS_TIMEOUT, remaining))
        except FileNotFoundError as exc:
            raise InspectionError(f"{command[0]} is missing; install FFmpeg and run zing doctor.") from exc
        except subprocess.TimeoutExpired as exc:
            raise InspectionError(f"{command[0]} timed out during {operation}; request fewer frames or a shorter range.") from exc
        except OSError as exc:
            raise InspectionError(f"Could not run {command[0]} for {operation}: {exc}") from exc
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()[-2000:]
            raise InspectionError(f"{command[0]} failed during {operation}: {detail or 'no diagnostic'}")
        return result.stdout

    def probe(self, video: Path) -> dict:
        raw = self.run([
            "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-show_entries", "format=duration:stream=codec_type,duration,avg_frame_rate",
            "-of", "json", str(video),
        ], "video probe")
        try:
            data = json.loads(raw)
            streams = data["streams"]
            stream = next(s for s in streams if s.get("codec_type") == "video")
            duration = float(stream.get("duration", data.get("format", {}).get("duration")))
            n, d = stream["avg_frame_rate"].split("/")
            fps = float(n) / float(d)
            if not math.isfinite(duration) or duration <= 0 or not math.isfinite(fps) or fps <= 0:
                raise ValueError("non-positive duration or frame rate")
        except (ValueError, KeyError, TypeError, StopIteration, ZeroDivisionError) as exc:
            raise InspectionError("ffprobe returned no usable video duration/frame rate; provide a decodable video.") from exc
        return {"duration": duration, "fps": fps,
                "has_audio": any(s.get("codec_type") == "audio" for s in streams)}

    @staticmethod
    def input_args(video: Path, start: float) -> list[str]:
        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-protocol_whitelist", "file,pipe", "-ss", f"{start:.9f}", "-i", str(video)]

    def frame(self, video: Path, timestamp: float, width: int, height: int) -> bytes:
        data = self.run(self.input_args(video, timestamp) + [
            "-map", "0:v:0", "-an", "-sn", "-dn", "-frames:v", "1",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
        ], f"frame extraction at {timestamp:.6f}s")
        if len(data) != width * height * 3:
            raise InspectionError(f"ffmpeg returned no complete frame at {timestamp:.6f}s; move the range away from the video end.")
        return data

    def envelope(self, video: Path, start: float, end: float, bins: int) -> list[float]:
        duration = end - start
        data = self.run(self.input_args(video, start) + [
            "-map", "0:a:0", "-vn", "-sn", "-dn", "-t", f"{duration:.9f}",
            "-af", "aresample=8000:async=1:first_pts=0,apad",
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
            "-f", "s16le", "pipe:1",
        ], f"waveform extraction at {start:.3f}-{end:.3f}s")
        if not data or len(data) % 2:
            raise InspectionError("ffmpeg returned incomplete audio; check the input audio stream.")
        pcm = array.array("h")
        pcm.frombytes(data)
        if sys.byteorder != "little":
            pcm.byteswap()
        # Partition the WHOLE requested range. Floor-sized windows plus truncation
        # would shift the right-hand waveform away from its timestamps.
        samples = max(1, round(duration * SAMPLE_RATE))
        values = []
        for i in range(bins):
            a, b = i * samples // bins, (i + 1) * samples // bins
            chunk = pcm[a:min(b, len(pcm))]
            values.append(math.sqrt(sum(v * v for v in chunk) / max(1, b - a)) / 32768)
        return values
