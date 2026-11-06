"""Find recent platform news from public feeds and channel uploads."""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from myzing.factory import network, visuals
from myzing.playbook import feeds
from myzing.playbook.common import append_jsonl

DEFAULT_FEEDS = ("https://blog.youtube/rss/", "https://about.fb.com/news/category/instagram/feed/")
DEFAULT_WATCH = ("UCGg-UqjRgzhYDPJMr-9HXCg", "UCkRfArvrzheW2E7b6SVT7vQ")   # Creator Insider, YouTube Creators; IDs skip the channel page
FEED_CAP = 4 * 1024 ** 2
NS = {"atom": "http://www.w3.org/2005/Atom", "content": "http://purl.org/rss/1.0/modules/content/"}
GROUPS = (
    ("money", 3, ("monetiz", "partner program", "ypp", "revenue", "rpm", "payout", "paid", "earn", "fund",
                  "brand deal", "sponsor", "shopping", "affiliate", "subscription", "super thanks", "tips")),
    ("reach", 3, ("algorithm", "recommend", "reach", "discovery", "for you", "explore", "ranking",
                  "distribution", "trending", "views")),
    ("format", 2, ("shorts", "reels", "live", "upload", "thumbnail", "title", "test & compare", "a/b",
                   "hype", "collab", "length")),
    ("policy", 2, ("policy", "eligib", "guideline", "copyright", "reused content", "ai label", "disclosure",
                   "inauthentic", "demonetiz", "strike")),
    ("creator", 1, ("creator", "channel", "analytics", "studio", "audience")),
)
BOUNDARIES = {"ypp", "rpm", "a/b", "tips", "paid", "earn", "live", "views", "title"}
OFF_TOPIC = ("earnings call", "investor", "quarterly results", "emmy", "award", "festival", "football", "soccer")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag.rsplit(":", 1)[-1] in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        self.handle_starttag(tag, ())


def _plain(value: str) -> str:
    parser = _Text()
    parser.feed(value)
    parser.close()
    return " ".join(unescape("".join(parser.parts)).split())


def _value(node, path: str) -> str:
    child = node.find(path, NS)
    if child is None:
        return ""
    return ((child.text or "") + "".join(ET.tostring(part, encoding="unicode") for part in child)).strip()


def _published(value: str) -> datetime | None:
    try:
        try:
            stamp = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            stamp = datetime.fromisoformat(value)
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def _score(text: str) -> tuple[int, list[str]]:
    text = text.casefold()
    score, why = 0, []
    for name, weight, words in GROUPS:
        if any(re.search(rf"\b{re.escape(word)}\b", text) if word in BOUNDARIES else word in text for word in words):
            score += weight
            if name != "creator":
                why.append(name)
    return score - (3 if any(word in text for word in OFF_TOPIC) else 0), why


def _bounded(body: bytes | str) -> bytes | str:
    if len(body.encode("utf-8") if isinstance(body, str) else body) > FEED_CAP:
        raise ValueError("news feed exceeds 4 MB")
    return body


def _fetch(url: str, root: Path) -> bytes:
    net = network.Network(root)
    net.check("news feed")
    net.project = root / "brief"  # keep the request ledger with the brief
    with net.open(url, "news feed", timeout=20, validate=visuals._public_url) as response:
        return _bounded(response.read(FEED_CAP + 1))


def _feed(url: str, root: Path, fetch):
    tree = ET.fromstring(_bounded(fetch(url) if fetch else _fetch(url, root)))
    channel = tree.find("channel") if tree.tag == "rss" else None
    if channel is not None:
        for item in channel.findall("item"):
            yield {"title": _value(item, "title"), "url": _value(item, "link"),
                   "published": _value(item, "pubDate"), "source": _value(channel, "title") or url,
                   "summary": _value(item, "description") or _value(item, "content:encoded")}
    elif tree.tag == "{" + NS["atom"] + "}feed":
        for item in tree.findall("atom:entry", NS):
            links = [link for link in item.findall("atom:link", NS) if link.get("href")]
            link = next((link for link in links if link.get("rel") == "alternate"), links[0] if links else None)
            yield {"title": _value(item, "atom:title"), "url": link.get("href", "") if link is not None else "",
                   "published": _value(item, "atom:published") or _value(item, "atom:updated"),
                   "source": _value(tree, "atom:title") or url,
                   "summary": _value(item, "atom:summary") or _value(item, "atom:content")}
    else:
        raise ValueError("response is not an RSS or Atom feed")


def _uploads(handle: str, root: Path, fetch):
    root = root / "brief"

    def request(url):
        body = _bounded(fetch(url) if fetch else feeds.request(url, root=root))
        if url.startswith("https://www.youtube.com/feeds/"):
            tree = ET.fromstring(body)
            for entry in tree.findall("atom:entry", NS):
                if _published(_value(entry, "atom:published")) is None:
                    tree.remove(entry)  # one bad date must not discard the other uploads
            body = ET.tostring(tree, encoding="unicode")
        return body

    ident = feeds.resolve(handle, request, root=root)
    for row in feeds.feed(ident, request, root=root):
        path = f"shorts/{row['id']}" if row.get("short") else f"watch?v={row['id']}"
        yield {"title": row["title"], "url": "https://www.youtube.com/" + path,
               "published": row["published"], "source": row["channel_title"], "summary": ""}


def collect(series: dict, root: Path, *, fetch=None, now: datetime | None = None, stop=None) -> list[dict]:
    if not isinstance(series, dict) or series.get("kind") != "news":
        raise ValueError("series must be a news series")
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    urls, watch = series.get("feeds") or (), series.get("watch") or ()
    if not urls and not watch:
        urls, watch = DEFAULT_FEEDS, DEFAULT_WATCH
    rows, seen = [], set()
    for source, reader in [(url, _feed) for url in urls] + [(handle, _uploads) for handle in watch]:
        if stop and stop():
            break
        try:
            for item in reader(source, root, fetch):
                stamp = _published(item["published"])
                if stamp is None or not now - timedelta(days=10) <= stamp <= now + timedelta(hours=1):
                    continue
                url = item["url"].strip()
                parts = urlsplit(url)
                if parts.scheme != "https" or not parts.hostname or url in seen:
                    continue
                seen.add(url)
                title, summary = _plain(item["title"]), _plain(item["summary"])[:600]
                score, why = _score(title + " " + summary)
                if score >= 4:
                    rows.append({"id": "news-" + hashlib.sha256(url.encode()).hexdigest()[:16],
                                 "series": series["id"], "kind": "news", "title": title, "url": url,
                                 "published": stamp.isoformat(), "source": item["source"], "summary": summary,
                                 "score": score, "why": why})
        except Exception as exc:
            append_jsonl(root / "brief" / "news-errors.jsonl", [
                {"at": now.isoformat(), "source": source, "error": str(exc) or type(exc).__name__}])
    return sorted(rows, key=lambda row: (row["score"], row["published"]), reverse=True)
