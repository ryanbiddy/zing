"""``zing inspect timeline``: local PNG inspection with JSON metadata."""

from __future__ import annotations

import argparse
import json
import sys

from myzing import storage
from .timeline import inspect_timeline


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing inspect")
    sub = parser.add_subparsers(dest="command", required=True)
    timeline = sub.add_parser("timeline", help="see frames, waveform and transcript on a shared time axis")
    timeline.add_argument("video", help="local video; with --edl supply its rendered output")
    timeline.add_argument("--start", type=float)
    timeline.add_argument("--end", type=float)
    timeline.add_argument("--around", type=float, help="center a row on this output time")
    timeline.add_argument("--edl", help="v1 EDL; defaults to one centered row per cut")
    timeline.add_argument("--breakdown", help="stored breakdown slug supplying timed transcript")
    timeline.add_argument("--out", required=True, help="destination PNG")
    timeline.add_argument("--frames", type=int, default=5, help="frames per row, 1-15; centered rows need odd >=3")
    timeline.add_argument("--width", type=int, default=1600, help="PNG width, 960-2400 pixels")
    timeline.add_argument("--radius", type=float, default=1, help="seconds each side of a centered time (default 1)")
    timeline.add_argument("--overwrite", action="store_true")
    timeline.add_argument("--workspace")
    timeline.add_argument("--json", action="store_true", help="print path and timing/pixel metadata, never image bytes")
    args = parser.parse_args(argv)
    kwargs = vars(args).copy()
    for key in ("command", "workspace", "json"):
        kwargs.pop(key)
    try:
        with storage.use_workspace(args.workspace or storage.workspace_root()):
            result = {"ok": True, **inspect_timeline(**kwargs).to_dict()}
    except (ValueError, OSError) as exc:
        result = {"ok": False, "error": str(exc)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        print(f"{result['path']} ({result['width']}x{result['height']})")
        for warning in result["warnings"]:
            print(f"  {warning}")
    else:
        print(f"zing inspect: {result['error']}", file=sys.stderr)
    return 0 if result["ok"] else 1
