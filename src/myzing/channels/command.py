"""Channel settings, posting kits and results."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import webbrowser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def run(argv: list[str]) -> int:
    from . import brief, digest, kit, learn, outcomes, publish, queue, registry, scorecard, tick, watch, youtube
    parser = argparse.ArgumentParser(prog="zing channels")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="create a channel")
    new.add_argument("slug")
    new.add_argument("--name", required=True)
    new.add_argument("--niche", required=True)
    for key in ("network-name", "network-line", "network-url", "pack", "mode"):
        new.add_argument("--" + key)
    commands.add_parser("list", help="list local channels")
    daily = commands.add_parser("brief", help="make or refill the daily brief")
    daily.add_argument("slug")
    daily.add_argument("--date", help="brief date as YYYY-MM-DD in the channel timezone")
    daily.add_argument("--answer", nargs=2, metavar=("TASK", "FILE"), help="save a script answer and refill the brief")
    daily.add_argument("--open", action="store_true", help="open the brief page")
    daily.add_argument("--takes", action="store_true", help="show what recent recordings teach the scripts")
    score = commands.add_parser("scorecard", help="compare local results with the channel bar")
    score.add_argument("slug")
    score.add_argument("--days", type=int, default=30, help="number of local days ending today")
    score.add_argument("--open", action="store_true", help="open the scorecard page")
    score.add_argument("--json", action="store_true", help="print the scorecard as JSON")
    flag = commands.add_parser("flag", help="record a channel problem")
    flag.add_argument("slug")
    flag.add_argument("--kind", required=True, choices=scorecard.KINDS)
    flag.add_argument("--note", required=True, help="what happened in up to 500 characters")
    flag.add_argument("--clip", help="clip ID")
    for name, help in (("show", "show settings and queue counts"), ("check", "check channel settings"),
                       ("queue", "queue clips that pass the gate"), ("kit", "make local post kits"),
                       ("track", "measure public YouTube results"), ("metrics", "merge a YouTube Studio CSV"),
                       ("learn", "report what worked on this channel"),
                       ("connect", "connect the owner's YouTube account"), ("disconnect", "remove the local YouTube connection"),
                       ("upload", "upload ready kits to YouTube"), ("analytics", "read YouTube owner analytics"),
                       ("watch", "check sources once and start ready episodes")):
        command = commands.add_parser(name, help=help)
        command.add_argument("slug")
        if name == "kit":
            command.add_argument("--out", type=Path, help="folder for kits and their index")
        if name == "metrics":
            command.add_argument("--csv", type=Path, required=True, help="YouTube Studio table export")
        if name == "connect":
            command.add_argument("--client-secret", type=Path, required=True, help="OAuth client JSON for a Desktop app")
        if name == "upload":
            command.add_argument("--dry-run", action="store_true", help="show uploads without sending requests")
            command.add_argument("--limit", type=int, default=3, help="maximum uploads in this run")
    step = commands.add_parser("tick", help="advance channels once")
    step.add_argument("slugs", nargs="*")
    step.add_argument("--all", action="store_true", help="run all local channels")
    step.add_argument("--max-minutes", type=float, default=50, help="stop between steps after this many minutes")
    summary = commands.add_parser("digest", help="summarize the last 24 hours and waiting work")
    summary.add_argument("slug", nargs="?")
    summary.add_argument("--all", action="store_true", help="include all local channels")
    summary.add_argument("--out", type=Path, help="write Markdown to this file")
    source = commands.add_parser("source", help="add or replace a source and its grant")
    source.add_argument("slug")
    for key in ("id", "name", "kind", "url", "rights", "grant"):
        source.add_argument("--" + key, required=True)
    for key in ("expires", "note"):
        source.add_argument("--" + key, default="")
    for name in ("posted", "skip"):
        command = commands.add_parser(name, help="mark a queue row " + name)
        command.add_argument("slug")
        command.add_argument("id")
        if name == "posted":
            command.add_argument("--url", help="the URL of the posted clip")
    for name in ("pause", "resume"):
        command = commands.add_parser(name, help=name + " a channel or all channels")
        command.add_argument("slug", nargs="?")
        command.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            network = {k: getattr(args, "network_" + k) for k in ("name", "line", "url") if getattr(args, "network_" + k) is not None}
            factory = {k: getattr(args, k) for k in ("pack", "mode") if getattr(args, k) is not None}
            result = registry.create(args.name, args.niche, args.slug, network=network, factory=factory)
        elif args.command == "list":
            result = [registry.load(p.parent.name) for p in sorted(registry.home().glob("*/channel.json"))]
        elif args.command == "show":
            channel, rows = registry.load(args.slug), queue.read(args.slug)
            now = datetime.now(timezone.utc)
            upcoming = [r["slot"] for r in rows if r["status"] in ("queued", "kit") and datetime.fromisoformat(r["slot"]) >= now]
            result = {"settings": channel, "counts": dict(Counter(r["status"] for r in rows)),
                      "series": [{"id": s["id"], "kind": s["kind"], "per_day": s["per_day"], "watch": len(s.get("watch", []))}
                                 for s in channel["series"]],
                      "next_slot": min(upcoming, key=lambda s: datetime.fromisoformat(s).timestamp()) if upcoming else queue.next_slot(channel, rows),
                      "paused": registry.paused(args.slug), "youtube_notice": youtube.AUDIT}
        elif args.command == "check":
            problems = []
            try:
                registry.load(args.slug)
                queue.read(args.slug)
            except (ValueError, OSError) as exc:
                problems.append(str(exc))
            print(json.dumps({"slug": args.slug, "problems": problems}, indent=2, ensure_ascii=False))
            return int(bool(problems))
        elif args.command == "source":
            channel = registry.load(args.slug)
            src = {"id": args.id, "name": args.name, "kind": args.kind, "url": args.url,
                   "rights": {"status": args.rights, "grant": args.grant, "expires": args.expires, "note": args.note}}
            channel["sources"] = [s for s in channel["sources"] if s["id"] != args.id] + [src]
            result = registry.save(channel)
        elif args.command == "watch":
            result = watch.run(args.slug)
        elif args.command == "scorecard":
            result = scorecard.build(args.slug, days=args.days)
            path = scorecard.page(args.slug, result)
            if args.open:
                webbrowser.open(path.as_uri())
            if not args.json:
                for row in result["rows"]:
                    print(f"{row['label']} {scorecard._value(row['value'])} / {scorecard._value(row['target'])} "
                          f"{scorecard._status(row['met'])}")
                print(f"Ready: {scorecard._status(result['ready'])} ({result['met']} of {result['total']} met)")
                return 0
        elif args.command == "flag":
            result = scorecard.flag(args.slug, args.kind, args.note, clip=args.clip)
        elif args.command == "brief":
            if args.takes:
                lines = brief.voice(args.slug, brief.when(registry.load(args.slug), args.date))
                print("\n".join(lines) or "Fewer than 3 recorded takes in the last 30 days.")
                return 0
            if args.answer:
                result = brief.answer(args.slug, args.answer[0], Path(args.answer[1]), date=args.date)
            else:
                result = brief.make(args.slug, now=brief.when(registry.load(args.slug), args.date))
            root = registry.directory(args.slug) / "brief"
            print(str(root / result["date"] / "brief.html"))
            if args.open:
                webbrowser.open((root / "latest.html").as_uri())
            return 0
        elif args.command == "tick":
            if bool(args.slugs) == args.all:
                raise registry.ChannelError("choose channel slugs or --all")
            result = tick.run(None if args.all else args.slugs, max_minutes=args.max_minutes,
                              say=lambda m: print(m, file=sys.stderr, flush=True))
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return result["exit_code"]
        elif args.command == "digest":
            if args.slug and args.all:
                raise registry.ChannelError("choose a channel slug or --all")
            text = digest.build([args.slug] if args.slug else None)
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(text, encoding="utf-8")
                print(str(args.out))
            else:
                print(text, end="")
            return 0
        elif args.command == "queue":
            result = queue.build(args.slug)
        elif args.command == "kit":
            result = kit.kit(args.slug, args.out)
        elif args.command == "connect":
            result = youtube.connect(args.slug, args.client_secret, say=lambda m: print(m, flush=True))
        elif args.command == "disconnect":
            result = youtube.disconnect(args.slug)
        elif args.command == "upload":
            result = publish.upload(args.slug, dry_run=args.dry_run, limit=args.limit)
        elif args.command == "analytics":
            result = publish.analytics(args.slug)
        elif args.command == "track":
            result = outcomes.track(args.slug)
        elif args.command == "metrics":
            result = outcomes.metrics(args.slug, args.csv)
        elif args.command == "learn":
            result = learn.learn(args.slug)
        elif args.command in ("posted", "skip"):
            result = queue.mark(args.slug, args.id, "posted" if args.command == "posted" else "skipped", getattr(args, "url", None))
        else:
            if bool(args.slug) == args.all:
                raise registry.ChannelError("choose a channel slug or --all")
            if args.slug:
                registry.load(args.slug)
            root = registry.home() if args.all else registry.directory(args.slug)
            root.mkdir(parents=True, exist_ok=True)
            path = root / "PAUSE"
            if args.command == "pause":
                path.touch(exist_ok=True)
            else:
                path.unlink(missing_ok=True)
            result = {"channel": args.slug, "all": args.all, "paused": registry.paused(args.slug) if args.slug else path.exists()}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except subprocess.SubprocessError as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        print(f"zing channels: {detail[-500:]}", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"zing channels: {exc}", file=sys.stderr)
        return 2
