"""Edits shared by the review page, CLI and agents."""
from __future__ import annotations

import math
import re
from pathlib import Path

from . import pick, pipeline, plan, render
from .judge import Judge, NeedsAnswer
from .pipeline import _read, _write
from .tools import FactoryError

CLIP = re.compile(r"^clip\d{2}$")
TEXT_FIELDS = {"x", "instagram", "tiktok", "youtube_title", "first_comment"}


def clipdir(project: Path, clip: str) -> Path:
    project = Path(project).resolve()
    if not (project / "factory.json").is_file():
        raise FactoryError(f"{project} is not a factory project")
    if not isinstance(clip, str) or not CLIP.fullmatch(clip) or not (project / clip).is_dir():
        raise FactoryError(f"unknown clip {clip!r}")
    return project / clip


def _result(d: Path, **changed) -> dict:
    context = _read(d / "context.json")
    return {"clip": d.name, **changed, "fact_check": _read(d / "plan.json", {}).get("fact_check", []),
            "context": context, "context_flags": (context or {}).get("flags", []),
            "receipt": _read(d / "receipt.json"), "brief_check": _read(d / "brief_check.json"),
            "pending": [p for p in Judge(d.parent).pending() if p["task"].startswith(d.name + "-")]}


def _rerender(d: Path) -> None:
    cfg = _read(d.parent / "factory.json", {})
    for shape in cfg.get("shapes", ["9x16"]):
        render.render(d, shape, cfg.get("pack", "zing"))


def _context(d: Path, judge: Judge | None = None) -> None:
    try:
        pipeline._context(d, judge or Judge(d.parent), say=lambda m: None)
    except NeedsAnswer:
        pass


def _finalize(d: Path, raw: dict, found: dict) -> None:
    cfg = _read(d.parent / "factory.json", {})
    plan.finalize(d, raw, found, cfg.get("brand"), cfg.get("news"))


def rate(project: Path, clip: str, verdict: str | None, why: str = "") -> dict:
    return pipeline.rate(project, clip, "fix" if verdict == "edits" else verdict, why)


def _check_visual(project: Path, clip: str, request: str, index: int) -> tuple:
    d = clipdir(project, clip)
    vis = d / "visuals"
    manifest, raw = _read(vis / "manifest.json", {}), _read(d / "plan-raw.json")
    if raw is None or request not in manifest or type(index) is not int or not 0 <= index < len(manifest[request]):
        raise FactoryError("no such visual candidate")
    return d, raw, manifest


def visual(project: Path, clip: str, request: str, index: int, *, why: str = "chosen by hand",
           context=None, rerender=None) -> dict:
    d, raw, manifest = _check_visual(project, clip, request, index)
    vis = d / "visuals"
    picks = _read(vis / "picks.json", {"picks": {}})
    picks["picks"][request] = {"pick": index, "why": why}
    _write(vis / "picks.json", picks)
    _finalize(d, raw, pick.chosen(d / "visuals", raw.get("visual_requests", []), manifest, picks["picks"]))
    (context or _context)(d)
    (rerender or _rerender)(d)
    return _result(d, request=request, index=index)


def _check_text(project: Path, clip: str, field: str, text: str) -> tuple:
    d = clipdir(project, clip)
    value = str(text or "").strip()
    if not value:
        raise FactoryError("text cannot be empty")
    if field in TEXT_FIELDS:
        return d, value[:2200], None
    if field != "hook":
        raise FactoryError(f"unknown field {field!r}")
    raw, current = _read(d / "plan-raw.json"), _read(d / "plan.json")
    if raw is None or current is None:
        raise FactoryError("this clip has no plan yet")
    return d, value[:120], raw


def text(project: Path, clip: str, field: str, text: str, *, context=None, rerender=None) -> dict:
    d, value, raw = _check_text(project, clip, field, text)
    if raw is None:
        post = _read(d / "post.json", {})
        post[field] = value
        _write(d / "post.json", post)
        if (d / "plan.json").is_file() and (d / "words.json").is_file():
            render.check_brief(d, stop=False)            # required tags and banned terms in the new copy
    else:
        raw["hook"] = value
        _write(d / "plan-raw.json", raw)
        Judge(d.parent).save(f"{d.name}-plan", raw)
        _finalize(d, raw, _read(d / "plan.json").get("visuals", {}))
        pipeline._forget_context(d)
        (context or _context)(d)
        (rerender or _rerender)(d)
    return _result(d, saved=field, text=value)


def _word(project: Path, clip: str, index, at, old, new) -> tuple:
    d = clipdir(project, clip)
    data = _read(d / "words.json")
    if not data or not data.get("words"):
        raise FactoryError("this clip has no caption words yet")
    if not isinstance(new, str) or not new.strip():
        raise FactoryError("text cannot be empty")
    words = data["words"]
    if index is None:
        if type(at) not in (int, float) or not math.isfinite(at) or not isinstance(old, str) or not old:
            raise FactoryError("give a word index or at and old")
        matches = [i for i, w in enumerate(words) if w["os"] <= at <= w["oe"] and w["w"] == old]
        if len(matches) != 1:
            raise FactoryError("no unique caption word at that time; use its index")
        index = matches[0]
    elif at is not None:
        raise FactoryError("give a word index or at and old, not both")
    if type(index) is not int or not 0 <= index < len(words):
        raise FactoryError(f"no such caption word; index must be from 0 to {len(words) - 1}")
    w = words[index]
    if old is not None and w["w"] != old:
        raise FactoryError(f"caption word {index} is {w['w']!r}, not {old!r}")
    if not (d / "plan-raw.json").is_file() or not (d / "plan.json").is_file():
        raise FactoryError("this clip has no plan yet")
    return d, data, {"index": index, "os": w["os"], "oe": w["oe"], "heard": w["w"], "meant": new.strip()}


def word(project: Path, clip: str, index: int | None = None, new: str = "", *, at: float | None = None,
         old: str | None = None, context=None, rerender=None) -> dict:
    d, data, fix = _word(project, clip, index, at, old, new)
    heard = d / "words-heard.json"
    if not heard.is_file():
        _write(heard, data)
    fixes = _read(d / "word-fixes.json", [])
    same = [f for f in fixes if (f["os"], f["oe"]) == (fix["os"], fix["oe"])]
    if same:
        fix["heard"] = same[0]["heard"]
    _write(d / "word-fixes.json", [f for f in fixes if f not in same] + [fix])
    _finalize(d, _read(d / "plan-raw.json"), _read(d / "plan.json").get("visuals", {}))
    pipeline._forget_context(d)
    (context or _context)(d)
    (rerender or _rerender)(d)
    return _result(d, index=fix["index"], at=fix["os"], old=fix["heard"], new=fix["meant"])


def _check_render(project: Path, clip: str, shape: str, pack: str) -> Path:
    d = clipdir(project, clip)
    if shape not in render.SHAPES:
        raise FactoryError(f"unknown shape {shape!r}")
    render.theme(pack)
    return d


def rerender(project: Path, clip: str, shape: str = "9x16", pack: str = "desk") -> dict:
    d = _check_render(project, clip, shape, pack)
    return _result(d, shape=shape, pack=pack, rendered=str(render.render(d, shape, pack)))


def apply(project: Path, clip: str, action: str, **values) -> dict:
    project = Path(project).resolve()
    if not (project / "factory.json").is_file():
        raise FactoryError(f"{project} is not a factory project")
    if action == "rate":
        verdict, why = values.get("verdict"), values.get("why", "")
        if verdict not in ("post", "edits", "no"):
            raise FactoryError("verdict must be post, edits or no")
        saved = rate(project, clip, verdict, why)
        return _result(project / clip, **saved, verdict=verdict, why=str(why or "")[:500])
    if action == "hook":
        return text(project, clip, "hook", values.get("text"))
    if action == "copy":
        field = values.get("field")
        if field not in TEXT_FIELDS:
            raise FactoryError(f"unknown field {field!r}")
        return text(project, clip, field, values.get("text"))
    if action == "visual":
        return visual(project, clip, values.get("request"), values.get("index"))
    if action == "word":
        return word(project, clip, values.get("index"), values.get("new"), at=values.get("at"), old=values.get("old"))
    if action == "render":
        return rerender(project, clip, values.get("shape", "9x16"), values.get("pack", "desk"))
    raise FactoryError("action must be rate, hook, copy, visual, word or render")
