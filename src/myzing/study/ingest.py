"""Media ingest: URL or local file -> media staged in the breakdown folder
plus an honest `VideoMeta`.

Measurement-critical policy: every downstream timestamp assumes a constant
frame rate, so sources that are VFR (common on TikTok/IG) or in codecs the
measurement stack can't decode reliably are normalized to CFR H.264 once,
here, and the normalized file is what gets measured. The re-encode is
recorded as a warning — we say what we did to the evidence.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from myzing.schemas import VideoMeta

from . import proc, workspace
from .proc import MediaError

# Prefer H.264 mp4 from yt-dlp: it is the one container/codec combo that
# every stage (OpenCV on Windows included) decodes with reliable timestamps.
YTDLP_FORMAT = "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"

_SAFE_VCODECS = {"h264"}
_VFR_TOLERANCE = 0.02  # relative avg-vs-declared fps disagreement


@dataclass
class IngestResult:
    meta: VideoMeta
    media_path: Path              # absolute path to the file measurements run on
    breakdown_dir: Path
    warnings: list[str] = field(default_factory=list)


def detect_platform(source: str) -> str:
    if not workspace.is_url(source):
        return "file"
    host = urlparse(source).netloc.lower()
    if "tiktok" in host:
        return "tiktok"
    if "instagram" in host or "instagr.am" in host:
        return "instagram"
    if "youtube" in host or "youtu.be" in host:
        return "youtube"
    return "url"


def ingest(source: str, root: Path | None = None) -> IngestResult:
    warnings: list[str] = []
    slug = workspace.slug_for_source(source)
    dest = workspace.breakdown_dir(slug, root)

    if workspace.is_url(source):
        media = _fetch(source, dest, warnings)
        info = _read_info_json(dest)
    else:
        media = _stage_local(source, dest)
        info = {}

    probed = probe(media)
    vstream = _video_stream(probed, media)

    need, why = _needs_normalize(vstream)
    if need:
        warnings.append(why)
        target_fps = _fps(vstream.get("avg_frame_rate", "0/0")) or 30.0
        media = _normalize(media, target_fps, warnings)
        probed = probe(media)
        vstream = _video_stream(probed, media)

    if _first_stream(probed, "audio") is None:
        warnings.append(
            "no audio stream: transcription and audio measurements will be skipped"
        )

    duration = _duration(probed, vstream)
    meta = VideoMeta(
        source_url=source if workspace.is_url(source) else str(Path(source).resolve()),
        platform=detect_platform(source),
        author=str(info.get("uploader") or info.get("channel") or ""),
        title=str(info.get("title") or ("" if workspace.is_url(source) else Path(source).stem)),
        duration=round(duration, 3),
        width=int(vstream.get("width", 0) or 0),
        height=int(vstream.get("height", 0) or 0),
        fps=round(_fps(vstream.get("avg_frame_rate", "0/0")), 3),
        # Relative to the breakdown folder so the folder survives being moved.
        media_path=media.name,
    )
    return IngestResult(meta=meta, media_path=media, breakdown_dir=dest, warnings=warnings)


# -- fetch / stage ----------------------------------------------------------

def _fetch(url: str, dest: Path, warnings: list[str]) -> Path:
    existing = _find_media(dest)
    if existing is not None:
        warnings.append(f"reusing already-downloaded media: {existing.name}")
        return existing
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", YTDLP_FORMAT,
        "--merge-output-format", "mp4",
        "--write-info-json",
        "-o", "media.%(ext)s",
        "-P", str(dest),
        url,
    ]
    res = proc.run(cmd, timeout=600)
    if res.returncode != 0:
        raise MediaError(
            f"yt-dlp could not fetch {url} (exit {res.returncode}):\n"
            f"{proc.tail(res.stderr)}"
        )
    media = _find_media(dest)
    if media is None:
        raise MediaError(
            f"yt-dlp exited 0 but no media file landed in {dest} — "
            "cannot measure a video we do not have"
        )
    return media


def _stage_local(path_str: str, dest: Path) -> Path:
    src = Path(path_str)
    if not src.is_file():
        raise MediaError(f"no such file: {src}")
    target = dest / ("media" + src.suffix.lower())
    if not (target.exists() and target.stat().st_size == src.stat().st_size):
        shutil.copy2(src, target)
    return target


def _find_media(dest: Path) -> Path | None:
    for p in sorted(dest.glob("media*")):
        if p.suffix.lower() not in (".json", ".md") and p.is_file():
            return p
    return None


def _read_info_json(dest: Path) -> dict:
    path = dest / "media.info.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# -- probe / normalize ------------------------------------------------------

def probe(path: Path) -> dict:
    res = proc.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)]
    )
    if res.returncode != 0:
        raise MediaError(f"ffprobe failed on {path.name}:\n{proc.tail(res.stderr)}")
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise MediaError(f"ffprobe produced unparseable output for {path.name}") from e


def _first_stream(probed: dict, kind: str) -> dict | None:
    for stream in probed.get("streams", []):
        if stream.get("codec_type") == kind:
            return stream
    return None


def _video_stream(probed: dict, media: Path) -> dict:
    vstream = _first_stream(probed, "video")
    if vstream is None:
        raise MediaError(f"{media.name} has no video stream — nothing to study")
    return vstream


def _needs_normalize(vstream: dict) -> tuple[bool, str]:
    codec = str(vstream.get("codec_name", ""))
    if codec not in _SAFE_VCODECS:
        return True, (
            f"source codec '{codec}' is not reliable for frame-accurate "
            "measurement here; re-encoding to H.264"
        )
    avg = _fps(vstream.get("avg_frame_rate", "0/0"))
    declared = _fps(vstream.get("r_frame_rate", "0/0"))
    if avg > 0 and declared > 0 and abs(declared - avg) / avg > _VFR_TOLERANCE:
        return True, (
            f"variable frame rate detected (average {avg:.2f} fps vs declared "
            f"{declared:.2f}); normalizing to constant frame rate so timestamps "
            "stay trustworthy"
        )
    return False, ""


def _normalize(media: Path, fps: float, warnings: list[str]) -> Path:
    out = media.with_name("media_cfr.mp4")
    if out.exists():
        warnings.append("reusing previously normalized media_cfr.mp4")
        return out
    cmd = [
        "ffmpeg", "-y", "-i", str(media),
        "-fps_mode", "cfr", "-r", f"{fps:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ]
    res = proc.run(cmd, timeout=900)
    if res.returncode != 0:
        raise MediaError(
            f"ffmpeg failed to normalize {media.name} (exit {res.returncode}):\n"
            f"{proc.tail(res.stderr)}"
        )
    if not out.is_file():
        raise MediaError("ffmpeg exited 0 but produced no normalized file")
    return out


# -- parsing helpers --------------------------------------------------------

def _fps(rate: str) -> float:
    """Parse ffprobe rational rates like '30000/1001'; 0.0 when unknown."""
    num, _, den = str(rate).partition("/")
    try:
        n = float(num)
        d = float(den) if den else 1.0
    except ValueError:
        return 0.0
    return n / d if d else 0.0


def _duration(probed: dict, vstream: dict) -> float:
    for holder in (probed.get("format", {}), vstream):
        raw = holder.get("duration")
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
    return 0.0
