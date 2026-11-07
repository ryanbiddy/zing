"""Channel settings and source grants."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import time as _time
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from myzing.factory import campaign, pipeline, render
from myzing.factory.tools import FactoryError
from myzing.playbook import feeds
from myzing.storage import workspace_root

KINDS = ("youtube", "podcast", "uoink", "folder", "own", "recordings")
HANDLES = ("youtube", "tiktok", "instagram", "x")
DEFAULTS = {"network": {}, "handles": {}, "factory": {}, "sources": [], "series": [],
            "judge": "host", "visuals": "cleared",
            "publish": {"youtube": "off"}, "youtube_category": "22", "youtube_daily_cap": 6,
            "cadence": {"per_day": 3, "times": ["12:00", "17:00", "20:00"], "timezone": "local"},
            "approval": {"policy": "manual", "veto_hours": 6, "manual_first": 30}, "seeding": {"every": 8}}


class ChannelError(ValueError):
    """A channel setting or local operation needs attention."""


class _Local(tzinfo):
    """This computer's own clock, daylight saving included; Windows Python has no IANA database without tzdata."""

    def utcoffset(self, dt):
        stamp = _time.mktime((dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, 0, 0, -1))
        return timedelta(seconds=_time.localtime(stamp).tm_gmtoff)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "local"

    def fromutc(self, dt):
        local = _time.localtime((dt.replace(tzinfo=None) - datetime(1970, 1, 1)) // timedelta(seconds=1))
        return datetime(*local[:6], dt.microsecond, tzinfo=self)

    def __repr__(self):
        return "local"


LOCAL = _Local()


def zone(name: str) -> tzinfo:
    """'local', a fixed offset such as UTC-08:00, or an IANA name when this Python has time zone data."""
    if name == "local":
        return LOCAL
    offset = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", name)
    if offset:
        hours, minutes = int(offset[2]), int(offset[3])
        if hours > 14 or minutes > 59:
            raise ChannelError("cadence.timezone offsets run from UTC-14:00 to UTC+14:00")
        sign = -1 if offset[1] == "-" else 1
        return timezone(sign * timedelta(hours=hours, minutes=minutes))
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ChannelError(f"cadence.timezone {name!r} is not known here. Use local, an offset such as UTC-08:00, "
                           "or an IANA name after pip install tzdata") from None


def home() -> Path:
    return Path(os.environ.get("ZING_CHANNELS_HOME") or workspace_root() / "channels").expanduser().resolve()


def _slug(value, field="slug") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) or len(value) > 60:
        raise ChannelError(f"{field} must use lowercase letters, digits and single dashes")
    if value in {"con", "prn", "aux", "nul", *[f"com{i}" for i in range(1, 10)], *[f"lpt{i}" for i in range(1, 10)]}:
        raise ChannelError(f"{field} is a reserved file name")
    return value


def directory(slug: str) -> Path:
    root = home()
    path = (root / _slug(slug)).resolve()
    if not path.is_relative_to(root):
        raise ChannelError("slug must stay inside the channels folder")
    return path


def _fields(value, allowed, field):
    if not isinstance(value, dict):
        raise ChannelError(f"{field} must be an object")
    extra = set(value) - set(allowed)
    if extra:
        raise ChannelError(f"{field}.{sorted(extra)[0]} is not a known field")


def _text(value, field, *, required=False, most=None):
    if not isinstance(value, str) or (required and not value.strip()) or (most is not None and len(value) > most):
        limit = f" of up to {most} characters" if most is not None else ""
        raise ChannelError(f"{field} must be {'non-empty ' if required else ''}text{limit}")


def _integer(value, field, least, most=None):
    if type(value) is not int or value < least or (most is not None and value > most):
        limit = f"between {least} and {most}" if most is not None else f"at least {least}"
        raise ChannelError(f"{field} must be an integer {limit}")


def web_url(value, field):
    _text(value, field)
    try:
        parts = urlsplit(value)
        good = parts.scheme in ("http", "https") and parts.hostname and not any(c.isspace() for c in value)
    except ValueError:
        good = False
    if not good:
        raise ChannelError(f"{field} must be an http or https URL")


def validate(data: dict) -> dict:
    _fields(data, {"schema_version", "slug", "name", "niche", "created", "prior", "youtube", "phone_folder", *DEFAULTS}, "channel")
    data = copy.deepcopy(data)
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ChannelError("schema_version must be 1")
    _text(data.get("name"), "name", required=True)
    _text(data.get("niche"), "niche", required=True, most=200)
    data["slug"] = _slug(data.get("slug", pipeline.show_slug(data["name"])))
    _text(data.get("created"), "created", required=True)
    if "prior" in data:
        _text(data["prior"], "prior", required=True)
    if "phone_folder" in data:
        _text(data["phone_folder"], "phone_folder", required=True)
    try:
        datetime.fromisoformat(data["created"])
    except ValueError:
        raise ChannelError("created must be an ISO date and time") from None
    for key, default in DEFAULTS.items():
        value = data.get(key, copy.deepcopy(default))
        if isinstance(default, dict):
            fields = {"network": {"name", "line", "url"}, "handles": HANDLES,
                      "factory": {"pack", "mode", "shapes", "moments", "focus", "vocab", "brief"}}.get(key, default)
            _fields(value, fields, key)
            value = {**copy.deepcopy(default), **value}
        data[key] = value
    if data["judge"] not in ("host", "claude"):
        raise ChannelError("judge must be host or claude")
    if data["visuals"] not in ("cleared", "editorial"):
        raise ChannelError("visuals must be cleared or editorial")
    if data["publish"]["youtube"] not in ("off", "private", "scheduled"):
        raise ChannelError("publish.youtube must be off, private or scheduled")
    _text(data["youtube_category"], "youtube_category", required=True)
    if not re.fullmatch(r"[1-9][0-9]*", data["youtube_category"]):
        raise ChannelError("youtube_category must be a numeric category ID")
    _integer(data["youtube_daily_cap"], "youtube_daily_cap", 0)
    if "youtube" in data:
        _fields(data["youtube"], {"channel_id", "title", "connected_at"}, "youtube")
        for key in ("channel_id", "title", "connected_at"):
            _text(data["youtube"].get(key), f"youtube.{key}", required=True)
        try:
            if datetime.fromisoformat(data["youtube"]["connected_at"]).tzinfo is None:
                raise ValueError
        except ValueError:
            raise ChannelError("youtube.connected_at must be an ISO date and time with a timezone") from None
    for key, value in data["network"].items():
        _text(value, f"network.{key}")
    if data["network"].get("url"):
        web_url(data["network"]["url"], "network.url")
    for key, value in data["handles"].items():
        _text(value, f"handles.{key}")
    factory = data["factory"]
    pack = factory.get("pack", pipeline.SETTINGS["pack"])
    _text(pack, "factory.pack", required=True)
    try:
        render.theme(pack)
    except (FactoryError, OSError, ValueError) as exc:
        raise ChannelError(f"factory.pack is invalid. {exc}") from exc
    if factory.get("mode", "context") not in pipeline.MODES:
        raise ChannelError("factory.mode must be context, fun, documentary or launch")
    shapes = factory.get("shapes", pipeline.SETTINGS["shapes"])
    if (not isinstance(shapes, list) or any(not isinstance(s, str) or s not in render.SHAPES for s in shapes)
            or "9x16" not in shapes or len(set(shapes)) != len(shapes)):
        raise ChannelError("factory.shapes must list unique factory shapes and include 9x16")
    if "moments" in factory:
        _integer(factory["moments"], "factory.moments", 0)
    if "focus" in factory:
        _text(factory["focus"], "factory.focus", required=True, most=300)
    if "vocab" in factory:
        from myzing.study.asr_hygiene import vocabulary_context
        vocab = factory["vocab"]
        if not isinstance(vocab, list) or any(not isinstance(s, str) or not s.strip() for s in vocab):
            raise ChannelError("factory.vocab must be a list of non-empty text")
        checked = vocabulary_context(vocab)
        if checked["omitted"]:
            raise ChannelError(f"factory.vocab is invalid. {checked['omitted'][0]['reason']}")
        factory["vocab"] = checked["terms"]
    if "brief" in factory:
        try:
            factory["brief"] = campaign.validate(factory["brief"])
        except FactoryError as exc:
            raise ChannelError(f"factory.brief is invalid. {exc}") from exc
    if not isinstance(data["series"], list):
        raise ChannelError("series must be a list")
    ids = set()
    for i, series in enumerate(data["series"]):
        field = f"series[{i}]"
        _fields(series, {"id", "name", "kind", "watch", "feeds", "per_day", "min_multiple", "lesson"}, field)
        kind = series.get("kind")
        if kind not in ("breakdown", "news", "clips"):
            raise ChannelError(f"{field}.kind must be breakdown, news or clips")
        defaults = {"breakdown": {"watch": [], "per_day": 2, "min_multiple": 3},
                    "news": {"watch": [], "feeds": [], "per_day": 1}, "clips": {"per_day": 0}}[kind]
        _fields(series, {"id", "name", "kind", "lesson", *defaults}, field)
        _slug(series.get("id"), f"{field}.id")
        if series["id"] in ids:
            raise ChannelError(f"{field}.id must be unique")
        ids.add(series["id"])
        _text(series.get("name"), f"{field}.name", required=True, most=60)
        for key, value in {**defaults, "lesson": ""}.items():
            series.setdefault(key, value)
        _text(series["lesson"], f"{field}.lesson", most=400)
        _integer(series["per_day"], f"{field}.per_day", 0, 10)
        if kind in ("breakdown", "news"):
            if not isinstance(series["watch"], list) or len(series["watch"]) > 40:
                raise ChannelError(f"{field}.watch must list up to 40 YouTube handles or UC IDs")
            for handle in series["watch"]:
                try:
                    feeds.channel(handle)
                except ValueError as exc:
                    raise ChannelError(f"{field}.watch {exc}") from exc
        if kind == "breakdown":
            if not series["watch"]:
                raise ChannelError(f"{field}.watch needs at least one YouTube handle or UC ID")
            multiple = series["min_multiple"]
            if type(multiple) not in (int, float) or not 1 <= multiple <= 1000 or not math.isfinite(multiple):
                raise ChannelError(f"{field}.min_multiple must be a number between 1 and 1000")
        if kind == "news":
            if not isinstance(series["feeds"], list) or len(series["feeds"]) > 10:
                raise ChannelError(f"{field}.feeds must list up to 10 https URLs")
            for url in series["feeds"]:
                web_url(url, f"{field}.feeds")
                if urlsplit(url).scheme != "https":
                    raise ChannelError(f"{field}.feeds must use https URLs")
    if not isinstance(data["sources"], list):
        raise ChannelError("sources must be a list")
    ids = set()
    for i, src in enumerate(data["sources"]):
        field = f"sources[{i}]"
        fields = {"id", "name", "kind", "url", "rights"}
        if isinstance(src, dict) and src.get("kind") == "recordings":
            fields.update({"settle_seconds", "since", "max_seconds", "require_match"})
        _fields(src, fields, field)
        _slug(src.get("id"), f"{field}.id")
        if src["id"] in ids:
            raise ChannelError(f"{field}.id must be unique")
        ids.add(src["id"])
        _text(src.get("name"), f"{field}.name", required=True)
        _text(src.get("url", ""), f"{field}.url", required=src.get("kind") == "recordings")   # an empty path reads the current folder
        if src.get("kind") not in KINDS:
            raise ChannelError(f"{field}.kind must be one of {', '.join(KINDS)}")
        if "settle_seconds" in src:
            _integer(src["settle_seconds"], f"{field}.settle_seconds", 0)
        if "since" in src:
            _text(src["since"], f"{field}.since", required=True)
            try:
                if date.fromisoformat(src["since"]).isoformat() != src["since"]:
                    raise ValueError
            except ValueError:
                raise ChannelError(f"{field}.since must be YYYY-MM-DD") from None
        if "max_seconds" in src:
            seconds = src["max_seconds"]
            if type(seconds) not in (int, float) or seconds <= 0 or not math.isfinite(seconds):
                raise ChannelError(f"{field}.max_seconds must be a positive number")
        if "require_match" in src and type(src["require_match"]) is not bool:
            raise ChannelError(f"{field}.require_match must be true or false")
        rights = src.get("rights", {})
        _fields(rights, {"status", "grant", "expires", "note"}, f"{field}.rights")
        if not isinstance(rights.get("status"), str) or rights["status"] not in campaign.RIGHTS:
            raise ChannelError(f"{field}.rights.status must be own, licensed, permission or unknown")
        if src["kind"] == "recordings" and rights["status"] != "own":
            raise ChannelError(f"{field}.rights.status must be own for recordings")
        for key in ("grant", "expires", "note"):
            _text(rights.get(key, ""), f"{field}.rights.{key}", required=key == "grant" and rights["status"] != "unknown")
        if rights.get("expires"):
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rights["expires"]):
                    raise ValueError
                date.fromisoformat(rights["expires"])
            except ValueError:
                raise ChannelError(f"{field}.rights.expires must be YYYY-MM-DD or empty") from None
    cadence = data["cadence"]
    _integer(cadence["per_day"], "cadence.per_day", 1, 24)
    times = cadence["times"]
    if (not isinstance(times, list) or not times
            or any(not isinstance(t, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in times)
            or len(set(times)) != len(times)):
        raise ChannelError("cadence.times must list unique HH:MM times")
    _text(cadence["timezone"], "cadence.timezone", required=True)
    zone(cadence["timezone"])
    approval = data["approval"]
    if approval["policy"] not in ("manual", "veto", "auto"):
        raise ChannelError("approval.policy must be manual, veto or auto")
    hours = approval["veto_hours"]
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not math.isfinite(hours) or hours < 0:
        raise ChannelError("approval.veto_hours must be a nonnegative number")
    _integer(approval["manual_first"], "approval.manual_first", 0)
    _integer(data["seeding"]["every"], "seeding.every", 1)
    return data


def voice(slug: str) -> str | None:
    path = directory(slug) / "voice.md"
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else None
    if text is not None and len(text) > 4000:
        raise ChannelError("voice.md must be at most 4000 characters")
    return text


def load(slug: str) -> dict:
    try:
        data = validate(json.loads((directory(slug) / "channel.json").read_text(encoding="utf-8-sig")))
    except (OSError, ValueError) as exc:
        if isinstance(exc, ChannelError):
            raise
        raise ChannelError(f"channel.json could not be read for {slug}. {exc}") from exc
    if data["slug"] != slug:
        raise ChannelError("slug must match the channel folder")
    voice(slug)
    return data


def save(data: dict) -> dict:
    data = validate(data)
    root = directory(data["slug"])
    voice(data["slug"])
    for name in ("projects", "kits"):
        (root / name).mkdir(parents=True, exist_ok=True)
    pipeline._write(root / "channel.json", data)
    (root / "queue.jsonl").touch(exist_ok=True)
    return data


def create(name: str, niche: str, slug: str | None = None, **settings) -> dict:
    slug = pipeline.show_slug(name) if slug is None else slug
    if (directory(slug) / "channel.json").exists():
        raise ChannelError(f"channel {slug} already exists")
    return save({"schema_version": 1, "slug": slug, "name": name, "niche": niche,
                 "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), **settings})


def source(channel: dict, ident: str) -> dict:
    found = next((s for s in channel["sources"] if s["id"] == ident), None)
    if found is None:
        raise ChannelError(f"source {ident} is not in channel {channel['slug']}")
    return found


def effective_rights(src: dict, now: datetime | None = None) -> str:
    rights = src.get("rights", {})
    today = (now or datetime.now(timezone.utc)).date()
    if rights.get("expires") and date.fromisoformat(rights["expires"]) < today:
        return "unknown"
    return rights.get("status", "unknown") if rights.get("grant", "").strip() else "unknown"


def project_settings(slug: str, source_id: str | None = None, **settings) -> dict:
    channel = load(slug)
    network = channel["network"]
    brand = {"name": network.get("name") or channel["name"], "url": network.get("url", ""), "cta": network.get("line", "")}
    brand.update(settings.pop("brand", {}))
    settings = {**channel["factory"], **settings, "channel": slug, "source": source_id, "show": slug, "brand": brand}
    if source_id:
        src = source(channel, source_id)
        if src["kind"] == "recordings":
            settings["rights"] = effective_rights(src)      # a take is always the owner's own
        settings.setdefault("rights", effective_rights(src))
        settings.setdefault("name", src["name"])
        settings["url"] = next((url for url in (settings.get("url"), src.get("url"))
                                if url and url.startswith(("http://", "https://"))), "")
    elif settings.get("url") and not settings["url"].startswith(("http://", "https://")):
        settings["url"] = ""
    return settings


def paused(slug: str) -> bool:
    return (home() / "PAUSE").exists() or (directory(slug) / "PAUSE").exists()


def require_running(slug: str) -> None:
    if paused(slug):
        raise ChannelError(f"channel {slug} is paused")
