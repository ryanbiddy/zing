"""Recent channel activity and work waiting for a person."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from myzing.factory import pipeline, render
from myzing.playbook.common import parse_time

from . import gate, queue, registry, tick, watch



def count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")

def _text(value) -> str:
    text = " ".join(str(value).split())
    return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", text)


def build(slugs: list[str] | None = None, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    def recent(value):
        try:
            return since <= parse_time(value) <= now
        except (ValueError, TypeError):
            return False

    lines = ["# Channel digest", "", f"Activity from {since.isoformat(timespec='seconds')} to {now.isoformat(timespec='seconds')}.",
             "Waiting work reflects the current files.", ""]
    for slug in tick.channels(slugs):
        lines.extend([f"## {_text(slug)}", ""])
        try:
            channel = registry.load(slug)
            root = registry.directory(slug)
            day = now.astimezone(registry.zone(channel["cadence"]["timezone"])).date().isoformat()
            brief = pipeline._read(root / "brief" / day / "brief.json")
            if brief is not None:
                ready = sum(bool(item.get("script")) for item in brief["items"])
                waiting = len(brief["items"]) - ready
                lines.extend([f"Brief: {ready} scripts ready, {waiting} waiting for answers. {root / 'brief' / 'latest.html'}", ""])
            items = [row for path in (root / "sources").glob("*.jsonl") for row in watch.read(path)]
            projects = sorted(root.glob("projects/*/factory.json"))
            found = sum(recent(row.get("found_at")) for row in items)
            started = sum(recent(pipeline._read(path).get("created")) for path in projects)
            clips = [d / f"clip{render.suffix('9x16', pipeline._read(file).get('pack', 'zing'))}.mp4"
                     for file in projects for d in file.parent.glob("clip[0-9][0-9]*") if re.fullmatch(r"clip\d{2,}", d.name)]
            clips = [p for p in clips if p.is_file()]
            made = sum(since.timestamp() <= p.stat().st_mtime <= now.timestamp() for p in clips)
            lines.extend([f"{count(found, 'item')} found. {count(started, 'project')} started. {count(made, 'clip')} made.", ""])
            rows = queue.read(slug)
            queued = [r for r in rows if recent(r.get("queued_at"))]
            lines.extend([f"{count(len(queued), 'clip')} queued in the last 24 hours.", ""])
            lines.extend(f"- {_text(r['id'])} has slot {_text(r['slot'])}." for r in queued)
            waiting = [r for r in rows if r["status"] == "kit"]
            lines.extend(["", f"{count(len(waiting), 'kit')} waiting to be posted.", ""])
            lines.extend(f"- {_text(r['id'])} waits at {_text(r.get('kit', ''))}." for r in waiting)
            closed = {r["id"] for r in rows if r["status"] in ("posted", "skipped")}
            blocked, prompts = {}, []
            for file in projects:
                project = file.parent
                prompts.extend(tick.pending(project))
                for d in sorted(project.glob("clip[0-9][0-9]*")):
                    ident = f"{project.name}/{d.name}"
                    if not d.is_dir() or not re.fullmatch(r"clip\d{2,}", d.name) or ident in closed:
                        continue
                    result = gate.check(project, d.name, channel, now=now)
                    if result["blockers"]:
                        blocked[ident] = result["blockers"]
            ticks = [row for row in watch.read(root / "ticks.jsonl") if recent(row.get("at"))]
            queued_ids = {r["id"] for r in rows}
            if ticks:
                for ident, reasons in ticks[-1].get("blocked", {}).items():
                    if ident not in queued_ids and any("three clips in a row" in r for r in reasons):
                        blocked.setdefault(ident, reasons)
            lines.extend(["", f"{count(len(blocked), 'clip')} blocked.", ""])
            lines.extend(f"- {_text(ident)}. {_text(' '.join(reasons))}" for ident, reasons in sorted(blocked.items()))
            rights = [src for src in channel["sources"] if registry.effective_rights(src, now) == "unknown"]
            lines.extend(["", f"{count(len(rights), 'source')} {'needs' if len(rights) == 1 else 'need'} rights.", ""])
            lines.extend(f"- {_text(src['id'])}. {_text(src['name'])}." for src in rights)
            audio = [row for row in items if row.get("audio_only") and recent(row.get("found_at"))]
            lines.extend(f"- {_text(row['title'])}. Audio only, needs a video." for row in audio)
            lines.extend(["", f"{count(len(prompts), 'pending judge prompt')}.", ""])
            lines.extend(f"- {_text(Path(p['project']).name)}/{_text(p['task'])}. {_text(p['prompt_path'])}." for p in prompts)
            errors = [(row["at"], error) for row in ticks for error in row.get("errors", [])]
            lines.extend(["", f"{count(len(errors), 'error')} from ticks.", ""])
            lines.extend(f"- {_text(at)}. {_text(error)}" for at, error in errors)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            lines.append(f"Could not read this channel. {_text(exc)}")
        lines.append("")
    return "\n".join(lines)
