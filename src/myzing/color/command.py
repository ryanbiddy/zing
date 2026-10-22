"""CLI for local procedural color matching and LUT application."""

import argparse
import json
import sys

from . import ColorError, require_numpy


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def run(argv):
    parser = _Parser(prog="zing color", description="Match an SDR look approximation from local videos.")
    sub = parser.add_subparsers(dest="command", required=True)
    match = sub.add_parser("match", help="measure, rank procedural looks, save a LUT and recipe")
    match.add_argument("--reference", required=True, help="local video or saved breakdown slug")
    match.add_argument("--clip", required=True, help="local user clip")
    match.add_argument("--out", required=True, help="new output folder for look.cube and recipe.json")
    match.add_argument("--samples", type=int, default=12, help="sample budget per video, 1..32 (default 12)")
    match.add_argument("--json", action="store_true")
    apply = sub.add_parser("apply", help="apply a validated SDR cube through FFmpeg lut3d")
    apply.add_argument("--lut", required=True)
    apply.add_argument("--in", dest="source", required=True)
    apply.add_argument("--out", required=True)
    apply.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except ValueError as exc:
        print(f"zing color: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        require_numpy()
        if args.command == "match":
            from .api import match_video
            recipe = match_video(args.reference, args.clip, args.out, samples=args.samples)
            payload = recipe.to_dict()
            if not args.json:
                t = recipe.match.chosen.transform
                print(f"Matched approximation: {t.look}, strength {t.strength:.4f}, "
                      f"confidence {recipe.match.confidence:.2f} (heuristic).")
                print(f"LUT: {recipe.cube_path}\nRecipe: {args.out}/recipe.json\nPreview: {recipe.preview_path}")
        else:
            from .media import apply_video
            payload = apply_video(args.lut, args.source, args.out)
            if not args.json:
                print(payload["output_path"])
        if args.json:
            print(json.dumps(payload, indent=2, allow_nan=False))
        else:
            for warning in payload["warnings"]:
                print(f"zing color: warning: {warning}", file=sys.stderr)
        return 0
    except (ColorError, ValueError, TypeError, KeyError, OSError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"zing color: {exc}", file=sys.stderr)
        return 1
