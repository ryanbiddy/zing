"""Local-only FFmpeg I/O shared by measurement, preview, and apply."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import ColorError


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_media(command, *, data=None, cwd=None, timeout=120):
    try:
        result = subprocess.run(command, input=data, capture_output=True, cwd=cwd, timeout=timeout)
    except FileNotFoundError as exc:
        raise ColorError(f"{command[0]} is missing. Install FFmpeg and run zing doctor.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ColorError(f"{command[0]} timed out after {timeout}s; use a shorter local clip.") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace")[-2000:]
        raise ColorError(f"{command[0]} failed: {detail}")
    return result.stdout


def local_video(path: Path | str) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ColorError(f"Local video does not exist: {path}. Supply a local file; no downloads are performed.")
    return path


def probe(path: Path | str):
    path = local_video(path)
    data = json.loads(run_media([
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "v:0",
        "-show_streams", "-show_format", "-of", "json", str(path),
    ]))
    if not data.get("streams"):
        raise ColorError(f"No video stream in {path}")
    stream = data["streams"][0]
    try:
        duration = float(stream.get("duration") or data.get("format", {}).get("duration", 0))
        width, height = int(stream["width"]), int(stream["height"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ColorError("Video metadata is invalid; remux the input with FFmpeg first.") from exc
    if not math.isfinite(duration) or duration <= 0 or min(width, height) <= 0:
        raise ColorError("Video needs finite positive duration and dimensions; remux it first.")
    rotation = next((float(s["rotation"]) for s in stream.get("side_data_list", [])
                     if "rotation" in s), 0.0)
    if not math.isfinite(rotation) or rotation % 90:
        raise ColorError("Unsupported display rotation; normalize the video's orientation before color matching.")
    if abs(rotation) % 180 == 90:
        width, height = height, width
    metadata = {key: str(stream.get(key, "unknown")) for key in (
        "color_space", "color_transfer", "color_primaries", "color_range", "pix_fmt",
    )}
    all_tags = {**data.get("format", {}).get("tags", {}), **stream.get("tags", {})}
    tags = {key: value for key, value in all_tags.items()
            if any(term in key.lower() for term in ("color", "gamma", "transfer", "profile"))}
    metadata["profile_tags"] = json.dumps(tags, sort_keys=True)
    metadata["rotation_degrees"] = str(rotation)
    return duration, width, height, metadata


def check_color_space(metadata):
    transfer = metadata.get("color_transfer", "unknown").lower()
    primaries = metadata.get("color_primaries", "unknown").lower()
    matrix = metadata.get("color_space", "unknown").lower()
    tags = metadata.get("profile_tags", "").lower()
    unsupported = transfer not in ("bt709", "iec61966-2-1", "unknown", "unspecified")
    unsupported |= primaries not in ("bt709", "unknown", "unspecified")
    unsupported |= matrix not in ("bt709", "bt470bg", "smpte170m", "gbr", "unknown", "unspecified")
    unsupported |= any(v in tags for v in ("s-log", "slog", "c-log", "clog", "v-log", "vlog", "logc", "log3", "log2", "hlg", "pq", "hdr"))
    if unsupported:
        raise ColorError(
            "Unsupported LOG/HDR or non-Rec.709 input color metadata. "
            "Convert with a declared camera/display transform to SDR Rec.709 before color match/apply. "
            f"Transfer={transfer}, primaries={primaries}, matrix={matrix}."
        )
    warnings = []
    if any(metadata.get(key, "unknown") in ("unknown", "unspecified")
           for key in ("color_transfer", "color_primaries", "color_space")):
        warnings.append("Color metadata is incomplete; SDR Rec.709/sRGB is assumed. Untagged LOG cannot be ruled out.")
    if transfer == "bt709":
        warnings.append("BT.709 display RGB is measured with the sRGB transfer approximation; no camera-profile recovery.")
    if matrix in ("bt470bg", "smpte170m"):
        warnings.append(f"Source {matrix} YUV matrix is decoded as BT.601 before the Rec.709 RGB grade; "
                        "untagged primaries/transfer retain the disclosed SDR assumption.")
    return warnings


def input_matrix(metadata):
    """Respect a declared SDR YUV matrix; retain the untagged BT.709 policy."""
    return "bt601" if metadata.get("color_space", "").lower() in ("bt470bg", "smpte170m") else "bt709"


def frame(path, timestamp, width=160, height=90, *, lut_dir=None):
    from . import require_numpy
    np = require_numpy()
    # Default FFmpeg autorotation; probe reports display-oriented dimensions.
    metadata = probe(path)[3]
    check_color_space(metadata)
    filters = f"scale={width}:{height}:flags=area:in_color_matrix={input_matrix(metadata)},format=rgb24"
    if lut_dir is not None:
        filters += ",lut3d=file=look.cube:interp=trilinear,format=rgb24"
    data = run_media([
        "ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
        "-ss", f"{timestamp:.9f}", "-i", str(Path(path).resolve()),
        "-map", "0:v:0", "-an", "-sn", "-frames:v", "1", "-vf", filters,
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ], cwd=lut_dir)
    if len(data) != width * height * 3:
        raise ColorError(f"No complete frame at requested timestamp {timestamp:.6f}s")
    return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3).astype(float) / 255


def workspace_tmp():
    root = Path.cwd() / "zing-workspace" / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    return root


def apply_video(lut: Path | str, source: Path | str, output: Path | str) -> dict:
    from .cube import read_cube, write_cube
    cube = read_cube(lut)
    source = local_video(source)
    output = Path(output).expanduser().resolve()
    if output.suffix.lower() not in (".mp4", ".mkv", ".mov"):
        raise ColorError("Choose an .mp4, .mkv, or .mov output for the H.264 grade.")
    if output == source or output.exists():
        raise ColorError(f"Output already exists or equals the input: {output}. Choose a new output path.")
    _, _, _, metadata = probe(source)
    warnings = check_color_space(metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    # A controlled basename avoids filtergraph quoting of Windows drives,
    # apostrophes, commas, brackets and user-supplied LUT paths.
    with tempfile.TemporaryDirectory(prefix="color-apply-", dir=workspace_tmp()) as work:
        write_cube(cube, Path(work) / "look.cube")
        staged = Path(work) / ("graded" + (output.suffix or ".mp4"))
        run_media([
            "ffmpeg", "-v", "error", "-nostdin", "-n", "-protocol_whitelist", "file,pipe",
            "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
            "-vf", f"scale=in_color_matrix={input_matrix(metadata)},format=rgb24,"
            "lut3d=file=look.cube:interp=trilinear,"
            "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,"
            "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709",
            "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv444p",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-c:a", "copy", str(staged),
        ], cwd=work, timeout=3600)
        # Confirm a decodable output before publishing; source is never rewritten.
        run_media(["ffmpeg", "-v", "error", "-nostdin", "-i", str(staged), "-f", "null", "-"], timeout=3600)
        dest = output.open("xb")
        try:
            with dest, staged.open("rb") as src:
                shutil.copyfileobj(src, dest)
        except BaseException:
            output.unlink(missing_ok=True)  # only the file this call just created
            raise
    return {"output_path": str(output), "sha256": sha256(output), "lut_sha256": sha256(lut), "warnings": warnings}
