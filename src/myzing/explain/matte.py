"""Baked-in matte detection: solid bars that are part of the encoded picture.

A letterboxed or pillarboxed export carries its bars inside every frame. The
detector decodes a few display-oriented frames at a small fixed size and finds
edge rows/columns whose pixels are flat (near one value). A bar is reported only
when every informative sample shows it; dark scenes cannot widen it. Blurred or
textured fills are not solid bars and stay unknown.
"""

from __future__ import annotations

import subprocess

FLAT_RANGE = 14          # max-min luma (0-255) for a row/column to count as matte
MIN_BAR_FRACTION = .02   # thinner edges are compression noise, not a matte
ANALYSIS_LONG_SIDE = 256


def _analysis_size(width: int, height: int) -> tuple[int, int]:
    scale = ANALYSIS_LONG_SIDE / max(width, height)
    return max(16, round(width * scale / 2) * 2), max(16, round(height * scale / 2) * 2)


def _frame(media, t: float, w: int, h: int) -> bytes | None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
               "-ss", f"{t:.6f}", "-i", str(media), "-map", "0:v:0", "-an", "-sn", "-dn", "-frames:v", "1",
               # Explicit full-range gray so FFmpeg 6 and 8 agree on black.
               "-vf", f"scale={w}:{h}:flags=neighbor:out_range=full,format=gray",
               "-f", "rawvideo", "pipe:1"]
    try:
        result = subprocess.run(command, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 and len(result.stdout) == w * h else None


def _flat_run(lines) -> tuple[int, float | None]:
    count, total = 0, 0.0
    for line in lines:
        if max(line) - min(line) > FLAT_RANGE:
            break
        count += 1
        total += sum(line) / len(line)
    return count, (total / count if count else None)


def bars_in_frame(data: bytes, w: int, h: int) -> dict | None:
    rows = [data[y * w:(y + 1) * w] for y in range(h)]
    columns = [bytes(rows[y][x] for y in range(h)) for x in range(w)]
    top, top_level = _flat_run(rows)
    if top >= h * .9:
        return None  # a flat frame (fade, black slate) says nothing about bars
    bottom, bottom_level = _flat_run(reversed(rows))
    left, left_level = _flat_run(columns)
    right, right_level = _flat_run(reversed(columns))
    if left >= w * .9:
        return None
    return {"top": top / h, "bottom": bottom / h, "left": left / w, "right": right / w,
            "levels": {"top": top_level, "bottom": bottom_level, "left": left_level, "right": right_level}}


def detect_matte(media, duration: float, width: int, height: int, *, samples: int = 7) -> dict:
    """Return bar fractions, the active picture box and how much evidence exists."""
    w, h = _analysis_size(width, height)
    times = [duration * (i + .5) / samples for i in range(samples)] if duration > .2 else [0.0]
    frames = []
    for t in times:
        data = _frame(media, t, w, h)
        if data is not None:
            frames.append(bars_in_frame(data, w, h))
    informative = [f for f in frames if f is not None]
    result = {"version": 1, "samples_requested": len(times), "samples_decoded": len(frames),
              "samples_informative": len(informative), "analysis_size": [w, h],
              "basis": "solid edge rows/columns present in every informative sampled frame",
              "status": "unknown", "kind": None, "bars": None, "active_box": None, "active_size": None}
    if len(informative) < min(3, len(times)):
        result["reason"] = "Too few decodable, non-blank frames to judge baked-in bars."
        return result
    bars = {side: min(f[side] for f in informative) for side in ("top", "bottom", "left", "right")}
    bars = {side: (value if value >= MIN_BAR_FRACTION else 0.0) for side, value in bars.items()}
    vertical, horizontal = bars["top"] + bars["bottom"] > 0, bars["left"] + bars["right"] > 0
    kind = ("windowbox" if vertical and horizontal else "letterbox" if vertical
            else "pillarbox" if horizontal else "none")
    box = [bars["left"], bars["top"], 1 - bars["right"], 1 - bars["bottom"]]
    levels = [f["levels"][side] for f in informative for side, value in bars.items() if value]
    result.update(status="measured", kind=kind, bars=bars, active_box=box,
                  active_size=[round((box[2] - box[0]) * width), round((box[3] - box[1]) * height)],
                  bar_level=(sum(levels) / len(levels)) if kind != "none" and levels else None,
                  precision=1 / min(w, h))
    return result
