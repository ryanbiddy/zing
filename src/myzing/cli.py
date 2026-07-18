"""Zing CLI entry point.

Commands land here as lanes deliver them:
  zing doctor            -> environment check (ffmpeg, yt-dlp, faster-whisper)
  zing study <url|file>  -> Lane A: produce a Breakdown (JSON + markdown)
  zing serve-mcp         -> Lane B: MCP server over the same functions
  zing render <edl.json> -> Lane C: execute an EDL to an output video
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zing", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor", help="check local dependencies")
    study = sub.add_parser("study", help="measure a video into a Breakdown")
    study.add_argument("source", help="URL or local media file")
    sub.add_parser("serve-mcp", help="run the Zing MCP server (stdio)")
    render = sub.add_parser("render", help="render an EDL JSON to video")
    render.add_argument("edl", help="path to EDL JSON")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    print(f"zing {args.command}: not implemented yet (see handoff/SPRINT-1-D1.md)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
