"""Daily picks, scripts and a page to record from."""
from __future__ import annotations

import html
import json
import math
import re
from datetime import date as Date, datetime, time, timezone
from importlib import resources
from pathlib import Path
from statistics import median

from myzing.factory.judge import Judge, NeedsAnswer
from myzing.factory.pipeline import _read, _write
from myzing.playbook.common import parse_time

from . import bandit, outliers, registry

updates = None
STOP = set("about been could from have into just more should some that their them then there these they this those were what when where which with would your".split())


def when(channel: dict, date: str | None = None) -> datetime:
    if date is None:
        return datetime.now(timezone.utc)
    try:
        day = Date.fromisoformat(date)
        if day.isoformat() != date:
            raise ValueError
    except ValueError:
        raise registry.ChannelError("--date must be YYYY-MM-DD") from None
    return datetime.combine(day, time(12), registry.zone(channel["cadence"]["timezone"]))


def _day(channel: dict, now: datetime) -> str:
    if now.tzinfo is None:
        raise registry.ChannelError("now must include a timezone")
    return now.astimezone(registry.zone(channel["cadence"]["timezone"])).date().isoformat()


def check(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("script answer must be an object")
    for key in ("hook", "script", "move", "title"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"{key} must be non-empty text")
    for key, least, most in (("hook", 1, 15), ("script", 60, 120), ("move", 1, 12)):
        if not least <= len(value[key].split()) <= most:
            raise ValueError(f"{key} must have {least} to {most} words")
    if len(value["title"]) > 70:
        raise ValueError("title must have at most 70 characters")
    if not isinstance(value.get("check"), list) or any(not isinstance(s, str) or not s.strip() for s in value["check"]):
        raise ValueError("check must list claims to verify")
    return {key: value[key] for key in ("hook", "script", "move", "title", "check")}


def _prompt(channel: dict, series: dict, facts: dict, *, now: datetime) -> str:
    root = registry.directory(channel["slug"])
    prior = bandit.prior(channel) if channel.get("prior") else _read(root / "prior.json", {})
    text = (resources.files("myzing") / "_data" / "channels" / "prompts" / "brief-script.md").read_text(encoding="utf-8")
    values = {"NAME": channel["name"], "NICHE": channel["niche"], "VOICE": registry.voice(channel["slug"]) or "None given.",
              "SERIES": series["name"], "LESSON": series.get("lesson") or "End with one move the viewer can copy.",
              "FACTS": json.dumps(facts, ensure_ascii=False, indent=1),
              "PRIOR": "\n".join(f"- {line}" for line in prior.get("guidance", [])) or "None yet.",
              "TAKES": "\n".join(f"- {line}" for line in voice(channel["slug"], now)) or "None yet."}
    return re.sub(r"\{(NAME|NICHE|VOICE|SERIES|LESSON|FACTS|PRIOR|TAKES)\}", lambda m: values[m[1]], text)


def _collector(kind: str, collectors):
    global updates
    if collectors is not None and kind in collectors:
        return collectors[kind]
    if kind == "breakdown":
        return outliers.collect
    if updates is None:
        from . import updates
    return updates.collect


def _receipt(facts: dict) -> str:
    if facts["kind"] == "breakdown":
        about = "about " if facts.get("approximate") else ""
        text = f"{facts['channel_title']}: {about}{facts['views']:,} views, {facts['multiple']}x their typical {facts.get('format', 'Short')}"
    else:
        day = parse_time(facts["published"])
        text = f"{facts['source']}, {day.strftime('%b')} {day.day}: {facts['title']}"
    return " ".join(text.split())


def _page(folder: Path, channel: dict, data: dict, *, latest=True) -> Path:
    cards = []
    for i, item in enumerate(data["items"], 1):
        receipt = html.escape(item["receipt"])
        url = item["facts"].get("url", "")
        try:
            registry.web_url(url, "link")
            receipt = f'<a href="{html.escape(url, quote=True)}">{receipt}</a>'
        except registry.ChannelError:
            pass
        body = f'<article><h2>{html.escape(item["series_name"])}</h2><p>{receipt}</p>'
        if item["kind"] == "breakdown" and item["facts"].get("title"):
            body += f'<p>Video: {html.escape(item["facts"]["title"])}</p>'
        if item.get("status") == "recorded":
            note = "Recorded"
            take = item.get("take")
            if isinstance(take, dict) and all(isinstance(take.get(k), (int, float)) for k in ("kept", "seconds")):
                note = f"Recorded. Kept {round(take['kept'] * 100)}% of the script in {take['seconds']:g} seconds."
            body += f'<p>{html.escape(note)}</p>'
        if item.get("script"):
            claims = "".join(f"<li>{html.escape(s)}</li>" for s in item["check"])
            body += (f'<p><strong>{html.escape(item["hook"])}</strong></p>'
                     f'<label for="script-{i}">Script</label><textarea id="script-{i}" readonly>{html.escape(item["script"])}</textarea>'
                     f'<button type="button" data-copy="script-{i}">Copy script</button>'
                     f'<div class="move"><h3>Try this</h3><p>{html.escape(item["move"])}</p></div>'
                     '<h3>Check before recording</h3>' + (f'<ul>{claims}</ul>' if claims else '<p>No extra claims listed.</p>')
                     + f'<h3>Title</h3><p>{html.escape(item["title"])}</p>')
        else:
            body += '<p>Waiting for an answer.</p>'
            if item.get("pending"):
                body += f'<p>Prompt file</p><code>{html.escape(item["pending"])}</code>'
        cards.append(body + '</article>')
    errors = "".join(f"<li>{html.escape(error)}</li>" for error in data["errors"])
    page = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily brief</title><style>
body{max-width:760px;margin:32px auto;padding:0 16px;font:16px/1.5 system-ui;color:#222;background:#fafafa}
article{margin:32px 0;padding:20px;border:1px solid #ccc;background:white}h1,h2,h3,p,li,code{overflow-wrap:anywhere}
textarea{display:block;box-sizing:border-box;width:100%;min-height:240px;font:22px/1.5 system-ui;resize:vertical}
button{margin:8px 0 20px;padding:12px;font:inherit;min-height:44px}label{display:block;margin-top:12px}
.move{border:1px solid #ccc;padding:16px;background:#fafafa}.move h3{margin-top:0}h2{font-size:24px}
</style><body><h1>''' + html.escape(channel["name"]) + ''' daily brief</h1><p>''' + html.escape(data["date"]) + '''</p>
<p>Only the receipt is a fact. Check the script's claims before recording.</p>
''' + ("".join(cards) or '<p>No picks today.</p>') + (f'<h2>Errors</h2><ul>{errors}</ul>' if errors else '') + '''<script>
document.querySelectorAll('textarea').forEach(text=>{text.style.height=text.scrollHeight+'px'});
document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{
  const text=document.getElementById(button.dataset.copy);
  try{await navigator.clipboard.writeText(text.value)}catch{ text.focus();text.select();document.execCommand('copy') }
}));
</script></body></html>'''
    path = folder / "brief.html"
    path.write_text(page, encoding="utf-8")
    if latest:
        (folder.parent / "latest.html").write_text(page, encoding="utf-8")
        if channel.get("phone_folder"):
            try:
                phone = Path(channel["phone_folder"]).expanduser() / f"{channel['slug']}-brief.html"
                phone.parent.mkdir(parents=True, exist_ok=True)
                tmp = phone.with_suffix(".html.tmp")
                tmp.write_text(page, encoding="utf-8")
                tmp.replace(phone)
            except Exception as exc:
                error = f"phone_folder {str(exc) or type(exc).__name__}"
                if error not in data["errors"]:
                    data["errors"].append(error)
                    _write(folder / "brief.json", data)
    return path


def make(slug, *, now=None, fetch=None, judge=None, stop=None, collectors=None) -> dict:
    channel = registry.load(slug)
    registry.require_running(slug)
    now = now or datetime.now(timezone.utc)
    root = registry.directory(slug) / "brief"
    day = _day(channel, now)
    folder = root / day
    path = folder / "brief.json"
    data = _read(path)
    seen = _read(root / "seen.json", {})

    def stopped():
        return registry.paused(slug) or bool(stop and stop())

    if data is None:
        data = {"schema_version": 1, "date": day, "made_at": now.isoformat(), "channel": slug, "items": [], "errors": []}
        picked = set(seen)
        for series in channel["series"]:
            if stopped():
                return data
            if not series["per_day"] or series["kind"] == "clips":
                continue
            try:
                rows = _collector(series["kind"], collectors)(series, root.parent, fetch=fetch, now=now, stop=stopped)
                rows = sorted(rows, key=lambda r: r["multiple" if series["kind"] == "breakdown" else "score"], reverse=True)
                count = 0
                for facts in rows:
                    if count == series["per_day"]:
                        break
                    if facts["id"] in picked:
                        continue
                    try:
                        registry.web_url(facts["url"], "candidate.url")
                    except registry.ChannelError:   # one bad link drops that candidate, not the series
                        continue
                    item = {"n": len(data["items"]) + 1, "id": facts["id"], "series": series["id"], "series_name": series["name"],
                            "kind": series["kind"], "facts": facts, "receipt": _receipt(facts), "hook": None, "script": None,
                            "move": None, "title": None, "check": [], "pending": None, "status": "open"}
                    data["items"].append(item)
                    picked.add(facts["id"])
                    count += 1
            except Exception as exc:
                data["errors"].append(f"{series['id']} {str(exc) or type(exc).__name__}")
        if stopped():
            return data
        _write(path, data)  # picks survive a stopped judge call
    seen.update({item["id"]: day for item in data["items"]})
    _write(root / "seen.json", seen)
    for item in data["items"]:
        if stopped():
            return data                 # due() finishes the unasked items on a later tick
        if item.get("script"):
            continue
        task = f"script-{item['n']}"
        prompt = None
        try:
            series = next((s for s in channel["series"] if s["id"] == item["series"]), {"name": item["series_name"]})
            prompt = _prompt(channel, series, item["facts"], now=now)
            answer = (judge or Judge(folder, backend=channel["judge"])).ask(task, prompt)
            item.update(check(answer), pending=None)
            data["errors"] = [e for e in data["errors"] if not e.startswith(task + " ")]
        except NeedsAnswer as exc:
            item["pending"] = str(exc.path)
        except Exception as exc:
            Judge(folder).forget(task)  # a bad cached answer would come back on every run
            item["attempts"] = item.get("attempts", 0) + 1
            error = f"{task} {str(exc) or type(exc).__name__}"
            if error not in data["errors"]:
                data["errors"].append(error)
            if prompt is not None and (channel["judge"] == "host" or item["attempts"] >= 3):
                pending = folder / "pending" / f"{task}.md"
                pending.parent.mkdir(parents=True, exist_ok=True)
                pending.write_text(prompt, encoding="utf-8")
                item["pending"] = str(pending)
        _write(path, data)
    newest = max((p.parent.name for p in root.glob("*/brief.json")), default=day)
    _page(folder, channel, data, latest=day >= newest)
    return data


def due(slug, now) -> bool:
    channel = registry.load(slug)
    if registry.paused(slug) or not any(s["per_day"] > 0 for s in channel["series"]):
        return False
    data = _read(registry.directory(slug) / "brief" / _day(channel, now) / "brief.json")
    return data is None or any(not item.get("script") and not item.get("pending") for item in data["items"])


def answer(slug, task, path_or_text, date=None):
    channel = registry.load(slug)
    registry.require_running(slug)
    now = when(channel, date)
    folder = registry.directory(slug) / "brief" / _day(channel, now)
    data = _read(folder / "brief.json", {})
    if task not in {f"script-{item['n']}" for item in data.get("items", [])}:
        raise registry.ChannelError("task must name an item in that day's brief")
    text = path_or_text
    if isinstance(text, Path):
        text = text.read_text(encoding="utf-8-sig")
    elif isinstance(text, str) and not text.lstrip().startswith(("{", "```")):
        text = Path(text).read_text(encoding="utf-8-sig")
    Judge(folder).save(task, text)
    return make(slug, now=now)


def _words(text: str) -> set[str]:
    return set(re.findall(r"\b[^\W\d_]{4,}\b", text.lower())) - STOP


def compare(item: dict, words: list[dict]) -> dict:
    item = item if isinstance(item, dict) else {}
    script = item.get("script") if isinstance(item.get("script"), str) else ""
    hook = _words(item.get("hook") if isinstance(item.get("hook"), str) else "")
    words = [w for w in words if isinstance(w, dict) and isinstance(w.get("w"), str) and w["w"].strip()] if isinstance(words, list) else []
    spoken = " ".join(w["w"] for w in words).split()
    content, said = _words(script), _words(" ".join(spoken))
    opening = " ".join(spoken[:20])
    try:
        seconds = float(words[-1]["e"]) - float(words[0]["s"])
    except (IndexError, KeyError, TypeError, ValueError, OverflowError):
        seconds = 0
    return {"words": len(spoken), "script_words": len(script.split()),
            "kept": round(len(content & said) / len(content), 2) if content else 0,
            "added": round(len(said - content) / len(said), 2) if said else 0,
            "hook_kept": bool(hook) and len(hook & _words(opening)) / len(hook) >= .6,
            "seconds": round(max(0, seconds), 1) if math.isfinite(seconds) else 0, "opening": opening[:200]}


def voice(slug: str, now: datetime) -> list[str]:
    today = Date.fromisoformat(_day(registry.load(slug), now))
    history = []
    for path in (registry.directory(slug) / "brief").glob("*/brief.json"):
        try:
            day = Date.fromisoformat(path.parent.name)
            if not 0 <= (today - day).days < 30:
                continue
            data = _read(path, {})
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            continue
        history.extend((day, item) for item in data["items"]
                       if isinstance(item, dict) and isinstance(item.get("take"), dict))
    history.sort(key=lambda row: (row[0], row[1].get("n", 0)), reverse=True)
    if len(history) < 3:
        return []
    takes = [item["take"] for _, item in history]
    lines = []
    rates = [t.get("words", 0) / t["seconds"] for t in takes if t.get("seconds", 0) >= 5]
    if rates:
        rate = median(rates)
        lines.append(f"The owner speaks about {rate:.1f} words a second. Aim for about {round(rate * 35)} spoken words.")
    ratios = [t.get("words", 0) / t["script_words"] for t in takes if t.get("script_words", 0) > 0]
    if ratios:
        ratio = median(ratios)
        if ratio < .85 or ratio > 1.15:
            lines.append(f"Recorded takes ran about {round(ratio * 100)}% of the script length.")
    changed = [item for _, item in history if not item["take"].get("hook_kept")]
    if len(changed) > len(takes) / 2:
        lines.append(f"The owner rewrote {len(changed)} of the last {len(takes)} hooks when recording.")
    kept = median(t.get("kept", 0) for t in takes)
    if kept < .6:
        lines.append(f"The owner kept about {round(kept * 100)}% of the script's words. Write closer to how they talk.")
    for item in changed[:3]:
        hook = " ".join(str(item.get("hook") or "").split())[:120]
        opening = " ".join(str(item["take"].get("opening") or "").split())[:120]
        lines.append(f"Script hook: {hook} | Said instead: {opening}")
    return lines


def match(slug: str, text: str, now: datetime):
    today = Date.fromisoformat(_day(registry.load(slug), now))
    words, best, score = _words(text), None, .35
    for path in sorted((registry.directory(slug) / "brief").glob("*/brief.json"), reverse=True):
        try:
            day = Date.fromisoformat(path.parent.name)
        except ValueError:
            continue
        if not 0 <= (today - day).days < 14:
            continue
        for item in _read(path)["items"]:
            content = _words(item.get("script") or "")
            if item.get("status") != "open" or not content:
                continue
            share = len(words & content) / len(content)
            if share >= score and (best is None or share > score):
                best, score = (path.parent.name, item), share
    return best


def recorded(slug: str, project: Path, take: dict) -> None:
    if not take.get("brief"):
        return
    folder = registry.directory(slug) / "brief" / take["brief"]
    data = _read(folder / "brief.json")
    item = next(item for item in data["items"] if item["n"] == take["item"])
    try:
        words = _read(project / "words.json", [])
    except (OSError, ValueError):
        words = []
    item.update(status="recorded", project=str(project), take=compare(item, words if isinstance(words, list) else []))
    _write(folder / "brief.json", data)
    newest = max(p.parent.name for p in folder.parent.glob("*/brief.json"))
    _page(folder, registry.load(slug), data, latest=folder.name == newest)
