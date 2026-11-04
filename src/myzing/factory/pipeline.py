"""The clip factory: long episode -> scouted moments -> cut -> on-screen plan -> visuals -> rendered clips + copy.

Resumable: every stage writes its output and is skipped when that output exists. With the host judge a run stops
when it needs answers and asks for all of them that are ready at once (scout, plan and copy, visual pick,
then context after the plan is final).
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import context, cut, pick, plan, postcopy, render, review, scout, source, visuals
from .judge import Judge, NeedsAnswer
from .tools import FactoryError

MODES = ("context", "fun", "documentary", "launch")
SETTINGS = {"moments": 8, "mode": "context", "shapes": ["9x16", "1x1"], "pack": "zing", "public": False, "parallax": True,
            "cutout": False, "upscale": True, "brand": None, "focus": None, "show": None}
BENCH = 8                                           # the scout also lists up to this many runners-up to make by hand
TASTE = 12                                          # past Post/No calls the scout learns from
HAND = (3.0, 180.0)                                 # a clip picked by hand: shortest and longest, in seconds
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
    for key, most in (("focus", 300), ("show", 80)):
        value = settings.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > most):
            raise FactoryError(f"{key} must be a short line of text (up to {most} characters)")
    if settings.get("show") and not show_slug(settings["show"]):
        raise FactoryError("show needs at least one letter or digit")
    moments = settings.get("moments", 1)
    if not isinstance(moments, int) or isinstance(moments, bool) or moments < 0:
        raise FactoryError("moments must be 0 (only clips you pick) or more")
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
    data = load_moments(project)
    moments = data.get("moments", [])
    if not data.get("scouted"):
        segments = _transcript(project, media, say)     # also what clips are picked from by hand
    if not data.get("scouted") and cfg["moments"]:
        n = cfg["moments"]
        found = scout.check(judge.ask("scout", scout.prompt(segments, n + min(n, BENCH), cfg["mode"],
                                                            focus=cfg.get("focus"), taste=taste(project, cfg))),
                            segments[-1]["e"] if segments else None)
        moments = moments + found[:n]                # clips picked by hand before the scout keep their numbers
        data = {**data, "moments": moments, "bench": found[n:], "scouted": True}
        _write(path, data)
    todo = [m for m in moments if not m.get("snapped")]
    if not todo:
        return moments
    words = _read(project / "words.json") or []
    pieces = []                                     # films share spans: transcribe each stretch of the episode once
    for a, b in sorted(ab for m in todo for ab in scout.parts(m)):
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
    moments = [m if m.get("snapped") else {**scout.snap(m, words), "snapped": True} for m in moments]
    _write(path, {**data, "moments": moments})
    return moments


# ----------------------------------------------------------------------------- steering by hand
def load_moments(project: Path) -> dict:
    """moments.json. A file written before clips could be picked by hand had every clip scouted and snapped."""
    data = _read(Path(project) / "moments.json") or {}
    if data.get("snapped") is True:
        data = {"moments": [{**m, "snapped": True} for m in data.get("moments", [])], "bench": data.get("bench", []),
                "scouted": True}
    return data


def show_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:60]


def _show_file(show: str) -> Path:
    from myzing.storage import workspace_root
    return workspace_root() / "factory" / "shows" / f"{show_slug(show)}.jsonl"


def taste(project: Path, cfg: dict) -> list[dict]:
    """The newest Post/No calls to learn from: every episode of the project's show, or this project alone."""
    project = Path(project)
    if cfg.get("show") and _show_file(cfg["show"]).is_file():
        rows = [json.loads(line) for line in _show_file(cfg["show"]).read_text(encoding="utf-8").splitlines()
                if line.strip()]
    else:
        moments = load_moments(project).get("moments", [])
        rows = [{"project": "", "clip": clip, "hook": moments[int(clip[4:]) - 1].get("hook", ""),
                 "topic": moments[int(clip[4:]) - 1].get("topic", ""), **r}
                for clip, r in (_read(project / "ratings.json") or {}).items()
                if r.get("v") and int(clip[4:]) <= len(moments)]
    latest = {}
    for r in sorted(rows, key=lambda r: r.get("at", "")):  # a clip rated twice counts once, as last rated
        latest[(r.get("project", ""), r["clip"])] = r
    return sorted(latest.values(), key=lambda r: r.get("at", ""), reverse=True)[:TASTE]


def rate(project: Path, clip: str, v: str | None, why: str = "") -> dict:
    """Save a Post / Post with edits / No call, and add it to the show's history so the next episode learns from it."""
    project = Path(project).resolve()
    if v not in ("post", "fix", "no", None):
        raise FactoryError("rating must be post, fix or no")
    i = _clip_number(project, clip)
    row = {"v": v, "why": str(why or "")[:500], "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ratings = _read(project / "ratings.json", {})
    ratings[clip] = row
    _write(project / "ratings.json", ratings)
    cfg = _read(project / "factory.json", {})
    if cfg.get("show") and v:
        m = load_moments(project)["moments"][i - 1]
        hook = ((_read(project / clip / "plan.json") or {}).get("hook") or m.get("hook", "")).replace("*", "")
        history = _show_file(cfg["show"])
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"project": project.name, "clip": clip, "hook": hook, "topic": m.get("topic", ""),
                                **row}, ensure_ascii=False) + "\n")
    return {"saved": clip}


def _clip_number(project: Path, clip: str) -> int:
    moments = load_moments(project).get("moments", [])
    if not isinstance(clip, str) or not re.fullmatch(r"clip\d{2}", clip) or not 1 <= int(clip[4:]) <= len(moments):
        raise FactoryError(f"unknown clip {clip!r}")
    return int(clip[4:])


def check_range(project: Path, start, end) -> tuple[float, float]:
    """A hand-picked stretch of the episode: inside it, and between 3 seconds and 3 minutes long."""
    try:
        a, b = float(start), float(end)
    except (TypeError, ValueError):
        raise FactoryError("start and end must be seconds") from None
    segments = _read(Path(project) / "transcript.json") or []
    last = segments[-1]["e"] if segments else None
    if a < 0 or b <= a or (last is not None and a >= last):
        raise FactoryError(f"{a:.1f}-{b:.1f}s is not inside the episode")
    if not HAND[0] <= b - a <= HAND[1]:
        raise FactoryError(f"a clip runs {HAND[0]:.0f} s to {HAND[1] / 60:.0f} min; this one is {b - a:.0f} s")
    return round(a, 2), round(min(b, last + 1) if last is not None else b, 2)


def add_clip(project: Path, start, end, hook: str = "") -> str:
    """Add a clip picked by hand; the next run snaps it to sentences, cuts and plans it. Returns its clip id."""
    project = Path(project).resolve()
    a, b = check_range(project, start, end)
    data = {"moments": [], "bench": [], **load_moments(project)}
    data["moments"] = data.get("moments", []) + [{"hook": str(hook or "").strip()[:120], "why": "picked by hand",
                                                  "topic": "", "score": "", "start": a, "end": b, "by": "hand"}]
    _write(project / "moments.json", data)
    return f"clip{len(data['moments']):02d}"


def make_bench(project: Path, index: int) -> str:
    """Make one of the scout's runners-up (0-based, in the order status lists them). Returns its clip id."""
    project = Path(project).resolve()
    data = load_moments(project)
    bench = data.get("bench", [])
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(bench):
        raise FactoryError("no such runner-up")
    data["moments"] = data["moments"] + [bench[index]]
    data["bench"] = bench[:index] + bench[index + 1:]
    _write(project / "moments.json", data)
    return f"clip{len(data['moments']):02d}"


def trim(project: Path, clip: str, start, end) -> str:
    """Move a clip's in and out points; the next run re-cuts, re-plans and re-renders it."""
    project = Path(project).resolve()
    i = _clip_number(project, clip)
    data = load_moments(project)
    m = data["moments"][i - 1]
    if m.get("spans"):
        raise FactoryError(f"{clip} is a film made of several parts; trim it with redo scout instead")
    a, b = check_range(project, start, end)
    data["moments"][i - 1] = {**{k: v for k, v in m.items() if k not in ("snapped", "scout_start", "scout_end")},
                              "start": a, "end": b}
    _write(project / "moments.json", data)
    judge = Judge(project)
    for kind in ("plan", "copy", "pick", "context"):         # the words changed, so every judgment on them goes
        judge.forget(f"{clip}-{kind}")
    shutil.rmtree(project / clip, ignore_errors=True)
    ratings = _read(project / "ratings.json", {})
    if ratings.pop(clip, None) is not None:
        _write(project / "ratings.json", ratings)
    return clip


def _forget_context(d: Path, judge: Judge) -> None:
    judge.forget(f"{d.name}-context")
    (d / "context.json").unlink(missing_ok=True)


def _context(d: Path, judge: Judge, say=print) -> None:
    path = d / "context.json"
    if path.is_file() or not (d / "words.json").is_file() or not (d / "plan.json").is_file():
        return
    m = load_moments(d.parent)["moments"][int(d.name[4:]) - 1]
    words = _read(d / "words.json")
    spans = context.windows(_read(d.parent / "transcript.json", []), words, words.get("spans") or scout.parts(m))
    hook = _read(d / "plan.json")["hook"].replace("*", "")
    result = {"flags": [], "window": {"before": spans[0]["window"]["before"], "after": spans[-1]["window"]["after"]},
              "text": {"before": spans[0]["text"]["before"], "after": spans[-1]["text"]["after"]}}
    if len(spans) > 1:
        result["spans"] = [{"window": s["window"], "text": s["text"]} for s in spans]
    if not any(text.strip() for s in spans for text in s["text"].values()):
        result["skipped"] = "No transcript around this clip."
    else:
        try:
            result["flags"] = context.check(judge.ask(f"{d.name}-context", context.prompt(hook, spans)), hook, spans)
        except (ValueError, TypeError, RuntimeError) as exc:
            result["error"] = " ".join(str(exc).split())[:300] or type(exc).__name__
            say(f"{d.name} context check skipped. {result['error']}")
    _write(path, result)
    if result["flags"]:
        n = len(result["flags"])
        say(f"{d.name} check the context. {n} flag{'s' if n != 1 else ''}.")


def _clip(project: Path, i: int, m: dict, judge: Judge, media: Path, cfg: dict, words: list[dict], say) -> list[str]:
    """Advance one clip as far as it can go; returns the tasks it is waiting on."""
    d = project / f"clip{i:02d}"
    task = f"clip{i:02d}"
    if not (d / "cams.json").is_file():
        _forget_context(d, judge)
        say(f"{task}: cutting " + ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in scout.parts(m)))
        cut.cut(d, media, words, m["start"], m["end"], **({"spans": scout.parts(m)} if m.get("spans") else {}))
    w = _read(d / "words.json")
    src = _read(project / "source.json", {})
    waiting = []
    if not (d / "post.json").is_file():
        try:
            _write(d / "post.json", postcopy.finalize(judge.ask(f"{task}-copy", postcopy.prompt(m, w, src, cfg["mode"],
                                                                                                cfg.get("brand"))), w, src))
        except NeedsAnswer:
            waiting.append(f"{task}-copy")
    try:
        raw = plan.check(judge.ask(f"{task}-plan", plan.prompt(m, w, cfg["mode"], cfg.get("brand"))))
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
        plan.finalize(d, raw, found, cfg.get("brand"))
        _forget_context(d, judge)
    try:
        _context(d, judge, say)
    except NeedsAnswer:
        waiting.append(f"{task}-context")
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
    data = load_moments(project)
    moments = data.get("moments", [])
    clips = []
    for i, m in enumerate(moments, 1):
        d = project / f"clip{i:02d}"
        clips.append({"clip": f"clip{i:02d}", "hook": m["hook"].replace("*", ""), "start": m["start"], "end": m["end"],
                      "added": (_read(d / "receipt.json") or {}).get("share"),
                      "context_flags": len((_read(d / "context.json") or {}).get("flags", [])),
                      "renders": sorted(p.name for p in d.glob("clip*.mp4")) if d.is_dir() else [],
                      "copy": (d / "post.json").is_file(), **({"by": "hand"} if m.get("by") == "hand" else {})})
    bench = [{"hook": m["hook"].replace("*", ""), "why": m.get("why", ""), "topic": m.get("topic", ""),
              "start": m["start"], "end": m["end"]} for m in data.get("bench", [])]
    return {"project": str(project), **(_read(project / "status.json") or {"state": "new"}), "settings": cfg,
            "pending": judge.pending(), "clips": clips, "bench": bench, "usage": judge.usage(),
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
    if kind == "context":
        (Path(project) / task.rsplit("-", 1)[0] / "context.json").unlink(missing_ok=True)
    return {"task": task, "saved": True}


def redo(project: Path, task: str) -> None:
    """Forget one judgment (and what was built from it) so the next run asks again."""
    project = Path(project)
    Judge(project).forget(task)
    clip, _, kind = task.partition("-")
    d = project / clip
    if task == "scout":
        for path in project.glob("clip[0-9][0-9]"):
            _forget_context(path, Judge(project))
        (project / "moments.json").unlink(missing_ok=True)
    elif kind in ("plan", "pick"):
        if kind == "plan":
            shutil.rmtree(d / "visuals", ignore_errors=True)
        (d / "plan.json").unlink(missing_ok=True)
        (d / "receipt.json").unlink(missing_ok=True)
        _forget_context(d, Judge(project))
    elif kind == "copy":
        (d / "post.json").unlink(missing_ok=True)
    elif kind == "context":
        (d / "context.json").unlink(missing_ok=True)
