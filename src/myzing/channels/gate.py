"""Check whether a clip can enter a channel's queue."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from myzing.factory import postcopy, render
from myzing.factory.pipeline import _read, _write

from . import registry

LOCAL = re.compile(r"file:/|\b[A-Za-z]:[\\/]|\\\\[^\\\s]+\\")   # file URIs, drive paths, UNC shares


def rating(project: Path, clip: str) -> str | None:
    return (_read(project / "ratings.json", {}).get(clip) or {}).get("v")


def _edited(project: Path, clip: str, pack: str = "zing") -> bool:
    row = _read(project / "ratings.json", {}).get(clip) or {}
    if row.get("v") != "post" or "at" not in row:  # older ratings have no timestamp
        return False
    try:
        approved = datetime.fromisoformat(row["at"])
        if approved.tzinfo is None:
            return True
        return any(p.is_file() and p.stat().st_mtime >= approved.timestamp()
                   for p in (project / clip / f"clip{render.suffix('9x16', pack)}.mp4", project / clip / "post.json"))
    except (TypeError, ValueError):
        return True


def _visuals(d: Path, pack: str = "zing") -> list[dict]:
    vis = d / "visuals"
    manifest = _read(vis / "manifest.json", {})
    picks = _read(vis / "picks.json", {}).get("picks", {})
    chosen, known = [], set()
    for ident in manifest.keys() | picks.keys():
        candidates = manifest.get(ident, [])
        index = picks.get(ident, {}).get("pick", 0)
        if index is not None and (candidates or ident in picks):
            chosen.append(candidates[index] if type(index) is int and 0 <= index < len(candidates) else {})
            known.add(ident)
    planned = _read(d / "plan.json", {}).get("visuals", {})
    chosen.extend(planned.values())
    known.update(planned)
    data = _read(d / f"data{render.suffix('9x16', pack)}.json", {})
    chosen.extend(v for ident, v in data.get("visuals", {}).items() if "rights" in v or ident not in known)
    return chosen


def _manual_count(channel: dict) -> int:
    from .queue import read
    return sum(row.get("manual", False) for row in read(channel["slug"]) if row["status"] in ("queued", "kit", "posted"))


def check(project: Path, clip: str, channel: dict, *, now: datetime | None = None) -> dict:
    project = Path(project).resolve()
    d = project / clip
    cfg = _read(project / "factory.json", {})
    pack = cfg.get("pack", "zing")
    now = now or datetime.now(timezone.utc)
    blockers = []
    if cfg.get("rights") not in ("own", "licensed", "permission"):
        blockers.append("Source rights are unknown.")
    if cfg.get("source"):
        try:
            src = registry.source(channel, cfg["source"])
            if registry.effective_rights(src, now) == "unknown" and "Source rights are unknown." not in blockers:
                blockers.append("Source rights are unknown.")
            expires = src["rights"].get("expires")
            if expires and date.fromisoformat(expires) < now.date():
                blockers.append("The source grant has expired.")
        except registry.ChannelError:
            blockers.append("The channel source is missing.")
    rights = ("cleared", "attribution", "editorial") if channel.get("visuals") == "editorial" else ("cleared", "attribution")
    if any(v.get("rights") not in rights for v in _visuals(d, pack)):
        blockers.append("Picked visuals need " + ", ".join(rights[:-1]) + " or " + rights[-1] + " rights.")
    context = _read(d / "context.json", {})
    if not (d / "context.json").is_file():
        blockers.append("The context check has not finished.")
    if "error" in context:
        blockers.append(f"The context check failed: {context['error']}.")
    if context.get("flags"):
        blockers.append("Context flags need review.")
    brief = _read(d / "brief_check.json", {})
    if (project / "brief.json").is_file() and not (d / "brief_check.json").is_file():
        blockers.append("The brief check has not finished.")
    if brief.get("errors"):
        blockers.append("Brief errors need fixing.")
    if brief.get("flags"):
        blockers.append("Brief flags need review.")
    video = d / f"clip{render.suffix('9x16', pack)}.mp4"
    if not video.is_file():
        blockers.append("The 9x16 render is missing.")
    if not (d / "post.json").is_file():
        blockers.append("Post copy is missing.")
    elif any(LOCAL.search(str(_read(d / "post.json", {}).get(field, ""))) for field in postcopy.FIELDS):
        blockers.append("Post copy contains a local file path.")
    vote = rating(project, clip)
    if _edited(project, clip, pack):
        blockers.append("The clip was edited after approval.")
        vote = "fix"
    if vote == "no":
        blockers.append("The clip is rated No.")
    else:
        approval = channel["approval"]
        policy = approval["policy"]
        if policy == "auto" and _manual_count(channel) < approval["manual_first"]:
            policy = "manual"
        if policy == "manual" and vote != "post":
            blockers.append("Manual approval needs a Post rating.")
        elif policy == "veto" and vote != "post":
            if vote is not None:
                blockers.append("The clip still needs a Post rating.")
            elif not video.is_file() or now.timestamp() - video.stat().st_mtime < approval["veto_hours"] * 3600:
                blockers.append("The veto window is still open.")
        elif policy == "auto" and vote not in (None, "post"):
            blockers.append("The clip still needs a Post rating.")
    if registry.paused(channel["slug"]):
        blockers.append("The channel or network is paused.")
    result = {"publishable": not blockers, "blockers": blockers}
    _write(d / "gate.json", result)
    return result
