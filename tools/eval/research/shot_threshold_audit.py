"""Regenerate the numbers in SHOT-THRESHOLD-AUDIT-2026-07-19.md.

The audit that measured our MIN_SCENE_LEN_S against SHOT's published
annotations was originally run ad hoc. This script IS the regeneration
command, so every figure in that note is reproducible by anyone
without trusting the note (the same rule P-C2's freeze.py follows).

Usage:
    python shot_threshold_audit.py [path/to/kuaishou_v2.txt]

With no argument it fetches the annotation file from the AutoShot repo
(MIT, github.com/wentaozhu/AutoShot). Network is used ONLY for that
fetch; pass a local path to run fully offline.

Deliberately dependency-free (stdlib only) and read-only: it downloads
nothing else, writes nothing, and imports no myzing code.
"""

from __future__ import annotations

import re
import statistics
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/wentaozhu/AutoShot/main/kuaishou_v2.txt"
)
# Our tuning under audit, and the PySceneDetect default-equivalent it
# replaced. Frames are what the annotations state; the file gives no fps,
# so seconds are derived under a stated 30fps assumption (typical for the
# platform). The RATIO between the two thresholds is fps-independent.
ASSUMED_FPS = 30.0
OUR_MIN_SCENE_LEN_S = 0.3
DEFAULT_EQUIV_S = 0.6


def load(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as resp:
        return resp.read().decode("utf-8")


def parse(text: str) -> tuple[dict, dict]:
    """-> (videos, anomalies). Anomalies are COUNTED, never smoothed:
    the file has repeated names, headers without a frame count (whose
    final shot cannot be bounded, so they are excluded), and at least
    one malformed annotation line."""
    videos: dict[str, dict] = {}
    anomalies = {
        "header_lines": 0,
        "headers_without_frame_count": 0,
        "duplicate_names": 0,
        "malformed_cut_lines": 0,
    }
    seen: set[str] = set()
    cur: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ".mp4" in line:
            anomalies["header_lines"] += 1
            parts = line.split()
            name = parts[0]
            if name in seen:
                anomalies["duplicate_names"] += 1
            seen.add(name)
            if len(parts) < 2:
                anomalies["headers_without_frame_count"] += 1
                cur = None
                continue
            cur = name
            videos.setdefault(name, {"frames": int(parts[1]), "cuts": []})
        elif "," in line and cur:
            nums = [n for n in re.split(r"[,\s]+", line) if n.isdigit()]
            if len(nums) < 2 or line.count(",") > 1:
                anomalies["malformed_cut_lines"] += 1
                if len(nums) < 2:
                    continue
            videos[cur]["cuts"].append((int(nums[0]), int(nums[1])))
    return videos, anomalies


def shot_lengths_in_frames(videos: dict) -> list[float]:
    """Shot = span between consecutive transition MIDPOINTS, bounded by
    video start and the stated frame count."""
    out: list[float] = []
    for v in videos.values():
        bounds = (
            [0.0]
            + [(a + b) / 2 for a, b in v["cuts"]]
            + [float(v["frames"])]
        )
        out += [y - x for x, y in zip(bounds, bounds[1:]) if y > x]
    return sorted(out)


def main() -> int:
    text = load(sys.argv[1] if len(sys.argv) > 1 else None)
    videos, anomalies = parse(text)
    gaps = shot_lengths_in_frames(videos)
    n = len(gaps)
    if not n:
        print("no shots derived — is this the right annotation file?")
        return 1

    print("source anomalies (counted, not smoothed):")
    for k, v in anomalies.items():
        print(f"  {k}: {v}")
    print(f"  usable videos (deduped, with frame count): {len(videos)}")
    print(f"\nshots derived: {n}")
    print(f"median: {statistics.median(gaps):.0f} frames")
    print(f"mean:   {statistics.mean(gaps):.1f} frames "
          f"({statistics.mean(gaps) / ASSUMED_FPS:.2f}s @{ASSUMED_FPS:g}fps)")
    for seconds, label in (
        (OUR_MIN_SCENE_LEN_S, "OUR min_scene_len"),
        (DEFAULT_EQUIV_S, "default-equivalent"),
    ):
        frames = seconds * ASSUMED_FPS
        below = sum(1 for g in gaps if g < frames)
        print(f"real shots shorter than {frames:.0f}f "
              f"({seconds:g}s, {label}): {below} ({100 * below / n:.2f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
