"""Review news-linked archive moments and hand a chosen span to the factory."""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path

from myzing.factory import pipeline
from myzing.factory.judge import Judge, NeedsAnswer

from . import resurface_corpus as corpus, resurface_match as match, resurface_signals as signals
from .registry import ChannelError, web_url


def build(archive) -> dict:
    index = corpus.build(archive)
    return {**corpus.status(archive), **{key: index.report[key] for key in ("indexed", "unchanged", "removed")}}


def status(archive) -> dict:
    root = corpus._root(archive)
    if not (root / ".zing" / "index.sqlite").is_file():
        raise ValueError("No archive index. Run zing resurface build first.")
    return corpus.status(root)


def _json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default


def _names(index) -> dict:
    names = {name: [] for episode in index.episodes() for name in episode["guests"]}
    aliases = _json(index.archive / "aliases.json", {})
    if (not isinstance(aliases, dict) or any(not isinstance(name, str) or not name.strip()
            or not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values)
            for name, values in aliases.items())):
        raise ValueError("aliases.json must map names to lists of aliases")
    for name, values in aliases.items():
        key = next((key for key in names if corpus.folded(key) == corpus.folded(name)), corpus.plain(name))
        names[key] = values
    return names


def _aliases(entity, names):
    return list(dict.fromkeys(term for name, values in names.items()
                             if corpus.pattern([name, *values]).search(corpus.folded(entity))
                             for term in [name, *values]))


def rights(root: Path, episode_id: str | None = None) -> str:
    settings = _json(root / "archive.json", {})
    if not isinstance(settings, dict):
        raise ValueError("archive.json must contain an object")
    row = next((row for row in corpus._manifest(root) if isinstance(row, dict)
                and isinstance(row.get("id"), str) and corpus.plain(row["id"]) == episode_id), {})
    value = row if row.get("rights") or row.get("grant") else settings
    claimed = value.get("rights", "unknown")
    if claimed in ("public-domain", "owned"):
        return claimed
    grant = value.get("grant") or claimed
    if not isinstance(grant, str) or not grant.strip():
        return "unknown"
    if re.match(r"^[a-zA-Z][\w+.-]*://|^//", grant.replace("\\", "/")):
        return "unknown"
    path = Path(grant).expanduser()
    path = (root / path).resolve()
    return "permission" if path.is_file() else "unknown"


def _event(value: dict) -> dict:
    entity = value.get("entity")
    headlines = value.get("headlines")
    if not isinstance(entity, str) or not entity.strip():
        raise ValueError("event needs an entity name")
    if (not isinstance(headlines, list) or not headlines
            or any(not isinstance(row, dict) or not isinstance(row.get("title"), str)
                   or not row["title"].strip() for row in headlines)):
        raise ValueError("event needs a headline")
    first = datetime.fromisoformat(value["first_seen"].replace("Z", "+00:00"))
    first = first.replace(tzinfo=timezone.utc) if first.tzinfo is None else first.astimezone(timezone.utc)
    return {**value, "entity": corpus.plain(entity), "first_seen": first.isoformat(),
            "expires": value.get("expires") or (first + timedelta(hours=48)).isoformat()}


def _slug(entity):
    return re.sub(r"[^\w]+", "-", corpus.folded(entity), flags=re.UNICODE).strip("-_")[:80] or "entity"


def _key(event):
    parts = [event.get("signal"), event.get("geo"), corpus.folded(event["entity"]), event["first_seen"]]
    if event.get("signal") == "replay":
        parts.append(event["headlines"])
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _link(title, url):
    text = html.escape(str(title))
    try:
        web_url(url, "link")
    except ChannelError:
        return text
    return f'<a href="{html.escape(url, quote=True)}">{text}</a>'


def _save(folder, data):
    pipeline._write(folder / "brief.json", data)
    event, e = data["event"], html.escape
    headlines = "".join(f'<li>{_link(row["title"], row.get("url", ""))}</li>' for row in event["headlines"])
    cards = []
    for i, pick in enumerate(data["picks"], 1):
        cards.append(f'''<article><h2>Pick {i} · {e(pick["title"])}</h2>
<p>Original date {e(pick["date"])} · {e(pick["kind"])} · {pick["start"]:g}–{pick["end"]:g} seconds</p>
<p>Rights · {e(pick["rights"])}</p><blockquote>{e(pick["quote"])}</blockquote>
<h3>Why it fits</h3><p>{e(pick["why"])}</p>
<h3>On screen for the whole clip</h3><p>{e(pick["on_screen_context"])}</p>
<h3>Risk note</h3><p>{e(pick["risk_note"])}</p></article>''')
    note = {"queued": "Waiting for review.", "waiting": "Waiting for a judge answer.",
            "no_candidates": "No candidates found.", "no_picks": "No picks passed review.", "ready": ""}[data["status"]]
    pending = data.get("pending")
    prompt = f'<p>Prompt file</p><code>{e(pending["prompt_path"])}</code>' if pending else ""
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Resurface brief</title>
<style>body{max-width:760px;margin:32px auto;padding:0 16px;font:16px/1.5 system-ui;color:#222;background:#fafafa}
article{margin:32px 0;padding:20px;border:1px solid #ccc;background:white}
h1,h2,h3,p,li,code,blockquote{overflow-wrap:anywhere}h2{font-size:24px}blockquote{margin:16px 0}</style><body>'''
    page += (f'<h1>{e(event["entity"])}</h1><p>{e(event["signal"])} · Traffic {e(str(event.get("traffic", 0)))}</p>'
             f'<ul>{headlines}</ul><p>First seen {e(event["first_seen"])}</p><p>Expires {e(event["expires"])}</p>'
             f'<p>Archive rights · {e(data["rights"])}</p>'
             '<p>Past footage. Review the quote, its context and the rights before using it.</p>'
             + (f'<p>{note}</p>' if note else "") + prompt + "".join(cards) + '</body></html>')
    temp = folder / "brief.html.tmp"
    temp.write_text(page, encoding="utf-8")
    temp.replace(folder / "brief.html")


def _seed(index, event, names, n):
    event = _event(event)
    root, key = index.archive / ".zing" / "briefs", _key(event)
    folder = root / f'{event["first_seen"][:10]}-{_slug(event["entity"])}'
    saved = _json(folder / "brief.json")
    if saved and saved["id"] != key:
        folder = folder.with_name(folder.name + "-" + key[:12])
        saved = _json(folder / "brief.json")
    if saved:
        return None
    aliases = _aliases(event["entity"], names)
    found = match.candidates(index, event["entity"], aliases=aliases, headline=event["headlines"][0]["title"])
    data = {"version": 1, "id": key, "archive": str(index.archive), "event": event, "n": n,
            "aliases": aliases, "candidates": found, "picks": [], "status": "queued", "pending": None,
            "rights": rights(index.archive)}
    _save(folder, data)
    return folder


def _finish(folders, judge):
    result = {"state": "done", "briefs": [], "pending": [], "errors": []}
    for folder in folders:
        data = _json(folder / "brief.json")
        if data["status"] not in ("queued", "waiting"):
            continue
        event = data["event"]
        try:
            picks = match.rank(data["candidates"], event["entity"], event["headlines"][0]["title"],
                               Judge(folder, judge) if isinstance(judge, str) else judge, n=data["n"])
            data.update(picks=[{**pick, "rights": rights(Path(data["archive"]), pick["episode_id"])} for pick in picks],
                        status="ready" if picks else "no_picks" if data["candidates"] else "no_candidates", pending=None)
        except NeedsAnswer as exc:
            data.update(status="waiting", pending={"task": exc.task, "prompt_path": str(exc.path)})
            result.update(state="waiting", pending=[data["pending"]])
        _save(folder, data)
        result["briefs"].append(str(folder / "brief.json"))
        if result["pending"]:
            break
    return result


def _limit(n):
    if type(n) is not int or n < 0:
        raise ValueError("n must be a nonnegative integer")


def watch(archive, *, feeds=None, geo="US", judge="host", n=5):
    _limit(n)
    index = corpus.build(archive)
    names = _names(index)
    urls = [] if feeds is None else [line.strip() for line in Path(feeds).read_text(encoding="utf-8-sig").splitlines()
                                   if line.strip() and not line.lstrip().startswith("#")]
    for url in urls:
        web_url(url, "feed")
    events = signals.watch(names, feeds=urls, state_dir=index.archive / ".zing", geo=geo)
    for event in events:
        if "error" not in event:
            _seed(index, event, names, n)  # save every event before the first judge can stop the run
    folders = sorted(path.parent for path in (index.archive / ".zing" / "briefs").glob("*/brief.json")
                     if _json(path)["status"] in ("queued", "waiting"))
    result = _finish(folders, judge)
    result["errors"] = [event for event in events if "error" in event]
    return result


def replay(archive, *, entity, headline, url="", date=None, judge="host", n=5):
    _limit(n)
    day = date or datetime.now(timezone.utc).date().isoformat()
    try:
        if Date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError:
        raise ValueError("date must be YYYY-MM-DD") from None
    if url:
        web_url(url, "headline link")
    index = corpus.build(archive)
    event = _event({"entity": entity, "signal": "replay", "traffic": 0,
                    "headlines": [{"title": headline, "url": url}], "first_seen": day + "T00:00:00+00:00"})
    folder = _seed(index, event, _names(index), n)
    if folder is None:
        folder = next(path.parent for path in (index.archive / ".zing" / "briefs").glob("*/brief.json")
                      if _json(path)["id"] == _key(event))
    result = _finish([folder], judge)
    if not result["briefs"]:
        result["briefs"] = [str(folder / "brief.json")]
    return result


def make(brief, *, pick, media=None, out=None, shapes=None):
    path = Path(brief).expanduser().resolve()
    path = path / "brief.json" if path.is_dir() else path
    if path.name == "brief.html":
        path = path.with_suffix(".json")
    data = _json(path)
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("status") != "ready":
        raise ValueError("Choose a resurface brief with reviewed picks")
    if type(pick) is not int or not 1 <= pick <= len(data["picks"]):
        raise ValueError("pick must name a pick number in the brief, starting at 1")
    saved = data["picks"][pick - 1]
    index = corpus.build(data["archive"])
    event = data["event"]
    candidates = match.candidates(index, event["entity"], aliases=data["aliases"], headline=event["headlines"][0]["title"])
    fields = ("id", "start", "end", "quote", "why", "on_screen_context", "risk_note")
    chosen = match.check({"picks": [{key: saved[key] for key in fields}]}, candidates, event["entity"], 1)[0]
    episode = next(row for row in index.episodes() if row["id"] == chosen["episode_id"])
    value = str(media if media is not None else episode["media"])
    if not value or re.match(r"^[a-zA-Z][\w+.-]*://|^//", value.replace("\\", "/")):
        raise ValueError("Download the media yourself only if you have the rights, then pass --media with a local file.")
    local = Path(value).expanduser()
    if media is None and not local.is_absolute():
        local = index.archive / local
    if not local.is_file():
        raise ValueError("Media file not found. Pass --media with a local file.")
    project = corpus._root(out) if out is not None else path.parent / f"pick-{pick}"
    if project.exists() and (not project.is_dir() or any(project.iterdir())):
        raise ValueError("The output folder is not empty. Choose another --out folder.")
    headline = event["headlines"][0]
    status = rights(index.archive, chosen["episode_id"])
    pipeline.init(project, local, transcript=corpus._transcript(index.archive, episode["transcript"]),
                  name=episode["title"], url=episode["url"], date=episode["date"], tag=chosen["on_screen_context"],
                  rights=status, moments=0, news={"peg": headline["title"], "links": [headline["url"]] if headline.get("url") else []},
                  **({"shapes": shapes} if shapes is not None else {}))
    src = pipeline._read(project / "source.json")
    pipeline._write(project / "source.json", {**src, "on_screen_context": chosen["on_screen_context"], "rights": status,
                                              "resurface": {"brief": str(path), "pick": pick, "episode_id": episode["id"]}})
    clip = pipeline.add_clip(project, chosen["start"], chosen["end"], basis="transcript")
    return {"project": str(project), "clip": clip, "rights": status, "hint": f'zing factory run "{project}"'}
