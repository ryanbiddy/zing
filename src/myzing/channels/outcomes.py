"""Match public uploads to local clips and measure them at the same ages."""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from statistics import median
from urllib.parse import parse_qs, urlsplit

from myzing.factory.pipeline import _read
from myzing.playbook import feeds, watch
from myzing.playbook.common import append_jsonl, number, utc_now

from . import bandit, queue, registry


def read(slug: str) -> list[dict]:
    path = registry.directory(slug) / "outcomes.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def write(slug: str, rows: list[dict]) -> None:
    path = registry.directory(slug) / "outcomes.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def video_id(url: str | None) -> str | None:
    try:
        parts = urlsplit(url or "")
        path = parts.path.strip("/").split("/")
        ident = None
        if parts.hostname in ("youtu.be", "www.youtu.be"):
            ident = path[0]
        elif parts.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            if path[0] == "watch":
                ident = parse_qs(parts.query).get("v", [None])[0]
            elif len(path) == 2 and path[0] in ("shorts", "embed", "live"):
                ident = path[1]
        return ident if ident and re.fullmatch(r"[A-Za-z0-9_-]{11}", ident) else None
    except ValueError:
        return None


def _title(text: str) -> str:
    return " ".join(text.split()).casefold()


def _match(rows: list[dict], videos: list[dict]) -> int:
    matched, used = set(), {r.get("video_id") or video_id(r.get("url")) for r in rows if r["status"] == "posted"}
    by_id = {v["id"]: v for v in videos}

    def posted(row, video):
        ident = video["id"]
        row.update(status="posted", video_id=ident, posted_at=video["published"],
                   url=f"https://www.youtube.com/shorts/{ident}" if video["short"] else f"https://www.youtube.com/watch?v={ident}")
        used.add(ident)
        matched.add(row["id"])

    for row in rows:
        ident = row.get("video_id") or video_id(row.get("url"))
        if row["status"] == "posted" and ident in by_id:
            posted(row, by_id[ident])
    waiting = [r for r in rows if r["status"] in ("kit", "queued") and _title(r.get("title", ""))]
    for row in waiting:
        title = _title(row["title"])
        matches = [v for v in videos if v["id"] not in used and _title(v["title"]) == title]
        if len(matches) == 1 and sum(_title(r["title"]) == title for r in waiting) == 1:
            posted(row, matches[0])
    return len(matched)


def rewards(rows: list[dict]) -> list[dict]:
    ordered = sorted(rows, key=lambda r: bandit.when(r, "posted_at"))
    medians, counts = {}, {}
    for basis in ("24h", "7d"):
        values = [r[f"views_{basis}"] for r in ordered if number(r.get(f"views_{basis}"))][-30:]
        medians[basis], counts[basis] = median(values) if values else None, len(values)
    for row in rows:
        basis = "7d" if number(row.get("views_7d")) else "24h" if number(row.get("views_24h")) else None
        row.update(channel_median_24h=medians["24h"], channel_median_7d=medians["7d"], reward_basis=basis,
                   reward=math.log2((row[f"views_{basis}"] + 50) / (medians[basis] + 50))
                   if basis and counts[basis] >= 5 else None, masked=bool(row.get("masked", False)))
    before, latest = ordered[-35:-5], ordered[-5:]
    if len(before) == 30 and all(number(r.get("views_24h")) for r in before + latest):
        typical = median(r["views_24h"] for r in before)
        if all(r["views_24h"] < .2 * typical for r in latest):
            for row in latest:
                row["masked"] = True
    return rows


def track(slug: str, *, fetch=None, now=None) -> dict:
    registry.require_running(slug)
    channel = registry.load(slug)
    handle = channel["handles"].get("youtube", "").strip()
    if not handle or not (handle.startswith("@") or re.fullmatch(feeds.ID, handle)):
        raise registry.ChannelError("Set handles.youtube to an @handle or UC channel ID before tracking.")
    root, at = registry.directory(slug), queue._now(now).isoformat(timespec="seconds")
    ident = feeds.resolve(handle, fetch, root=root)
    registry.require_running(slug)
    videos = feeds.feed(ident, fetch, root=root)
    append_jsonl(root / "snapshots.jsonl", [{"at": at, "channel": slug,
                 **{key: v[key] for key in ("channel_id", "id", "title", "published", "views", "short")}} for v in videos])
    rows = queue.read(slug)
    matched = _match(rows, videos)
    queue.write(slug, rows)
    velocity = {v["id"]: v for v in watch.velocity(root)["videos"] if v["channel_id"] == ident}
    saved = {r["id"]: r for r in read(slug)}
    results = []
    for row in rows:
        if row["status"] != "posted":
            continue
        old = saved.get(row["id"], {})
        d = Path(row["project"]) / row["clip"]
        post = _read(d / "post.json", {})
        arms = row.get("arms") or _read(d / "arms.json", old.get("arms", {}))
        vid = row.get("video_id") or video_id(row.get("url"))
        measured = velocity.get(vid, {})
        results.append({**old, "schema_version": 1, "id": row["id"], "channel": slug, "platform": "youtube",
                        "video_id": vid, "url": row.get("url"),
                        "posted_at": measured.get("published") or row.get("posted_at") or row["slot"],
                        "arms": arms, "propensity": arms.get("title_propensity") or post.get("title_propensity") or old.get("propensity"),
                        "policy": arms.get("title_policy") or post.get("title_policy") or old.get("policy"),
                        **{f"views_{basis}": measured.get("views", {}).get(basis, old.get(f"views_{basis}"))
                           for basis in ("1h", "24h", "7d")},
                        "avg_view_pct": old.get("avg_view_pct"), "subs": old.get("subs"), "updated_at": at})
    rewards(results)
    write(slug, results)
    masked = [r["id"] for r in results if r["masked"]]
    return {"entries": len(videos), "matched": matched, "posted": len(results), "masked": masked,
            "summary": ["A reach drop was detected. Masked clips do not teach the bandit."] if masked else []}


def _number(value):
    try:
        result = float((value or "").strip().replace(",", "").removesuffix("%"))
        return result if number(result) else None
    except ValueError:
        return None


def metrics(slug: str, path: Path) -> dict:
    registry.load(slug)
    rows = read(slug)
    by_id = {r["video_id"]: r for r in rows if r.get("video_id")}
    matched, unmatched, at = 0, 0, utc_now()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        table = csv.DictReader(stream)
        headers = {_title(h): h for h in table.fieldnames or []}
        content = headers.get("content") or headers.get("video")
        fields = {"studio_views": "views", "avg_view_pct": "average percentage viewed", "subs": "subscribers"}
        if not content or any(h not in headers for h in fields.values()):
            raise registry.ChannelError("CSV needs Content or Video, Views, Average percentage viewed and Subscribers columns.")
        for entry in table:
            row = by_id.get((entry.get(content) or "").strip())
            if row is None:
                unmatched += 1
                continue
            for field, header in fields.items():
                value = _number(entry.get(headers[header]))
                if value is not None and (field == "subs" or value >= 0):
                    row[field] = value
            row["updated_at"] = at
            matched += 1
    write(slug, rows)
    return {"matched": matched, "unmatched": unmatched}
