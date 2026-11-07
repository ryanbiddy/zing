"""Resumable YouTube uploads and owner analytics."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from myzing.factory.pipeline import _read, _write
from myzing.playbook.common import number

from . import gate, kit, outcomes, queue, registry, youtube

UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
REPORTS = "https://youtubeanalytics.googleapis.com/v2/reports"
CHUNK = 8 * 1024 * 1024
METRICS = {"views": "views", "engagedViews": "engaged_views", "averageViewPercentage": "avg_view_pct",
           "averageViewDuration": "avg_view_duration", "subscribersGained": "subs"}


def _day(now: datetime) -> str:
    now = now.astimezone(timezone.utc)
    march, november = datetime(now.year, 3, 8, 10, tzinfo=timezone.utc), datetime(now.year, 11, 1, 9, tzinfo=timezone.utc)
    start = march + timedelta(days=(6 - march.weekday()) % 7)
    end = november + timedelta(days=(6 - november.weekday()) % 7)
    return (now - timedelta(hours=7 if start <= now < end else 8)).date().isoformat()  # Pacific rules since 2007


def _ledgers(slug, project, now):
    day = _day(now)
    path, shared = registry.directory(slug) / "youtube-quota.json", registry.home() / "youtube-quota.json"
    channel, projects = _read(path, {}), _read(shared, {})
    if channel.get("day") != day:
        channel = {"day": day, "uploads": 0}
    if projects.get("day") != day:
        projects = {"day": day, "projects": {}}
    ledger = projects["projects"].setdefault(project, {"uploads": 0})
    return path, channel, shared, projects, ledger


def _quota(channel, project, now, *, reserve=False, reason=None):
    path, local, shared, projects, ledger = _ledgers(channel["slug"], project, now)
    if reason:
        local["blocked"] = reason
        if reason == "quotaExceeded":
            ledger["blocked"] = reason
    else:
        stopped = local.get("blocked") or ledger.get("blocked")
        if stopped:
            return stopped
        if reserve:
            if local["uploads"] >= channel["youtube_daily_cap"]:
                return "YouTube daily channel cap reached."
            if ledger["uploads"] >= 80:
                return "YouTube daily project cap reached."
            local["uploads"] += 1
            ledger["uploads"] += 1
    if reserve or reason:
        _write(shared, projects)
        _write(path, local)
    return None


def _outbox(slug):
    path = registry.directory(slug) / "outbox.jsonl"
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
        if len({r["id"] for r in rows}) != len(rows) or any(r["state"] not in ("uploading", "done") for r in rows):
            raise ValueError
        return rows
    except (ValueError, KeyError, TypeError):
        raise registry.ChannelError("The YouTube outbox needs repair before uploading.") from None


def _save_outbox(slug, rows):
    path = registry.directory(slug) / "outbox.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        stream.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def _generated(value):
    if isinstance(value, list):
        return any(_generated(v) for v in value)
    if not isinstance(value, dict):
        return False
    keys = ("generated_media", "synthetic_media", "containsSyntheticMedia", "contains_synthetic_media", "generated")
    return any(value.get(k) is True for k in keys) or any(_generated(v) for v in value.values())


def _metadata(row, channel, now):
    folder = Path(row["kit"])
    title, _, description = (folder / "youtube.txt").read_text(encoding="utf-8").partition("\n\n")
    if not title.strip():
        raise registry.ChannelError("The kit needs a YouTube title.")
    d = Path(row["project"]) / row["clip"]
    generated = any(_generated(_read(p, {})) for p in (d / "plan.json", d / "post.json", folder / "post.json"))
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": generated}
    slot = datetime.fromisoformat(row["slot"])
    if channel["publish"]["youtube"] == "scheduled" and slot >= now + timedelta(minutes=15):
        status["publishAt"] = slot.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"snippet": {"title": title, "description": description, "categoryId": channel["youtube_category"]}, "status": status}


def _session(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme == "https" and parts.hostname and parts.hostname.endswith(".googleapis.com")
                and not parts.username and not parts.password and parts.port in (None, 443)):
            return url
    except (TypeError, ValueError):
        pass
    raise registry.ChannelError("YouTube returned an invalid upload session.")


def _offset(response, size):
    if response[0] != 308:
        youtube.checked(response)
        raise registry.ChannelError("YouTube returned an incomplete upload result.")
    value = response[1].get("range", "")
    match = re.fullmatch(r"bytes=0-(\d+)", value)
    offset = int(match[1]) + 1 if match else 0
    if (value and not match) or offset > size:
        raise registry.ChannelError("YouTube returned an invalid upload offset.")
    return offset


def _transfer(client, entry, *, resume):
    path, size = Path(entry["kit"]) / "video.mp4", entry["size"]
    stat = path.stat()
    if stat.st_size != size or (entry.get("mtime_ns") is not None and stat.st_mtime_ns != entry["mtime_ns"]):
        raise registry.ChannelError("The saved upload file changed. Keep its original kit to resume.")
    session, offset = _session(entry["session_uri"]), 0
    if resume:
        response = client.request("PUT", session, b"", {"Content-Length": "0", "Content-Range": f"bytes */{size}"})
        if response[0] in (200, 201):
            return youtube.checked(response)
        offset = _offset(response, size)
    with path.open("rb") as stream:
        while offset < size:
            client.checkpoint()
            stream.seek(offset)
            data = stream.read(min(CHUNK, size - offset))
            if not data:
                raise registry.ChannelError("The saved upload file is incomplete.")
            response = client.request("PUT", session, data, {"Content-Type": "video/mp4", "Content-Length": str(len(data)),
                                      "Content-Range": f"bytes {offset}-{offset + len(data) - 1}/{size}"})
            if response[0] in (200, 201):
                return youtube.checked(response)
            next_offset = _offset(response, size)
            if not offset < next_offset <= offset + len(data):
                raise registry.ChannelError("YouTube did not advance the upload. Try again later.")
            offset = next_offset
    raise registry.ChannelError("YouTube has not confirmed the upload. Try again later.")


def _finish(slug, rows, row, entries, entry, now, video=None):
    if video is not None:
        ident = video.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", ident):
            raise registry.ChannelError("YouTube did not return a video ID. Resume this upload later.")
        entry.update(video_id=ident, posted_at=now.isoformat(timespec="seconds"))
        _save_outbox(slug, entries)  # save the ID before touching the queue
    rows = queue.read(slug)
    row = next((r for r in rows if r["id"] == row["id"]), None)
    if row is None:
        raise registry.ChannelError("A YouTube outbox row is missing from the queue.")
    if row.get("video_id") and row["video_id"] != entry["video_id"]:
        raise registry.ChannelError("The queue and upload have different video IDs.")
    row.update(status="posted", video_id=entry["video_id"], posted_at=entry.get("posted_at") or now.isoformat(timespec="seconds"),
               url="https://www.youtube.com/shorts/" + entry["video_id"])
    queue.write(slug, rows)
    entry["state"] = "done"
    _save_outbox(slug, entries)
    return {k: row[k] for k in ("id", "video_id", "url")}


def upload(slug, *, dry_run=False, limit=3, opener=None, now=None, sleep=None, stop=None) -> dict:
    channel = registry.load(slug)
    registry.require_running(slug)
    registry._integer(limit, "limit", 1)
    clock, now = now, queue._now(now)
    result = {"uploaded": 0, "posted": [], "uploads": [], "blocked": {}, "stopped": None, "dry_run": dry_run}
    if channel["publish"]["youtube"] == "off":
        result["stopped"] = "YouTube publishing is off."
        return result
    with youtube.lock():
        rows, entries = queue.read(slug), _outbox(slug)
        saved, by_id = {r["id"]: r for r in entries}, {r["id"]: r for r in rows}
        for entry in entries:
            row = by_id.get(entry["id"])
            if row is None:
                raise registry.ChannelError("A YouTube outbox row is missing from the queue.")
            if entry.get("video_id") and not dry_run and (entry["state"] != "done" or not row.get("video_id")):
                result["posted"].append(_finish(slug, rows, row, entries, entry, now))
        client = None
        for row in sorted(rows, key=lambda r: (r["id"] not in saved, datetime.fromisoformat(r["slot"]))):
            if len(result["uploads"] if dry_run else result["posted"]) >= limit:
                break
            if stop and stop():
                result["stopped"] = "YouTube work stopped."
                break
            registry.require_running(slug)
            now = queue._now(clock)
            row = next((r for r in queue.read(slug) if r["id"] == row["id"]), None)
            if row is None:
                continue
            entry = saved.get(row["id"])
            if row["status"] != "kit" or row.get("video_id") or (entry and entry.get("video_id")):
                continue
            if entry and entry["state"] == "done":
                raise registry.ChannelError("A finished YouTube outbox row needs its video ID.")
            slot = datetime.fromisoformat(row["slot"])
            if not entry and not now <= slot <= now + timedelta(hours=36):
                continue
            checked = gate.check(Path(row["project"]), row["clip"], channel, now=now)
            if not checked["publishable"]:
                result["blocked"][row["id"]] = checked["blockers"]
                continue
            folder = Path(entry["kit"] if entry else row["kit"])
            if kit._stale(Path(row["project"]) / row["clip"], folder):
                result["blocked"][row["id"]] = ["The kit is older than the clip. Run zing channels kit."]
                continue
            path = folder / "video.mp4"
            stat = path.stat()
            if stat.st_size <= 0:
                raise registry.ChannelError("The kit video is empty.")
            metadata = entry.get("metadata") if entry else None
            metadata = metadata or _metadata({**row, "kit": str(folder)}, channel, now)
            if dry_run:
                result["uploads"].append({"title": metadata["snippet"]["title"], "privacy": metadata["status"]["privacyStatus"],
                                           "publishAt": metadata["status"].get("publishAt"), "file": str(path), "size": stat.st_size})
            else:
                if not channel.get("youtube"):
                    raise registry.ChannelError(youtube.RECONNECT)
                client = client or youtube.Client(slug, opener=opener, now=clock, sleep=sleep, stop=stop)
                if client.token.get("channel_id", channel["youtube"]["channel_id"]) != channel["youtube"]["channel_id"]:
                    raise registry.ChannelError(youtube.RECONNECT)
                project = client.token["project_id"]
                result["stopped"] = _quota(channel, project, now)
                if result["stopped"]:
                    break
                if entry and entry.get("channel_id", channel["youtube"]["channel_id"]) != channel["youtube"]["channel_id"]:
                    raise registry.ChannelError("Reconnect the YouTube channel that started this upload.")
                try:
                    if entry:
                        try:
                            video = _transfer(client, entry, resume=True)
                        except youtube.Error as exc:
                            if exc.status not in (404, 410):
                                raise
                            entries.remove(entry)
                            _save_outbox(slug, entries)
                            saved.pop(row["id"], None)
                            entry = None
                            metadata = _metadata({**row, "kit": str(folder)}, channel, now)
                    if not entry:
                        client.checkpoint()
                        current = next((r for r in queue.read(slug) if r["id"] == row["id"]), None)
                        if current is None or current["status"] != "kit" or current.get("video_id"):
                            continue
                        result["stopped"] = _quota(channel, project, now, reserve=True)
                        if result["stopped"]:
                            break
                        response = client.request("POST", UPLOAD, json.dumps(metadata).encode("utf-8"), {
                            "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Length": str(stat.st_size),
                            "X-Upload-Content-Type": "video/mp4"})
                        youtube.checked(response)
                        session = _session(response[1].get("location"))
                        entry = {"id": row["id"], "kit": str(folder.resolve()), "state": "uploading", "session_uri": session,
                                 "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "metadata": metadata,
                                 "channel_id": channel["youtube"]["channel_id"], "started_at": now.isoformat(timespec="seconds")}
                        entries.append(entry)
                        _save_outbox(slug, entries)
                        video = _transfer(client, entry, resume=False)
                    result["posted"].append(_finish(slug, rows, row, entries, entry, queue._now(clock), video))
                except youtube.Error as exc:
                    if exc.reason:
                        _quota(channel, project, now, reason=exc.reason)
                    result["stopped"] = str(exc)
                    break
            if len(result["uploads"] if dry_run else result["posted"]) >= limit:
                break
    result["uploaded"] = len(result["posted"])
    return result


def analytics_due(slug, now=None):
    last = _read(registry.directory(slug) / "youtube-analytics.json", {}).get("last_run")
    return not last or _day(datetime.fromisoformat(last)) != _day(queue._now(now))


def analytics(slug, *, opener=None, now=None, sleep=None, stop=None) -> dict:
    channel = registry.load(slug)
    registry.require_running(slug)
    if not channel.get("youtube"):
        raise registry.ChannelError(youtube.RECONNECT)
    now = queue._now(now)
    at = now.isoformat(timespec="seconds")
    with youtube.lock():
        posted = [r for r in queue.read(slug) if r["status"] == "posted" and (r.get("video_id") or outcomes.video_id(r.get("url")))]
        ids = list(dict.fromkeys(r.get("video_id") or outcomes.video_id(r.get("url")) for r in posted))
        marker = registry.directory(slug) / "youtube-analytics.json"
        _write(marker, {"last_run": at, "complete": False})
        measured = {}
        if ids:
            client = youtube.Client(slug, opener=opener, now=now, sleep=sleep, stop=stop)
            if client.token.get("channel_id", channel["youtube"]["channel_id"]) != channel["youtube"]["channel_id"]:
                raise registry.ChannelError(youtube.RECONNECT)
            start = min(datetime.fromisoformat(r.get("posted_at") or r["slot"]).date() for r in posted)
            for offset in range(0, len(ids), 200):
                batch = ids[offset:offset + 200]
                query = {"ids": "channel==MINE", "dimensions": "video", "filters": "video==" + ",".join(batch),
                         "metrics": ",".join(METRICS), "startDate": start.isoformat(), "endDate": now.date().isoformat()}
                data = youtube.checked(client.request("GET", REPORTS + "?" + urlencode(query)))
                headers = [h.get("name") for h in data.get("columnHeaders", [])]
                for values in data.get("rows", []):
                    record = dict(zip(headers, values))
                    if record.get("video") in batch:
                        measured[record["video"]] = {field: record.get(metric) if number(record.get(metric)) else None
                                                     for metric, field in METRICS.items()}
        rows = outcomes.read(slug)
        saved = {r["id"]: r for r in rows}
        for row in posted:
            ident = row.get("video_id") or outcomes.video_id(row.get("url"))
            d = Path(row["project"]) / row["clip"]
            post = _read(d / "post.json", {})
            old = saved.get(row["id"])
            if old is None:
                old = {"id": row["id"], **{f"views_{basis}": None for basis in ("1h", "24h", "7d")}}
                rows.append(old)
            arms = row.get("arms") or _read(d / "arms.json", old.get("arms", {}))
            old.update(schema_version=1, channel=slug, platform="youtube", video_id=ident, url=row.get("url"),
                       posted_at=row.get("posted_at") or row["slot"], arms=arms,
                       propensity=arms.get("title_propensity") or post.get("title_propensity") or old.get("propensity"),
                       policy=arms.get("title_policy") or post.get("title_policy") or old.get("policy"), updated_at=at,
                       **{field: measured.get(ident, {}).get(field) if measured.get(ident, {}).get(field) is not None
                          else old.get(field) for field in METRICS.values()})
        outcomes.write(slug, outcomes.rewards(rows))
        _write(marker, {"last_run": at, "complete": True})
    return {"videos": len(ids), "matched": len(measured)}
