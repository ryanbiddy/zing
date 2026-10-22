"""`zing fonts list|fetch|match`: explicit assets, offline comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import URLError

from . import library


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing fonts", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "fetch", "match"):
        command = sub.add_parser(name)
        command.add_argument("--workspace", type=Path)
        command.add_argument("--json", action="store_true")
        if name == "fetch":
            command.add_argument("font_ids", nargs="*")
            command.add_argument("--all", action="store_true", help="fetch the complete pinned library")
        if name == "match":
            command.add_argument("breakdown_slug")
    args = parser.parse_args(argv)
    if args.command == "fetch" and not args.all and not args.font_ids:
        parser.error("fetch requires font IDs or --all; run zing fonts list")
    try:
        if args.command == "match":
            from myzing.study.font_match import match_study
            path, result = match_study(args.breakdown_slug, args.workspace)
            if args.json:
                print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            else:
                print(f"font candidates -> {path}")
                for track in result.tracks:
                    candidates = track["candidates"]
                    best = f"{candidates[0]['family']} ({candidates[0]['score']:.3f})" if candidates else "no usable comparison"
                    print(f"  {track['track_id']}: {track['status']} — {best}")
                for warning in result.warnings:
                    print(f"  note: {warning}")
            return 0
        if args.command == "fetch":
            ids = [r["id"] for r in library.manifest()["fonts"]] if args.all else args.font_ids
            rows = library.fetch(ids, args.workspace)
        else:
            rows = library.inventory(args.workspace)
        if args.json:
            print(json.dumps({"version": 1, "fonts": rows}, indent=2, ensure_ascii=False))
        else:
            for row in rows:
                print(f"{row['id']:<18} {row['family']:<20} {row['license']:<12} {row['status']}")
        return 0
    except (OSError, ValueError, RuntimeError, URLError) as exc:
        print(f"zing fonts: {exc}")
        return 1
