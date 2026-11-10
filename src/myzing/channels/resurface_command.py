"""The resurface command."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from myzing.factory.command import _shapes

from . import resurface


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing resurface")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help in (("build", "index local archive transcripts"), ("status", "show archive counts and bad rows"),
                       ("watch", "review new trends against an archive"), ("replay", "review a supplied headline")):
        command = commands.add_parser(name, help=help)
        command.add_argument("archive", type=Path)
        if name == "watch":
            command.add_argument("--feeds", type=Path, help="publisher RSS URLs, one per line")
            command.add_argument("--geo", default="US", help="two-letter country code")
            command.add_argument("--judge", choices=("host", "claude"), default="host")
            command.add_argument("--n", type=int, default=5, help="maximum picks per event")
            command.add_argument("--json", action="store_true", help="print JSON")
        if name == "replay":
            command.add_argument("--entity", required=True)
            command.add_argument("--headline", required=True)
            command.add_argument("--url", default="")
            command.add_argument("--date", help="headline date as YYYY-MM-DD")
    make = commands.add_parser("make", help="start a factory project from a reviewed pick")
    make.add_argument("brief", type=Path)
    make.add_argument("--pick", type=int, required=True, help="pick number, starting at 1")
    make.add_argument("--media", help="local media file")
    make.add_argument("--out", type=Path, help="factory project folder")
    make.add_argument("--shapes", type=_shapes, help="comma-separated delivery shapes")
    args = parser.parse_args(argv)
    try:
        values = vars(args).copy()
        name = values.pop("command")
        as_json = values.pop("json", False)
        result = getattr(resurface, name)(**values)
        if as_json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif name in ("build", "status"):
            print(f'{result["episodes"]} episodes · {result["cues"]} cues · {result["complete"]} complete')
            for key in ("indexed", "unchanged", "removed"):
                if key in result:
                    print(f'{result[key]} {key}')
            print(f'{len(result["errors"])} bad rows')
            for error in result["errors"]:
                print(error)
            print(f'{len(result["incomplete"])} incomplete episodes')
            for ident in result["incomplete"]:
                print(ident)
        elif name == "make":
            print(result["project"])
            print(result["hint"])
        else:
            for path in result["briefs"]:
                print(str(Path(path).with_suffix(".html")))
            for pending in result["pending"]:
                path = Path(pending["prompt_path"])
                print(path)
                print(f'zing factory answer "{path.parent.parent}" {pending["task"]} answer.json')
                print("Then run the same resurface command again.")
            for error in result["errors"]:
                print(f'{error["signal"]}. {error["error"]}', file=sys.stderr)
            if not result["briefs"] and not result["errors"]:
                print("No new events.")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
