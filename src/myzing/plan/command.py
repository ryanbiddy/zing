"""zing plan choose: record the user's choice of a local draft."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from myzing.project.choices import choose_draft
from myzing.project.models import ProjectError


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing plan")
    sub = parser.add_subparsers(dest="action", required=True)
    choose = sub.add_parser("choose", help="save an observed draft choice; never publish")
    choose.add_argument("project", type=Path)
    choose.add_argument("--draft", choices=["A", "B", "C"], required=True)
    choose.add_argument("--note")
    choose.add_argument("--share-choice", action="store_true", help="send/retry a Uoink reference citation with a stable event ID")
    choose.add_argument("--draft-file", type=Path, help="explicit draft artifact (default: <project>/drafts/<A|B|C>.json)")
    choose.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = choose_draft(args.project, args.draft, note=args.note,
                              share_choice=args.share_choice, draft_file=args.draft_file)
    except (ProjectError, OSError) as exc:
        print(f"zing plan: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        receipt = result["receipt"]
        print(f"Draft {receipt['draft']} chosen: {result['receipt_path']}")
        print(f"  event: {receipt['event_id']} ({receipt['delivery']['state']})")
        print("  " + result["hint"])
    return 0
