"""Local progress against a channel's bar."""
from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

from myzing.factory import pipeline
from myzing.playbook.common import number, parse_time

from . import bandit, outcomes, queue, registry

BAR = {"days": 30, "posts": 60, "recorded": 0.6, "kept": 0.7, "flags": 0}
KINDS = ("claim", "strike", "reused", "other")


def _check_flag(row):
    registry._fields(row, {"at", "kind", "note", "clip"}, "flag")
    if row.get("kind") not in KINDS:
        raise registry.ChannelError("kind must be claim, strike, reused or other")
    registry._text(row.get("note"), "note", required=True, most=500)
    if row.get("clip") is not None:
        registry._text(row["clip"], "clip")
    registry._text(row.get("at"), "at", required=True)
    try:
        queue._now(datetime.fromisoformat(row["at"]))
    except ValueError:
        raise registry.ChannelError("at must be an ISO date and time with a timezone") from None


def flag(slug, kind, note, *, clip=None, now=None) -> dict:
    registry.load(slug)
    row = {"at": queue._now(now).isoformat(), "kind": kind, "note": note, "clip": clip}
    _check_flag(row)
    row["note"] = note.strip()
    with (registry.directory(slug) / "flags.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def flags(slug) -> tuple[list[dict], list[str]]:
    path = registry.directory(slug) / "flags.jsonl"
    rows, problems = [], []
    if not path.is_file():
        return rows, problems
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as exc:
        return rows, [f"flags.jsonl could not be read. {exc}"]
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            _check_flag(row)
            rows.append(row)
        except (ValueError, TypeError) as exc:
            problems.append(f"flags.jsonl line {i} is invalid. {exc}")
    return rows, problems


def _briefs(slug, problems):
    rows = []
    for folder in sorted((registry.directory(slug) / "brief").glob("*")):
        if not folder.is_dir():
            continue
        try:
            day = date.fromisoformat(folder.name)
            if day.isoformat() != folder.name:
                raise ValueError("folder must be YYYY-MM-DD")
            data = pipeline._read(folder / "brief.json")
            if (not isinstance(data, dict) or data.get("date") != folder.name
                    or not isinstance(data.get("items"), list) or any(not isinstance(item, dict) for item in data["items"])):
                raise ValueError("brief must have its folder's date and a list of items")
            rows.append((day, data["items"]))
        except (OSError, ValueError, TypeError) as exc:
            problems.append(f"brief/{folder.name}/brief.json is invalid. {exc}")
    return rows


def _window(slug, name, reader, start, today, zone, problems):
    rows = []
    try:
        for row in reader(slug):
            if not isinstance(row, dict):
                raise ValueError("rows must be objects")
            if name == "queue" and row["status"] != "posted":
                continue
            at = parse_time(row.get("posted_at") or (row.get("slot") if name == "queue" else None))
            if name == "outcomes" and "arms" in row and not isinstance(row["arms"], dict):
                raise ValueError("arms must be an object")
            if start <= at.astimezone(zone).date() <= today:
                rows.append((at, row))
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        problems.append(f"{name}.jsonl is invalid. {exc}")
        return []
    return sorted(rows, key=lambda pair: pair[0])


def build(slug: str, *, now: datetime | None = None, days: int = 30) -> dict:
    registry._integer(days, "days", 1)
    channel = registry.load(slug)
    now = queue._now(now)
    zone = registry.zone(channel["cadence"]["timezone"])
    today = now.astimezone(zone).date()
    try:
        start = today - timedelta(days=days - 1)
    except OverflowError:
        raise registry.ChannelError("days exceeds the calendar range") from None
    bar = {**BAR, **channel.get("bar", {})}
    flag_rows, problems = flags(slug)
    briefs = [(day, items) for day, items in _briefs(slug, problems) if day <= today]
    posts = _window(slug, "queue", queue.read, start, today, zone, problems)
    measured = _window(slug, "outcomes", outcomes.read, start, today, zone, problems)
    items = [(day, item) for day, entries in briefs if day >= start for item in entries]
    eligible = [item for day, item in items if (today - day).days >= 2]
    totals = Counter(str(item.get("series") or "unknown") for item in eligible)
    recorded = Counter(str(item.get("series") or "unknown") for item in eligible if item.get("status") == "recorded")
    share = round(sum(recorded.values()) / len(eligible), 2) if eligible else None
    kept = [item["take"]["kept"] for _, item in items if item.get("status") == "recorded"
            and isinstance(item.get("take"), dict) and number(item["take"].get("kept"))]
    retention = round(median(kept), 2) if kept else None
    views, series = [], defaultdict(list)
    for _, row in measured:
        value = row.get("views_7d") if number(row.get("views_7d")) else row.get("views_24h")
        if not number(value):
            continue
        views.append(value)
        name = bandit.value(row, "series")
        if name is not None:
            series[str(name)].append(value)
    half = len(views) // 2
    earlier = median(views[:half]) if half else None
    newer = median(views[half:]) if views else None
    kinds = Counter(row["kind"] for row in flag_rows if start <= parse_time(row["at"]).astimezone(zone).date() <= today)
    masked = sum(row.get("masked") is True for _, row in measured)
    if masked:
        kinds["masked"] += masked
    first = min((day for day, _ in briefs), default=None)
    age = (today - first).days + 1 if first else None
    rows = []

    def add(ident, label, value, target, met, detail):
        rows.append({"id": ident, "label": label, "value": value, "target": target, "met": met, "detail": detail})

    add("days", "Days", age, bar["days"], age >= bar["days"] if age is not None else None,
        f"First brief {first.isoformat()}" if first else "No briefs")
    add("posts", "Posts", len(posts), bar["posts"], len(posts) >= bar["posts"], f"{start.isoformat()} through {today.isoformat()}")
    add("recorded", "Recorded", share, bar["recorded"], share >= bar["recorded"] if len(eligible) >= 10 else None,
        ", ".join(f"{name} {recorded[name]}/{n}" for name, n in sorted(totals.items())) or "No items at least 2 days old")
    add("kept", "Kept", retention, bar["kept"], retention >= bar["kept"] if len(kept) >= 3 else None,
        f"{len(kept)} recorded takes with a kept share")
    detail = [f"earlier half median {_value(earlier)}"]
    detail.extend(f"{name} median {_value(median(values))}" for name, values in sorted(series.items()))
    add("median", "Median views", newer, earlier, newer > earlier if len(views) >= 10 else None, ", ".join(detail))
    add("flags", "Flags", sum(kinds.values()), bar["flags"], sum(kinds.values()) <= bar["flags"],
        ", ".join(f"{kind} {n}" for kind, n in sorted(kinds.items())) or "No flags")
    try:
        setup = pipeline._read(registry.directory(slug) / "setup.json", {})
        if not isinstance(setup, dict):
            raise ValueError("setup must be an object")
        minutes = setup.get("minutes")
        if minutes is not None:
            if not number(minutes) or minutes < 0:
                raise ValueError("minutes must be a nonnegative number")
            add("setup_minutes", "Niche to first brief", minutes, 15, minutes <= 15, "Minutes from setup to the first brief")
    except (OSError, ValueError, TypeError) as exc:
        problems.append(f"setup.json is invalid. {exc}")
    return {"schema_version": 1, "channel": slug, "made_at": now.isoformat(), "days": days, "bar": bar,
            "rows": rows, "met": sum(row["met"] is True for row in rows), "total": len(rows),
            "ready": all(row["met"] is True for row in rows), "problems": problems}


def _value(value):
    return "—" if value is None else f"{value:g}" if number(value) else str(value)


def _status(met):
    return "not enough data" if met is None else "yes" if met else "no"


def page(slug: str, data: dict) -> Path:
    root = registry.directory(slug)
    cards = []
    for row in data["rows"]:
        cards.append(f'<article><h2>{html.escape(str(row["label"]))}</h2>'
                     f'<p>Value {html.escape(_value(row["value"]))} / target {html.escape(_value(row["target"]))}</p>'
                     f'<p>{html.escape(_status(row["met"]))}</p><p>{html.escape(str(row["detail"]))}</p></article>')
    problems = "".join(f"<li>{html.escape(str(problem))}</li>" for problem in data.get("problems", []))
    text = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Channel scorecard</title><style>
body{max-width:760px;margin:32px auto;padding:0 16px;font:16px/1.5 system-ui;color:#222;background:#fafafa}
article{margin:32px 0;padding:20px;border:1px solid #ccc;background:white}h1,h2,p,li{overflow-wrap:anywhere}
h2{font-size:24px}
</style><body><h1>''' + html.escape(slug) + ''' scorecard</h1><p>''' + html.escape(
        f'Last {data["days"]} local days. Made {data["made_at"]}.') + '''</p><p>''' + html.escape(
        f'Ready {_status(data["ready"])} ({data["met"]} of {data["total"]} met)') + '''</p>
''' + "".join(cards) + (f'<h2>Problems</h2><ul>{problems}</ul>' if problems else '') + '</body></html>'
    pipeline._write(root / "scorecard.json", data)
    path = root / "scorecard.html"
    path.write_text(text, encoding="utf-8")
    return path
