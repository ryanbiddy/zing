"""Lazy CLI surface for the four playbook stages and model discovery."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing playbook")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list channel Shorts metadata or import pilot candidates")
    inputs = listing.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--channels", nargs="+", help="handles or a UTF-8 file of handles")
    inputs.add_argument("--from-candidates", type=Path)
    listing.add_argument("--out", type=Path, required=True)
    listing.add_argument("--skip-newest", type=int, default=10)
    listing.add_argument("--k", type=int, default=5)
    measure = commands.add_parser("measure", help="measure local media; fetching requires --download")
    measure.add_argument("directory", type=Path)
    measure.add_argument("--media-dir", type=Path)
    measure.add_argument("--download", action="store_true")
    measure.add_argument("--force", action="store_true")
    notes = commands.add_parser("notes", help="request cached blind Gemini notes")
    notes.add_argument("directory", type=Path)
    notes.add_argument("--model")
    notes.add_argument("--limit", type=int)
    notes.add_argument("--budget-hours", type=float, default=7.5)
    notes.add_argument("--dry-run", action="store_true", help="print the first request with key redacted; send nothing")
    commands.add_parser("models", help="list model IDs available to GEMINI_API_KEY")
    distill = commands.add_parser("distill", help="compare the two sets and write publishable patterns")
    distill.add_argument("directory", type=Path)
    distill.add_argument("--version", required=True)
    for name, kind, default in (("min-n", int, 20), ("min-delta", float, .33),
                                ("min-rate-diff", float, .15), ("min-consistency", float, .6),
                                ("min-channel-n", int, 3), ("min-channels", int, 8), ("bootstrap-samples", int, 2000), ("seed", int, 42)):
        distill.add_argument("--" + name, type=kind, default=default)
    distill.add_argument("--multiple-testing", choices=("bonferroni", "none"), default="bonferroni")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            from .sources import build
            channels = args.channels or []
            if len(channels) == 1 and Path(channels[0]).is_file():
                channels = [word for line in Path(channels[0]).read_text(encoding="utf-8-sig").splitlines()
                            for word in line.split("#", 1)[0].split()]
            result = build(args.out, channels, from_candidates=args.from_candidates, skip_newest=args.skip_newest, k=args.k)
            print(json.dumps({"entries": len(result["entries"]), "channels": result["channels"]}, indent=2))
            return int(any(s.get("status") == "failed" for s in result["channels"].values()))
        if args.command == "measure":
            from .measure import measure
            result = measure(args.directory, media_dir=args.media_dir, download=args.download, force=args.force)
        elif args.command == "notes":
            from .notes import notes
            result = notes(args.directory, model=args.model, limit=args.limit, budget_hours=args.budget_hours, dry_run=args.dry_run)
        elif args.command == "models":
            from .notes import models
            result = models()
        else:
            from .distill import Thresholds, distill
            thresholds = Thresholds(**{name: getattr(args, name) for name in Thresholds.__dataclass_fields__})
            data = distill(args.directory, version=args.version, thresholds=thresholds)
            result = {"kept": len(data["patterns"]), "no_separation": len(data["no_separation"])}
        print(json.dumps(result, indent=2))
        return int(bool(result.get("failed"))) if isinstance(result, dict) else 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # NotesError text is deliberately credential-free; raw HTTP failures stay inside its client.
        print(f"zing playbook: {exc}")
        return 2
