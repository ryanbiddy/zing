"""Allocate local posting slots without posting anything."""
from __future__ import annotations

import json
import os
import random
import re
import secrets
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from myzing.factory import campaign, postcopy
from myzing.factory.pipeline import _read, _write

from . import bandit, gate, registry, youtube
from .registry import ChannelError

STATUSES = ("queued", "kit", "posted", "skipped")


def read(slug: str) -> list[dict]:
    path = registry.directory(slug) / "queue.jsonl"
    if not path.is_file():
        return []
    try:
        rows = [json.loads(line.rstrip("\r")) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
        for row in rows:
            slot = datetime.fromisoformat(row["slot"])
            if slot.tzinfo is None or row["status"] not in STATUSES:
                raise ValueError("invalid slot or status")
            if row["id"] != f"{Path(row['project']).name}/{row['clip']}" or not re.fullmatch(r"clip\d{2,}", row["clip"]):
                raise ValueError("invalid clip id")
        return rows
    except (ValueError, KeyError, TypeError) as exc:
        raise ChannelError(f"queue.jsonl is invalid. {exc}") from exc


def write(slug: str, rows: list[dict]) -> None:
    path = registry.directory(slug) / "queue.jsonl"
    tmp = path.with_name(".queue-" + secrets.token_hex(8) + ".tmp")
    try:
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _now(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ChannelError("now must include a timezone")
    return now


def _daily(day, channel: dict):
    cadence = channel["cadence"]
    zone = registry.zone(cadence["timezone"])
    for value in sorted(cadence["times"]):
        slot = datetime.combine(day, time.fromisoformat(value), zone)
        if slot.astimezone(timezone.utc).astimezone(zone) == slot:  # skip local times lost when clocks move forward
            yield slot


def slots(channel: dict, rows: list[dict], now: datetime | None = None):
    now = _now(now)
    zone = registry.zone(channel["cadence"]["timezone"])
    occupied = {datetime.fromisoformat(r["slot"]).timestamp() for r in rows}
    counts = Counter(datetime.fromisoformat(r["slot"]).astimezone(zone).date() for r in rows)
    day = now.astimezone(zone).date()
    while True:
        if counts[day] < channel["cadence"]["per_day"]:
            for slot in _daily(day, channel):
                if counts[day] >= channel["cadence"]["per_day"]:
                    break
                if slot.timestamp() >= now.timestamp() and slot.timestamp() not in occupied:
                    yield slot
                    counts[day] += 1
        day += timedelta(days=1)


def next_slot(channel: dict, rows: list[dict], now: datetime | None = None) -> str:
    return next(slots(channel, rows, now)).isoformat(timespec="seconds")


def _seed_ok(slot: datetime, rows: list[dict], channel: dict) -> bool:
    every = channel["seeding"]["every"]
    zone = slot.tzinfo
    for row in rows:
        if not row.get("own") or row["status"] == "skipped":
            continue
        a, b = sorted((slot, datetime.fromisoformat(row["slot"]).astimezone(zone)), key=lambda d: d.timestamp())
        day, count = a.date(), 0
        while day <= b.date() and count < every:
            count += min(channel["cadence"]["per_day"],
                         sum(a.timestamp() < s.timestamp() <= b.timestamp() for s in _daily(day, channel)))
            day += timedelta(days=1)
        if count < every:
            return False
    return True


def _episode_ok(project: str, slot: datetime, rows: list[dict]) -> bool:
    active = sorted((r for r in rows if r["status"] != "skipped"), key=lambda r: datetime.fromisoformat(r["slot"]).timestamp())
    before = [r for r in active if datetime.fromisoformat(r["slot"]).timestamp() < slot.timestamp()]
    after = active[len(before):]
    count = 1
    for side in (reversed(before), iter(after)):
        for row in side:
            if row["project"] != project:
                break
            count += 1
    return count <= 3


def _title(row: dict, history: list[dict], channel: dict, rng) -> None:
    d = Path(row["project"]) / row["clip"]
    post = _read(d / "post.json", {})
    recent = sorted((r for r in history if r.get("status", "posted") in ("queued", "kit", "posted")), key=bandit.when)[-9:]
    counts = Counter(bandit.value(r, "title_pattern") for r in recent)
    if not post.get("title_pattern") or counts[post["title_pattern"]] < 4:
        return
    options = post.get("title_options", [])
    candidates = list(dict.fromkeys(t["pattern"] for t in options if counts[t["pattern"]] < 4))
    if not candidates:
        return
    value, propensity, policy = bandit.choose("title_pattern", candidates, history, rng,
                                            baseline="name_claim", prior=bandit.prior(channel))
    post.update(youtube_title=next(t["text"] for t in options if t["pattern"] == value), title_pattern=value,
                title_propensity=propensity, title_policy=policy, title_candidates=candidates)
    post = postcopy.require_tags(post, campaign.read(d.parent))
    stat = (d / "post.json").stat()
    _write(d / "post.json", post)
    os.utime(d / "post.json", ns=(stat.st_atime_ns, stat.st_mtime_ns))  # keep the approved copy's timestamp
    row["title"] = post["youtube_title"]
    row["arms"].update({k: post[k] for k in ("title_pattern", "title_propensity", "title_policy", "title_candidates")})


def build(slug: str, now: datetime | None = None, *, rng: random.Random | None = None, stop=None) -> dict:
    channel = registry.load(slug)
    registry.require_running(slug)
    with youtube.lock():
        return _build(channel, now, rng, stop)


def _build(channel, now, rng, stop):
    slug = channel["slug"]
    now = _now(now)
    rows = read(slug)
    history = bandit.history(slug)
    rng = rng or random.Random()
    seen = {r["id"] for r in rows}
    pending, blocked = [], {}
    for project in sorted((registry.directory(slug) / "projects").iterdir()):
        if stop and stop():
            break
        if not project.is_dir():
            continue
        try:
            cfg = _read(project / "factory.json", {})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            blocked[project.name] = [str(exc) or type(exc).__name__]
            continue
        for d in sorted(project.glob("clip[0-9][0-9]*")):
            if stop and stop():
                break
            if not d.is_dir() or not re.fullmatch(r"clip\d{2,}", d.name):
                continue
            ident = f"{project.name}/{d.name}"
            if ident in seen:
                continue
            try:
                result = gate.check(project, d.name, channel, now=now)
                if not result["publishable"]:
                    blocked[ident] = result["blockers"]
                    continue
                src = registry.source(channel, cfg["source"]) if cfg.get("source") else {}
                pending.append({"id": ident, "project": str(project.resolve()), "clip": d.name, "status": "queued",
                                "title": _read(d / "post.json", {}).get("youtube_title", ""), "own": src.get("kind") in ("own", "recordings"),
                                "arms": _read(d / "arms.json", {"archetype": "other"}),
                                "manual": gate.rating(project, d.name) == "post", "queued_at": now.isoformat(timespec="seconds")})
            except (OSError, ValueError, KeyError, TypeError) as exc:
                blocked[ident] = [str(exc) or type(exc).__name__]
    added = 0
    cursor = now
    while pending:
        if stop and stop():
            break
        slot = next(slots(channel, rows, cursor))
        candidates = [r for r in pending if _episode_ok(r["project"], slot, rows)]
        if not candidates and all(datetime.fromisoformat(r["slot"]).timestamp() < slot.timestamp() for r in rows):
            break
        candidates = [r for r in candidates if not r["own"] or _seed_ok(slot, rows, channel)]
        chosen = None
        if candidates:
            archetypes = [r["arms"].get("archetype", "other") for r in candidates]
            if not bandit.allowed("archetype", archetypes, history):
                for row in candidates:
                    blocked[row["id"]] = ["Waiting for another archetype under the variety rule."]
                break
            value, propensity, policy = bandit.choose("archetype", archetypes, history, rng)
            chosen = next(r for r in candidates if r["arms"].get("archetype", "other") == value)
        if chosen is not None:
            try:
                _title(chosen, history, channel, rng)
                row = {**chosen, "slot": slot.isoformat(timespec="seconds"), "order_propensity": propensity,
                       "order_policy": policy, "arms": {**chosen["arms"], "hour": slot.hour}}
                _write(Path(row["project"]) / row["clip"] / "arms.json", row["arms"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                blocked[chosen["id"]] = [str(exc) or type(exc).__name__]
                pending.remove(chosen)
                continue
            rows.append(row)
            history.append(row)
            pending.remove(chosen)
            added += 1
        cursor = datetime.fromtimestamp(slot.timestamp() + 1, timezone.utc)
    if added:
        write(slug, rows)
    for row in pending:
        if not (stop and stop()):
            blocked.setdefault(row["id"], ["Waiting for another episode after three clips in a row."])
    return {"added": added, "blocked": blocked, "next_slot": next_slot(channel, rows, now)}


def mark(slug: str, ident: str, status: str, url: str | None = None) -> dict:
    registry.load(slug)
    if status not in ("posted", "skipped"):
        raise ChannelError("status must be posted or skipped")
    if url is not None:
        registry.web_url(url, "url")
    with youtube.lock():
        rows = read(slug)
        row = next((r for r in rows if r["id"] == ident), None)
        if row is None:
            raise ChannelError(f"queue id {ident} was not found")
        row["status"] = status
        if url is not None:
            row["url"] = url
        if status == "posted":
            from .outcomes import video_id
            row.setdefault("posted_at", _now().isoformat(timespec="seconds"))
            row["video_id"] = video_id(url) if url is not None else row.get("video_id") or video_id(row.get("url"))
        write(slug, rows)
        return row
