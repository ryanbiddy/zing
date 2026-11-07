"""Find episodes and start projects from local media with known rights."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from myzing import uoink_bridge
from myzing.factory import batch, network, pipeline, visuals
from myzing.factory.tools import FactoryError, ffprobe
from myzing.playbook import feeds

from . import brief, registry

CAP = 4 * 1024 ** 3
FEED_CAP = 8 * 1024 ** 2


def read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("rows must be objects")
        return rows
    except ValueError as exc:
        raise registry.ChannelError(f"{path.name} could not be read. {exc}") from exc


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(path)


def _published(value: str) -> str:
    if not value:
        return ""
    try:
        stamp = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        try:
            stamp = datetime.fromisoformat(value)
        except ValueError:
            return ""
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).isoformat()


def _channel(value: str) -> str:
    if "://" not in value:
        return value
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or parts.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        raise registry.ChannelError("YouTube sources need a channel handle, UC ID or channel URL")
    path = parts.path.strip("/").split("/")
    if path[0].startswith("@"):
        return path[0]
    if len(path) >= 2 and path[0] == "channel":
        return path[1]
    raise registry.ChannelError("YouTube sources need a channel handle or UC ID")


def _video_id(value: str) -> str | None:
    parts = urlsplit(value)
    if parts.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com") and parts.path == "/watch":
        return (parse_qs(parts.query).get("v") or [None])[0]
    if parts.hostname == "youtu.be":
        return parts.path.strip("/")
    return None


def _kept(query: str, search, resolve, stop=None):
    if stop and stop():
        return
    result = search(query)
    if not result.get("ok"):
        return
    for item in result.get("results", []):
        if stop and stop():
            return
        result = resolve(item["item_ref"])
        data = result.get("data", {}) if result.get("ok") else {}
        media = data.get("media") or {}
        path = Path(media["path"]) if media.get("path") else None
        if data.get("state") == "available" and path and path.is_absolute() and path.is_file():
            yield {"id": item["item_ref"], "title": item.get("title") or path.stem,
                   "url": data.get("source_url") or item.get("source_url") or "", "published": "", "media": str(path)}


def _fetch(url: str, root: Path) -> bytes:
    with network.Network(root).open(url, "podcast feed", timeout=20, validate=visuals._public_url) as response:
        body = response.read(FEED_CAP + 1)
    if len(body) > FEED_CAP:
        raise registry.ChannelError("podcast feed exceeds 8 MB")
    return body


def download(url: str, path: Path, *, root: Path, cap: int = CAP, stop=None) -> Path | None:
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        with network.Network(root).open(url, "podcast enclosure", validate=visuals._public_url) as response:
            length = response.headers.get("Content-Length", "")
            if length.isdigit() and int(length) > cap:
                raise registry.ChannelError("podcast enclosure exceeds 4 GB")
            size = 0
            with tmp.open("wb") as stream:
                while chunk := response.read(1024 ** 2):
                    if stop and stop():
                        return None
                    size += len(chunk)
                    if size > cap:
                        raise registry.ChannelError("podcast enclosure exceeds 4 GB")
                    stream.write(chunk)
            if length.isdigit() and size != int(length):
                raise registry.ChannelError("podcast enclosure is incomplete")
        tmp.replace(path)
        return path
    finally:
        tmp.unlink(missing_ok=True)


def _items(src: dict, root: Path, fetch, search, resolve, stop=None):
    kind = src["kind"]
    if kind in ("folder", "own", "recordings"):
        folder = Path(src["url"]).expanduser().resolve()
        if not folder.is_dir():
            raise registry.ChannelError(f"source folder not found at {folder}")
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in batch.MEDIA:
                media = path.resolve()
                modified = datetime.fromtimestamp(media.stat().st_mtime, timezone.utc)
                if kind == "recordings" and src.get("since") and modified.date().isoformat() < src["since"]:
                    continue
                info = batch._settings(media, {})
                yield {"id": hashlib.sha256(str(media).encode()).hexdigest(), "title": info["name"] or media.stem,
                       "url": info["url"] or "", "published": info["date"] or modified.isoformat(),
                       "media": str(media), "own": kind in ("own", "recordings")}
    elif kind == "youtube":
        ident = feeds.resolve(_channel(src["url"]), fetch, root=root)
        if stop and stop():
            return
        for row in feeds.feed(ident, fetch, root=root, watch_only=True):
            yield {key: row[key] for key in ("id", "title", "published")} | {"url": f"https://www.youtube.com/watch?v={row['id']}"}
    elif kind == "podcast":
        tree = ET.fromstring(fetch(src["url"]) if fetch else _fetch(src["url"], root))
        for item in tree.findall(".//item"):
            enclosures = [e for e in item.findall("enclosure") if e.get("type", "").lower().startswith(("video/", "audio/")) and e.get("url")]
            if not enclosures:
                continue
            enclosure = next((e for e in enclosures if e.get("type", "").lower().startswith("video/")), enclosures[0])
            url, kind = enclosure.get("url"), enclosure.get("type").lower()
            yield {"id": item.findtext("guid") or url, "title": item.findtext("title") or "Episode",
                   "url": item.findtext("link") or url, "published": _published(item.findtext("pubDate", "")),
                   "enclosure": url, "media_type": kind, "audio_only": kind.startswith("audio/")}
    else:
        yield from _kept(src["url"], search, resolve, stop)


def _stem(src: dict, item: dict) -> str:
    digest = hashlib.sha256(item["id"].encode()).hexdigest()[:16]
    title = pipeline.show_slug(item["title"]) or "episode"
    return f"{src['id']}-{title[:40]}-{digest}"


def _media(src: dict, item: dict, root: Path, search, resolve, downloader, stop) -> None:
    media = Path(item["media"]) if item.get("media") else None
    if media and media.is_file():
        return
    item.pop("media", None)
    if src["kind"] == "youtube":
        ident = item["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", ident):
            raise registry.ChannelError("invalid YouTube video ID")
        media = next((p for p in sorted((root / "inbox").iterdir())
                      if p.stem == ident and p.suffix.lower() in batch.MEDIA and p.is_file()), None)
        if media:
            item["media"] = str(media.resolve())
            return
        for query in (item["url"], ident):
            for kept in _kept(query, search, resolve, stop):
                if kept["url"] == item["url"] or _video_id(kept["url"]) == ident:
                    item["media"] = kept["media"]
                    return
    elif src["kind"] == "podcast":
        ext = Path(urlsplit(item["enclosure"]).path).suffix.lower()
        allowed = {".mp3", ".m4a", ".ogg", ".wav", ".aac", ".flac", ".opus"} if item["audio_only"] else batch.MEDIA
        if ext not in allowed:
            ext = ".audio" if item["audio_only"] else ".mp4"
        path = root / "inbox" / (_stem(src, item) + ext)
        if not path.is_file():
            downloader(item["enclosure"], path, root=root, cap=CAP, stop=stop)
        if path.is_file() and path.stat().st_size <= CAP:
            item["media"] = str(path.resolve())


def _duration(path: Path) -> float:
    out = subprocess.run([ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=30).stdout
    seconds = float(out.strip())
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("invalid duration")
    return seconds


def _recording(slug: str, item: dict, project: Path, settings: dict, now: datetime, stop=None, *, require_match=False) -> bool:
    inbox = registry.directory(slug) / "inbox"
    stage = (inbox / ("." + project.name)).resolve()
    if stage.parent != inbox.resolve():
        raise registry.ChannelError("recording must stay inside the channel inbox")
    media = Path(item["media"])
    settings = {**settings, "moments": 0}
    stat = media.stat()
    stamp = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if stage.exists() and pipeline._read(stage / "take.json") != stamp:
        shutil.rmtree(stage)                # the file changed since the last try; its cached transcript is stale
    pipeline.init(stage, media, **settings)
    pipeline._write(stage / "take.json", stamp)
    segments = pipeline._transcript(stage, media, lambda m: None, settings.get("vocab"))
    if registry.paused(slug) or stop and stop():
        return False
    text = " ".join(s["text"] for s in segments)
    if not text.strip():
        raise registry.ChannelError("recording has no spoken words")
    words = pipeline._read(stage / "words.json") or segments
    start, end = max(0, words[0]["s"]), words[-1]["e"]        # add_clip checks the range once
    matched = brief.match(slug, text, now)
    if not matched and require_match:
        shutil.rmtree(stage)
        item["skip"] = {"reason": "matched no brief item", **stamp}
        item["state"] = "skipped, matched no brief item"
        return False
    take, hook = {"series": None}, " ".join(text.split()[:12])
    if matched:
        day, chosen = matched
        take = {"brief": day, "item": chosen["n"], "series": chosen["series"]}
        hook = chosen["hook"]
        settings["news"] = {"peg": chosen["receipt"], "links": [chosen["facts"]["url"]]}
        pipeline.init(stage, media, **settings)
    pipeline._write(stage / "moments.json", {"moments": [], "bench": []})
    pipeline.add_clip(stage, start, end, hook=hook)
    moments = pipeline.load_moments(stage)
    moments["moments"][0].update(series=take["series"], whole=True)   # snapping keeps the take's last word
    pipeline._write(stage / "moments.json", moments)
    pipeline._write(stage / "recording.json", take)
    if registry.paused(slug) or stop and stop():
        return False
    project.parent.mkdir(parents=True, exist_ok=True)   # a new channel has no projects folder yet
    stage.replace(project)
    brief.recorded(slug, project, take)
    item.update(take)
    return True


def _start(slug: str, src: dict, item: dict, root: Path, now: datetime, stop=None) -> bool:
    project = batch._project(root / "projects", Path(_stem(src, item) + ".mp4")).resolve()
    if project.parent != (root / "projects").resolve():
        raise registry.ChannelError("project must stay inside the channel projects folder")
    if (project / "factory.json").is_file():
        cfg = pipeline._read(project / "factory.json")
        saved = pipeline._read(project / "source.json", {})
        url = item["url"] if item["url"].startswith(("http://", "https://")) else ""
        if cfg.get("channel") != slug or cfg.get("source") != src["id"] or saved.get("url") != url:
            raise registry.ChannelError(f"{project.name} belongs to another episode")
        if src["kind"] == "recordings":
            take = pipeline._read(project / "recording.json", {})
            brief.recorded(slug, project, take)
            item.update(take)
        item.update(project=str(project), started_at=cfg["created"])
        return False
    media = Path(item["media"])
    if src["kind"] == "recordings":
        stat = media.stat()
        stamp = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        skip = item.get("skip", {})
        if skip and all(skip.get(key) == value for key, value in stamp.items()):
            item["state"] = f"skipped, {skip['reason']}"
            return False
        item.pop("skip", None)
        if stat.st_mtime > now.timestamp() - src.get("settle_seconds", 120):
            item["state"] = "found, still syncing"
            return False
        try:
            seconds = _duration(media)
            limit = src.get("max_seconds", 180)
            reason = f"longer than {limit:g} seconds" if seconds > limit else None
        except (FactoryError, OSError, ValueError, subprocess.SubprocessError):
            reason = "could not read the video"
        if reason:
            item["skip"] = {"reason": reason, **stamp}
            item["state"] = f"skipped, {reason}"
            return False
    settings = registry.project_settings(slug, src["id"], **batch._settings(media, {
        "name": item["title"], "url": item["url"], "date": item["published"][:10]}))
    if settings["rights"] == "unknown":
        item["state"] = "found, needs rights"
        return False
    if src["kind"] == "recordings":
        if not _recording(slug, item, project, settings, now, stop, require_match=src.get("require_match", False)):
            return False
    else:
        pipeline.init(project, media, **settings)
    item.update(project=str(project), started_at=now.isoformat())
    return True


def run(slug: str, *, fetch=None, downloader=None, search=None, resolve=None, now: datetime | None = None, stop=None) -> dict:
    channel = registry.load(slug)
    registry.require_running(slug)
    root = registry.directory(slug)
    (root / "inbox").mkdir(exist_ok=True)
    now = now or datetime.now(timezone.utc)
    search, resolve = search or uoink_bridge.search_references, resolve or uoink_bridge.resolve_kept_media
    result = {"found": 0, "started": 0, "errors": []}

    def stopped():
        return registry.paused(slug) or bool(stop and stop())

    for src in channel["sources"]:
        if stopped():
            break
        path = root / "sources" / f"{src['id']}.jsonl"
        rows = read(path)
        seen = {row["id"]: row for row in rows}
        changed = False
        known = registry.effective_rights(src, now) != "unknown"
        try:
            for item in _items(src, root, fetch, search, resolve, stopped):
                if stopped():
                    break
                if item["id"] not in seen:
                    rows.append({**item, "found_at": now.isoformat(), "state": "found" if known else "found, needs rights"})
                    seen[item["id"]] = rows[-1]
                    changed = True
                    result["found"] += 1
                elif src["kind"] == "uoink" and not seen[item["id"]].get("project") and seen[item["id"]].get("media") != item["media"]:
                    seen[item["id"]]["media"] = item["media"]
                    changed = True
        except Exception as exc:
            result["errors"].append(f"{src['id']} {exc}")
        if changed or not path.exists():
            _write(path, rows)
        for item in rows:
            if stopped():
                break
            before = dict(item)
            item.pop("error", None)
            item["state"] = "found" if known else "found, needs rights"
            if item.get("audio_only"):
                item["note"] = "audio only, needs a video"
            try:
                if known:
                    _media(src, item, root, search, resolve, downloader or download, stopped)
                if known and item.get("media") and Path(item["media"]).is_file() and not item.get("audio_only"):
                    item["state"] = "ready"
                    if not item.get("project") and not stopped():
                        result["started"] += _start(slug, src, item, root, now, stopped)
            except Exception as exc:
                item["error"] = str(exc) or type(exc).__name__
                result["errors"].append(f"{src['id']} {item['id']} {item['error']}")
            if item != before:
                _write(path, rows)
    return result
