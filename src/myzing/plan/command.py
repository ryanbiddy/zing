"""zing plan: write three style-constrained drafts, then record which one you chose."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from myzing.project.choices import choose_draft
from myzing.project.models import ProjectError


def run(argv: list[str]) -> int:
    if argv and argv[0] == "screen":
        from myzing.screen.command import run as screen
        return screen(argv[1:])
    parser = argparse.ArgumentParser(
        prog="zing plan",
        description="Plan three edits from local studies and a saved brief, then record your choice.",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("screen", help="plan a screen demo with smooth zoom/pan; zing plan screen --help")
    drafts = sub.add_parser("drafts", help="write Composition v2 plans, v1 derivatives where supported (music plans: picture and "
                                       "dialogue plus a music sidecar), and comparison.json")
    drafts.add_argument("project", type=Path)
    drafts.add_argument("--recipe", type=Path, required=True)
    drafts.add_argument("--seed", type=int, default=0)
    drafts.add_argument("--no-repair-asr", dest="repair_asr", action="store_false")
    drafts.add_argument("--out", type=Path, required=True,
                        help="output folder; <project>/drafts lets 'zing plan choose' find the plans")
    choose = sub.add_parser("choose", help="save an observed draft choice; never publish")
    choose.add_argument("project", type=Path)
    choose.add_argument("--draft", choices=["A", "B", "C"], required=True)
    choose.add_argument("--note")
    choose.add_argument("--share-choice", action="store_true", help="send/retry a Uoink reference citation with a stable event ID")
    choose.add_argument("--draft-file", type=Path,
                        help="explicit draft artifact (default: <project>/drafts/<A|B|C>.json or plan-<A|B|C>.json)")
    choose.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "drafts":
        from myzing.director.api import plan_drafts

        try:
            result = plan_drafts(args.project, args.recipe, args.out, seed=args.seed, repair_asr=args.repair_asr)
        except (ValueError, OSError) as exc:
            print(f"zing plan: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0 if result["status"] == "ready" else 1
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
