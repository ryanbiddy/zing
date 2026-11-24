"""Make thumbnails and covers from a local video frame."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from myzing.factory.tools import FactoryError

from . import cover_directory, data_path
from .contract import CAPS, OPTIONAL, STYLES, load, messages
from .geometry import SIZES
from .render import render
from .starter import new


def styles():
    uses = {
        "clipping": "A named source, the person in the news and a transcript passage.",
        "plate": "One short spoken phrase split across two plates.",
        "number": "A figure the speaker gives and the words that explain it.",
        "quote": "A verbatim line, a highlighted phrase and the speaker credit.",
    }
    result = {}
    for name, block in STYLES.items():
        fields = block.__dataclass_fields__
        result[name] = {"use": uses[name], "required": [key for key in fields if key not in OPTIONAL],
                        "optional": [key for key in fields if key in OPTIONAL], "character_limits": CAPS[name]}
    return {"styles": result, "sizes": SIZES}


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing cover", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("styles", help="list styles, fields and canvas sizes")
    draft = sub.add_parser("new", help="copy or extract a frame and write cover.json")
    check = sub.add_parser("check", help="check the frame, text and attribution")
    capture = sub.add_parser("render", help="write covers, a contact sheet and a receipt")
    prompt = sub.add_parser("prompt", help="print the cover writing prompt for your agent")
    for cmd in (listing, draft, check, capture, prompt):
        cmd.add_argument("--json", action="store_true")
    for cmd in (draft, check, capture):
        cmd.add_argument("directory")
    source = draft.add_mutually_exclusive_group(required=True)
    source.add_argument("--frame", type=Path)
    source.add_argument("--video", type=Path)
    draft.add_argument("--at", type=float)
    draft.add_argument("--style", choices=STYLES)
    capture.add_argument("--style", default="all")
    capture.add_argument("--size", default="all")
    capture.add_argument("--scale", default=1, type=int, choices=(1, 2))
    capture.add_argument("--format", default="jpg", choices=("jpg", "png"))
    try:
        # Programmatic CLI callers can pass values the OS argv cannot contain.
        if any(not isinstance(arg, str) for arg in argv):
            raise ValueError("Supply a nonempty cover directory and pass arguments as text.")
        args = parser.parse_args(argv)
        if hasattr(args, "directory"):
            args.directory = cover_directory(args.directory)
        if args.command == "prompt":
            value = data_path("prompts", "cover.md").read_text(encoding="utf-8")
            if not args.json:
                print(value, end="")
                return 0
            result = {"prompt": value}
        elif args.command == "styles":
            result = styles()
        elif args.command == "new":
            result = new(args.directory, frame=args.frame, video=args.video, at=args.at, style=args.style)
        elif args.command == "render":
            result = render(args.directory, style=args.style, size=args.size, scale=args.scale, format=args.format)
        else:
            _, result = load(args.directory)
            if not args.json:
                for warning in result["warnings"]:
                    print(f"Warning: {warning['path']}: {warning['message']}", file=sys.stderr)
                print("Cover is valid." if result["valid"] else messages(result))
                return int(not result["valid"])
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return int(result.get("valid") is False)
    except (ValueError, FactoryError, OSError, subprocess.SubprocessError) as exc:
        if "--json" in argv:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"zing cover: {exc}", file=sys.stderr)
        return 1
