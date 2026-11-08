"""Lazy CLI surface for playbook comparisons and public metadata scouting."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def run(argv: list[str]) -> int:
    from .distill import Thresholds
    parser = argparse.ArgumentParser(prog="zing playbook")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list channel Shorts metadata or import pilot candidates")
    inputs = listing.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--channels", nargs="+", help="handles or a UTF-8 file of handles")
    inputs.add_argument("--from-candidates", type=Path)
    listing.add_argument("--out", type=Path, required=True)
    listing.add_argument("--skip-newest", type=int, default=10)
    listing.add_argument("--k", type=int, default=5)
    listing.add_argument("--scope", metavar="TEXT", help="cohort label, up to 120 characters (default YouTube Shorts)")
    measure = commands.add_parser("measure", help="measure local media; fetching requires --download")
    measure.add_argument("directory", type=Path)
    measure.add_argument("--media-dir", type=Path)
    measure.add_argument("--download", action="store_true")
    measure.add_argument("--force", action="store_true")
    measure.add_argument("--retry-failed", action="store_true", help="retry only saved failures")
    measure.add_argument("--max-blocks", type=int, default=3, metavar="N",
                         help="pause downloads after N consecutive YouTube blocks (default 3, minimum 1)")
    measure.add_argument("--gap", type=float, default=3, metavar="SECONDS",
                         help="wait between download attempts (default 3, minimum 0)")
    notes = commands.add_parser("notes", help="request cached blind Gemini notes")
    notes.add_argument("directory", type=Path)
    notes.add_argument("--model")
    notes.add_argument("--limit", type=int)
    notes.add_argument("--budget-hours", type=float, default=7.5)
    notes.add_argument("--dry-run", action="store_true", help="print the first request with key redacted; send nothing")
    commands.add_parser("models", help="list model IDs available to GEMINI_API_KEY")
    watch = commands.add_parser("watch", help="append one snapshot of public channel feeds")
    watch.add_argument("--channels", nargs="+", required=True, help="handles, channel IDs or a UTF-8 file")
    watch.add_argument("--out", type=Path, required=True)
    velocity = commands.add_parser("velocity", help="compare saved views at fixed ages after publication")
    velocity.add_argument("directory", type=Path)
    niches = commands.add_parser("niches", help="compare niches from public Shorts metadata")
    niches.add_argument("input", type=Path)
    niches.add_argument("--out", type=Path, required=True)
    niches.add_argument("--source", choices=("feeds", "ytdlp"), default="feeds")
    niches.add_argument("--min-shorts", type=int, default=15)
    niches.add_argument("--fresh-days", type=int, default=3, help="leave out dated Shorts younger than this")
    niches.add_argument("--skip-newest", type=int, default=10, help="undated listings: leave out the newest few")
    prior = commands.add_parser("prior", help="write title guidance from a saved niche scorecard")
    prior.add_argument("directory", type=Path)
    prior.add_argument("--niche", required=True)
    prior.add_argument("--out", type=Path, required=True)
    distill = commands.add_parser("distill", help="compare the two sets and write publishable patterns")
    distill.add_argument("directory", type=Path)
    distill.add_argument("--version", required=True)
    distill.add_argument("--scope", metavar="TEXT", help="override the library's cohort label, up to 120 characters")
    for name, kind, default in (("min-n", int, 20), ("min-delta", float, .33),
                                ("min-rate-diff", float, .15), ("min-consistency", float, .6),
                                ("min-channel-n", int, 3), ("min-channels", int, Thresholds().min_channels), ("bootstrap-samples", int, 2000), ("seed", int, 42)):
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
            result = build(args.out, channels, from_candidates=args.from_candidates, skip_newest=args.skip_newest,
                           k=args.k, scope=args.scope)
            print(json.dumps({"entries": len(result["entries"]), "channels": result["channels"]}, indent=2))
            return int(any(s.get("status") == "failed" for s in result["channels"].values()))
        if args.command == "measure":
            from .measure import DOWNLOAD_HINTS, measure
            result = measure(args.directory, media_dir=args.media_dir, download=args.download, force=args.force,
                             retry_failed=args.retry_failed, max_blocks=args.max_blocks, gap=args.gap)
        elif args.command == "notes":
            from .notes import notes
            result = notes(args.directory, model=args.model, limit=args.limit, budget_hours=args.budget_hours, dry_run=args.dry_run)
        elif args.command == "models":
            from .notes import models
            result = models()
        elif args.command == "watch":
            from .watch import watch
            channels = args.channels
            if len(channels) == 1 and Path(channels[0]).is_file():
                channels = [word for line in Path(channels[0]).read_text(encoding="utf-8-sig").splitlines()
                            for word in line.split("#", 1)[0].split()]
            result = watch(args.out, channels)
        elif args.command == "velocity":
            from .watch import velocity
            result = velocity(args.directory)
        elif args.command == "niches":
            from .common import read_json
            from .niches import build
            data = build(args.out, read_json(args.input), source=args.source, min_shorts=args.min_shorts,
                         fresh_days=args.fresh_days, skip_newest=args.skip_newest)
            result = {key: value for key, value in data.items() if key != "local"}
        elif args.command == "prior":
            from .niches import prior
            result = prior(args.directory, args.niche, args.out)
        else:
            from .distill import distill
            thresholds = Thresholds(**{name: getattr(args, name) for name in Thresholds.__dataclass_fields__})
            data = distill(args.directory, version=args.version, thresholds=thresholds, scope=args.scope)
            result = {"kept": len(data["patterns"]), "no_separation": len(data["no_separation"])}
        print(json.dumps(result, indent=2))
        if args.command == "measure":
            for category, hint in DOWNLOAD_HINTS.items():
                count = sum(row.get("reason", "").partition(": ")[2] == category
                            for row in result["entries"] if row["status"] == "failed")
                if count:
                    print(f"{count} failed: {category}. {hint}")
            if result["paused"]:
                print(f"Downloads paused after {result['stopped']}. {result['paused']} left unmeasured.")
        return int(bool(result.get("failed"))) if isinstance(result, dict) else 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # NotesError text is deliberately credential-free; raw HTTP failures stay inside its client.
        print(f"zing playbook: {exc}")
        return 2
