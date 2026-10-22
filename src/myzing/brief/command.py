"""zing brief new|show, using plain stdin/stdout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from myzing.project.api import load_project
from myzing.project.models import ProjectError
from .api import brief_path, brief_result, load_brief, save_brief
from .models import Brief, BriefError
from .questions import brief_questions, interview


def _print_result(result: dict, *, show_answers: bool):
    print(f"Brief: {result['brief_path']}")
    if show_answers:
        print(json.dumps(result["brief"], indent=2, ensure_ascii=False))
    rec = result["recommendation"]
    print(f"\nI'd start here: {rec['summary']}")
    print("Basis:")
    for fact in rec["basis"]:
        print(f"  - {fact}")
    if rec["missing"]:
        print("Still needed:")
        for gap in rec["missing"]:
            print(f"  - {gap}")


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing brief", description="Find the edit, then save the answers for reruns.")
    sub = parser.add_subparsers(dest="action", required=True)
    new = sub.add_parser("new", help="ask six topics, or reuse the saved brief",
                         epilog="Answer keys and defaults: " + json.dumps(Brief().to_dict())
                         + '. Optional framing: auto (default), fit, fill, reframe, or blurfill. Auto checks subject coverage, crop loss and framing_max_upscale (default 2.5). Optional aspects: ["16:9", "1:1", "9:16"] for multiple deliveries.'
                         + ". JSON examples: " + json.dumps(brief_questions()["answer_examples"]))
    new.add_argument("project", type=Path)
    source = new.add_mutually_exclusive_group()
    source.add_argument("--brief", type=Path, help="import a versioned brief file without prompting")
    source.add_argument("--answers", help="JSON object of answers; omitted keys use disclosed defaults")
    source.add_argument("--restart", action="store_true", help="ask again and replace the saved brief after completion")
    new.add_argument("--json", action="store_true", help="print machine-readable output (requires saved brief, --brief, or --answers)")
    show = sub.add_parser("show", help="read the saved brief and current inventory recommendation")
    show.add_argument("project", type=Path)
    show.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        load_project(args.project)
        path = brief_path(args.project)
        if args.action == "show":
            brief = load_brief(path)
        elif args.brief:
            brief = save_brief(args.project, load_brief(args.brief))
        elif args.answers is not None:
            try:
                answers = json.loads(args.answers)
            except ValueError as exc:
                raise BriefError(f"--answers: invalid JSON ({exc}). Supply an object, such as '{{}}'.") from exc
            brief = save_brief(args.project, Brief.from_answers(answers))
        elif path.exists() and not args.restart:
            brief = load_brief(path)
        else:
            if args.json:
                raise BriefError("No saved brief to reuse. Supply --answers '{}' or --brief <file> with --json, or omit --json for the interview.")
            brief = save_brief(args.project, interview(args.project, sys.stdin, sys.stdout), replace=args.restart)
        result = brief_result(args.project, brief)
    except KeyboardInterrupt:
        print("\nzing brief: interview cancelled; no completed answers were saved.", file=sys.stderr)
        return 130
    except (BriefError, ProjectError, OSError, ValueError) as exc:
        print(f"zing brief: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_result(result, show_answers=args.action == "show")
    return 0
