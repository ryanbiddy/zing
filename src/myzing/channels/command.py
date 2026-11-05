"""The local channel CLI."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def run(argv: list[str]) -> int:
    from . import kit, queue, registry
    parser = argparse.ArgumentParser(prog="zing channels")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="create a channel")
    new.add_argument("slug")
    new.add_argument("--name", required=True)
    new.add_argument("--niche", required=True)
    for key in ("network-name", "network-line", "network-url", "pack", "mode"):
        new.add_argument("--" + key)
    commands.add_parser("list", help="list local channels")
    for name, help in (("show", "show settings and queue counts"), ("check", "check channel settings"),
                       ("queue", "queue clips that pass the gate"), ("kit", "make local post kits")):
        command = commands.add_parser(name, help=help)
        command.add_argument("slug")
        if name == "kit":
            command.add_argument("--out", type=Path, help="folder for kits and their index")
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
                      "next_slot": min(upcoming, key=lambda s: datetime.fromisoformat(s).timestamp()) if upcoming else queue.next_slot(channel, rows),
                      "paused": registry.paused(args.slug)}
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
        elif args.command == "queue":
            result = queue.build(args.slug)
        elif args.command == "kit":
            result = kit.kit(args.slug, args.out)
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
