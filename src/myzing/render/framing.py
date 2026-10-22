"""Compile bounded crop motion using crop's per-frame x/y expressions (FFmpeg 6+)."""

import json
import subprocess
from fractions import Fraction

from .validation import EDLValidationError


def display_dimensions(stream):
    width, height = int(stream["width"]), int(stream["height"])
    sar = stream.get("sample_aspect_ratio", "1:1")
    ratio = Fraction(sar.replace(":", "/")) if sar not in (None, "N/A", "0:1") else Fraction(1)
    if ratio <= 0:
        raise ValueError("source pixel aspect must be positive")
    width = max(1, round(width * ratio))
    rotation = float(next((s["rotation"] for s in stream.get("side_data_list", []) if "rotation" in s),
                          stream.get("tags", {}).get("rotate", 0))) % 360
    if rotation not in (0, 90, 180, 270):
        raise ValueError("framing requires a right-angle source rotation; normalize the source first")
    return (height, width) if rotation in (90, 270) else (width, height)


def probe_dimensions(path, ffprobe="ffprobe"):
    result = subprocess.run([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
                             "-select_streams", "v:0", "-show_streams", "-of", "json", str(path)],
                            capture_output=True, text=True, timeout=30, check=False)
    try:
        if result.returncode:
            raise ValueError(result.stderr[-1000:])
        return display_dimensions(json.loads(result.stdout)["streams"][0])
    except (ValueError, KeyError, IndexError) as exc:
        raise EDLValidationError(f"Cannot validate framing dimensions for {path}: {exc}") from exc


def _number(value):
    return format(float(value), ".12g")


def _expression(framing, axis, rate):
    """Piecewise smoothstep selected by a balanced binary search on time.

    A flat sum with one term per segment exceeds FFmpeg 8's expression limit
    at about 93 moving segments. Nested if() halving keeps the depth at
    ceil(log2(pieces)) (8 for the 256-key contract) and evaluates one
    segment per frame, using Framing.center_at's selection rule: a segment
    owns times up to and including its end key.
    """
    half = framing.width / 2 if axis == "center_x" else framing.height / 2
    keys = framing.keyframes
    if not keys:
        return _number(getattr(framing, axis) - half)
    # n is the CFR clip-local frame index, independent of source/container
    # PTS and the rounded absolute timeline endpoint allocation.
    clock = f"n/({rate})"
    pieces = []  # (exclusive start time, expression); the first start is unused.
    for a, b in zip(keys, keys[1:]):
        start, delta = getattr(a, axis) - half, getattr(b, axis) - getattr(a, axis)
        if abs(delta) < 1e-10:
            pieces.append((a.time, _number(start)))
            continue
        u = f"clip(({clock}-{_number(a.time)})/{_number(b.time - a.time)},0,1)"
        pieces.append((a.time, f"{_number(start)}+({_number(delta)})*(({u})*({u})*(3-2*({u})))"))
    pieces.append((keys[-1].time, _number(getattr(keys[-1], axis) - half)))
    # Adjacent holds at the same value form one piece (a static axis is a constant).
    pieces = [piece for i, piece in enumerate(pieces) if i == 0 or piece[1] != pieces[i - 1][1]]

    def select(lo, hi):
        if lo == hi:
            return pieces[lo][1]
        mid = (lo + hi + 1) // 2
        return f"if(lte({clock},{_number(pieces[mid][0])}),{select(lo, mid - 1)},{select(mid, hi)})"

    return select(0, len(pieces) - 1)


def framing_filter(framing, width, height, rate, label="framing"):
    normal = "" if framing is None else f"scale={framing.source_width}:{framing.source_height},setsar=1,"
    if framing is None or framing.mode == "fit":
        return (normal + f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p")
    if framing.mode == "blurfill":
        # Blur at quarter delivery resolution, then enlarge. Both branches
        # share the same decoded, graded CFR frames; there is no temporal lag.
        bw, bh = max(2, width // 4), max(2, height // 4)
        return (normal + f"split=2[{label}_fg][{label}_bg];\n"
                f"[{label}_bg]scale={bw}:{bh}:force_original_aspect_ratio=increase,"
                f"crop={bw}:{bh}:exact=1,gblur=sigma=12:steps=2,"
                # The lut constants are 8-bit limited-range levels. Convert
                # 10/12-bit, RGB and full-range input first, or neutral chroma
                # (512 at 10 bits) is pulled toward green.
                "format=yuv420p,"
                "lutyuv=y='16+(val-16)*0.55':u='128+(val-128)*0.65':v='128+(val-128)*0.65',"
                f"scale={width}:{height},setsar=1[{label}_back];\n"
                f"[{label}_fg]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"setsar=1[{label}_front];\n"
                # The main/background CFR stream owns EOF. Restore the exact
                # clock after framesync: without it FFmpeg 6's downstream
                # concat/fps drops the last frame despite overlay emitting it.
                f"[{label}_back][{label}_front]overlay=x=(W-w)/2:y=(H-h)/2:eof_action=repeat:shortest=0:repeatlast=1:format=yuv420,"
                f"setsar=1,format=yuv420p,settb=expr=1/({rate}),setpts=N")
    x, y = (_expression(framing, axis, rate) for axis in ("center_x", "center_y"))
    # exact=1 avoids chroma-subsampling rounding of crop size/origin. The final
    # output is even yuv420p. Explicit display dimensions handle SAR/autorotate.
    return (f"scale={framing.source_width}:{framing.source_height},setsar=1,"
            f"crop=w={framing.width}:h={framing.height}:x='{x}':y='{y}':exact=1,"
            f"scale={width}:{height},setsar=1,format=yuv420p")
