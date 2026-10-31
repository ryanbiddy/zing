"""Metadata-only channel listing and import of the existing pilot selection."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from myzing import doctor
from myzing.study import proc
from .common import SCHEMA_VERSION, number, read_json, safe_name, utc_now, write_json


def list_channel(handle: str) -> list[dict]:
    argv = doctor.resolve_ytdlp_argv()
    if argv is None:
        raise ValueError("yt-dlp is unavailable; run zing doctor")
    result = proc.run([*argv, "--ignore-config", "--no-update", "--flat-playlist",
                       "--skip-download", "--playlist-end", "160", "-j",
                       f"https://www.youtube.com/@{safe_name(handle)}/shorts"], timeout=240)
    if result.returncode:
        raise ValueError(f"channel listing failed (exit {result.returncode})")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def select(rows: list[dict], *, skip_newest=10, k=5, now=None) -> dict:
    if skip_newest < 0 or k < 1:
        raise ValueError("skip-newest must be nonnegative and k must be positive")
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=14)
    aged, seen, unknown_age = [], set(), 0
    for row in rows[skip_newest:]:
        ident = row.get("id")
        views = row.get("view_count", row.get("views"))
        if not ident or ident in seen or not number(views) or views < 0:
            continue
        safe_name(ident)
        seen.add(ident)
        uploaded = None
        if row.get("upload_date"):
            uploaded = datetime.strptime(row["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc)
        elif number(row.get("timestamp")):
            uploaded = datetime.fromtimestamp(row["timestamp"], timezone.utc)
        if uploaded is not None and uploaded > cutoff:
            continue
        unknown_age += uploaded is None
        aged.append({"id": ident, "views": views, "title": row.get("title") or "",
                     **({"duration": row["duration"]} if number(row.get("duration")) and row["duration"] > 0 else {})})
    summary = {"n": len(aged), "age_unverified": unknown_age, "skip_newest": skip_newest}
    if len(aged) < max(30, 2 * k):
        return {**summary, "status": "skipped", "reason": "fewer than 30 aged Shorts or fewer than 2*k"}
    med = median(r["views"] for r in aged)
    if med <= 0:
        return {**summary, "status": "skipped", "reason": "channel median is zero"}
    ranked = sorted(aged, key=lambda r: (r["views"], r["id"]))
    worked = [r for r in reversed(ranked) if r["views"] > med][:k]
    didnt = [r for r in ranked if r["views"] < med][:k]
    if len(worked) < k or len(didnt) < k:
        return {**summary, "status": "skipped", "reason": "too few Shorts strictly above/below median"}
    return {**summary, "status": "listed", "median_views": med, "worked": worked, "didnt": didnt}


def build(out: Path, channels=(), *, from_candidates: Path | None = None, skip_newest=10, k=5) -> dict:
    if skip_newest < 0 or k < 1:
        raise ValueError("skip-newest must be nonnegative and k must be positive")
    if from_candidates is not None:
        selected = read_json(from_candidates)
    else:
        selected = {}
        for handle in channels:
            handle = safe_name(handle.lstrip("@"))
            if handle in selected:
                continue
            try:
                selected[handle] = select(list_channel(handle), skip_newest=skip_newest, k=k)
            except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
                selected[handle] = {"status": "failed", "reason": str(exc)}
    entries, summaries, seen = [], {}, set()
    listed_at = utc_now()
    for handle, summary in selected.items():
        handle = safe_name(handle.lstrip("@"))
        if summary.get("status") in ("skipped", "failed"):
            summaries[handle] = summary
            continue
        med = summary["median_views"]
        if summary["n"] < 30 or not number(med) or med <= 0:
            summaries[handle] = {"status": "skipped", "reason": "insufficient aged Shorts or invalid median"}
            continue
        channel_entries = []
        for group in ("worked", "didnt"):
            for row in summary[group][:k]:
                ident = safe_name(row["id"])
                views = row["views"]
                if ident in seen or not number(views) or views < 0:
                    raise ValueError("duplicate ID or invalid views in selection")
                if (group == "worked" and views <= med) or (group == "didnt" and views >= med):
                    raise ValueError("selection does not contrast above/below the channel median")
                seen.add(ident)
                channel_entries.append({"platform": "youtube", "channel": handle, "id": ident,
                    "url": f"https://www.youtube.com/shorts/{ident}", "title": row.get("title") or "",
                    "views": views, "channel_median": med, "outlier": views / med,
                    "set": group, "listed_at": listed_at,
                    **({"duration": row["duration"]} if number(row.get("duration")) and row["duration"] > 0 else {})})
        if any(sum(e["set"] == group for e in channel_entries) != k for group in ("worked", "didnt")):
            raise ValueError("each imported channel must supply k Shorts per side")
        entries.extend(channel_entries)
        summaries[handle] = {"status": "listed", "n": summary["n"], "median_views": med,
            "worked": k, "didnt": k, "age_unverified": summary.get("age_unverified", summary["n"]),
            "age_policy": "skip newest; exclude known uploads under 14 days; unknown dates unverified",
            "origin": "candidates" if from_candidates else "yt-dlp", "listed_at": listed_at}
    result = {"schema_version": SCHEMA_VERSION, "listed_at": listed_at, "entries": entries, "channels": summaries}
    write_json(out / "library.json", result)
    for handle, summary in summaries.items():
        write_json(out / "channels" / f"{handle}.json", summary)
    return result
