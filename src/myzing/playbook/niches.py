"""Metadata scorecards and title-free priors for a supplied set of channels."""
from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median

from . import feeds, sources, titles
from .common import SCHEMA_VERSION, number, parse_time, read_json, safe_name, utc_now, write_json

ENUMS = {"rights": ("campaign", "encouraged", "mixed", "claims", "public_domain", "unknown"),
         "fit": ("high", "medium", "low"), "money": ("low", "mid", "high")}


def validate(config):
    if not isinstance(config, dict) or not isinstance(config.get("niches"), list):
        raise ValueError("niches must be a list")
    seen = set()
    for niche in config["niches"]:
        if not isinstance(niche, dict) or not isinstance(niche.get("niche"), str) or not niche["niche"].strip():
            raise ValueError("each niche needs a name")
        if niche["niche"] in seen:
            raise ValueError("niche names must be unique")
        seen.add(niche["niche"])
        if not isinstance(niche.get("channels"), list):
            raise ValueError("niche channels must be a list")
        for handle in niche["channels"]:
            feeds.channel(handle)
        for key, choices in ENUMS.items():
            if key in niche and niche[key] not in choices:
                raise ValueError(f"{key} must be one of {' | '.join(choices)}")
        if "notes" in niche and not isinstance(niche["notes"], str):
            raise ValueError("niche notes must be text")


def published(row):
    try:
        if row.get("published"):
            return parse_time(row["published"]).isoformat()
        if row.get("upload_date"):
            return datetime.strptime(row["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
        if number(row.get("timestamp")):
            return datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def shorts(rows, source, now=None, *, fresh_days=3, skip_newest=10):
    """Shorts old enough to compare: dated rows older than fresh_days; undated flat listings drop their newest few."""
    result, seen = [], set()
    if source == "ytdlp" and not any(published(row) for row in rows):
        rows = rows[skip_newest:]
    cutoff = now - timedelta(days=fresh_days) if now and fresh_days else None
    for row in rows:
        when = published(row)
        if cutoff and when and parse_time(when) > cutoff:
            continue
        duration = row.get("duration")
        short = row.get("short") is True if source == "feeds" else (
            any("/shorts/" in (row.get(key) or "") for key in ("url", "webpage_url", "original_url"))
            or number(duration) and 0 < duration <= 180)
        views, ident = row.get("views", row.get("view_count")), row.get("id")
        if not short or not ident or ident in seen or not number(views) or views < 0:
            continue
        seen.add(ident)
        result.append({"id": safe_name(ident), "title": row.get("title") or "", "views": views,
                       "published": published(row), "short": True,
                       **({"duration": duration} if number(duration) and duration > 0 else {})})
    return result


def summarize(rows):
    values = sorted(row["views"] for row in rows)
    med = median(values)
    position = (len(values) - 1) * .9
    low = int(position)
    p90 = values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (position - low)
    dates = sorted(parse_time(row["published"]) for row in rows if row["published"] is not None)
    span = (dates[-1] - dates[0]).total_seconds() / 86400 if dates else 0
    for row in rows:
        row.update(outlier=row["views"] / med if med > 0 else None, features=titles.features(row["title"]))
    return {"n": len(rows), "median_views": med, "mean_views": mean(values), "p90_views": p90,
            "outlier_rate": sum(value >= 3 * med for value in values) / len(values) if med > 0 else None,
            "posting_rate": len(dates) / span if span > 0 else None, "n_dated": len(dates),
            "newest_published": dates[-1].isoformat() if dates else None,
            "top": [{key: row[key] for key in ("id", "views", "outlier")} for row in
                    sorted(rows, key=lambda row: (-row["views"], row["id"]))[:3]]}


def lifts(rows):
    hits = [row for row in rows if row["outlier"] is not None and row["outlier"] >= 2]
    misses = [row for row in rows if row["outlier"] is not None and row["outlier"] < 1]
    result = []
    for feature in titles.LABELS:
        hit_count = sum(row["features"][feature] for row in hits)
        miss_count = sum(row["features"][feature] for row in misses)
        hit_share = hit_count / len(hits) if hits else None
        miss_share = miss_count / len(misses) if misses else None
        result.append({"feature": feature, "n_hits": len(hits), "n_misses": len(misses),
                       "hit_count": hit_count, "miss_count": miss_count, "hit_share": hit_share, "miss_share": miss_share,
                       "lift": hit_share / miss_share if hit_share is not None and miss_share else None,
                       "weak": min(len(hits), len(misses)) < 10})
    return {"n_hits": len(hits), "n_misses": len(misses), "lifts": result}


def build(out: Path, config: dict, *, source="feeds", min_shorts=15, fetch=None, now=None,
          fresh_days=3, skip_newest=10) -> dict:
    validate(config)
    if source not in ("feeds", "ytdlp") or type(min_shorts) is not int or min_shorts < 1:
        raise ValueError("source must be feeds or ytdlp and min-shorts must be positive")
    now = now or datetime.now(timezone.utc)
    now = parse_time(now.isoformat())
    results, local, listings = [], [], {}
    for spec in config["niches"]:
        summaries, cohort, seen = [], [], set()
        for handle in spec["channels"]:
            channel_id = None
            try:
                name = feeds.channel(handle)
                key = name if name.startswith("UC") else name.casefold()
                channel_id = name if name.startswith("UC") and len(name) == 24 else None
                if source == "feeds":
                    channel_id = feeds.resolve(handle, fetch, root=out)
                    key = channel_id
                if key in seen:
                    continue
                seen.add(key)
                if key not in listings:
                    listings[key] = (feeds.feed(channel_id, fetch, root=out) if source == "feeds"
                                     else sources.list_channel(name))
                rows = shorts(listings[key], source, now, fresh_days=fresh_days, skip_newest=skip_newest)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                summaries.append({"channel": handle, "channel_id": channel_id, "status": "skipped", "n": 0,
                                  "reason": f"listing failed ({type(exc).__name__})"})
                continue
            summary = {"channel": handle, "channel_id": channel_id, "status": "listed", "n": len(rows)}
            if rows:
                summary.update(summarize(rows))
            if len(rows) < min_shorts:
                summary.update(status="skipped", reason=f"fewer than {min_shorts} Shorts with view counts")
            for row in rows:
                row.update(niche=spec["niche"], channel=handle, channel_id=channel_id,
                           eligible=summary["status"] == "listed")
            local.extend(rows)
            if summary["status"] == "listed":
                cohort.extend(rows)
            summaries.append(summary)
        listed = [summary for summary in summaries if summary["status"] == "listed"]
        medians = {}
        for field in ("median_views", "outlier_rate", "posting_rate"):
            values = [summary[field] for summary in listed if summary[field] is not None]
            medians[field] = median(values) if values else None
        active = sum(summary["newest_published"] is not None and
                     now - timedelta(days=14) <= parse_time(summary["newest_published"]) <= now for summary in listed)
        demand = round(min(10, 2 * math.log10(max(1, medians["median_views"]))), 2) if listed else None
        results.append({**{key: spec[key] for key in ("niche", "rights", "fit", "money", "notes") if key in spec},
                        "channels": summaries, "channels_listed": len(listed), "channels_skipped": len(summaries) - len(listed),
                        "median_views": medians["median_views"], "median_outlier_rate": medians["outlier_rate"],
                        "median_posting_rate": medians["posting_rate"], "active_channels": active,
                        "demand_score": demand,
                        "crowding_note": f"{active} listed channels posted in the last 14 days. Only supplied channels count.",
                        **lifts(cohort),
                        "top": [{key: row[key] for key in ("channel", "id", "views", "outlier")} for row in
                                sorted(cohort, key=lambda row: (-row["views"], row["id"]))[:3]]})
    result = {"schema_version": SCHEMA_VERSION, "made_at": now.isoformat(), "source": source,
              "min_shorts": min_shorts, "niches": results, "local": {"titles": local}}
    write_json(out / "niches.json", result)
    temporary = out / "titles.jsonl.tmp"
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in local), encoding="utf-8")
    temporary.replace(out / "titles.jsonl")
    (out / "NICHES.md").write_text(report(result), encoding="utf-8")
    return result


def lift_text(item):
    label = titles.LABELS[item["feature"]]
    if item["lift"] is None:
        return (f"Titles {label} appeared in {item['hit_count']}/{item['n_hits']} hits and "
                f"{item['miss_count']}/{item['n_misses']} misses. The ratio is unavailable.")
    return f"Titles {label} were {item['lift']:.2g}x as common among 2x hits as among misses."


def _cell(value):
    if value is None:
        return "unavailable"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.0f}" if abs(value) >= 100 else f"{value:.2f}" if isinstance(value, float) else str(value)
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")
            .replace("[", "\\[").replace("]", "\\]").replace("*", "\\*").replace("`", "\\`"))


def report(data):
    lines = ["# Niche scorecard", "", "Only public metadata was read. Competitor titles stay in local files.",
             "Hits have at least 2x their channel median. Misses fall below it. Title labels are heuristics.", ""]
    for niche in data["niches"]:
        lines.extend([f"## {_cell(niche['niche'])}", "", "| Measure | Value |", "| --- | --- |"])
        for label, key in (("Channels listed", "channels_listed"), ("Channels skipped", "channels_skipped"),
                           ("Median of channel medians", "median_views"), ("Median outlier share", "median_outlier_rate"),
                           ("Median Shorts per day", "median_posting_rate"), ("Active channels", "active_channels"),
                           ("Demand out of 10", "demand_score"), ("Rights input", "rights"), ("Fit input", "fit"),
                           ("Money input", "money"), ("Notes input", "notes")):
            lines.append(f"| {label} | {_cell(niche.get(key))} |")
        lines.extend(["", niche["crowding_note"], "",
                      "| Channel | Shorts | Median views | Mean views | P90 views | Outlier share | Shorts per day | Newest upload |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- |"])
        for channel in niche["channels"]:
            if channel["status"] == "listed":
                lines.append("| " + " | ".join(_cell(channel.get(key)) for key in
                             ("channel", "n", "median_views", "mean_views", "p90_views", "outlier_rate", "posting_rate", "newest_published")) + " |")
        lines.append("")
        for channel in niche["channels"]:
            if channel["status"] == "skipped":
                lines.append(f"- Skipped {_cell(channel['channel'])}. {_cell(channel['reason'])} ({channel['n']} Shorts).")
        lines.extend(["", "### Title patterns", "", f"{niche['n_hits']} hits and {niche['n_misses']} misses.", ""])
        for item in sorted(niche["lifts"], key=lambda item: (item["lift"] is None, -(item["lift"] or 0), item["feature"]))[:5]:
            weak = " Weak evidence with fewer than 10 Shorts in a group." if item["weak"] else ""
            lines.append("- " + lift_text(item) + weak)
        lines.extend(["", "### Biggest Shorts", ""])
        for row in niche["top"]:
            lines.append(f"- [{row['id']}](https://www.youtube.com/shorts/{row['id']}) from {_cell(row['channel'])} "
                         f"with {_cell(row['views'])} views and {_cell(row['outlier'])}x the channel median.")
        lines.append("")
    return "\n".join(lines)


def prior(root: Path, niche: str, out: Path) -> dict:
    data = read_json(root / "niches.json")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported niche schema")
    selected = next((row for row in data["niches"] if row["niche"] == niche), None)
    if selected is None:
        raise ValueError("niche not found")
    if any(type(selected.get(key)) is not int or selected[key] < 0 for key in ("n_hits", "n_misses")):
        raise ValueError("niche hit and miss counts must be nonnegative integers")
    items = [{key: row[key] for key in ("feature", "hit_share", "miss_share", "lift", "weak")}
             for row in selected["lifts"] if row["feature"] in titles.LABELS]
    for row in items:
        if (type(row["weak"]) is not bool
                or any(row[key] is not None and (not number(row[key]) or not 0 <= row[key] <= 1)
                       for key in ("hit_share", "miss_share"))
                or row["lift"] is not None and (not number(row["lift"]) or row["lift"] < 0)):
            raise ValueError("invalid title lift statistics")
    guidance = [lift_text(row) for row in items if not row["weak"] and number(row["lift"])
                and (row["lift"] >= 1.5 or row["lift"] <= .67)]
    result = {"schema_version": SCHEMA_VERSION, "niche": niche, "made_at": utc_now(),
              "n_hits": selected["n_hits"], "n_misses": selected["n_misses"], "lifts": items, "guidance": guidance}
    write_json(out, result)
    return result
