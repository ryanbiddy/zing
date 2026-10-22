"""``zing meme`` CLI; JSON uses the same errors-as-data shape as MCP."""

from __future__ import annotations

import argparse
import json
import sys

from myzing import storage
from . import MemeError
from .ideas import generate_ideas
from .render import render_meme
from .templates import get_template, list_templates
from .validate import check_texts


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing meme", description="Offline meme ideas, checks, and local image rendering.")
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
    source = render.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", default="")
    source.add_argument("--template", default="")
    render.add_argument("--text", action="append", required=True)
    render.add_argument("--layout", choices=("classic", "caption", "labels"), default="")
    render.add_argument("--aspect", default="1:1")
    render.add_argument("--out", default="")
    render.add_argument("--fit", choices=("cover", "contain"), default="")
    render.add_argument("--font", default="", help="anton, sans, system font name, or font file path")
    render.add_argument("--regions", help="JSON list of normalized [x,y,width,height] boxes for labels")
    render.add_argument("--plate", action="store_true")
    render.add_argument("--shadow", action="store_true")
    render.add_argument("--rotation", type=float, default=0)
    render.add_argument("--offline", action="store_true", help="use cached templates only")
    render.add_argument("--overwrite", action="store_true", help="replace an existing --out file")
    for command in (templates, ideas, check, render):
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
                result = {"ok": True, **render_meme(
                    args.text, image=args.image, template=args.template, layout=args.layout,
                    aspect=args.aspect, out=args.out, fit=args.fit, font=args.font,
                    regions=regions, plate=args.plate, shadow=args.shadow,
                    rotation=args.rotation, offline=args.offline,
                    overwrite=args.overwrite,
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
        for warning in result["warnings"]:
            print(f"  {warning}")
    return code
