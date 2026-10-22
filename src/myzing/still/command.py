"""``zing still`` and ``zing still pick``; no model calls."""

from __future__ import annotations

import argparse
import json
import sys

from myzing import storage
from .api import create_stills, pick_still


def run(argv: list[str]) -> int:
    # Accept the shared workspace option before or after `pick`, like meme.
    workspace_parser = argparse.ArgumentParser(add_help=False)
    workspace_parser.add_argument("--workspace", default=None)
    workspace_args, argv = workspace_parser.parse_known_args(argv)
    picking = bool(argv and argv[0] == "pick")
    parser = argparse.ArgumentParser(prog="zing still pick" if picking else "zing still",
                                     parents=[workspace_parser],
                                     description="Turn local photos and a topic into still meme concepts, offline.")
    parser.add_argument("--json", action="store_true")
    if picking:
        parser.add_argument("out_folder")
        parser.add_argument("--id", required=True)
        parser.add_argument("--video", action="store_true", help="also export a five-second MP4")
        parser.add_argument("--gif", action="store_true", help="also export MP4 and a bounded GIF")
    else:
        parser.add_argument("--photos", required=True)
        parser.add_argument("--topic", required=True)
        parser.add_argument("--out", required=True, help="new or empty output folder")
        parser.add_argument("--n", type=int, default=6, help="total concepts, 1-8 (default 6)")
        parser.add_argument("--aspect", choices=("1:1", "4:5", "9:16", "16:9"), default="1:1")
        parser.add_argument("--layout", choices=("auto", "classic", "caption", "labels"), default="auto")
        parser.add_argument("--fit", choices=("auto", "fill", "blur", "contain", "cover"), default="auto",
                            help="photo framing: auto (default) fills the frame when a crop keeps every "
                                 "prominent face, else blur-fills; contain letterboxes")
        parser.add_argument("--lines", help="local JSON file of AI/user-written ideas; its length overrides --n")
    args = parser.parse_args(argv[1:] if picking else argv, namespace=workspace_args)
    try:
        with storage.use_workspace(args.workspace or storage.workspace_root()):
            if picking:
                result = {"ok": True, **pick_still(args.out_folder, args.id, video=args.video, gif=args.gif)}
            else:
                result = {"ok": True, **create_stills(args.photos, args.topic, args.out, n=args.n,
                                                     aspect=args.aspect, layout=args.layout, lines=args.lines,
                                                     fit=args.fit)}
    except (OSError, ValueError) as exc:
        result = {"ok": False, "error": str(exc)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not result["ok"]:
        print(f"zing still: {result['error']}", file=sys.stderr)
    elif picking:
        print(f"{result['path']} ({result['width']}x{result['height']})")
        for name in ("video", "gif"):
            if name in result:
                print(result[name]["path"])
        print(result["alt_text"])
    else:
        print(f"{result['count']} concepts: {result['contact_sheet']}\nIndex: {result['index_path']}")
        for idea in result["summary"]:
            print(f"{idea['id']} [{idea['layout']}, {idea['fit']}]: {' / '.join(idea['texts'])}")
        print(f"\nWriter prompt saved to {result['prompt_path']}\n\n{result['prompt']}")
    if not args.json and result["ok"]:
        for warning in result.get("warnings", []):
            print(f"Warning: {warning}")
    return 0 if result["ok"] else 1
