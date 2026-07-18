"""CLI for ``zing render <edl.json>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from myzing.schemas import EDL

from .pipeline import RenderError, render_edl
from .validation import EDLValidationError


class _UsageError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="zing render")
    parser.add_argument("edl", type=Path, help="EDL JSON file")
    parser.add_argument("-o", "--output", type=Path, help="output MP4 path")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument(
        "--keep-work",
        type=Path,
        help="retain generated ASS and filtergraph in this directory",
    )
    return parser


def run(argv: list[str]) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError as exc:
        print(f"zing render: {exc}", file=sys.stderr)
        print(parser.format_usage().strip(), file=sys.stderr)
        return 2
    except SystemExit as exc:
        return int(exc.code or 0)

    edl_path = args.edl.expanduser().resolve()
    if not edl_path.is_file():
        print(f"zing render: EDL file does not exist: {edl_path}", file=sys.stderr)
        return 2
    try:
        payload = json.loads(edl_path.read_text(encoding="utf-8"))
        edl = EDL.from_dict(payload)
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"zing render: invalid EDL JSON: {exc}", file=sys.stderr)
        return 2

    output = (
        args.output.expanduser().resolve()
        if args.output
        else edl_path.with_suffix(".mp4")
    )
    try:
        result = render_edl(
            edl,
            output,
            base_dir=edl_path.parent,
            work_dir=args.keep_work,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
        )
    except (EDLValidationError, RenderError) as exc:
        print(f"zing render: {exc}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"zing render: warning: {warning}", file=sys.stderr)
    print(result.output_path)
    return 0
