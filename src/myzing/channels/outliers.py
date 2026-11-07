"""Public uploads that cleared their channel's usual view count."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from myzing.playbook import feeds, titles
from myzing.playbook.common import append_jsonl, parse_time

FLOOR = 10_000


def collect(series: dict, root: Path, *, fetch=None, now=None, stop=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    root = Path(root) / "brief"
    found = []
    for handle in series["watch"]:
        if stop and stop():
            break
        try:
            ident = feeds.resolve(handle, fetch, root=root)
            if stop and stop():
                break
            rows = feeds.feed(ident, fetch, root=root)
            aged = [(row, (now - parse_time(row["published"])).total_seconds() / 86400) for row in rows]
            usual = {}                          # a Short is compared with the channel's Shorts, a video with its videos
            for short in (True, False):
                views = [row["views"] for row, age in aged if age >= 2 and row["short"] is short]
                if len(views) >= 5 and median(views) > 0:
                    usual[short] = median(views)
            candidates = []
            for row, age in aged:
                typical = usual.get(row["short"])
                if typical is None or not 1 <= age <= 21 or row["views"] < max(FLOOR, series["min_multiple"] * typical):
                    continue
                url = f"https://www.youtube.com/shorts/{row['id']}" if row["short"] else f"https://www.youtube.com/watch?v={row['id']}"
                candidates.append({"id": "yt-" + row["id"], "series": series["id"], "kind": "breakdown",
                                   "title": row["title"][:200], "url": url, "channel": handle,
                                   "channel_title": row["channel_title"][:120], "published": row["published"],
                                   "format": "Short" if row["short"] else "video",
                                   "views": row["views"], "median": typical, "multiple": round(row["views"] / typical, 1),
                                   **({"approximate": row["approximate"]} if "approximate" in row else {}),
                                   "age_days": round(age, 1), "features": titles.features(row["title"])})
            found.extend(candidates)
        except Exception as exc:
            append_jsonl(root / "errors.jsonl", [{"at": now.isoformat(), "source": handle,
                                                "error": str(exc) or type(exc).__name__}])
    return sorted(found, key=lambda row: row["multiple"], reverse=True)
