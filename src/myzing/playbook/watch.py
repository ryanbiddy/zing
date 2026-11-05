"""Append feed observations and compare them at fixed ages after publication."""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median

from . import feeds
from .common import SCHEMA_VERSION, append_jsonl, number, parse_time, utc_now, write_json

TARGETS = {"1h": 1, "6h": 6, "24h": 24, "72h": 72, "7d": 168}


def watch(out: Path, channels=(), *, fetch=None, now=None) -> dict:
    summaries, seen, total = {}, set(), 0
    for handle in dict.fromkeys(channels):
        ident = feeds.resolve(handle, fetch, root=out)
        if ident in seen:
            continue
        seen.add(ident)
        rows = feeds.feed(ident, fetch, root=out)
        at = now.isoformat() if now is not None else utc_now()
        append_jsonl(out / "snapshots.jsonl", [{"at": at, "channel": handle,
                     **{key: row[key] for key in ("channel_id", "id", "title", "published", "views", "short")}}
                    for row in rows])
        summaries[handle] = {"channel_id": ident, "entries": len(rows)}
        total += len(rows)
    return {"entries": total, "channels": summaries}


def velocity(root: Path) -> dict:
    grouped = {}
    for line in (root / "snapshots.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not number(row["views"]) or row["views"] < 0:
            raise ValueError("snapshot views must be nonnegative numbers")
        parse_time(row["published"])
        grouped.setdefault((row["channel_id"], row["id"]), {})[parse_time(row["at"])] = row
    videos, channels = [], {}
    for (channel_id, ident), samples in sorted(grouped.items()):
        ordered = sorted(samples.items())
        row = ordered[0][1]
        published = parse_time(row["published"])
        ages = [((at - published).total_seconds() / 3600, sample["views"]) for at, sample in ordered]
        views = {}
        for label, target in TARGETS.items():
            near = min(ages, key=lambda sample: abs(sample[0] - target))
            views[label] = (near[1] if abs(near[0] - target) <= target * .25
                            and not (label == "1h" and ages[0][0] > 2) else None)
        rate = (ages[1][1] - ages[0][1]) / (ages[1][0] - ages[0][0]) if len(ages) > 1 else None
        videos.append({"id": ident, "channel": row["channel"], "channel_id": channel_id,
                       "published": row["published"], "short": row["short"], "first_seen": ordered[0][0].isoformat(),
                       "views": views, "views_per_hour": rate})
        summary = channels.setdefault(channel_id, {"channel": row["channel"], "values": []})
        if views["24h"] is not None:
            summary["values"].append(views["24h"])
    for summary in channels.values():
        values = summary.pop("values")
        summary.update(n_24h=len(values), median_24h_views=median(values) if values else None)
    result = {"schema_version": SCHEMA_VERSION, "made_at": utc_now(), "videos": videos, "channels": channels}
    write_json(root / "velocity.json", result)
    return result
