"""``zing meme`` CLI; JSON uses the same errors-as-data shape as MCP."""

from __future__ import annotations

import argparse
import json
import sys

from myzing import storage
from . import MemeError
from .ideas import generate_ideas
from .render import render_meme
from .video import render_meme_video
from .templates import get_template, list_templates
from .validate import check_texts


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing meme", description="Offline meme ideas, checks, and local image/video rendering.")
    # Both 'meme --json templates' and 'meme templates --json' are accepted.
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--workspace", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    templates = sub.add_parser("templates", help="browse the offline classic catalog")
    templates.add_argument("--search", default="")
    ideas = sub.add_parser("ideas", help="generate seeded formula starting points")
    ideas.add_argument("--topic", required=True)
    ideas.add_argument("--template", default="")
    ideas.add_argument("--n", type=int, default=6)
    ideas.add_argument("--tone", default="dry")
    ideas.add_argument("--audience", default="")
    check = sub.add_parser("check", help="validate on-image text budgets and filler")
    check.add_argument("--text", action="append", required=True)
    check.add_argument("--template", default="")
    check.add_argument("--box-count", type=int, help="number of custom label regions (1-6)")
    render = sub.add_parser("render", help="render from a photo or explicitly requested template")
    motion = sub.add_parser("render-video", help="render local video/GIF or a still to MP4, optionally GIF")
    for command in (render, motion):
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--image", default="")
        source.add_argument("--template", default="")
        if command is motion:
            source.add_argument("--video", default="", help="local video or GIF, at most 30s after trimming")
        command.add_argument("--text", action="append", required=True)
        command.add_argument("--layout", choices=("classic", "caption", "labels"), default="")
        command.add_argument("--aspect", default="1:1")
        command.add_argument("--out", default="")
        command.add_argument("--fit", choices=(("auto", "fill", "blur", "cover", "contain") if command is render
                                               else ("cover", "contain", "blur")), default="",
                             help=("photo framing (default auto: crop only when detected faces or a "
                                   "measured subject fit with margin, else blur-fill with a warning); "
                                   "templates default to contain"
                                   if command is render else "video framing (default cover; blur keeps the "
                                   "whole frame over a blurred copy)"))
        command.add_argument("--font", default="", help="anton, sans, system font name, or font file path")
        command.add_argument("--regions", help="JSON list of normalized [x,y,width,height] boxes for labels")
        command.add_argument("--plate", action="store_true")
        command.add_argument("--shadow", action="store_true")
        command.add_argument("--rotation", type=float, default=0)
        command.add_argument("--overwrite", action="store_true", help="replace existing outputs")
    render.add_argument("--offline", action="store_true", help="use cached templates only")
    motion.add_argument("--start", type=float, default=0, help="source trim start in seconds")
    motion.add_argument("--end", type=float, help="source trim end in seconds")
    motion.add_argument("--max-duration", type=float, default=30, help="reject longer selections (at most 30s)")
    motion.add_argument("--duration", type=float, default=5, help="still motion duration in seconds")
    motion.add_argument("--zoom", type=float, default=0, help="still zoom amount, 0..0.25 (e.g. 0.1)")
    motion.add_argument("--fps", type=int, default=30)
    motion.add_argument("--width", type=int, help="even output width, 64..1920; aspect sets height")
    motion.add_argument("--gif", action="store_true", help="also write a bounded GIF next to the MP4")
    motion.add_argument("--gif-fps", type=int, default=10, help="1..10")
    motion.add_argument("--gif-width", type=int, default=640, help="16..640")
    motion.add_argument("--gif-duration", type=float, default=8, help="at most 8 seconds")
    motion.add_argument("--at", type=float, action="append", help="one onset per text, in output seconds")
    motion.add_argument("--until", type=float, action="append", help="one inclusive end per text, in output seconds")
    for command in (templates, ideas, check, render, motion):
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        command.add_argument("--workspace", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    code = 0
    try:
        with storage.use_workspace(args.workspace or storage.workspace_root()):
            if args.command == "templates":
                result = {"ok": True, "templates": list_templates(args.search)}
            elif args.command == "ideas":
                result = {"ok": True, "ideas": generate_ideas(args.topic, args.template, args.n, args.tone, args.audience)}
            elif args.command == "check":
                count = get_template(args.template)["box_count"] if args.template else args.box_count
                result = {"ok": True, **check_texts(args.text, box_count=count)}
                code = 0 if result["valid"] else 1
            else:
                regions = json.loads(args.regions) if args.regions is not None else None
                if args.command == "render-video":
                    renderer = render_meme_video
                    options = {key: getattr(args, key) for key in (
                        "video", "start", "end", "max_duration", "duration", "zoom", "fps", "width",
                        "gif", "gif_fps", "gif_width", "gif_duration", "at", "until")}
                else:
                    renderer, options = render_meme, {"offline": args.offline}
                result = {"ok": True, **renderer(
                    args.text, image=args.image, template=args.template, layout=args.layout,
                    aspect=args.aspect, out=args.out, fit=args.fit, font=args.font,
                    regions=regions, plate=args.plate, shadow=args.shadow,
                    rotation=args.rotation, overwrite=args.overwrite, **options,
                )}
    except (MemeError, OSError, ValueError) as exc:
        result = {"ok": False, "error": str(exc)}
        code = 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not result["ok"]:
        print(f"zing meme: {result['error']}", file=sys.stderr)
    elif args.command == "templates":
        for template in result["templates"]:
            print(f"{template['id']:20} {template['name']} ({template['box_count']} boxes)")
    elif args.command == "ideas":
        for idea in result["ideas"]:
            print(f"{idea['title']}: {' / '.join(idea['texts'])}")
            for problem in idea["validation"]["problems"]:
                print(f"  check: {problem['message']}")
    elif args.command == "check":
        print(f"{'valid' if result['valid'] else 'invalid'}: {result['beats']} beats, {result['characters']} characters")
        for problem in result["problems"]:
            print(f"  {problem['code']}: {problem['message']}")
    else:
        print(f"{result['path']} ({result['width']}x{result['height']})")
        if result.get("gif"):
            g = result["gif"]
            print(f"{g['path']} ({g['width']}x{g['height']}, {g['duration']:g}s, {g['fps']} fps, {g['size_bytes']:,} bytes)")
        for warning in result["warnings"]:
            print(f"  {warning}")
    return code
