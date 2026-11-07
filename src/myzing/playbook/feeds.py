"""Public channel metadata, with no cookies, keys or media requests."""
from __future__ import annotations

import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

from .common import append_jsonl, parse_time, read_json, safe_name, utc_now, write_json

ID = r"UC[A-Za-z0-9_-]{22}"
NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
_lock = threading.Lock()
_last_request = None


def channel(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("a channel handle or ID is required")
    if value.startswith("UC"):
        if not re.fullmatch(ID, value):
            raise ValueError("invalid YouTube channel ID")
    elif not re.fullmatch(r"@?[\w.-]+", value):
        raise ValueError("invalid YouTube handle")
    return value.removeprefix("@")


def _url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "www.youtube.com" or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("feed requests require https://www.youtube.com")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url: str, *, root: Path = Path(".")) -> str:
    global _last_request
    _url(url)
    opener = urllib.request.build_opener(_NoRedirect())
    for _ in range(6):
        _url(url)
        with _lock:
            if _last_request is not None:
                time.sleep(max(0, 1.5 - (time.monotonic() - _last_request)))
            _last_request = time.monotonic()
            at, status, redirect = utc_now(), "error", None
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Zing)"})
                with opener.open(req, timeout=20) as response:
                    status = response.status
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                status = exc.code
                exc.close()
                if exc.code not in (301, 302, 303, 307, 308) or not exc.headers.get("Location"):
                    raise ValueError(f"YouTube feed request failed with HTTP {exc.code}") from None
                redirect = urllib.parse.urljoin(url, exc.headers["Location"])
            except OSError:
                raise ValueError("YouTube feed request failed") from None
            finally:
                append_jsonl(root / "feeds" / "requests.jsonl", [{"at": at, "url": url, "status": status}])
        url = redirect
    raise ValueError("too many YouTube redirects")


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ident = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and "canonical" in (attrs.get("rel") or "").lower().split():
            match = re.fullmatch(rf"https://www\.youtube\.com/channel/({ID})/?", attrs.get("href") or "")
            if match:
                self.ident = match[1]


def resolve(handle_or_id: str, fetch=None, *, root: Path = Path(".")) -> str:
    handle = channel(handle_or_id)
    if not handle_or_id.startswith("@") and re.fullmatch(ID, handle):
        return handle
    path = root / "feeds" / "ids.json"
    ids = read_json(path) if path.exists() else {}
    if re.fullmatch(ID, ids.get(handle.casefold(), "")):
        return ids[handle.casefold()]
    url = "https://www.youtube.com/@" + urllib.parse.quote(handle)
    page = fetch(url) if fetch else request(url, root=root)
    if isinstance(page, bytes):
        page = page.decode("utf-8")
    parser = _Page()
    parser.feed(page)
    match = re.search(rf'"externalId"\s*:\s*"({ID})"', page)
    ident = parser.ident or (match[1] if match else None)
    if ident is None:
        raise ValueError("channel page has no public channel ID")
    ids[handle.casefold()] = ident
    write_json(path, ids)
    return ident


def feed(channel_id: str, fetch=None, *, root: Path = Path("."), watch_only: bool = False) -> list[dict]:
    if not re.fullmatch(ID, channel_id):
        raise ValueError("invalid YouTube channel ID")
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        tree = ET.fromstring(fetch(url) if fetch else request(url, root=root))
    except ET.ParseError:
        raise ValueError("invalid YouTube feed XML") from None
    if tree.tag != "{" + NS["atom"] + "}feed":
        raise ValueError("response is not a YouTube feed")
    rows = []
    for entry in tree.findall("atom:entry", NS):
        if watch_only:
            links = [urllib.parse.urlsplit(link.get("href", "")) for link in entry.findall("atom:link", NS)]
            if not any(p.path == "/watch" for p in links) or any(p.path.startswith("/shorts/") for p in links):
                continue
        stats = entry.find(".//media:statistics", NS)
        ident, published = entry.findtext("yt:videoId", namespaces=NS), entry.findtext("atom:published", namespaces=NS)
        views = stats.get("views", "") if stats is not None else ""
        if not ident or not published or (not watch_only and not views.isdigit()):
            continue
        try:
            ident, published = safe_name(ident), parse_time(published).isoformat()
            views = int(views) if views.isdigit() else 0
        except ValueError:
            continue
        rows.append({"id": ident, "title": entry.findtext("atom:title", "", NS),
                     "published": published, "views": views,
                     "short": any("/shorts/" in link.get("href", "") for link in entry.findall("atom:link", NS)),
                     "channel_id": channel_id,
                     "channel_title": entry.findtext("atom:author/atom:name", tree.findtext("atom:title", "", NS), NS)})
    return rows
