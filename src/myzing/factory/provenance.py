"""Required source context carried from archive picks to the review and scene."""
from __future__ import annotations

import html
import json

RIGHTS = {"public-domain": "public domain", "owned": "you own this source"}


def _source(project):
    path = project / "source.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def scene(project):
    src = _source(project)
    context, tag = src.get("on_screen_context", ""), src.get("tag", "")
    if not context:
        return {}
    text = tag if context in tag else context if not tag or tag in context else f"{tag} · {context}"
    return {"sourceTag": text, "onScreenContext": context}


def receipt(project, duration):
    src = _source(project)
    if not src.get("on_screen_context"):
        return {}
    return {"on_screen_context": src["on_screen_context"], "original_date": src.get("date", ""),
            "rights": src.get("rights", "unknown"),
            "source_context": {"from": 0, "to": duration, "text": scene(project)["sourceTag"]}}


def review(project):
    src = _source(project)
    if not src.get("on_screen_context"):
        return ""
    return (f'<p class="sub">On screen for the whole clip · {html.escape(scene(project)["sourceTag"])}</p>'
            f'<p class="sub">Original date {html.escape(src.get("date", ""))} · '
            f'Archive rights {html.escape(src.get("rights", "unknown"))}</p>')
