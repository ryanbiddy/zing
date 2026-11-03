"""The clip factory: long episode -> scouted moments -> cut -> on-screen plan -> visuals -> rendered clips + copy.

Resumable: every stage writes its output and is skipped when that output exists. With the host judge a run stops
when it needs answers and asks for all of them that are ready at once (scout; then every clip's plan and copy; then
every clip's visual pick), so an agent answers three rounds per episode, not twenty-five calls.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import cut, pick, plan, postcopy, render, review, scout, source, visuals
from .judge import Judge, NeedsAnswer
from .tools import FactoryError

MODES = ("context", "fun", "documentary", "launch")
SETTINGS = {"moments": 8, "mode": "context", "shapes": ["9x16", "1x1"], "pack": "zing", "public": False, "parallax": True,
            "brand": None, "news": None}
LAUNCH = {"moments": 2, "shapes": ["16x9", "1x1", "9x16"], "pack": "launch"}   # a launch film is landscape first


def _read(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def init(project: Path, media: Path, *, transcript: Path | None = None, offset: float = 0.0, name: str | None = None,
         url: str = "", date: str = "", tag: str = "", **settings) -> dict:
    """Create a factory project. The media stays where it is; nothing is downloaded or uploaded."""
    project, media = Path(project).resolve(), Path(media).resolve()
    if not media.is_file():
        raise FactoryError(f"media not found: {media}")
    unknown = set(settings) - set(SETTINGS)
    if unknown:
        raise FactoryError(f"unknown settings: {', '.join(sorted(unknown))}")
    if settings.get("mode", "context") not in MODES:
        raise FactoryError(f"mode must be one of {', '.join(MODES)}")
    if settings.get("mode") == "launch":
        settings = {**LAUNCH, **{k: v for k, v in settings.items() if v is not None}}
    brand = settings.get("brand")
    if brand is not None and (not isinstance(brand, dict) or not str(brand.get("name", "")).strip()):
        raise FactoryError("brand needs at least a name")
    news = settings.get("news")
    if news is not None:
        if not isinstance(news, dict) or not str(news.get("peg", "")).strip():
            raise FactoryError("news needs a peg: one line on what happened")
        bad = [u for u in news.get("links", []) if not str(u).startswith(("https://", "http://"))]
        if bad:
            raise FactoryError(f"news links must be web addresses: {', '.join(map(str, bad))}")
    for shape in settings.get("shapes", SETTINGS["shapes"]):
        if shape not in render.SHAPES:
            raise FactoryError(f"unknown shape {shape}")
    render.theme(settings.get("pack", SETTINGS["pack"]))
    project.mkdir(parents=True, exist_ok=True)
    src = {"media": str(media), "name": name or media.stem, "url": url, "date": date, "tag": tag}
    _write(project / "source.json", src)
    _write(project / "factory.json", {**SETTINGS, **settings, "created": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    if transcript:
        segments, words = source.load_transcript(Path(transcript), offset)
        _write(project / "transcript.json", segments)
        if words:
            _write(project / "words.json", words)
    return status(project)


def _transcript(project: Path, media: Path, say) -> list[dict]:
    segments = _read(project / "transcript.json")
    if segments is None:
        quick = source.scout_model()
        say(f"transcribing the whole episode with the {quick or 'configured'} speech model (no caption file given)")
        words = source.transcribe_episode(media, quick)
        if not quick:                      # a quick pass only finds the moments; their words come from the full model
            _write(project / "words.json", words)
        segments = source.segments_from_words(words)
        _write(project / "transcript.json", segments)
    return segments


def _moments(project: Path, judge: Judge, media: Path, cfg: dict, say) -> list[dict]:
    path = project / "moments.json"
    data = _read(path)
    if data and data.get("snapped"):
        return data["moments"]
    segments = _transcript(project, media, say)
    moments = scout.check(judge.ask("scout", scout.prompt(segments, cfg["moments"], cfg["mode"], cfg.get("news"))),
                          segments[-1]["e"] if segments else None)
    words = _read(project / "words.json") or []
    pieces = []                                     # films share spans: transcribe each stretch of the episode once
    for a, b in sorted(ab for m in moments for ab in scout.parts(m)):
        if pieces and a <= pieces[-1]["end"] + 2 * source.MARGIN:
            pieces[-1]["end"] = max(pieces[-1]["end"], b)
        else:
            pieces.append({"start": a, "end": b})
    if not all(any(p["start"] <= w["s"] <= p["end"] for w in words) for p in pieces):
        say(f"transcribing {len(pieces)} spans for word timing")
        fresh = source.transcribe_moments(media, pieces)
        span = [(p["start"] - source.MARGIN, p["end"] + source.MARGIN) for p in pieces]
        words = sorted(fresh + [w for w in words if not any(a <= w["s"] <= b for a, b in span)], key=lambda w: w["s"])
        _write(project / "words.json", words)
    moments = [scout.snap(m, words) for m in moments]
    _write(path, {"moments": moments, "snapped": True})
    return moments


def _clip(project: Path, i: int, m: dict, judge: Judge, media: Path, cfg: dict, words: list[dict], say) -> list[str]:
    """Advance one clip as far as it can go; returns the tasks it is waiting on."""
    d = project / f"clip{i:02d}"
    task = f"clip{i:02d}"
    if not (d / "cams.json").is_file():
        say(f"{task}: cutting " + ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in scout.parts(m)))
        cut.cut(d, media, words, m["start"], m["end"], **({"spans": scout.parts(m)} if m.get("spans") else {}))
    w = _read(d / "words.json")
    src = _read(project / "source.json", {})
    waiting = []
    if not (d / "post.json").is_file():
        try:
            _write(d / "post.json", postcopy.finalize(judge.ask(f"{task}-copy", postcopy.prompt(m, w, src, cfg["mode"],
                                                                                                cfg.get("brand"),
                                                                                                cfg.get("news"))), w, src))
        except NeedsAnswer:
            waiting.append(f"{task}-copy")
    try:
        raw = plan.check(judge.ask(f"{task}-plan", plan.prompt(m, w, cfg["mode"], cfg.get("brand"), cfg.get("news"))))
    except NeedsAnswer:
        return waiting + [f"{task}-plan"]
    _write(d / "plan-raw.json", raw)
    sensitive = bool(raw.get("sensitive"))
    mode = cfg["mode"] if not sensitive or cfg["mode"] == "documentary" else "context"   # a documentary is already restrained
    reqs = raw.get("visual_requests", [])
    visdir = d / "visuals"
    found: dict = {}
    if reqs:
        if not (visdir / "manifest.json").is_file():
            say(f"{task}: finding visuals for {len(reqs)} requests ({mode})")
            _write(visdir / "requests.json", reqs)
            visuals.find(reqs, visdir, "context" if mode == "launch" else mode, public=cfg.get("public", False), say=say)
        manifest = _read(visdir / "manifest.json", {})
        if any(manifest.values()):
            sheet = pick.sheet(visdir, reqs, manifest)
            try:
                answer = judge.ask(f"{task}-pick", pick.prompt(sheet, "context" if mode == "launch" else mode,
                                                           raw.get("sensitive_reason", "") if sensitive else None),
                                   images=(sheet,))
            except NeedsAnswer:
                return waiting + [f"{task}-pick"]
            picks = pick.picks_from(answer)
            _write(visdir / "picks.json", {"mode": mode, "picks": picks})
            found = pick.chosen(visdir, reqs, manifest, picks)
    final_path = d / "plan.json"
    if not final_path.is_file() or final_path.stat().st_mtime < (judge.project / "answers" / f"{task}-plan.json").stat().st_mtime:
        plan.finalize(d, raw, found, cfg.get("brand"), cfg.get("news"))
    for shape in cfg["shapes"]:
        out = d / f"clip{render.suffix(shape, cfg['pack'])}.mp4"
        if not out.is_file() or out.stat().st_mtime < final_path.stat().st_mtime:
            say(f"{task}: rendering {shape} ({cfg['pack']})")
            render.render(d, shape, cfg["pack"])
    return waiting


def run(project: Path, judge: Judge, *, only: set[int] | None = None, say=print) -> dict:
    project = Path(project).resolve()
    src, cfg = _read(project / "source.json"), _read(project / "factory.json")
    if not src or not cfg:
        raise FactoryError(f"{project} is not a factory project; start one with 'zing factory new'")
    media = Path(src["media"])
    _write(project / "status.json", {"state": "running", "at": _now()})
    try:
        try:
            moments = _moments(project, judge, media, cfg, say)
        except NeedsAnswer:
            return _finish(project, judge, "waiting")
        words = _read(project / "words.json", [])
        failed = {}
        for i, m in enumerate(moments, 1):
            if only and i not in only:
                continue
            try:
                _clip(project, i, m, judge, media, cfg, words, say)
            except (FactoryError, ValueError, OSError) as exc:      # one bad clip never sinks the episode
                failed[f"clip{i:02d}"] = str(exc)[:300]
                say(f"clip{i:02d}: failed: {exc}")
        review.build(project, cfg["pack"])
        return _finish(project, judge, "waiting" if judge.pending() else "done", failed)
    except Exception as exc:
        _write(project / "status.json", {"state": "failed", "error": str(exc)[:500], "at": _now()})
        raise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finish(project: Path, judge: Judge, state: str, failed: dict | None = None) -> dict:
    _write(project / "status.json", {"state": state, "failed": failed or {}, "at": _now()})
    return status(project, judge)


def status(project: Path, judge: Judge | None = None) -> dict:
    project = Path(project).resolve()
    judge = judge or Judge(project)
    cfg = _read(project / "factory.json", {})
    moments = (_read(project / "moments.json") or {}).get("moments", [])
    clips = []
    for i, m in enumerate(moments, 1):
        d = project / f"clip{i:02d}"
        clips.append({"clip": f"clip{i:02d}", "hook": m["hook"].replace("*", ""), "start": m["start"], "end": m["end"],
                      "renders": sorted(p.name for p in d.glob("clip*.mp4")) if d.is_dir() else [],
                      "copy": (d / "post.json").is_file()})
    return {"project": str(project), **(_read(project / "status.json") or {"state": "new"}), "settings": cfg,
            "pending": judge.pending(), "clips": clips, "usage": judge.usage(),
            "review": str(project / "index.html") if (project / "index.html").is_file() else None}


def answer(project: Path, task: str, text: str | dict) -> dict:
    """Record an answer for a pending task (validated like the claude judge's answers)."""
    from .judge import parse
    kind = task.split("-")[-1]
    try:
        value = text if isinstance(text, dict) else parse(text)
        if kind == "scout":
            scout.check(value)
        elif kind == "plan":
            plan.check(value)
        elif kind == "copy":
            missing = [k for k in postcopy.FIELDS if not isinstance(value.get(k), str)]
            if missing:
                raise ValueError(f"copy answer is missing {', '.join(missing)}")
    except (ValueError, KeyError, TypeError) as exc:       # the prompt stays pending for another try
        raise FactoryError(f"answer for {task} rejected: {exc}") from exc
    Judge(Path(project)).save(task, value)
    return {"task": task, "saved": True}


def redo(project: Path, task: str) -> None:
    """Forget one judgment (and what was built from it) so the next run asks again."""
    project = Path(project)
    Judge(project).forget(task)
    clip, _, kind = task.partition("-")
    d = project / clip
    if task == "scout":
        (project / "moments.json").unlink(missing_ok=True)
    elif kind == "plan":
        shutil.rmtree(d / "visuals", ignore_errors=True)
        (d / "plan.json").unlink(missing_ok=True)
    elif kind == "pick":
        (d / "plan.json").unlink(missing_ok=True)
    elif kind == "copy":
        (d / "post.json").unlink(missing_ok=True)
