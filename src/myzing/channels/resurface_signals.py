"""Watch public trends and publisher feeds for returning archive subjects."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from myzing.factory import network, visuals
from myzing.playbook.common import read_json, write_json

from . import updates

TRENDS_URL = "https://trends.google.com/trending/rss?geo={geo}"
PAGEVIEWS_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
USER_AGENT = "Zing resurface (https://github.com/ryanbiddy/zing)"
NS = {"ht": "https://trends.google.com/trending/rss"}


def _now(value):
    value = value or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _load(root):
    path = root / "signals.json"
    if not path.exists():
        return {"version": 1, "events": {}, "notified": {}, "history": {}, "http": {}}
    state = read_json(path)
    if (not isinstance(state, dict) or state.get("version") != 1
            or any(not isinstance(state.get(key), dict) for key in ("events", "notified", "history", "http"))):
        raise ValueError("signals.json has an unsupported format")
    return state


class _Client:
    def __init__(self, root, state, now, fetch):
        self.root, self.state, self.now, self.fetch = root, state, now, fetch
        for url, entry in list(state["http"].items()):
            at = updates._published(entry.get("at"))
            retry = updates._published(entry.get("retry_at"))
            if at and now - at > timedelta(days=8) and (retry is None or retry <= now):
                (root / "signals-cache" / hashlib.sha256(url.encode()).hexdigest()).unlink(missing_ok=True)
                del state["http"][url]

    def read(self, url, purpose="trend feed"):
        entry = self.state["http"].setdefault(url, {})
        retry = updates._published(entry.get("retry_at"))
        if retry and self.now < retry:
            raise ValueError(f"feed retry waits until {retry.isoformat()}")
        path = self.root / "signals-cache" / hashlib.sha256(url.encode()).hexdigest()
        headers = {"User-Agent": USER_AGENT}
        if path.is_file():
            headers.update({header: entry[key] for header, key in (
                ("If-None-Match", "etag"), ("If-Modified-Since", "modified")) if entry.get(key)})
        entry["at"] = self.now.isoformat()
        try:
            if self.fetch is not None:
                body, received = updates._bounded(self.fetch(url)), {}
            else:
                net = network.Network(self.root)
                net.check(purpose)
                net.project = self.root
                with net.open(url, purpose, headers=headers, timeout=20, validate=visuals._public_url) as response:
                    body = updates._bounded(response.read(updates.FEED_CAP + 1))
                    received = response.headers
            entry.clear()
            entry.update(at=self.now.isoformat(), etag=received.get("ETag"), modified=received.get("Last-Modified"))
            if entry["etag"] or entry["modified"]:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(body.encode("utf-8") if isinstance(body, str) else body)
                temporary.replace(path)
            return body
        except urllib.error.HTTPError as exc:
            try:
                if exc.code == 304 and len(headers) > 1 and path.is_file():
                    entry.pop("retry_at", None)
                    entry.pop("failures", None)
                    for header, key in (("ETag", "etag"), ("Last-Modified", "modified")):
                        if (exc.headers or {}).get(header):
                            entry[key] = exc.headers[header]
                    with path.open("rb") as stream:
                        return updates._bounded(stream.read(updates.FEED_CAP + 1))
                if exc.code == 429 or 500 <= exc.code < 600:
                    failures = min(7, entry.get("failures", 0) + 1)
                    delay = min(3600, 60 * 2 ** (failures - 1))
                    value = (exc.headers or {}).get("Retry-After", "").strip()
                    stamp = updates._published(value)
                    if value.isascii() and value.isdigit():
                        delay = max(delay, min(int(value), 86400 * 7))
                    elif stamp:
                        delay = max(delay, min((stamp - self.now).total_seconds(), 86400 * 7))
                    entry.update(failures=failures, retry_at=(self.now + timedelta(seconds=delay)).isoformat())
                raise ValueError(f"feed request failed with HTTP {exc.code}") from None
            finally:
                exc.close()


def _traffic(value: str) -> int:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([KMB]?)\+?", value.replace(",", "").strip().upper())
    if not match:
        return 0
    whole, _, fraction = match[1].partition(".")
    scale = {"": 1, "K": 1000, "M": 1000000, "B": 1000000000}[match[2]]
    return int(whole + fraction) * scale // 10 ** len(fraction)


def _trends(body, geo):
    tree = ET.fromstring(updates._bounded(body))
    channel = tree.find("channel") if tree.tag == "rss" else None
    if channel is None:
        raise ValueError("response is not a Trends RSS feed")
    rows = []
    for item in channel.findall("item"):
        entity = updates._plain(item.findtext("title", ""))
        if not entity:
            continue
        headlines = []
        for news in item.findall("ht:news_item", NS):
            title = updates._plain(news.findtext("ht:news_item_title", "", NS))
            if title:
                headlines.append({"title": title, "url": news.findtext("ht:news_item_url", "", NS).strip(),
                                  "source": updates._plain(news.findtext("ht:news_item_source", "", NS))})
        published = updates._published(item.findtext("pubDate", ""))
        rows.append({"entity": entity, "signal": "google_trends",
                     "traffic": _traffic(item.findtext("ht:approx_traffic", "", NS)),
                     "published": published.isoformat() if published else "", "headlines": headlines, "geo": geo})
    return rows


def _names(watch_list):
    if isinstance(watch_list, dict):
        watch_list = [{"entity": name, "aliases": aliases} for name, aliases in watch_list.items()]
    if isinstance(watch_list, str):
        watch_list = [watch_list]
    names = {}
    for item in watch_list:
        name = item if isinstance(item, str) else item.get("entity", item.get("name", ""))
        aliases = () if isinstance(item, str) else item.get("aliases", ())
        aliases = [aliases] if isinstance(aliases, str) else aliases
        name = " ".join(name.split())
        if not name:
            raise ValueError("watch entries need an entity name")
        terms = [unicodedata.normalize("NFKC", term).casefold().strip() for term in (name, *aliases) if term.strip()]
        names[name] = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(term) for term in terms) + r")(?!\w)")
    return names


def _matches(pattern, text):
    return pattern.search(unicodedata.normalize("NFKC", text).casefold()) is not None


def _canonical(value):
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            return ""
        host = parts.hostname.removeprefix("www.")
        port = parts.port
        if port not in (None, 80 if parts.scheme == "http" else 443):
            host += f":{port}"
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if not key.casefold().startswith("utm_") and key.casefold() not in ("fbclid", "gclid", "dclid", "mc_cid", "mc_eid")]
        return urlunsplit(("https", host, parts.path.rstrip("/"), urlencode(sorted(query)), ""))
    except ValueError:
        return ""


def _independent(rows):
    groups, titles, links = {}, {}, {}
    for index, row in enumerate(rows):
        title = " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", row["title"]).casefold()))
        link = _canonical(row["url"])
        joined = {lookup[value] for lookup, value in ((titles, title), (links, link)) if value and value in lookup}
        group = min(joined) if joined else index
        groups.setdefault(group, []).append(row)
        for other in joined - {group}:
            groups[group].extend(groups.pop(other))
            for lookup in (titles, links):
                for value in lookup:
                    if lookup[value] == other:
                        lookup[value] = group
        if title:
            titles[title] = group
        if link:
            links[link] = group
    assigned = {}

    def assign(group, visited):
        for row in groups[group]:
            publisher = row["publisher"]
            if publisher in visited:
                continue
            visited.add(publisher)
            if publisher not in assigned or assign(assigned[publisher][0], visited):
                assigned[publisher] = (group, row)
                return True
        return False

    for group in groups:
        assign(group, set())  # one independent story per publisher, regardless of feed order
    return [row for _, row in assigned.values()]


def _window(rows, end, hours):
    return _independent([row for row in rows if end - timedelta(hours=hours) < updates._published(row["published"]) <= end])


def _coverage(windows, start, end):
    merged = []
    for lower, upper in sorted([*windows, [start.isoformat(), end.isoformat()]]):
        if merged and lower <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], upper)
        else:
            merged.append([lower, upper])
    return merged


def _publishers(names, urls, client, geo, hours, days, warmup_days, min_publishers, warmup_publishers, ratio, errors):
    now, state = client.now, client.state
    urls = sorted(set(urls))
    collected, good = [], 0
    for url in urls:
        try:
            publisher = urlsplit(url).hostname
            if not publisher:
                raise ValueError("publisher feeds need an HTTP URL")
            items = list(updates._feed(url, client.root, client.read))
            good += 1
            for row in items:
                stamp = updates._published(row["published"])
                if stamp is None or not now - timedelta(days=days, hours=hours) < stamp <= now:
                    continue
                title = updates._plain(row["title"])
                if title and _canonical(row["url"]):
                    collected.append({"title": title, "url": row["url"], "source": updates._plain(row["source"]),
                                      "published": stamp.isoformat(), "publisher": publisher.removeprefix("www.")})
        except Exception as exc:
            errors.append({"signal": "publisher_rss", "url": url, "error": str(exc) or type(exc).__name__})
    events = []
    for name, pattern in names.items():
        key = name.casefold()
        scope = [urls, pattern.pattern]
        if state["history"].get(key, {}).get("scope") != scope:
            state["history"][key] = {"started": None, "rows": [], "windows": [], "scope": scope}
        history = state["history"][key]
        if good and not history["started"]:
            history["started"] = now.isoformat()
        if good and good == len(urls):
            history["windows"] = _coverage(history["windows"], now - timedelta(hours=hours), now)
        rows = history["rows"] + [row for row in collected if _matches(pattern, row["title"])]
        unique = {(row["publisher"], row["published"], row["title"], row["url"]): row for row in rows}
        history["rows"] = list(unique.values())
        recent = _window(history["rows"], now, hours)
        if not recent:
            continue
        ends = [now - timedelta(days=day) for day in range(1, days + 1)]
        baseline = [len(_window(history["rows"], end, hours)) for end in ends
                    if any(lower <= (end - timedelta(hours=hours)).isoformat() and end.isoformat() <= upper
                           for lower, upper in history["windows"])]
        middle = median(baseline) if baseline else 0
        warm = len(baseline) < warmup_days
        required = warmup_publishers if warm else min_publishers
        if len(recent) < required or (not warm and len(recent) < ratio * middle):
            continue
        events.append({"entity": name, "signal": "publisher_rss", "traffic": len(recent),
                       "published": max(row["published"] for row in recent),
                       "headlines": [{key: row[key] for key in ("title", "url", "source")} for row in recent],
                       "geo": geo, "median_publishers": middle})
    return events


def _observe(row, name, state, now, cooldown):
    key = "|".join((row["signal"], row["geo"], name.casefold()))
    previous = state["events"].get(key)
    published = updates._published(row["published"])
    first = updates._published(previous["first_seen"]) if previous else now
    if (previous and now - first >= timedelta(hours=cooldown) and published
            and published > (updates._published(previous["published"]) or first)):
        first = now
    row = {**row, "first_seen": first.isoformat(), "traffic_previous": previous["traffic"] if previous else 0,
           "traffic_growth": row["traffic"] - previous["traffic"] if previous else 0}
    state["events"][key] = row
    return row


def _prune(state, now, expiry, cooldown, days, hours):
    state["events"] = {key: row for key, row in state["events"].items()
                       if now - updates._published(row["first_seen"]) < timedelta(hours=expiry)}
    state["notified"] = {key: at for key, at in state["notified"].items()
                         if now - updates._published(at) < timedelta(hours=cooldown)}
    for history in state["history"].values():
        history["rows"] = [row for row in history["rows"]
                           if now - timedelta(days=days, hours=hours) < updates._published(row["published"]) <= now]
        history["windows"] = [window for window in history["windows"]
                              if updates._published(window[1]) >= now - timedelta(days=days)]


def _pageviews(article, client, ratio=3, extra=500):
    end = client.now.date() - timedelta(days=1)
    start = end - timedelta(days=28)
    article = quote(article.replace(" ", "_"), safe="")
    url = f"{PAGEVIEWS_URL}/en.wikipedia.org/all-access/user/{article}/daily/{start:%Y%m%d}00/{end:%Y%m%d}00"
    data = json.loads(client.read(url, "Wikimedia pageviews"))
    views = {}
    for row in data.get("items", []):
        try:
            day = datetime.strptime(row["timestamp"], "%Y%m%d%H").date()
            count = row["views"]
        except (KeyError, TypeError, ValueError):
            continue
        if type(count) is int and count >= 0 and start <= day <= end:
            views[day] = count
    if len(views) != 29:
        return False
    middle = median(views[end - timedelta(days=day)] for day in range(1, 29))
    return views[end] >= ratio * middle and views[end] - middle >= extra


def pageview_spike(article: str, *, state_dir=Path("."), now=None, fetch=None, ratio=3, extra=500) -> bool:
    """Compare yesterday in UTC with the preceding 28 complete days."""
    root, now = Path(state_dir), _now(now)
    state = _load(root)
    try:
        return _pageviews(article, _Client(root, state, now, fetch), ratio, extra)
    finally:
        write_json(root / "signals.json", state)


def watch(watch_list, *, feeds=(), state_dir=Path("."), geo="US", now=None, fetch=None,
          min_traffic=200, window_hours=2, min_headlines=1, cooldown_hours=24, expiry_hours=48,
          min_publishers=3, publisher_ratio=3, history_days=7, warmup_days=3, warmup_publishers=5,
          articles=None) -> list[dict]:
    """Return new signals and source errors. Names may map to lists of aliases.

    Lists also accept objects with entity (or name) and aliases. Trends retain
    their search title. Publisher traffic is the independent publisher count.
    Publisher baselines use matching UTC windows on previous days. Only fully
    polled windows count toward the warm-up.
    Pass a name-to-Wikipedia-title map in articles to request corroboration.
    """
    root, now, names = Path(state_dir), _now(now), _names(watch_list)
    geo = geo.upper()
    if not re.fullmatch(r"[A-Z]{2}", geo):
        raise ValueError("geo must be a two-letter country code")
    state = _load(root)
    _prune(state, now, expiry_hours, cooldown_hours, history_days, window_hours)
    client, errors, found = _Client(root, state, now, fetch), [], []
    if not names:
        write_json(root / "signals.json", state)
        return []
    try:
        primary = _trends(client.read(TRENDS_URL.format(geo=geo)), geo)
    except Exception as exc:
        primary = []
        errors.append({"signal": "google_trends", "error": str(exc) or type(exc).__name__})
    candidates = [(row, name) for row in primary for name, pattern in names.items() if _matches(pattern, row["entity"])]
    if feeds or not primary:                       # niche guests rarely reach the top 10, so news feeds always run when given
        candidates += [(row, row["entity"]) for row in _publishers(
            names, feeds, client, geo, window_hours, history_days, warmup_days,
            min_publishers, warmup_publishers, publisher_ratio, errors)]
    observed = set()
    ranked = sorted(candidates, key=lambda pair: (pair[0]["traffic"] >= min_traffic and len(pair[0]["headlines"]) >= min_headlines,
                                                pair[0]["published"], pair[0]["traffic"]), reverse=True)
    for row, name in ranked:
        if name.casefold() in observed:
            continue
        published = updates._published(row["published"])
        if published and not now - timedelta(hours=expiry_hours) < published <= now:
            continue
        observed.add(name.casefold())
        row = _observe(row, name, state, now, cooldown_hours)
        if (now - updates._published(row["first_seen"]) > timedelta(hours=window_hours)
                or len(row["headlines"]) < min_headlines
                or (row["signal"] == "google_trends" and row["traffic"] < min_traffic)):
            continue
        key = geo + "|" + name.casefold()
        if key in state["notified"]:
            continue
        if articles and name in articles:
            try:
                row["corroborated"] = _pageviews(articles[name], client)
            except Exception as exc:
                errors.append({"signal": "wikimedia", "entity": name, "error": str(exc) or type(exc).__name__})
        state["notified"][key] = now.isoformat()
        found.append(row)
    write_json(root / "signals.json", state)
    return sorted(found, key=lambda row: (row["published"] or row["first_seen"], row["first_seen"]), reverse=True) + errors
