"""Find licensed visuals (stills and video) for a clip's visual requests.

requests: [{"id", "query", "kind": photo|video|logo|gif|screenshot, "url"?, "entity"?, "context"?, "orientation"?}]

Modes:
  context (default)  the specific thing named: Wikidata entity -> its Commons image/logo/video + official site
                     (screenshot, 6 s scroll recording, og:image/og:video) -> NASA (space topics) -> Commons ->
                     Library of Congress -> Internet Archive [-> Exa page finder, Pexels/Pixabay when keys exist]
  documentary        archives only: Wikidata -> NASA (space topics) -> Commons -> Library of Congress -> Internet
                     Archive; no stock, no site captures unless a request gives its url
  fun                stock video first (Pexels, then Pixabay, when keys exist); kind "gif" = a short stock video of
                     that action; keyless fallback = Commons / Internet Archive / NASA clips, then stills.
                     GIPHY, KLIPY and Tenor are deliberately not used: their terms forbid baking clips into video.

Writes in outdir: <id>/ (up to 5 varied candidates, near-duplicates dropped), manifest.json ({id: [ranked candidates]}
with rights "cleared" | "attribution" | "editorial" | "unknown" and credit_text), run_log.json (key presence, never
values; per-source health; routing and rejections) and contact_sheet.jpg.

Optional keys: PEXELS_API_KEY, PIXABAY_API_KEY, EXA_API_KEY, read from the environment (and on Windows from the user's
HKCU\\Environment, for variables set after this process started). Values are never printed, logged or written; a
missing key switches that source off. Downloaded files are untrusted bytes: parsed for validation (Pillow / ffprobe),
never executed. Site captures hide cookie banners with CSS only; nothing on a page is clicked or accepted.
"""
from __future__ import annotations

import hashlib
import html
import io
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections import Counter
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont

from . import tools
from .network import Network
from .plan import visual_id
from .tools import FactoryError, run

FFPROBE = shutil.which("ffprobe") or "ffprobe"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
UA = "zing-factory/0.1 (+https://myzing.app)"  # Wikimedia robot policy wants contact info; without it upload.wikimedia.org 429s
MIN_LONG_SIDE = 900
IMG_CAP = 40 << 20
VID_CAP = 120 << 20
JSON_CAP = 15 << 20
EXCERPT_S = 20  # long videos become a 20 s excerpt from ~15% in (skips slates; the renderer uses <= 20 s)
KINDS = ("photo", "video", "logo", "gif", "screenshot")
KEY_NAMES = ("PEXELS_API_KEY", "PIXABAY_API_KEY", "EXA_API_KEY")
SOURCES = "nasa|commons|wikidata|openverse|pexels|pixabay|loc|ia|exa|screenshot|scroll|ogimage|ogvideo|local"
OUR_FILE = re.compile(rf"^({SOURCES})_[0-9a-f]{{8}}(\.pick)?\.(jpg|jpeg|png|webp|mp4|mov|webm)(\.part)?$")
LOCAL = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"}
CODE_TITLE = re.compile(r"[A-Za-z]{2,8}[-_]?\d[\w.\-]*")
IMAGE_MIMES = ("image/jpeg", "image/png", "image/svg+xml", "image/webp", "image/tiff")
NASA_LICENSE = "NASA (public domain)"
EDITORIAL = "screenshot, editorial use, check rights"
PEXELS_LICENSE = "Pexels License (free to use, no attribution required)"
PIXABAY_LICENSE = "Pixabay Content License (free to use, no attribution required)"
SOURCE_LABEL = {"nasa": "NASA", "commons": "Wikimedia Commons", "wikidata": "Wikimedia Commons",
                "openverse": "Openverse", "pexels": "Pexels", "pixabay": "Pixabay", "loc": "Library of Congress",
                "ia": "Internet Archive"}
Image.MAX_IMAGE_PIXELS = 120_000_000

# ----------------------------------------------------------------------------- keys (values never leave this module)
_KEYS: dict[str, str | None] = {}


def get_key(name: str) -> str | None:
    """Process environment first, then HKCU\\Environment (user vars set after launch). Cached per run."""
    if name not in _KEYS:
        v = os.environ.get(name)
        if not v and sys.platform == "win32":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                    v = str(winreg.QueryValueEx(k, name)[0])
            except OSError:
                v = None
        _KEYS[name] = (v or "").strip() or None
    return _KEYS[name]


def scrub(s: str) -> str:
    for v in _KEYS.values():
        if v and len(v) >= 6:
            s = s.replace(v, "***")
    return s


# ----------------------------------------------------------------------------- text matching
STOP = set("a an the of and or in on at to for with from by as is are was were be this that these those it its "
           "into over about vs via new".split())
KIND_WORDS = set("logo logos photo photos image images picture pictures pic pics video videos footage clip clips "
                 "screenshot screenshots wallpaper stock hd 4k gif gifs reaction meme".split())
WEAK = {"nasa", "man", "men", "woman", "women", "person", "people", "guy", "girl", "boy", "someone"}
SPACE_HINTS = set("nasa space astronaut astronauts cosmonaut iss orbit orbital rocket launch moon lunar mars apollo "
                  "artemis shuttle spacex satellite galaxy nebula planet planets spacewalk hubble webb telescope jsc "
                  "ksc t-38 spacecraft capsule soyuz starship crew-dragon station".split())
PHOTO_OFF = {"logo", "icon", "diagram", "chart", "map", "patch", "insignia", "seal", "emblem", "graph",
             "infographic", "poster", "document", "letter", "page", "cover", "stamp"}
LOGO_OFF = {"favicon", "icon", "screenshot", "building", "office", "headquarter", "sign", "signage", "photo"}
VIDEO_TALKY = {"briefing", "conference", "interview", "update", "panel", "q", "ask", "asknasa", "replay", "live",
               "webinar", "lecture", "podcast", "ceremony", "talk", "what", "how", "why", "explained", "news"}
VIDEO_BROLL = {"b-roll", "broll", "footage", "timelapse", "time-lapse", "view", "views", "flyover", "fly", "flight",
               "orbit", "tour", "aerial", "beauty"}
THIS_YEAR = time.localtime().tm_year


def stem(t: str) -> str:
    if len(t) > 4 and t.endswith("ies"):
        t = t[:-3] + "y"
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    if len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
    if len(t) > 4 and t.endswith("e"):
        t = t[:-1]
    return t


def raw_tokens(text: str) -> list[str]:
    text = html.unescape(text or "").lower().replace("_", " ")
    out = []
    for t in re.findall(r"[a-z0-9]+(?:['\u2019-][a-z0-9]+)*", text):
        t = re.sub(r"['\u2019]", "", t)
        for p in [t] + ([x for x in t.split("-") if x] if "-" in t else []):
            if len(p) > 1 or p.isdigit():
                out.append(p)
    return out


def terms(text: str) -> set[str]:
    return {stem(t) for t in raw_tokens(text) if t not in STOP}


def flat(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", html.unescape(text or "").lower()).strip() + " "


def _norm_word(w: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", w.lower())


class Query:
    def __init__(self, req: dict, kind: str, mode: str):
        self.raw, self.kind, self.mode = req["query"].strip(), kind, mode
        self.entity = (req.get("entity") or "").strip()            # the planner's canonical name, when it gave one
        context = req.get("context") or ""
        self.context = context
        words = [w for w in raw_tokens(self.raw) if w not in STOP and w not in KIND_WORDS]
        strong = [w for w in dict.fromkeys(words) if w not in WEAK]
        weak = [w for w in dict.fromkeys(words) if w in WEAK]
        if not strong:
            strong, weak = weak, []
        self.strong_raw = strong
        self.strong = list(dict.fromkeys(stem(w) for w in strong))
        self.weights = {stem(w): (1.5 if any(ch.isdigit() for ch in w) else 1.0) for w in strong}
        for w in weak:
            self.weights.setdefault(stem(w), 0.35)
        self.min_hits = 1 if len(self.strong) <= 3 else 2  # long queries need two real words in the title
        core = [w for w in self.raw.split() if _norm_word(w) not in KIND_WORDS]
        self.core = " ".join(core) or self.raw
        self.core_strong = " ".join(w for w in core if _norm_word(w) not in WEAK) or self.core
        self.phrase = flat(self.core_strong) if len(self.core_strong.split()) >= 2 else ""
        self.ctx = terms(context) - set(self.weights)
        both = set(raw_tokens(self.raw + " " + context))
        self.space = bool(both & SPACE_HINTS) or "space center" in self.raw.lower()
        self.named = kind == "logo" or any(ch.isupper() for ch in self.raw)
        self.vertical = (req.get("orientation") or "").lower() in ("vertical", "portrait", "9:16") or \
            bool({"vertical", "portrait"} & both)
        self.wants_video = kind in ("video", "gif")


def clean_nasa_title(t: str) -> str:
    """Drop caption datelines/ids ('JOHNSON SPACE CENTER, HOUSTON -- (S95-0577) -- ...') so they can't match."""
    def is_dateline(s: str) -> bool:
        s = s.strip()
        return bool(re.match(r"^[A-Z][A-Z .'&]{2,},", s)) or (
            bool(re.fullmatch(r"\(?[A-Za-z]{1,8}[-_]?\d[\w-]*\)?", s)) and sum(ch.isdigit() for ch in s) >= 5)

    segs = [s for s in re.split(r"\s+-{1,3}\s+|\s*-{2,3}\s*", t) if s.strip()]
    while len(segs) > 1 and is_dateline(segs[0]):
        segs.pop(0)
    out = re.sub(r"^\([^)]*\)\s*", "", " - ".join(s.strip() for s in segs)).strip()
    return out or t


def logo_adjust(c: dict) -> float:
    """Logos change: prefer the current mark, avoid former ones, re-uploads '(2)', and photos of logos."""
    text = f"{c['title']} {c.get('desc', '')}".lower()
    s = 0.0
    years = [int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", text)]
    if re.search(r"\b(former|old|previous|historic(al)?|retired|until|obsolete|defunct)\b", text):
        s -= 0.08
    elif re.search(r"\b(current|since|in use|official)\b", text) or (years and max(years) >= THIS_YEAR - 2):
        s += 0.06
    elif years and max(years) < THIS_YEAR - 4:
        s -= 0.05
    if re.search(r"\(\d\)\s*$", c["title"]):
        s -= 0.03
    if re.search(r"\(\d{7,}\)", c["title"]):
        s -= 0.10
    return s


def shape_bonus(w, h, q: Query) -> float:
    if not isinstance(w, (int, float)) or not isinstance(h, (int, float)) or not w or not h:
        return 0.0
    a, s = w / h, 0.0
    if q.vertical:
        s += 0.08 if a <= 0.8 else (-0.06 if a > 1.2 else 0.0)
    elif 0.95 <= a <= 1.9:
        s += 0.08  # landscape/square fits the 1080x960 slot
    elif 1.9 < a <= 2.4:
        s += 0.03
    elif a > 2.4:
        s -= 0.0 if q.kind == "logo" else 0.06
    elif a < 0.9:
        s -= 0.15  # portrait gets cropped hard in the slot
    if max(w, h) >= 1600:
        s += 0.03
    return s


def score(c: dict, q: Query) -> float | None:
    """None = title shares too few meaningful words with the query (skip). Entity, official-site and stock
    candidates carry their own relevance ('base' / 'stock') instead of the title gate."""
    tt = terms(c.get("title", ""))
    total = sum(q.weights.values()) or 1.0
    hits = [t for t in q.weights if t in tt]
    title_m = sum(q.weights[t] for t in hits) / total
    c["matched_terms"] = hits
    if c.get("base") is not None:
        s = c["base"]
    elif c.get("stock"):  # stock APIs rank by their own relevance; slugs are short, so no hard gate
        s = 0.85 + 0.25 * title_m + c.get("engine_bonus", 0.0) + c.get("route_bonus", 0.0)
    else:
        if sum(1 for t in q.strong if t in tt) < q.min_hits:
            return None
        dt = terms(c.get("desc", "")) | tt
        desc_m = sum(w for t, w in q.weights.items() if t in dt) / total
        precision = min(1.0, 2 * len(hits) / max(len(tt), 1))
        phrase = 1.0 if q.phrase and q.phrase in flat(c["title"]) else 0.0
        ctx = len(q.ctx & dt) / len(q.ctx) if q.ctx else 0.0
        s = 0.55 * title_m + 0.15 * desc_m + 0.10 * precision + 0.15 * phrase + 0.10 * ctx
        s += c.get("route_bonus", 0.0) + c.get("engine_bonus", 0.0)
        rt, qraw = set(raw_tokens(c["title"])), set(raw_tokens(q.raw))
        if q.kind == "logo":
            s += 0.15 if rt & {"logo", "wordmark", "logotype"} else -0.10
            s += 0.08 if c.get("mime") == "image/svg+xml" else 0.0
            s -= 0.10 if (rt & LOGO_OFF) - qraw else 0.0
        elif c.get("media_type") == "video":
            s -= 0.12 if rt & VIDEO_TALKY else 0.0
            s += 0.06 if rt & VIDEO_BROLL else 0.0
        else:
            s -= 0.12 if (rt & PHOTO_OFF) - qraw else 0.0
    if q.kind == "logo" and c.get("media_type") == "image":
        s += logo_adjust(c)
    s += shape_bonus(c.get("width"), c.get("height"), q)
    if q.wants_video:
        s += 0.12 if c.get("media_type") == "video" else -0.10
    return round(s, 4)


# ----------------------------------------------------------------------------- polite HTTP
class Http:
    def __init__(self, min_interval: float = 0.3, project: Path | None = None):
        self.min_interval, self._last, self.count = min_interval, 0.0, 0
        self.network = Network(project)

    def _pace(self):
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)  # at most ~3 requests/second overall
        self._last = time.monotonic()
        self.count += 1

    def open(self, url, headers=None, timeout=20, method="GET", data=None, *, purpose="visual request"):
        self.network.check(purpose)
        self._pace()
        url = safe_url(url)
        return self.network.open(url, purpose, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})},
                                 timeout=timeout, method=method, data=data, validate=_public_url)

    def get_json(self, url, headers=None, timeout=20):
        with self.open(url, headers, timeout, purpose="visual search") as r:
            return json.loads(r.read(JSON_CAP))

    def post_json(self, url, body, headers=None, timeout=30):
        with self.open(url, {"Content-Type": "application/json", **(headers or {})}, timeout, "POST",
                       json.dumps(body).encode(), purpose="visual search") as r:
            return json.loads(r.read(JSON_CAP))

    def get_bytes(self, url, cap, headers=None, timeout=60):
        with self.open(url, headers, timeout, purpose="visual download") as r:
            n = r.headers.get("Content-Length")
            if n and n.isdigit() and int(n) > cap:
                raise TooLarge(f"too large ({int(n) >> 20} MB)")
            buf = io.BytesIO()
            while chunk := r.read(1 << 16):
                buf.write(chunk)
                if buf.tell() > cap:
                    raise TooLarge("too large")
            return buf.getvalue()

    def download_to(self, url, path: Path, cap, timeout=60):
        with self.open(url, None, timeout, purpose="visual download") as r, open(path, "wb") as f:
            n = r.headers.get("Content-Length")
            if n and n.isdigit() and int(n) > cap:
                raise TooLarge(f"too large ({int(n) >> 20} MB)")
            got = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if got > cap:
                    raise TooLarge("too large")
        return got


def safe_url(u: str) -> str:
    p = urllib.parse.urlsplit(u.strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError(f"refusing non-http url: {u[:80]!r}")
    scheme = "https" if p.netloc.endswith(("nasa.gov", "archive.org", "loc.gov")) else p.scheme
    path = urllib.parse.quote(p.path, safe="/%~-._!$&'()*+,;=:@")
    query = urllib.parse.quote(p.query, safe="=&%~-._!$'()*+,;:@/?")
    return urllib.parse.urlunsplit((scheme, p.netloc, path, query, ""))


def _check_host(url: str) -> None:
    p = urllib.parse.urlsplit(url)
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError(f"refusing private address {p.hostname}")


def _public_url(url):
    url = safe_url(url)
    _check_host(url)
    return url


class TooLarge(ValueError):
    pass


class Health:
    """Per-source call stats plus a circuit breaker: a source that times out or 5xx/429s is skipped afterwards."""

    def __init__(self):
        self.d: dict[str, dict] = {}
        self.down: set[str] = set()

    def e(self, src):
        return self.d.setdefault(src, {"calls": 0, "ok": 0, "results": 0, "downloads": 0, "errors": []})

    def ok(self, src, n):
        e = self.e(src)
        e["calls"] += 1
        e["ok"] += 1
        e["results"] += n

    def fail(self, src, err: Exception) -> str:
        e = self.e(src)
        e["calls"] += 1
        msg = scrub(f"{type(err).__name__}: {err}")[:200]
        fatal = isinstance(err, (TimeoutError, socket.timeout, urllib.error.URLError)) and not (
            isinstance(err, urllib.error.HTTPError) and err.code < 500 and err.code != 429)
        if fatal:
            self.down.add(src)
            msg += " -> source disabled for this run"
        e["errors"].append(msg)
        return msg


def strip_html(s) -> str:
    if isinstance(s, list):
        s = " ".join(str(x) for x in s)
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def h8(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:8]


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(url or "").netloc.removeprefix("www.")


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def cand(source: str, media_type: str, **kw) -> dict:
    c = {"source": source, "media_type": media_type, "title": "", "desc": "", "file_url": None}
    c.update(kw)
    c["title"] = (c.get("title") or "").strip()
    return c


# ----------------------------------------------------------------------------- rights
def rights_for(c: dict) -> tuple[str, str]:
    """('cleared'|'attribution'|'editorial'|'unknown', exact credit line)."""
    src, lic = c["source"], c.get("license") or ""
    if src == "local":
        return "cleared", f"Your file: {c['title']}"
    low = lic.lower()
    creator = strip_html(c.get("creator") or "")[:80]
    label = SOURCE_LABEL.get(src, src)
    if re.search(r"\b(nc|nd)\b|non[- ]?commercial|no[- ]?deriv", f"{lic} {c.get('license_url') or ''}", re.I):
        r = "unknown"
    elif src == "nasa" and re.search(r"copyright|©|all rights reserved|used with permission",
                                   " ".join(strip_html(c.get(k)) for k in ("desc", "title", "creator")), re.I):
        r = "unknown"
    elif src in ("screenshot", "scroll", "ogimage", "ogvideo", "exa"):
        what = {"screenshot": "Screenshot", "scroll": "Screen recording", "ogimage": "Image",
                "ogvideo": "Video", "exa": "Image"}[src]
        return "editorial", f"{what}: {host_of(c.get('source_url') or c.get('file_url') or '')}"
    elif src in ("pexels", "pixabay"):
        return "cleared", f"{creator or 'Creator'} / {label}"
    elif src == "loc":
        adv = (c.get("rights_advisory") or "").lower()
        r = "cleared" if "no known restrictions" in adv else "unknown"
        return r, f"{creator} / Library of Congress" if creator else "Library of Congress"
    elif re.search(r"public domain|\bpd\b|pd-|cc0|cc-zero|publicdomain|\bpdm\b|no known restrictions", low):
        r = "cleared"
    elif re.search(r"\bcc[- ]by\b|creativecommons\.org/licenses/by|gfdl|apache|\bmit\b|\bbsd\b|attribution|"
                   r"free art|\bogl\b", low):
        r = "attribution"
    else:
        r = "unknown"
    if r == "attribution":
        return r, f"\u201c{c['title'][:60]}\u201d by {creator or 'unknown'}, {lic}, via {label}"
    if creator and label.lower() not in creator.lower():
        return r, f"{creator} / {label}"
    return r, creator or label


# ----------------------------------------------------------------------------- sources (metadata only)
def search_nasa(ctx, q: Query, media: str) -> list[dict]:
    url = "https://images-api.nasa.gov/search?" + urllib.parse.urlencode(
        {"q": q.core_strong, "media_type": media, "page_size": 40})
    items = ctx.http.get_json(url)["collection"]["items"]
    out = []
    for i, it in enumerate(items[:40]):
        m = (it.get("data") or [{}])[0]
        title = (m.get("title") or "").strip()
        desc = m.get("description_508") or m.get("description") or ""
        if not title or CODE_TITLE.fullmatch(title):
            title = re.split(r"(?<=[.!?])\s", re.sub(r"^\S+\s*\([^)]*\)\s*-+\s*", "", strip_html(desc)))[0][:160]
        c = cand("nasa", "video" if media == "video" else "image", title=clean_nasa_title(title),
                 desc=strip_html(desc) + " " + " ".join(m.get("keywords") or []),
                 license=NASA_LICENSE, license_url="https://www.nasa.gov/nasa-brand-center/images-and-media/",
                 creator=m.get("photographer") or m.get("secondary_creator") or
                 (f"NASA/{m['center']}" if m.get("center") else "NASA"),
                 source_url="https://images.nasa.gov/details/" + urllib.parse.quote(m.get("nasa_id", "")),
                 collection=it.get("href"), engine_bonus=0.04 * (1 - i / 40))
        if media == "image":  # search links often carry rendition sizes, so the 900px rule applies pre-download
            best = None
            for ln in it.get("links") or []:
                href, w, hh = ln.get("href", ""), ln.get("width"), ln.get("height")
                if ln.get("render") != "image" or not w or not hh:
                    continue
                if "~large." in href and max(w, hh) >= MIN_LONG_SIDE:
                    best = (href, w, hh)
                elif "~orig." in href and (ln.get("size") or 0) < 25e6 and best is None and \
                        href.lower().endswith((".jpg", ".jpeg", ".png")):
                    best = (href, w, hh)
            if best:
                c["file_url"], c["width"], c["height"] = best
                if max(best[1], best[2]) < MIN_LONG_SIDE:
                    continue
        out.append(c)
    return out


COMMONS_API = "https://commons.wikimedia.org/w/api.php?"
EM_FILTER = "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|ObjectName|Restrictions"


def commons_query(http: Http, params: dict, video: bool = False) -> list[dict]:
    p = {"action": "query", "format": "json", "formatversion": 2, **params}
    if video:
        p.update(prop="videoinfo", viprop="url|size|mime|extmetadata|derivatives", viextmetadatafilter=EM_FILTER)
    else:
        p.update(prop="imageinfo", iiprop="url|size|mime|extmetadata", iiurlwidth=1600, iiextmetadatafilter=EM_FILTER)
    d = http.get_json(COMMONS_API + urllib.parse.urlencode(p))
    return sorted(d.get("query", {}).get("pages", []), key=lambda pg: pg.get("index", 99))


def commons_cand(page: dict, source: str, min_video: int) -> dict | None:
    info = (page.get("videoinfo") or page.get("imageinfo") or [{}])[0]
    mime = info.get("mime", "")
    w, h = info.get("width") or 0, info.get("height") or 0
    em = {k: (v or {}).get("value", "") for k, v in (info.get("extmetadata") or {}).items()}
    title = re.sub(r"^File:", "", page.get("title", ""))
    title = re.sub(r"\.(jpe?g|png|svg|webp|tiff?|webm|ogv|ogg|mp4)$", "", title, flags=re.I).replace("_", " ")
    common = dict(title=title, mime=mime,
                  desc=strip_html(em.get("ImageDescription", ""))[:600] + " " + strip_html(em.get("ObjectName", "")),
                  license=strip_html(em.get("LicenseShortName", "")) or "see source page",
                  license_url=em.get("LicenseUrl") or None,
                  creator=strip_html(em.get("Artist", "")) or strip_html(em.get("Credit", "")) or "unknown (see source page)",
                  source_url=info.get("descriptionurl"))
    if mime.startswith("video/") or mime == "application/ogg":
        derivs = [d for d in info.get("derivatives") or [] if (d.get("type") or "").startswith("video/webm")
                  and max(d.get("width") or 0, d.get("height") or 0) >= min_video]
        derivs.sort(key=lambda d: d.get("width") or 0)
        if derivs:
            url, w, h = urllib.parse.urljoin("https://commons.wikimedia.org/", derivs[0]["src"]), derivs[0]["width"], derivs[0]["height"]
        elif mime == "video/webm" and max(w, h) >= min_video:
            url = info.get("url")
        else:
            return None
        return cand(source, "video", file_url=url, width=w, height=h, duration=info.get("duration"), **common)
    if mime not in IMAGE_MIMES:
        return None
    if mime != "image/svg+xml" and max(w, h) < MIN_LONG_SIDE:
        return None  # tiny raster (icons); SVGs rasterize to 1600px so they are exempt
    c = cand(source, "image", file_url=info.get("thumburl") or info.get("url"), width=w, height=h, **common)
    if em.get("Restrictions"):
        c["notes"] = "restrictions: " + strip_html(em["Restrictions"])
    return c


def _query_chain(q: Query) -> list[str]:
    """Commons/IA search is AND-ish, so long phrases get progressively shorter fallbacks (nouns tend to come last)."""
    w = q.strong_raw
    pairs = [f"{w[i]} {w[i + 1]}" for i in range(len(w) - 2, -1, -1)]  # adjacent pairs, last first
    chain = []
    for s in [q.core, q.core_strong] + pairs:
        s = s.strip()
        if s and s not in chain:
            chain.append(s)
    return chain


def search_commons(ctx, q: Query, video: bool = False) -> list[dict]:
    if q.kind == "logo":
        chain = [f"{q.core_strong} logo"]
    else:
        chain = [f"{s} filetype:{'video' if video else 'bitmap'}" for s in _query_chain(q)]
    pages, seen = [], set()
    for s in chain[:4]:
        if len(pages) >= 30:
            break
        for pg in commons_query(ctx.http, {"generator": "search", "gsrsearch": s, "gsrnamespace": 6,
                                           "gsrlimit": 15}, video=video):
            if pg["title"] not in seen:
                seen.add(pg["title"])
                pages.append(pg)
    out = []
    for i, pg in enumerate(pages):
        c = commons_cand(pg, "commons", ctx.min_video)
        if c and (c["media_type"] == "video") == video:
            c["engine_bonus"] = 0.04 * (1 - i / max(len(pages), 1))
            out.append(c)
    return out


WD_API = "https://www.wikidata.org/w/api.php?"
BAD_DESC = re.compile(r"given name|family name|surname|disambiguation|wikimedia (category|list|template)|"
                      r"scholarly article|human settlement in", re.I)


def wikidata_entities(http: Http, q: Query, limit: int = 2) -> list[dict]:
    """Resolve the named thing(s): wbsearchentities on the query, then shorter prefixes; a second capitalized name
    ('Anthropic' in 'Anthropic Claude') is accepted only when the first entity's description mentions it."""
    qtok, strong = terms(q.raw), set(q.strong)

    def search(s):
        return http.get_json(WD_API + urllib.parse.urlencode({
            "action": "wbsearchentities", "search": s, "language": "en", "uselang": "en", "type": "item",
            "limit": 7, "format": "json"})).get("search") or []

    def fits(hh):
        lt = terms((hh.get("match") or {}).get("text") or hh.get("label") or "")
        return bool(lt) and lt <= qtok and not BAD_DESC.search(hh.get("description") or "")

    words = q.core.split()
    tries = [" ".join(words[:n]) for n in range(len(words), 1, -1)][:4] if len(words) > 1 else [q.core]
    accepted = []
    if q.entity:
        # a bare name is ambiguous ("Ramp"): take the hit whose description shares a word with the query or context
        hint = terms(q.raw) | terms(getattr(q, "context", "")) 
        hits = [hh for hh in search(q.entity) if not BAD_DESC.search(hh.get("description") or "")]
        best = next((hh for hh in hits if terms(hh.get("description") or "") & (hint - terms(q.entity))), None)
        if best:
            accepted.append(best)
            tries = []
    for s in tries:
        hit = next((hh for hh in search(s) if fits(hh)), None)
        if hit:
            accepted.append(hit)
            break
    if accepted:
        first = accepted[0]
        covered = terms(first.get("label", ""))
        desc_t = terms(first.get("description", ""))
        for w in words:
            wt = terms(w)
            if len(accepted) >= limit or not w[:1].isupper() or not wt or wt <= covered or not wt <= desc_t:
                continue
            hit = next((hh for hh in search(w) if terms(hh.get("label", "")) == wt
                        and not BAD_DESC.search(hh.get("description") or "")), None)
            if hit and hit["id"] != first["id"]:
                accepted.append(hit)
    if not accepted:
        return []
    ents = http.get_json(WD_API + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": "|".join(hh["id"] for hh in accepted), "props": "claims",
        "format": "json"})).get("entities", {})
    out = []
    for n, hh in enumerate(accepted):
        claims = (ents.get(hh["id"]) or {}).get("claims") or {}

        def vals(p):
            cs = [c for c in claims.get(p, []) if c.get("rank") != "deprecated"]
            cs.sort(key=lambda c: c.get("rank") != "preferred")
            return [c["mainsnak"]["datavalue"]["value"] for c in cs if (c.get("mainsnak") or {}).get("datavalue")]

        lt = terms((hh.get("match") or {}).get("text") or hh.get("label", ""))
        cov = len(lt & strong) / max(len(strong), 1)
        out.append({"qid": hh["id"], "label": hh.get("label", ""), "desc": hh.get("description", ""),
                    "coverage": min(cov, 0.8) if n else cov, "P18": vals("P18"), "P154": vals("P154"),
                    "P10": vals("P10"), "sites": [v for v in vals("P856") if isinstance(v, str)]})
    return out


def search_wikidata(ctx, q: Query) -> list[dict]:
    out = []
    for e in wikidata_entities(ctx.http, q):
        rel = 0.55 + 0.6 * e["coverage"]  # 'Library of Congress' covers half of '... reading room': its shots rank lower
        ctx.log["entities"].append(f"{e['qid']} {e['label']} ({e['desc'][:50]})")
        for site in e["sites"][:1]:
            ctx.sites.append((site, rel, f"{e['label']} official site (Wikidata P856)"))
        files = [(t, "P18") for t in e["P18"][:2]] + [(t, "P154") for t in e["P154"][:2]]
        if files:
            role = {("File:" + t.replace("_", " ")).lower(): p for t, p in files}
            for pg in commons_query(ctx.http, {"titles": "|".join("File:" + t for t, _ in files)}):
                c = commons_cand(pg, "wikidata", ctx.min_video)
                if not c:
                    continue
                prop = role.get(pg.get("title", "").lower(), "P18")
                off = {"P18": -0.3 if q.kind == "logo" else 0.0, "P154": 0.15 if q.kind == "logo" else -0.25}[prop]
                c.update(base=rel + off, entity=f"{e['label']} {e['qid']} {prop}")
                out.append(c)
        if e["P10"] and q.kind != "logo":
            for pg in commons_query(ctx.http, {"titles": "File:" + e["P10"][0]}, video=True):
                c = commons_cand(pg, "wikidata", ctx.min_video)
                if c:
                    c.update(base=rel + 0.03, entity=f"{e['label']} {e['qid']} P10")
                    out.append(c)
    return out


def search_loc(ctx, q: Query) -> list[dict]:
    d = ctx.http.get_json("https://www.loc.gov/photos/?" + urllib.parse.urlencode(
        {"q": q.core, "fo": "json", "c": 25}), timeout=30)
    out = []
    for i, r in enumerate(d.get("results") or []):
        if r.get("access_restricted"):
            continue
        best = None
        for u in r.get("image_url") or []:
            m = re.search(r"#h=(\d+)&w=(\d+)", u) if isinstance(u, str) else None
            if m and (best is None or int(m[1]) * int(m[2]) > best[1] * best[2]):
                best = (u.split("#")[0], int(m[2]), int(m[1]))
        if not best or max(best[1], best[2]) < MIN_LONG_SIDE:
            continue
        out.append(cand("loc", "image", title=strip_html(r.get("title")).strip("[] ."), file_url=best[0],
                        width=best[1], height=best[2], desc=strip_html(r.get("description")) + " " +
                        " ".join(r.get("subject") or []), creator=strip_html(r.get("contributor"))[:80],
                        source_url=r.get("url"), item_url=r.get("url"), license="see rights advisory",
                        rights_pending=True, engine_bonus=0.04 * (1 - i / 25)))
    return out


def _ia_license(url: str) -> str | None:
    u = (url or "").lower()
    if not u or "-nc" in u or "-nd" in u:
        return None  # non-commercial / no-derivatives licences don't fit a rendered, posted clip
    if "publicdomain/zero" in u:
        return "CC0 1.0"
    if "publicdomain/mark" in u:
        return "Public Domain Mark 1.0"
    if "publicdomain" in u:
        return "Public domain"
    m = re.search(r"licenses/(by(?:-sa)?)/([\d.]+)", u)
    return f"CC {m[1].upper()} {m[2]}" if m else None


def search_ia(ctx, q: Query, media: str) -> list[dict]:
    words = [re.sub(r"[^\w-]", "", w) for w in q.strong_raw][:5]
    words = [w for w in words if w]
    if not words:
        return []
    attempts = ["(" + " AND ".join(words) + ")"] + (["(" + " OR ".join(words) + ")"] if len(words) > 1 else [])
    out, seen = [], set()
    for a in attempts:
        if len(out) >= 8:
            break
        params = [("q", f"title:{a} AND mediatype:({media})")] + \
                 [("fl[]", f) for f in ("identifier", "title", "description", "licenseurl", "creator")] + \
                 [("rows", "40"), ("sort[]", "downloads desc"), ("output", "json")]
        d = ctx.http.get_json("https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params), timeout=30)
        for i, x in enumerate((d.get("response") or {}).get("docs") or []):
            lic = _ia_license(x.get("licenseurl"))
            ident = x.get("identifier")
            if not lic or not ident or ident in seen:
                continue
            seen.add(ident)
            out.append(cand("ia", "video" if media == "movies" else "image", title=strip_html(x.get("title")),
                            desc=strip_html(x.get("description"))[:600], ia_id=ident, license=lic,
                            license_url=x.get("licenseurl"), creator=strip_html(x.get("creator"))[:80] or "unknown",
                            source_url=f"https://archive.org/details/{ident}", engine_bonus=0.03 * (1 - i / 40)))
    return out


def ov_license(r: dict) -> str:
    lic, ver = (r.get("license") or "").lower(), r.get("license_version") or ""
    if lic == "cc0":
        return "CC0 1.0"
    if lic == "pdm":
        return "Public Domain Mark 1.0"
    return f"CC {lic.upper()} {ver}".strip()


def search_openverse(ctx, q: Query) -> list[dict]:
    d = ctx.http.get_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": q.core, "license_type": "commercial,modification", "page_size": 10}), timeout=15)
    out = []
    for i, r in enumerate(d.get("results") or []):
        w, h = r.get("width"), r.get("height")
        if r.get("mature") or not r.get("url") or (w and h and max(w, h) < MIN_LONG_SIDE):
            continue
        out.append(cand("openverse", "image", title=r.get("title") or "", file_url=r["url"], width=w, height=h,
                        desc=" ".join(t.get("name", "") for t in r.get("tags") or []), license=ov_license(r),
                        license_url=r.get("license_url"), creator=r.get("creator") or "unknown",
                        source_url=r.get("foreign_landing_url"), provider=r.get("provider"),
                        engine_bonus=0.04 * (1 - i / 10)))
    return out


def _slug_title(url: str) -> str:
    slug = urllib.parse.urlsplit(url or "").path.rstrip("/").split("/")[-1]
    return re.sub(r"-?\d+$", "", slug).replace("-", " ").strip()


def _closest(files: list[dict], wkey="width", hkey="height") -> dict | None:
    """The rendition whose long side is closest to 1280-1920."""
    def dist(f):
        long_side = max(f[wkey], f[hkey])
        return 0 if 1280 <= long_side <= 1920 else min(abs(long_side - 1280), abs(long_side - 1920))
    files = [f for f in files if f.get(wkey) and f.get(hkey)]
    return min(files, key=lambda f: (dist(f), -max(f[wkey], f[hkey]))) if files else None


def search_pexels(ctx, q: Query, video: bool) -> list[dict]:
    params = {"query": q.core[:200], "per_page": 15, "orientation": "portrait" if q.vertical else "landscape"}
    url = ("https://api.pexels.com/videos/search?" if video else "https://api.pexels.com/v1/search?") + \
        urllib.parse.urlencode(params)
    d = ctx.http.get_json(url, headers={"Authorization": get_key("PEXELS_API_KEY")})  # key only to api.pexels.com
    out = []
    for i, r in enumerate(d.get("videos" if video else "photos") or []):
        page = r.get("url") or ""
        common = dict(source_url=page, license=PEXELS_LICENSE, license_url="https://www.pexels.com/license/",
                      stock=True, engine_bonus=0.05 * (1 - i / 15))
        if video:
            files = [f for f in r.get("video_files") or [] if f.get("file_type") == "video/mp4" and f.get("link")]
            f = _closest([f for f in files if f.get("quality") in ("hd", "uhd")] or files)
            if f:
                out.append(cand("pexels", "video", title=_slug_title(page), file_url=f["link"], width=f["width"],
                                height=f["height"], duration=r.get("duration"),
                                creator=(r.get("user") or {}).get("name") or "Pexels creator", **common))
        else:
            src = r.get("src") or {}
            if src.get("large2x") or src.get("original"):
                out.append(cand("pexels", "image", title=r.get("alt") or _slug_title(page),
                                file_url=src.get("large2x") or src.get("original"), width=r.get("width"),
                                height=r.get("height"), creator=r.get("photographer") or "Pexels creator", **common))
    return out


def search_pixabay(ctx, q: Query, video: bool) -> list[dict]:
    params = {"key": get_key("PIXABAY_API_KEY"), "q": q.core[:100], "per_page": 20, "safesearch": "true"}
    if not video:
        params.update(image_type="photo", orientation="vertical" if q.vertical else "horizontal")
    base = "https://pixabay.com/api/videos/?" if video else "https://pixabay.com/api/?"
    d = ctx.http.get_json(base + urllib.parse.urlencode(params))  # URL holds the key: never logged or stored
    out = []
    for i, r in enumerate(d.get("hits") or []):
        page = r.get("pageURL") or ""
        common = dict(source_url=page, license=PIXABAY_LICENSE, license_url="https://pixabay.com/service/license-summary/",
                      stock=True, engine_bonus=0.05 * (1 - i / 20), title=r.get("tags") or _slug_title(page),
                      creator=r.get("user") or "Pixabay creator")
        if video:
            vids = [v for v in (r.get("videos") or {}).values() if isinstance(v, dict) and v.get("url")]
            if q.vertical:
                vids = [v for v in vids if v.get("height", 0) > v.get("width", 0)] or vids
            v = _closest(vids)
            if v:
                out.append(cand("pixabay", "video", file_url=v["url"], width=v["width"], height=v["height"],
                                duration=r.get("duration"), **common))
        elif r.get("largeImageURL"):
            W, H = r.get("imageWidth") or 0, r.get("imageHeight") or 0
            s = 1280 / max(W, H, 1)
            out.append(cand("pixabay", "image", file_url=r["largeImageURL"], width=round(W * min(s, 1)),
                            height=round(H * min(s, 1)), **common))
    return out


def search_exa(ctx, q: Query) -> list[dict]:
    """Exa finds the page being discussed: its preview image + on-page images (editorial), and the URL to record."""
    d = ctx.http.post_json("https://api.exa.ai/search",
                           {"query": q.core, "numResults": 5, "type": "auto",
                            "contents": {"extras": {"imageLinks": 6}}},
                           headers={"x-api-key": get_key("EXA_API_KEY")}, timeout=30)
    out = []
    for i, r in enumerate(d.get("results") or []):
        url, title = r.get("url"), r.get("title") or ""
        if not url:
            continue
        if i < 2:
            ctx.sites.append((url, 0.95 - 0.05 * i, f"Exa result: {title[:60]}"))
        imgs = ([r["image"]] if r.get("image") else []) + list(((r.get("extras") or {}).get("imageLinks") or [])[:4])
        for j, u in enumerate(dict.fromkeys(x for x in imgs if isinstance(x, str))):
            if re.search(r"\.(svg|ico|gif)(\?|$)|logo|favicon|sprite|icon|avatar", u, re.I):
                continue
            out.append(cand("exa", "image", title=title, file_url=urllib.parse.urljoin(url, u), source_url=url,
                            license=EDITORIAL, creator=host_of(url), base=0.9 - 0.05 * i - 0.03 * j))
    return out


SEARCHERS = {
    "wikidata": search_wikidata,
    "nasa": lambda ctx, q: search_nasa(ctx, q, "image"),
    "nasa_video": lambda ctx, q: search_nasa(ctx, q, "video"),
    "commons": lambda ctx, q: search_commons(ctx, q, video=False),
    "commons_video": lambda ctx, q: search_commons(ctx, q, video=True),
    "loc": search_loc,
    "ia_image": lambda ctx, q: search_ia(ctx, q, "image"),
    "ia_video": lambda ctx, q: search_ia(ctx, q, "movies"),
    "openverse": search_openverse,
    "pexels": lambda ctx, q: search_pexels(ctx, q, video=False),
    "pexels_video": lambda ctx, q: search_pexels(ctx, q, video=True),
    "pixabay": lambda ctx, q: search_pixabay(ctx, q, video=False),
    "pixabay_video": lambda ctx, q: search_pixabay(ctx, q, video=True),
    "exa": search_exa,
}
SOURCE_KEY = {"pexels": "PEXELS_API_KEY", "pexels_video": "PEXELS_API_KEY", "pixabay": "PIXABAY_API_KEY",
              "pixabay_video": "PIXABAY_API_KEY", "exa": "EXA_API_KEY"}


def route_for(ctx, q: Query) -> list[str]:
    if ctx.network.offline:
        return []
    def has(*names):
        return [n for n in names if ctx.keys.get(SOURCE_KEY.get(n, ""), True)]
    stock_v, stock_p = has("pexels_video", "pixabay_video"), has("pexels", "pixabay")
    wd = ["wikidata"] if q.named else []
    ov = ["openverse"] if ctx.openverse else []
    if q.kind == "logo":
        return wd + ["commons"] + ov
    if ctx.mode == "fun" or q.kind == "gif":
        if q.wants_video:
            return stock_v + (["nasa_video"] if q.space else []) + ["commons_video", "ia_video"] + wd
        return stock_v + stock_p + wd + (["nasa"] if q.space else []) + ["commons", "loc", "ia_image"] + ov
    if ctx.mode == "documentary":           # archives only: no stock, no web pages
        if q.wants_video:
            return wd + (["nasa_video"] if q.space else []) + ["commons_video", "ia_video"]
        return wd + (["nasa"] if q.space else []) + ["commons", "loc", "ia_image"] + ov
    if q.kind == "video":
        return wd + (["nasa_video"] if q.space else []) + has("exa") + ["commons_video", "ia_video"] + stock_v
    return wd + has("exa") + (["nasa"] if q.space else []) + ["commons", "loc", "ia_image"] + stock_p + ov


# ----------------------------------------------------------------------------- official site: screenshot, scroll, og
def _og_from_html(http: Http, url: str) -> tuple[str | None, str | None, str | None]:
    page = http.get_bytes(url, 3 << 20, timeout=20).decode("utf-8", "replace")

    def meta(names):
        for m in re.finditer(r"<meta\b[^>]*>", page, re.I):
            tag = m.group(0)
            if re.search(r'(?:property|name)=["\'](?:' + names + r')["\']', tag, re.I):
                v = re.search(r'content=["\']([^"\']+)', tag, re.I)
                if v:
                    return html.unescape(v.group(1))
        return None
    tm = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    return (meta("og:image|twitter:image"), meta("og:video:secure_url|og:video:url|og:video|twitter:player:stream"),
            strip_html(tm.group(1)) if tm else None)


def capture_site(ctx, url: str, folder: Path, rel: float, why: str, scroll: bool = True) -> list[dict]:
    net = getattr(ctx, "network", None) or Network(folder)
    with net.request(url, "site capture"):
        fragment = urllib.parse.urlsplit(url.strip()).fragment
        url = safe_url(url) + ("#" + fragment if fragment else "")
        _check_host(url)
        return _capture_site(ctx, url, folder, rel, why, scroll, net)


def _capture_site(ctx, url: str, folder: Path, rel: float, why: str, scroll: bool, net: Network) -> list[dict]:
    out = []
    hid = h8(url)
    shot = folder / f"screenshot_{hid}.png"
    frames = ctx.tmp / f"frames_{hid}"
    ctx.tmp.mkdir(parents=True, exist_ok=True)
    if scroll:
        shutil.rmtree(frames, ignore_errors=True)
        frames.mkdir(parents=True)
    t = time.monotonic()
    try:
        from .tools import node_sidecar, sidecar_env
        node, sidecar = node_sidecar()
        env = sidecar_env(ctx.tmp)  # no stock keys; Chrome's throwaway profile stays inside the clip folder
        try:
            p = run(node, str(sidecar / "shot.cjs"), url, str(shot), *([str(frames)] if scroll else []), check=False,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240, env=env,
                               cwd=str(sidecar))
        except subprocess.TimeoutExpired as exc:
            net.capture_requests(exc.stdout)
            raise
        net.capture_requests(p.stdout)
        lines = [ln for ln in (p.stdout or "").splitlines() if ln.startswith("{")]
        res = json.loads(lines[-1]) if lines else {"ok": False, "error": (p.stderr or "no output")[-300:]}
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    http_error = isinstance(res.get("http_status"), int) and res["http_status"] >= 400
    if http_error:  # an error page is neither a screenshot nor a source of og tags
        res.update(ok=False, error=res.get("error") or f"HTTP {res['http_status']}", og_image=None, og_video=None)
    final = res.get("final_url") or url
    host = host_of(final)
    title = res.get("title") or host
    common = dict(license=EDITORIAL, creator=host, source_url=final)
    ctx.log["site"] = {"url": url, "why": why, "seconds": round(time.monotonic() - t, 1),
                       "blocked": res.get("blocked"), "http_status": res.get("http_status"), "error": res.get("error")}
    if res.get("ok") and not res.get("blocked") and shot.exists():
        try:
            ext, w, hh, alpha = validate_image(shot.read_bytes())
            out.append(cand("screenshot", "image", title=title, path=shot, width=w, height=hh, has_alpha=alpha,
                            mime="image/png", base=rel - 0.03, **common))
            ctx.health.ok("screenshot", 1)
        except Exception as e:
            ctx.health.fail("screenshot", e)
    else:
        ctx.health.fail("screenshot", RuntimeError(res.get("error") or ("bot wall" if res.get("blocked") else "failed")))
    if shot.exists() and not any(c["source"] == "screenshot" for c in out):
        shot.unlink()
    if scroll and res.get("ok") and res.get("frames") and not res.get("blocked"):
        mp4 = folder / f"scroll_{hid}.mp4"
        try:
            run(str(FFMPEG), "-v", "error", "-y", "-framerate", "30", "-i", str(frames / "f%04d.jpg"),
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(mp4), capture_output=True, timeout=180)
            info = probe_video(mp4)
            out.append(cand("scroll", "video", title=f"{title} (6 s scroll)", path=mp4, mime="video/mp4",
                            base=rel + 0.02, notes=f"scrolls {res.get('scroll_px')}px of {host}", **info, **common))
            ctx.health.ok("scroll", 1)
        except Exception as e:
            mp4.unlink(missing_ok=True)
            ctx.health.fail("scroll", e)
    shutil.rmtree(frames, ignore_errors=True)
    og_img, og_vid = res.get("og_image"), res.get("og_video")
    if not res.get("ok") and not http_error:
        try:
            og_img, og_vid, t2 = _og_from_html(ctx.http, url)
            title = t2 or title
        except Exception as e:
            ctx.health.fail("ogimage", e)
    if og_img:
        out.append(cand("ogimage", "image", title=title, file_url=urllib.parse.urljoin(final, og_img),
                        base=rel - 0.08, notes="page og:image", **common))
    if og_vid and re.search(r"\.(mp4|webm|mov)(\?|$)", og_vid, re.I) and \
            not re.search(r"youtube|youtu\.be|vimeo", og_vid, re.I):
        out.append(cand("ogvideo", "video", title=title, file_url=urllib.parse.urljoin(final, og_vid),
                        base=rel, notes="page og:video", **common))
    return out


# ----------------------------------------------------------------------------- download + validate
def validate_image(data: bytes):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        im = Image.open(io.BytesIO(data))
        fmt = im.format
        im.verify()  # structural check; the object is unusable afterwards, so reopen for size
        im = Image.open(io.BytesIO(data))
        w, h = im.size
        alpha = "A" in im.getbands() or (im.mode == "P" and "transparency" in im.info)
    ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(fmt)
    if not ext:
        raise ValueError(f"unsupported image format {fmt}")
    return ext, w, h, alpha


def dhash(data: bytes) -> int:
    """64-bit difference hash; catches the same photo re-hosted on another source."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        im = Image.open(io.BytesIO(data))
        im.draft("L", (64, 64))
        if im.mode in ("P", "PA", "LA", "RGBA") or "transparency" in im.info:
            im = im.convert("RGBA")  # flatten onto white: transparent pixels are often black and would hash alike
            im = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im)
        px = list(im.convert("L").resize((9, 8), Image.BILINEAR).tobytes())
    bits = 0
    for r in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[r * 9 + col] > px[r * 9 + col + 1])
    return bits


def _video_url(url, network: Network):
    final = safe_url(url)

    def checked(value):
        nonlocal final
        final = _public_url(value)
        return final

    for method in ("HEAD", "GET"):
        try:
            headers = {"User-Agent": UA, **({"Range": "bytes=0-0"} if method == "GET" else {})}
            with network.open(final, "video redirect", headers=headers, method=method, validate=checked):
                return final
        except urllib.error.HTTPError as exc:
            exc.close()
            if method != "HEAD" or exc.code not in (403, 405, 501):
                raise


@cache
def _redirect_support():
    with tools.process([str(FFMPEG), "-hide_banner", "-h", "protocol=http"], stdin=subprocess.DEVNULL,
                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as p, p:
        try:
            output, _ = p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            raise
    if p.returncode != 0 or b"max_redirects" not in output:
        raise ValueError("FFmpeg cannot disable redirects")
    return True


def _max_redirects():
    try:
        return _redirect_support()
    except Exception:
        return False


_max_redirects.cache_clear = _redirect_support.cache_clear


def _run_video(net, url, purpose, argv, **kwargs):
    with net.request(url, purpose):
        _check_host(url)
        try:
            result = run(*argv, check=False, **kwargs)
        except subprocess.TimeoutExpired as exc:
            net.video_requests(exc.stderr, url, purpose)
            raise
        net.video_requests(result.stderr, url, purpose)
        return result


def probe_video(path_or_url, *, project: Path | None = None) -> dict:
    """ffprobe a local file (magic-checked) or a remote http(s) URL; returns width/height/duration/codec."""
    src = str(path_or_url)
    if isinstance(path_or_url, Path):
        with open(path_or_url, "rb") as f:
            head = f.read(16)
        mov = path_or_url.suffix.lower() == ".mov" and head[4:8] in (b"moov", b"mdat", b"wide")
        if head[4:8] != b"ftyp" and head[:4] != b"\x1a\x45\xdf\xa3" and not mov:
            raise ValueError("not an mp4/webm container")
        args = ["-protocol_whitelist", "file,pipe", src]
    else:
        Network(project).check("video probe")
        src = _video_url(src, Network(project))
        if not _max_redirects():
            with TemporaryDirectory(prefix="zing-video-", dir=project) as tmp:
                part = Path(tmp) / "video.part"
                Http(project=project).download_to(src, part, VID_CAP)
                return probe_video(part)
        args = ["-user_agent", UA, "-protocol_whitelist", "https,http,tls,tcp", "-max_redirects", "0", src]
    remote = not isinstance(path_or_url, Path)
    argv = [str(FFPROBE), "-v", "debug" if remote else "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height,codec_name:format=duration", "-of", "json"] + args
    options = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    p = _run_video(Network(project), src, "video probe", argv, **options) if remote else \
        run(*argv, check=False, **options)
    d = json.loads(p.stdout or "{}")
    st = (d.get("streams") or [{}])[0]
    if not st.get("width"):
        raise ValueError("no video stream: " + scrub((p.stderr or "").strip().splitlines()[-1:][0][:120]
                                                     if (p.stderr or "").strip() else "empty probe"))
    return {"width": st["width"], "height": st["height"], "codec": st.get("codec_name"),
            "duration_s": round(float((d.get("format") or {}).get("duration") or 0), 1)}


def resolve_urls(ctx, c: dict) -> list[str]:
    src = c["source"]
    if src == "nasa" and not c.get("file_url"):
        assets = [u for u in ctx.http.get_json(c["collection"]) if isinstance(u, str)]
        # NASA's ~mobile/~small mp4s are 320-640 px wide (below the rule), so medium/large come first
        order = ["~medium.mp4", "~large.mp4"] if c["media_type"] == "video" else \
            ["~large.jpg", "~orig.jpg", "~orig.png", "~orig.jpeg", "~medium.jpg"]
        return [u for suffix in order for u in assets if u.lower().endswith(suffix)][:2]
    if src == "ia":
        md = ctx.http.get_json(f"https://archive.org/metadata/{urllib.parse.quote(c['ia_id'])}", timeout=30)
        base = f"https://archive.org/download/{urllib.parse.quote(c['ia_id'])}/"
        files = md.get("files") or []
        if c["media_type"] == "video":
            vids = [f for f in files if str(f.get("name", "")).lower().endswith((".mp4", ".webm"))]
            vids.sort(key=lambda f: (-_int(f.get("height")), _int(f.get("size"))))
            return [base + urllib.parse.quote(f["name"]) for f in vids[:2]]
        imgs = [f for f in files if f.get("format") in ("JPEG", "PNG") and 0 < _int(f.get("size")) < IMG_CAP]
        imgs.sort(key=lambda f: -_int(f.get("size")))
        return [base + urllib.parse.quote(f["name"]) for f in imgs[:2]]
    if src == "loc" and c.get("rights_pending"):
        try:
            item = ctx.http.get_json(c["item_url"].split("?")[0].rstrip("/") + "/?fo=json", timeout=30).get("item") or {}
            adv = item.get("rights_advisory")
            c["rights_advisory"] = strip_html(adv)
            c["license"] = c["rights_advisory"] or "see source page"
        except FactoryError:
            raise
        except Exception:
            c["rights_advisory"] = ""
        c["rights_pending"] = False
    return [c["file_url"]] if c.get("file_url") else []


def fetch_video(ctx, c: dict, url: str, folder: Path):
    ctx.network.check("video download")
    ext = "webm" if re.search(r"\.webm(\?|$)", url, re.I) or "webm" in (c.get("mime") or "") else "mp4"
    final = folder / f"{c['source']}_{h8(url)}.{ext}"
    part = final.with_name(final.name + ".part")
    downloaded = part.with_name(part.name + ".download")
    try:
        local = not _max_redirects()
        if local:
            src = _video_url(url, ctx.network)
            c["bytes"] = ctx.http.download_to(src, part, VID_CAP)
            remote = probe_video(part)
        elif c.get("width") and c.get("height") and c.get("duration"):
            remote = {"width": c["width"], "height": c["height"], "duration_s": float(c["duration"])}
        else:
            remote = probe_video(url, project=ctx.network.project)
        if max(remote["width"], remote["height"]) < ctx.min_video:
            raise ValueError(f"video too small {remote['width']}x{remote['height']}")
        dur = float(c.get("duration") or remote["duration_s"] or 0)
        if 0 < dur <= EXCERPT_S + 10:
            if not local:
                c["bytes"] = ctx.http.download_to(url, part, VID_CAP)
        else:  # long video: cut a 20 s excerpt over HTTP range requests (no full download)
            start = min(0.15 * dur, 60.0)
            info = None
            if local:
                part.replace(downloaded)
            # input-side seek is fast (mp4); some hosts' webm can't seek remotely, so fall back to reading from
            # the start and seeking on the output side (bounded at 15 s so we don't stream much)
            for seek_in, s in ((True, start), (False, min(start, 15.0))):
                src = str(downloaded) if local else _video_url(url, ctx.network)
                seek = ["-ss", f"{s:.1f}"]
                args = ["-protocol_whitelist", "file,pipe"] if local else [
                    "-user_agent", UA, "-protocol_whitelist", "https,http,tls,tcp", "-max_redirects", "0"]
                argv = [str(FFMPEG), "-v", "debug", "-y"] + args + (seek if seek_in else []) + \
                    ["-i", src] + ([] if seek_in else seek) + \
                    ["-t", str(EXCERPT_S), "-fs", str(VID_CAP), "-map", "0:v:0", "-c", "copy", "-an", "-f", ext, str(part)]
                if local:
                    run(*argv, check=False, capture_output=True, timeout=180)
                else:
                    _run_video(ctx.network, src, "video excerpt", argv, capture_output=True, timeout=180)
                if part.is_file() and part.stat().st_size >= VID_CAP:
                    raise ValueError("video exceeds the byte limit")
                try:
                    info = probe_video(part)
                    start = s
                    break
                except Exception:
                    continue
            if not info:
                raise ValueError("could not cut a playable excerpt")
            c["notes"] = (c.get("notes", "") + f"; {EXCERPT_S}s excerpt from {start:.0f}s of {dur:.0f}s").strip("; ")
        if 0 < dur <= EXCERPT_S + 10:
            info = probe_video(part)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    finally:
        downloaded.unlink(missing_ok=True)
    final.unlink(missing_ok=True)
    part.rename(final)
    c.update(info, path=final, file_url=safe_url(url), mime=f"video/{ext}")


def fetch_candidate(ctx, c: dict, folder: Path, hashes: list[int]) -> dict:
    if c.get("local_path"):
        src = c["local_path"]
        path = folder / f"local_{h8(str(src))}{src.suffix.lower()}"
        shutil.copyfile(src, path)
        c["path"] = path
        return c
    if c.get("path"):  # captured locally (site screenshot / scroll recording)
        if c["media_type"] == "image":
            dh = dhash(c["path"].read_bytes())
            if any(bin(dh ^ o).count("1") <= 10 for o in hashes):
                raise ValueError("near-duplicate of a better-ranked pick")
            hashes.append(dh)
        return c
    ctx.network.check("visual download")
    urls = resolve_urls(ctx, c)
    if not urls:
        raise ValueError("no downloadable asset")
    last = None
    for url in urls:
        try:
            if c["media_type"] == "video":
                try:
                    fetch_video(ctx, c, url, folder)
                except Exception as e:
                    if "429" not in str(e):
                        raise
                    time.sleep(11)  # Wikimedia asks for retry-after 10 s; one retry, then give up
                    fetch_video(ctx, c, url, folder)
            else:
                data = ctx.http.get_bytes(url, IMG_CAP)
                ext, w, h, alpha = validate_image(data)
                if max(w, h) < MIN_LONG_SIDE:
                    raise ValueError(f"image too small {w}x{h}")
                dh = dhash(data)
                if any(bin(dh ^ o).count("1") <= 10 for o in hashes):
                    raise ValueError("near-duplicate of a better-ranked pick")
                final = folder / f"{c['source']}_{h8(url)}.{ext}"
                final.write_bytes(data)
                hashes.append(dh)
                c.update(width=w, height=h, has_alpha=alpha, path=final, file_url=safe_url(url),
                         mime={"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[ext])
            return c
        except FactoryError:
            raise
        except Exception as e:  # try the next rendition, if any
            last = e
    raise last


# ----------------------------------------------------------------------------- per request
class Ctx:
    def __init__(self, outdir: Path, mode: str = "context", public: bool = False, openverse: bool = False,
                 min_video: int = MIN_LONG_SIDE, maxc: int = 5, *, project: Path | None = None,
                 visuals: Path | None = None):
        self.network = Network(project or outdir)
        self.http, self.health = Http(project=self.network.project), Health()
        self.visuals = Path(visuals) if visuals else None
        self.mode, self.public, self.openverse = mode, public, openverse
        self.min_video, self.maxc = min_video, max(1, min(5, maxc))
        self.tmp = outdir / "_tmp"
        self.keys = {n: bool(get_key(n)) for n in KEY_NAMES}
        self.sites: list[tuple[str, float, str]] = []
        self.log: dict = {}


def local_candidates(ctx, q: Query) -> list[dict]:
    if ctx.visuals is None:
        return []
    found = []
    for path in sorted(ctx.visuals.iterdir()):
        if not path.is_file() or path.suffix.lower() not in LOCAL:
            continue
        video = path.suffix.lower() in (".mp4", ".mov", ".webm")
        try:
            if video:
                info = probe_video(path)
            else:
                ext, w, h, alpha = validate_image(path.read_bytes())
                info = {"width": w, "height": h, "has_alpha": alpha,
                        "mime": {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[ext]}
        except (OSError, ValueError) as exc:
            ctx.log["rejected"].append({"title": path.name, "source": "local", "why": str(exc)[:160]})
            continue
        hits = len(terms(path.stem) & set(q.weights)) / max(1, len(q.weights))
        found.append(cand("local", "video" if video else "image", title=path.name, local_path=path,
                          bytes=path.stat().st_size, base=.75 + .4 * hits, **info))
    return found


def gather(ctx, q: Query, route: list[str]) -> list[dict]:
    if route:
        ctx.network.check("visual search")
    found, seen = [], set()
    for pos, src in enumerate(route):
        ctx.log["route"].append(src)
        base = src.replace("_video", "").replace("_image", "")
        if base in ctx.health.down:
            ctx.log["notes"].append(f"{src} skipped (disabled after an earlier failure)")
            continue
        try:
            res = SEARCHERS[src](ctx, q)
            ctx.health.ok(base, len(res))
        except FactoryError:
            raise
        except Exception as e:
            ctx.log["notes"].append(f"{src}: " + ctx.health.fail(base, e))
            continue
        for c in res:
            key = c.get("source_url") or c.get("file_url")
            if key in seen:
                continue
            seen.add(key)
            c["route_bonus"] = [0.06, 0.04, 0.02][pos] if pos < 3 else 0.0
            found.append(c)
    return found


def rank(cands: list[dict], q: Query, log: dict) -> list[dict]:
    scored = []
    for c in cands:
        s = score(c, q)
        if s is None:
            log["rejected"].append({"title": c["title"][:80], "source": c["source"], "why": "no title match"})
            continue
        c["score"] = s
        c["rights"], c["credit_text"] = rights_for(c)
        scored.append(c)
    scored.sort(key=lambda c: -c["score"])
    seen_titles: Counter = Counter()
    for c in scored:  # nudge same-titled items (one NASA shoot, one timestamped Commons batch) down
        k = re.sub(r"\s+", " ", re.sub(r"\d+", " ", flat(c["title"])))
        c["score"] -= 0.08 * seen_titles[k]
        seen_titles[k] += 1
    out, used, pool = [], Counter(), scored[:]
    while pool:  # greedy variety: each extra pick from the same source costs a little
        b = max(pool, key=lambda c: c["score"] - 0.06 * used[c["source"]])
        pool.remove(b)
        out.append(b)
        used[b["source"]] += 1
    return out


def download_ranked(ctx, ranked: list[dict], q: Query, folder: Path) -> list[dict]:
    got, hashes, tries, downloads = [], [], 0, 0
    limit = 8 if q.wants_video else 12  # actual downloads; size/res skips decided from metadata don't count
    for c in ranked:
        if len(got) >= ctx.maxc or downloads >= limit or tries >= 22:
            break
        why = None
        if c["score"] < 0.2:
            why = f"score {c['score']:.2f}"
        elif ctx.public and not c.get("rights_pending") and c["rights"] not in ("cleared", "attribution"):
            why = f"--public: rights {c['rights']}"
        if why:
            ctx.log["rejected"].append({"title": c["title"][:80], "source": c["source"], "why": why})
            continue
        tries += 1
        try:
            fetch_candidate(ctx, c, folder, hashes)
            c["rights"], c["credit_text"] = rights_for(c)  # LoC rights are known only after the item lookup
            if ctx.public and c["rights"] not in ("cleared", "attribution"):
                c["path"].unlink(missing_ok=True)
                raise ValueError(f"--public: rights {c['rights']}")
            got.append(c)
            downloads += 1
            ctx.health.e(c["source"])["downloads"] += 1
        except FactoryError:
            raise
        except Exception as e:
            downloads += 0 if isinstance(e, TooLarge) or "too small" in str(e) else 1
            ctx.log["rejected"].append({"title": c["title"][:80], "source": c["source"],
                                        "why": scrub(f"{type(e).__name__}: {e}")[:160]})
    return got


def process(ctx, req: dict, folder: Path) -> list[dict]:
    kind = req.get("kind") or "photo"
    q = Query(req, kind, ctx.mode)
    ctx.sites = []
    ctx.log = {"query": req["query"], "kind": kind, "mode": ctx.mode, "route": [], "entities": [],
               "rejected": [], "notes": []}
    folder.mkdir(parents=True, exist_ok=True)
    for f in folder.iterdir():  # clear only files this tool (or the picker's thumbnail cache) wrote before
        if f.is_file() and OUR_FILE.match(f.name):
            f.unlink()
    if kind == "screenshot" and not req.get("url"):
        ctx.log["notes"].append("no url given; searched for a photo instead")
        q = Query(req, "photo", ctx.mode)
    found = local_candidates(ctx, q) + gather(ctx, q, [] if kind == "screenshot" else route_for(ctx, q))
    # official site / given url: screenshot + scroll recording + og media (context mode, or an explicit url)
    site = None
    if ctx.network.offline:
        ctx.log["notes"].append("offline project; only your files are used")
    elif req.get("url"):
        site = (req["url"], 1.15, "request url")
    elif ctx.mode == "context" and kind in ("photo", "video") and ctx.sites:
        site = ctx.sites[0]
    if site and not (ctx.public and kind != "screenshot"):
        found += capture_site(ctx, site[0], folder, site[1], site[2])
    elif site:
        ctx.log["notes"].append("--public: skipped site capture (editorial only)")
    got = download_ranked(ctx, rank(found, q, ctx.log), q, folder)
    if not got and q.wants_video:
        ctx.log["notes"].append("no usable video; fell back to stills")
        q2 = Query(req, "photo", ctx.mode)
        got = download_ranked(ctx, rank(local_candidates(ctx, q2) + gather(ctx, q2, route_for(ctx, q2)), q2, ctx.log), q2, folder)
        for c in got:
            c["notes"] = (c.get("notes", "") + "; still fallback for a video request").strip("; ")
        q = q2
    for c in found:  # local captures that didn't make the cut
        if c.get("path") and c not in got:
            Path(c["path"]).unlink(missing_ok=True)
    return finalize(got, q, folder, ctx.maxc)


def finalize(got: list[dict], q: Query, folder: Path, maxc: int) -> list[dict]:
    for c in got:  # re-score with the real pixel size
        c["score"] = score(c, q) or c["score"]
    got.sort(key=lambda c: -c["score"])
    out = []
    for i, c in enumerate(got[:maxc], 1):
        rec = {"rank": i, "path": f"{folder.name}/{Path(c['path']).name}", "media_type": c["media_type"],
               "width": c.get("width"), "height": c.get("height"), "source": c["source"],
               "license": c.get("license"), "license_url": c.get("license_url"), "creator": c.get("creator"),
               "source_url": c.get("source_url"), "title": c.get("title"), "file_url": c.get("file_url"),
               "rights": c.get("rights"), "credit_text": c.get("credit_text"),
               "score": round(c["score"], 3), "matched_terms": c.get("matched_terms", [])}
        if c["media_type"] == "video":
            rec.update(duration_s=c.get("duration_s"), codec=c.get("codec"), mime=c.get("mime") or "video/mp4")
        else:
            rec.update(mime=c.get("mime"), has_alpha=c.get("has_alpha", False))
        for k in ("entity", "notes", "bytes"):
            if c.get(k):
                rec[k] = c[k]
        out.append(rec)
    for c in got[maxc:]:
        Path(c["path"]).unlink(missing_ok=True)
    return out


# ----------------------------------------------------------------------------- contact sheet
def _font(size):
    for name in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _thumb(path: Path, media: str, box: tuple[int, int], duration=None) -> Image.Image:
    cell = Image.new("RGB", box, (40, 40, 44))
    try:
        if media == "video":  # sample ~35% in: openings are often title slates
            at = f"{max(0.5, 0.35 * (duration or 4)):.1f}"
            p = run(str(FFMPEG), "-v", "error", "-ss", at, "-i", str(path), "-frames:v", "1",
                    "-f", "image2pipe", "-vcodec", "png", "-", check=False, capture_output=True, timeout=60)
            im = Image.open(io.BytesIO(p.stdout))
        else:
            im = Image.open(path)
        im.load()
        im.thumbnail(box)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            checker = Image.new("RGBA", im.size, (200, 200, 200, 255))
            d = ImageDraw.Draw(checker)
            for y in range(0, im.size[1], 16):
                for x in range(0, im.size[0], 16):
                    if (x // 16 + y // 16) % 2:
                        d.rectangle([x, y, x + 15, y + 15], fill=(150, 150, 150, 255))
            im = Image.alpha_composite(checker, im)
        cell.paste(im.convert("RGB"), ((box[0] - im.size[0]) // 2, (box[1] - im.size[1]) // 2))
    except Exception as e:
        ImageDraw.Draw(cell).text((10, 10), f"preview failed: {e}"[:60], fill=(255, 120, 120), font=_font(14))
    return cell


def contact_sheet(manifest: dict, outdir: Path, requests: list[dict], mode: str) -> Path:
    big, small, label_w, pad = (432, 384), (216, 186), 300, 12
    rows = list(manifest.items())
    W = label_w + big[0] + 2 * small[0] + 4 * pad
    H = len(rows) * (big[1] + 2 * pad) + 50
    sheet = Image.new("RGB", (W, H), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    f_b, f_s = _font(18), _font(13)
    d.text((pad, 14), f"find_visuals contact sheet  |  mode: {mode}  |  #1 large, #2-#5 small", fill=(255, 210, 63), font=f_b)
    byid = {r["_safe"]: r for r in requests}
    for i, (rid, cands) in enumerate(rows):
        y = 50 + i * (big[1] + 2 * pad)
        r = byid.get(rid, {})
        lines = [rid, f"{r.get('kind', '')}: {r.get('query', '')}"]
        if cands:
            c = cands[0]
            lines += [f"{c['source']} | {c.get('width')}x{c.get('height')} {c['media_type']}"
                      + (f" {c.get('duration_s')}s" if c["media_type"] == "video" else ""),
                      f"rights: {c.get('rights')} | {c.get('license')}", f"credit: {c.get('credit_text') or ''}",
                      f"title: {(c.get('title') or '')[:70]}",
                      f"{len(cands)} cands: " + " ".join(f"{x['source']}{'(v)' if x['media_type'] == 'video' else ''}" for x in cands)]
        else:
            lines.append("NO CANDIDATES")
        ty = y
        for j, ln in enumerate(lines):
            for chunk in [ln[k:k + 38] for k in range(0, max(len(ln), 1), 38)][:3 if j in (4, 5, 6) else 2]:
                d.text((pad, ty), chunk, fill=(240, 240, 240) if j else (255, 210, 63), font=f_b if j == 0 else f_s)
                ty += 22 if j == 0 else 17
        x0 = label_w + pad
        for k, c in enumerate(cands[:5]):
            if k == 0:
                box, x, cy = big, x0, y
            else:
                box = small
                x = x0 + big[0] + pad + ((k - 1) % 2) * (small[0] + pad)
                cy = y + ((k - 1) // 2) * (small[1] + pad)
            sheet.paste(_thumb(outdir / c["path"], c["media_type"], box, c.get("duration_s")), (x, cy))
            if k == 0:
                d.rectangle([x - 2, cy - 2, x + box[0] + 1, cy + box[1] + 1], outline=(255, 210, 63), width=2)
            tag = f"#{k + 1} {c['source']}{' VIDEO' if c['media_type'] == 'video' else ''} [{c.get('rights')}]"
            d.rectangle([x, cy + box[1] - 18, x + 8 + 7 * len(tag), cy + box[1]], fill=(0, 0, 0))
            d.text((x + 4, cy + box[1] - 18), tag, fill=(255, 255, 255), font=f_s)
    path = outdir / "contact_sheet.jpg"
    sheet.save(path, quality=88)
    return path


# ----------------------------------------------------------------------------- entry point
def find(requests: list[dict], outdir: Path, mode: str = "context", *, public: bool = False, openverse: bool = False,
         maxc: int = 5, min_video: int = MIN_LONG_SIDE, sheet: bool = True, say=print,
         project: Path | None = None, visuals: Path | None = None) -> dict:
    """Search, download and rank candidates for every request; returns the manifest written to outdir."""
    from .pipeline import _write
    if mode not in ("context", "fun", "documentary"):
        raise ValueError("mode must be 'context', 'fun' or 'documentary'")
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    ctx = Ctx(outdir, mode, public, openverse, min_video, maxc, project=project, visuals=visuals)
    keys = {n: ("present" if v else "absent") for n, v in ctx.keys.items()}
    skipped = [f"{s}: {SOURCE_KEY[s]} absent" for s in ("pexels", "pixabay", "exa") if not ctx.keys[SOURCE_KEY[s]]]
    if not openverse:
        skipped.append("openverse: off by default")
    manifest, logs, used = {}, {}, set()
    for req in requests:
        if not isinstance(req, dict) or not req.get("id") or not req.get("query"):
            say(f"skipping malformed request: {str(req)[:80]}")
            continue
        if (req.get("kind") or "photo") not in KINDS:
            req["kind"] = "photo"
        safe = visual_id(req["id"], used)
        req["_safe"] = safe
        folder = (outdir / safe).resolve()
        if not folder.is_relative_to(outdir):
            continue
        t = time.monotonic()
        try:
            cands = process(ctx, req, folder)
            log = ctx.log
        except FactoryError:
            raise
        except Exception as e:
            cands, log = [], {"query": req["query"], "kind": req.get("kind"), "error": scrub(f"{type(e).__name__}: {e}")}
        log["seconds"] = round(time.monotonic() - t, 1)
        manifest[safe], logs[safe] = cands, log
        mix = " ".join(f"{c['source']}{'(v)' if c['media_type'] == 'video' else ''}" for c in cands)
        say(f"  [{safe}] {req.get('kind', 'photo')} '{req['query']}' -> {len(cands)} in {log['seconds']}s: {mix}")
    try:
        ctx.tmp.rmdir()
    except OSError:
        pass
    _write(outdir / "manifest.json", manifest)
    (outdir / "run_log.json").write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": mode, "public": public,
        "runtime_s": round(time.monotonic() - t0, 1), "http_requests": ctx.http.count, "keys": keys,
        "skipped_sources": skipped, "sources": ctx.health.d, "disabled_sources": sorted(ctx.health.down),
        "requests": logs}, indent=2, ensure_ascii=False), encoding="utf-8")
    if sheet and manifest:
        contact_sheet(manifest, outdir, [r for r in requests if isinstance(r, dict) and "_safe" in r], mode)
    return manifest
