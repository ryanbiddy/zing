"""A watch list and first brief from public channel feeds."""
from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from statistics import median
from urllib.parse import unquote, urlsplit

from myzing.factory.judge import Judge, NeedsAnswer
from myzing.playbook import feeds
from myzing.playbook.common import SCHEMA_VERSION, number, parse_time, read_json

from . import brief, registry


def _handle(value):
    value = value.strip()
    if "://" in value:
        url = urlsplit(value)
        parts = unquote(url.path).strip("/").split("/")
        if (url.scheme not in ("http", "https") or url.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com")
                or url.username or url.password or url.port not in (None, 80, 443)):
            raise ValueError("use a YouTube channel URL")
        if len(parts) > 1 and parts[-1] in ("shorts", "videos", "featured", "streams", "podcasts", "about"):
            parts.pop()
        if len(parts) == 1 and parts[0].startswith("@"):
            value = parts[0]
        elif len(parts) == 2 and parts[0] == "channel" and parts[1].startswith("UC"):
            value = parts[1]
        else:
            raise ValueError("use a YouTube handle or channel ID URL")
    feeds.channel(value)
    return value


def _candidates(values, path, *, required=True, limit=40):
    values = list(values)
    if path is not None:
        try:
            values.extend(line.split("#", 1)[0].strip() for line in Path(path).read_text(encoding="utf-8-sig").splitlines())
        except (OSError, ValueError) as exc:
            raise registry.ChannelError(f"candidates file could not be read. {exc}") from exc
    result, seen = [], set()
    for value in values:
        value = value.strip()
        if not value:
            continue
        try:
            value = _handle(value)
        except ValueError:
            pass
        key = value.removeprefix("@").casefold()
        if key not in seen:
            result.append(value)
            seen.add(key)
    if required and not result:
        raise registry.ChannelError("supply --candidates or --candidates-file")
    if limit is not None and len(result) > limit:
        raise registry.ChannelError("candidates must list at most 40 channels")
    return result


def _scan(path, niche):
    path = Path(path)
    path = (path / "niches.json" if path.is_dir() else path).resolve()
    try:
        data = read_json(path)
    except (OSError, ValueError) as exc:
        raise registry.ChannelError(f"niche scan could not be read. {path}. {exc}") from exc
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
            or data["schema_version"] != SCHEMA_VERSION):
        raise registry.ChannelError(f"unsupported niche scan schema. {path}")
    niches = data.get("niches")
    if not isinstance(niches, list) or any(not isinstance(row, dict) or not isinstance(row.get("niche"), str)
                                         or not row["niche"].strip() for row in niches):
        raise registry.ChannelError(f"invalid niches in scan. {path}")
    if niche is None:
        selected = niches[0] if len(niches) == 1 else None
    else:
        exact = [row for row in niches if row["niche"].strip() == niche.strip()]
        loose = [row for row in niches if row["niche"].strip().casefold() == niche.strip().casefold()]
        matches = exact or loose                        # scans may hold names that differ only by case
        selected = matches[0] if len(matches) == 1 else None
    if selected is None:
        raise registry.ChannelError("choose a niche with --scan-niche: " + " | ".join(row["niche"] for row in niches))
    rows = selected.get("channels")
    if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("channel"), str) or not row["channel"].strip()
            or row.get("status") not in ("listed", "skipped")
            or row["status"] == "listed" and (not number(row.get("median_views")) or row["median_views"] < 0)
            for row in rows):
        raise registry.ChannelError(f"invalid channels in niche scan. {path}")
    listed = sorted((row for row in rows if row["status"] == "listed"), key=lambda row: row["median_views"], reverse=True)
    handles = _candidates([row["channel"] for row in listed + [row for row in rows if row["status"] == "skipped"]],
                          None, required=False, limit=None)
    return {"path": str(path), "niche": selected["niche"], "made_at": data.get("made_at"),
            "candidates": len(handles), "left_out": 0}, handles


def _suggestions(value):
    if not isinstance(value, dict) or not isinstance(value.get("candidates"), list):
        raise registry.ChannelError("suggestion answer must have a candidates list")
    if not 1 <= len(value["candidates"]) <= 40:
        raise registry.ChannelError("suggested candidates must list 1 to 40 channels")
    result = []
    for row in value["candidates"]:
        if not isinstance(row, dict) or not isinstance(row.get("handle"), str):
            raise registry.ChannelError("each suggested candidate must have a handle")
        try:
            if not row["handle"].strip().startswith("@"):
                raise ValueError
            handle = _handle(row["handle"])
        except ValueError:
            raise registry.ChannelError("suggested candidates must use YouTube handles such as @name") from None
        why = row.get("why", "")
        registry._text(why, "suggested candidate why", most=200)
        result.append({"handle": handle, "why": why})
    return result


def _page(channel, data):
    reasons = {row["handle"].removeprefix("@").casefold(): row["why"] for row in reversed(data.get("suggested", []))}

    def label(row):
        return html.escape(row["handle"]) + (" (suggested)" if row.get("suggested") else "")

    def title(row):
        why = reasons.get(row["handle"].removeprefix("@").casefold(), "")
        return f' title="{html.escape(why, quote=True)}"' if row.get("suggested") else ""

    rows = "".join(f'<tr><td{title(row)}>{label(row)}</td><td>{row["shorts"]}</td>'
                   f'<td>{row["median_views"]:g}</td><td>{html.escape(row["newest"])}</td></tr>' for row in data["kept"])
    dropped = "".join(f'<li{title(row)}>{label(row)} — {html.escape(row["reason"])}</li>' for row in data["dropped"])
    minutes = f'Niche to first brief {data["minutes"]:.1f} min' if data["minutes"] is not None else "No first brief yet"
    error = f'<p>Brief failed. {html.escape(data["brief_error"])}</p>' if data.get("brief_error") else ""
    scan = ""
    if data.get("scan"):
        made = data["scan"]["made_at"]
        try:
            made = parse_time(made).date().isoformat()  # scans store a full timestamp
        except ValueError:
            pass
        when = f" made {made}" if made else ""
        scan = "<p>" + html.escape(f'Candidates came from the niche scan{when} for {data["scan"]["niche"]}.') + "</p>"
    return '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Channel setup</title><style>
body{max-width:760px;margin:32px auto;padding:0 16px;font:16px/1.5 system-ui;color:#222;background:#fafafa}
table{width:100%;border-collapse:collapse;background:white}th,td{padding:8px;text-align:left;border:1px solid #ccc}
h1,h2,p,li,td{overflow-wrap:anywhere}h2{font-size:24px}
</style><body><h1>''' + html.escape(channel["name"]) + ''' setup</h1>''' + scan + '''<p>''' + html.escape(data["niche"]) + '''</p>
<p>''' + minutes + '''. Target 15 min.</p>''' + error + '''<h2>Kept channels</h2>
<table><thead><tr><th>Channel</th><th>Shorts</th><th>Median views</th><th>Newest Short</th></tr></thead>
<tbody>''' + rows + '''</tbody></table><h2>Dropped channels</h2>''' + (
        f'<ul>{dropped}</ul>' if dropped else '<p>None.</p>') + '</body></html>'


def _publish(root, channel, data):
    brief._publish(root / "setup.json", json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    brief._publish(root / "setup.html", _page(channel, data))


def run(slug: str, niche: str | None = None, candidates=(), *, name=None, candidates_file=None, keep=15, min_shorts=3,
        no_brief=False, suggest=False, judge=None, from_scan=None, scan_niche=None, fetch=None, feed=None) -> dict:
    started = datetime.now(timezone.utc)
    if scan_niche is not None and from_scan is None:
        raise registry.ChannelError("--scan-niche requires --from-scan")
    scan, scanned = None, []
    if from_scan is not None:
        scan, scanned = _scan(from_scan, scan_niche)
        if niche is None:
            niche = scan["niche"].strip()[:200]
    registry._text(niche, "niche", required=True, most=200)
    registry._integer(keep, "keep", 3, 40)
    registry._integer(min_shorts, "min-shorts", 1)
    root = registry.directory(slug)
    channel = registry.load(slug) if (root / "channel.json").exists() else None
    if judge is None:
        judge = channel["judge"] if channel else "host"
    if judge not in ("host", "claude"):
        raise registry.ChannelError("judge must be host or claude")
    series = next((s for s in channel["series"] if s["kind"] == "breakdown"), None) if channel else None
    if channel is not None and series is None:
        raise registry.ChannelError(f"channel {slug} has no breakdown series")
    if channel is None:
        name = slug.replace("-", " ").title() if name is None else name
        registry._text(name, "name", required=True)
    handles = _candidates(candidates, candidates_file, required=not suggest and scan is None)
    supplied = {handle.removeprefix("@").casefold() for handle in handles}
    scan_only = set()
    if scan is not None:
        handles = _candidates([*handles, *scanned], None, required=not suggest, limit=None)
        scan["left_out"] = max(0, len(handles) - 40)
        handles = handles[:40]
        scan_only = {handle.removeprefix("@").casefold() for handle in handles} - supplied
        supplied.update(scan_only)
    suggested = []
    if suggest:
        folder = root / "setup"
        ask = Judge(folder, backend=judge)
        prompt = (resources.files("myzing") / "_data" / "channels" / "prompts" / "setup-candidates.md").read_text(encoding="utf-8")
        task = "suggest-candidates"
        try:
            answer = ask.ask(task, prompt.replace("{NICHE}", niche))
        except NeedsAnswer as exc:
            return {"pending": str(exc.path), "answer": str(folder / "answers" / f"{task}.json")}
        try:
            suggested = _suggestions(answer)
        except registry.ChannelError:
            ask.forget(task)
            raise
        handles = _candidates([*handles, *(row["handle"] for row in suggested)], None)
    kept, dropped = [], []
    for handle in handles:
        try:
            handle = _handle(handle)
            ident = feeds.resolve(handle, fetch, root=root)
            if not ident:
                raise ValueError("no channel ID")
        except Exception:
            dropped.append({"handle": handle, "reason": "could not resolve"})
            continue
        try:
            rows = (feed or feeds.feed)(ident, fetch, root=root)
            rows = sorted(rows, key=lambda row: parse_time(row["published"]), reverse=True)[:15]  # fallbacks return up to 30
            shorts = [row for row in rows if row["short"] is True]
            newest = max((parse_time(row["published"]) for row in shorts), default=None)
            if len(shorts) < min_shorts:
                reason = f"fewer than {min_shorts} Shorts in its 15 newest uploads"
            elif newest is None or not started - timedelta(days=60) <= newest <= started:
                reason = "no Short in the last 60 days"
            else:
                kept.append({"handle": handle, "channel_id": ident, "shorts": len(shorts),
                             "median_views": median(row["views"] for row in shorts), "newest": newest.isoformat()})
                continue
        except Exception as exc:
            reason = f"feed failed ({str(exc) or type(exc).__name__})"
        dropped.append({"handle": handle, "reason": reason})
    if len(kept) < 3:
        reasons = Counter(row["reason"] for row in dropped)
        detail = "; ".join(f"{reason} ({count})" for reason, count in reasons.most_common(3))
        names = f" Kept {', '.join(row['handle'] for row in kept)}." if kept else ""
        raise registry.ChannelError(f"Only {len(kept)} candidates survived. Need at least 3.{names}" + (f" {detail}" if detail else ""))
    kept.sort(key=lambda row: row["median_views"], reverse=True)
    dropped.extend({"handle": row["handle"], "reason": f"outside top {keep}"} for row in kept[keep:])
    kept = kept[:keep]
    if suggest or scan is not None:
        for row in kept + dropped:
            key = row["handle"].removeprefix("@").casefold()
            if key in scan_only:
                row["from_scan"] = True
            if suggest:
                row["suggested"] = key not in supplied
    watch = [row["handle"] for row in kept]
    if channel is None:
        channel = registry.create(name, niche, slug, judge=judge, series=[
            {"id": "blew-up", "name": "Why it blew up", "kind": "breakdown", "watch": watch, "per_day": 2,
             "min_multiple": 3, "lesson": "End on one move a viewer can copy this week."},
            {"id": "news", "name": "What changed", "kind": "news", "per_day": 1,
             "lesson": "Say who it affects and what to do about it today."},
            {"id": "podcast", "name": "Heard on a podcast", "kind": "clips", "per_day": 0}])
    else:
        series["watch"] = watch
        channel = registry.save(channel)
    data = {"niche": niche, "started": started.isoformat(), "saved": datetime.now(timezone.utc).isoformat(),
            "first_brief": None, "minutes": None, "kept": kept, "dropped": dropped}
    if scan is not None:
        data["scan"] = scan
    if suggest:
        data["suggested"] = suggested
    _publish(root, channel, data)
    path = None
    if not no_brief:
        try:
            result = brief.make(slug)
            made = root / "brief" / result["date"] / "brief.html"
            if not made.is_file():
                raise registry.ChannelError("brief stopped before the page was written")
            finished = datetime.now(timezone.utc)
            data.update(first_brief=finished.isoformat(), minutes=round((finished - started).total_seconds() / 60, 1))
            path = made
        except Exception as exc:
            data["brief_error"] = str(exc) or type(exc).__name__
        _publish(root, channel, data)
    return {**data, "page": str(root / "setup.html"), "brief": str(path) if path else None}
