"""The clip factory: long episode -> scouted moments -> cut -> on-screen plan -> visuals -> rendered clips + copy.

Resumable: every stage writes its output and is skipped when that output exists. With the host judge a run stops
when it needs answers and asks for all of them that are ready at once (scout, plan and copy, visual pick,
then context after the plan is final).
"""
from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import campaign, context, cut, jev, network, pick, plan, postcopy, render, review, scout, source, transcript_sync, visuals
from .judge import Judge, NeedsAnswer
from .tools import FactoryError

MODES = ("context", "fun", "documentary", "launch")
SETTINGS = {"moments": 8, "mode": "context", "shapes": ["9x16", "1x1"], "pack": "desk", "public": False, "parallax": True,
            "cutout": False, "upscale": True, "uhd": False, "brand": None, "focus": None, "show": None, "vocab": [],
            "news": None, "offline": False, "visuals": None, "rights": "unknown", "channel": None, "source": None,
            "uoink_ref": None, "no_sync_check": False, "rank": None}
BENCH = 8                                           # the scout also lists up to this many runners-up to make by hand
TASTE = 12                                          # past Post/No calls the scout learns from
HAND = (3.0, 180.0)                                 # a clip picked by hand: shortest and longest, in seconds
LAUNCH = {"moments": 2, "shapes": ["16x9", "1x1", "9x16"], "pack": "launch"}   # a launch film is landscape first


class _Stopped(Exception):
    pass


def _checkpoint(stop):
    if stop and stop():
        raise _Stopped


def _read(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _stage(path: Path):
    try:
        return _read(path)
    except json.JSONDecodeError:
        path.unlink(missing_ok=True)
        return None


def init(project: Path, media: Path, *, transcript: Path | None = None, offset: float | None = None, name: str | None = None,
         url: str = "", date: str = "", tag: str = "", rights: str = "unknown", brief: Path | dict | None = None, **settings) -> dict:
    """Create a factory project. The media stays where it is; nothing is downloaded or uploaded."""
    project, media = Path(project).resolve(), Path(media).resolve()
    if not media.is_file():
        raise FactoryError(f"media not found: {media}")
    if not isinstance(rights, str) or rights not in campaign.RIGHTS:
        raise FactoryError(f"rights must be one of {', '.join(campaign.RIGHTS)}")
    rules = None
    if brief is not None:
        rules = campaign.validate(dict(brief)) if isinstance(brief, dict) else campaign.load(Path(brief).expanduser())
    settings["rights"] = rights
    unknown = set(settings) - set(SETTINGS)
    if unknown:
        raise FactoryError(f"unknown settings: {', '.join(sorted(unknown))}")
    if not isinstance(settings.get("offline", False), bool):
        raise FactoryError("offline must be true or false")
    if settings.get("rank") not in (None, "jev"):
        raise FactoryError("rank must be jev")
    if not isinstance(settings.get("no_sync_check", False), bool):
        raise FactoryError("no_sync_check must be true or false")
    if offset is not None and (not isinstance(offset, (int, float)) or isinstance(offset, bool) or not math.isfinite(offset)):
        raise FactoryError("offset must be a finite number of seconds")
    if settings.get("visuals") is not None:
        folder = Path(settings["visuals"]).expanduser().resolve()
        if not folder.is_dir():
            raise FactoryError(f"visuals folder not found at {folder}")
        settings["visuals"] = str(folder)
    render.scale(settings)
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
    from myzing.study.asr_hygiene import vocabulary_context
    context = vocabulary_context(settings.get("vocab", ()))
    if context["omitted"]:
        raise FactoryError(context["omitted"][0]["reason"])
    settings["vocab"] = context["terms"]
    moments = settings.get("moments", 1)
    if not isinstance(moments, int) or isinstance(moments, bool) or moments < 0:
        raise FactoryError("moments must be 0 (only clips you pick) or more")
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
    if transcript:
        segments, words = source.load_transcript(Path(transcript))
        settings["transcript_offset"] = offset or 0.0
        settings["transcript_sync"] = ({"status": "skipped", "method": "offset"} if offset is not None else
                                       {"status": "skipped", "method": "disabled"} if settings.get("no_sync_check") else
                                       {"status": "pending"})
    project.mkdir(parents=True, exist_ok=True)
    src = {"media": str(media), "name": name or media.stem, "url": url, "date": date, "tag": tag}
    _write(project / "source.json", src)
    if rules is not None:
        _write(project / "brief.json", rules)
    (project / "network.jsonl").touch(exist_ok=True)
    if transcript:
        _write(project / "transcript.json", segments)
        if words:
            _write(project / "words.json", words)
        if offset is not None:
            _shift_transcript(project, media, offset)
    _write(project / "factory.json", {**SETTINGS, **settings, "created": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return status(project)


def _transcript(project: Path, media: Path, say, vocab: list[str] | None = None) -> list[dict]:
    segments = _read(project / "transcript.json")
    if segments is None:
        quick = source.scout_model()
        say(f"transcribing the whole episode with the {quick or 'configured'} speech model (no caption file given)")
        words = source.transcribe_episode(media, quick, **({"vocab": vocab} if vocab else {}))
        if not quick:                      # a quick pass only finds the moments; their words come from the full model
            _write(project / "words.json", words)
        segments = source.segments_from_words(words)
        _write(project / "transcript.json", segments)
    return segments


def _shift_transcript(project: Path, media: Path, offset: float) -> list[dict]:
    duration = transcript_sync.duration(media)
    originals = {}
    for name in ("transcript", "words"):
        path = project / f"{name}.unsynced.json"
        rows = _read(path) if path.is_file() else _read(project / f"{name}.json")
        if rows is not None:
            if not path.is_file():
                _write(path, rows)
            originals[name] = rows
    for name, rows in originals.items():
        _write(project / f"{name}.json", transcript_sync.shift(rows, offset, duration))
    return _read(project / "transcript.json", [])


def _restore_transcript(project: Path) -> None:
    for name in ("transcript", "words"):
        path = project / f"{name}.unsynced.json"
        if path.is_file():
            _write(project / f"{name}.json", _read(path))


def configure_sync(project: Path, *, no_sync_check: bool = False, offset: float | None = None) -> None:
    if not isinstance(no_sync_check, bool):
        raise FactoryError("no_sync_check must be true or false")
    if offset is not None and (not isinstance(offset, (int, float)) or isinstance(offset, bool) or not math.isfinite(offset)):
        raise FactoryError("offset must be a finite number of seconds")
    if not no_sync_check and offset is None:
        return
    project = Path(project).resolve()
    cfg = _read(project / "factory.json", {})
    if load_moments(project).get("scouted"):
        raise FactoryError("Transcript sync cannot change after moments have already been scouted.")
    if not cfg.get("transcript_sync"):
        raise FactoryError("This project has no supplied transcript.")
    if offset is not None:
        _shift_transcript(project, Path(_read(project / "source.json")["media"]), offset)
        cfg["transcript_offset"] = offset
        Judge(project).forget("scout")
    elif cfg["transcript_sync"].get("status") == "pending":
        _restore_transcript(project)
    cfg.update(no_sync_check=no_sync_check,
               transcript_sync={"status": "skipped", "method": "offset" if offset is not None else "disabled"})
    _write(project / "factory.json", cfg)


def _sync_transcript(project: Path, media: Path, cfg: dict, segments: list[dict], say) -> list[dict]:
    saved = cfg.get("transcript_sync", {})
    if saved.get("status") == "pending":
        _restore_transcript(project)
        segments = _read(project / "transcript.json", segments)
        words = _read(project / "words.json")
        saved = transcript_sync.check(media, segments, words, cfg.get("vocab"))
        offset = saved.get("offset", 0.0)
        if offset:
            segments = _shift_transcript(project, media, offset)
            direction = "behind" if offset > 0 else "ahead of"
            say(f"The transcript was {transcript_sync.stamp(offset)} {direction} the video, "
                f"so Zing shifted it (checked at {len(saved['probes'])} points).")
        elif saved.get("status") == "skipped":
            why = {"no_cached_model": "no speech model is cached", "speech_off": "speech is turned off",
                   "too_little_speech": "too little speech was heard", "probe_error": "the speech probes could not run"}
            say(f"Zing skipped the transcript sync check because {why[saved['method']]}.")
            if saved.get("error"):
                say(saved["error"])
        cfg.update(transcript_offset=offset, transcript_sync=saved)
        _write(project / "factory.json", cfg)
    if saved.get("status") == "failed":
        raise FactoryError(transcript_sync.MISMATCH.format(project=project))
    return segments


def _moments(project: Path, judge: Judge, media: Path, cfg: dict, say, stop=None) -> list[dict]:
    path = project / "moments.json"
    brief = campaign.read(project)
    mode = cfg.get("mode", "context")
    data = load_moments(project)
    moments = data.get("moments", [])
    if not data.get("scouted"):
        segments = _transcript(project, media, say, cfg.get("vocab"))     # also what clips are picked from by hand
        segments = _sync_transcript(project, media, cfg, segments, say)
    if not data.get("scouted") and cfg["moments"]:
        _checkpoint(stop)
        n = cfg["moments"]
        found = scout.check(judge.ask("scout", scout.prompt(segments, n + min(n, BENCH), mode,
                                                            focus=cfg.get("focus"), taste=taste(project, cfg),
                                                            news=cfg.get("news"), brief=brief, channel=cfg.get("channel"),
                                                            ranked=_ranked(project, cfg, segments, say))),
                            segments[-1]["e"] if segments else None, brief=brief, mode=mode)
        moments = moments + found[:n]                # clips picked by hand before the scout keep their numbers
        data = {**data, "moments": moments, "bench": found[n:], "scouted": True}
        _write(path, data)
    todo = [m for m in moments if not m.get("snapped")]
    if not todo:
        return moments
    _checkpoint(stop)
    words = _read(project / "words.json") or []
    pieces = []                                     # films share spans: transcribe each stretch of the episode once
    for a, b in sorted(ab for m in todo for ab in scout.parts(m)):
        if pieces and a <= pieces[-1]["end"] + 2 * source.MARGIN:
            pieces[-1]["end"] = max(pieces[-1]["end"], b)
        else:
            pieces.append({"start": a, "end": b})
    if not all(any(p["start"] <= w["s"] <= p["start"] + 2 for w in words)
               and any(p["end"] - 2 <= w["e"] <= p["end"] for w in words) for p in pieces):
        say(f"transcribing {len(pieces)} spans for word timing")
        fresh = source.transcribe_moments(media, pieces, **({"vocab": cfg["vocab"]} if cfg.get("vocab") else {}))
        span = [(p["start"] - source.MARGIN, p["end"] + source.MARGIN) for p in pieces]
        words = sorted(fresh + [w for w in words if not any(a <= w["s"] <= b for a, b in span)], key=lambda w: w["s"])
        _write(project / "words.json", words)
    if words and cfg.get("transcript_sync", {}).get("status") == "matched":
        transcript = _read(project / "transcript.json", [])
        for m in todo:
            error = transcript_sync.guard(transcript, words, scout.parts(m))
            if error:
                m["timing_error"] = error
    moments = [m if m.get("snapped") else {**scout.snap(m, words, brief, mode), "snapped": True} for m in moments]
    _write(path, {**data, "moments": moments})
    return moments


def _ranked(project: Path, cfg: dict, segments: list[dict], say) -> str | None:
    """The Jev shortlist for the scout prompt. A failure is recorded and the scout runs as before."""
    if cfg.get("rank") != "jev":
        return None
    try:
        ranked = jev.shortlist(jev.score(project, segments, say))
    except Exception as exc:                        # never stops the factory
        reason = " ".join(str(exc).split())[:300] or type(exc).__name__
        _write(project / "rank.json", {"rank": "jev", "state": "failed", "reason": reason, "at": _now()})
        say(f"Jev ranking skipped: {reason}")
        return None
    _write(project / "rank.json", {"rank": "jev", "state": "scored", "windows": len(ranked), "at": _now()})
    return jev.block(ranked)


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
        rows = [json.loads(line.rstrip("\r")) for line in _show_file(cfg["show"]).read_text(encoding="utf-8").split("\n")
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
    row = {"v": v, "why": str(why or "")[:500], "at": datetime.now(timezone.utc).isoformat(timespec="microseconds")}
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
    data["moments"][i - 1] = {**{k: v for k, v in m.items() if k not in ("snapped", "scout_start", "scout_end", "timing_error")},
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


def _forget_context(d: Path, judge: Judge | None = None) -> None:
    Judge(d.parent).forget(f"{d.name}-context")             # the cached answer is a file, whoever the judge is
    (d / "context.json").unlink(missing_ok=True)


def _context(d: Path, judge: Judge, say=print, m: dict | None = None) -> None:
    path = d / "context.json"
    if path.is_file() or not (d / "words.json").is_file() or not (d / "plan.json").is_file():
        return
    m = m or load_moments(d.parent)["moments"][int(d.name[4:]) - 1]
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


def _arms(d: Path, moment: dict, cfg: dict, post: dict) -> dict:
    planned, words = _read(d / "plan.json", {}), _read(d / "words.json", {})
    duration = render.timeline(planned, words)[0]
    graphics = sum(s.get("layout") == "graphic" for s in planned.get("shots", []))
    arms = {"archetype": moment.get("archetype") if moment.get("archetype") in scout.ARCHETYPES else "other",
            "title_pattern": post.get("title_pattern"), "title_propensity": post.get("title_propensity"),
            "title_policy": post.get("title_policy"), "length": "short" if duration < 29 else "mid" if duration <= 45 else "long",
            "density": "heavy" if duration > 0 and graphics * 60 / duration >= 6 else "light",
            "pack": cfg["pack"], "hour": _read(d / "arms.json", {}).get("hour")}
    if "title_candidates" in post:
        arms["title_candidates"] = post["title_candidates"]
    if moment.get("series") is not None:
        arms["series"] = moment["series"]
    _write(d / "arms.json", arms)
    return arms


def _clip(project: Path, i: int, m: dict, judge: Judge, media: Path, cfg: dict, words: list[dict], say, stop=None) -> list[str]:
    """Advance one clip as far as it can go; returns the tasks it is waiting on."""
    if m.get("timing_error"):
        raise FactoryError(m["timing_error"])
    d = project / f"clip{i:02d}"
    task = f"clip{i:02d}"
    if _stage(d / "cams.json") is None:
        _forget_context(d, judge)
        say(f"{task}: cutting " + ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in scout.parts(m)))
        cut.cut(d, media, words, m["start"], m["end"], **({"spans": scout.parts(m)} if m.get("spans") else {}))
    w = _read(d / "words.json")
    src = _read(project / "source.json", {})
    brief = campaign.read(project)
    src["url"] = src.get("url") or cfg.get("url", "")
    src["rights"] = cfg.get("rights", "unknown")
    waiting = []
    _checkpoint(stop)
    if not (d / "post.json").is_file():
        voice = None
        if cfg.get("channel"):
            from myzing.channels.registry import voice as channel_voice
            voice = channel_voice(cfg["channel"])
        try:
            post = postcopy.finalize(judge.ask(f"{task}-copy", postcopy.prompt(m, w, src, cfg["mode"], cfg.get("brand"),
                                                                           cfg.get("news"), voice=voice)), w, src, brief,
                                     cfg.get("news"))
            if cfg.get("channel"):
                post = postcopy.require_tags(postcopy.choose(post, cfg["channel"], clipdir=d), brief)
            _write(d / "post.json", post)
        except NeedsAnswer:
            waiting.append(f"{task}-copy")
    heard = _read(d / "words-heard.json", w)
    _checkpoint(stop)
    try:
        raw = plan.check(judge.ask(f"{task}-plan", plan.prompt(m, heard, cfg["mode"], cfg.get("brand"), cfg.get("vocab"),
                                                               news=cfg.get("news"))), w["words"][-1]["oe"])
    except NeedsAnswer:
        return waiting + [f"{task}-plan"]
    _write(d / "plan-raw.json", raw)
    sensitive = bool(raw.get("sensitive"))
    mode = cfg["mode"] if not sensitive or cfg["mode"] == "documentary" else "context"   # a documentary is already restrained
    reqs = raw.get("visual_requests", [])
    visdir = d / "visuals"
    found: dict = {}
    _checkpoint(stop)
    if reqs:
        if _stage(visdir / "manifest.json") is None:
            say(f"{task}: finding visuals for {len(reqs)} requests ({mode})")
            _write(visdir / "requests.json", reqs)
            visuals.find(reqs, visdir, "context" if mode == "launch" else mode, public=cfg.get("public", False), say=say,
                         project=project, visuals=cfg.get("visuals"), words=" ".join(x["w"] for x in w["words"]))
        manifest = _read(visdir / "manifest.json", {})
        if any(manifest.values()):
            saved = _read(visdir / "picks.json")
            if saved is None:
                _checkpoint(stop)
                sheet = pick.sheet(visdir, reqs, manifest)
                if sheet is None:
                    say(f"{task} has no pick sheet. Continuing without visuals.")
                else:
                    try:
                        answer = judge.ask(f"{task}-pick", pick.prompt(sheet, "context" if mode == "launch" else mode,
                                                                   raw.get("sensitive_reason", "") if sensitive else None),
                                           images=(sheet,))
                    except NeedsAnswer:
                        return waiting + [f"{task}-pick"]
                    saved = {"mode": mode, "picks": pick.picks_from(answer)}
                    _write(visdir / "picks.json", saved)
            if saved is not None:
                found = pick.chosen(visdir, reqs, manifest, saved["picks"])
    final_path = d / "plan.json"
    inputs = [project / "answers" / f"{task}-{kind}.json" for kind in ("plan", "pick")] + [visdir / "picks.json"]
    if _stage(final_path) is None or any(p.is_file() and p.stat().st_mtime > final_path.stat().st_mtime for p in inputs):
        plan.finalize(d, raw, found, cfg.get("brand"), cfg.get("news"))
        _forget_context(d, judge)
    try:
        _checkpoint(stop)
        _context(d, judge, say, m)
    except NeedsAnswer:
        waiting.append(f"{task}-context")
    post = _read(d / "post.json")
    if post is not None:
        updated = {**postcopy.require_tags(post, brief), "rights": src.get("rights", "unknown")}
        if updated != post:
            _write(d / "post.json", updated)
    elif brief:
        return waiting
    _arms(d, m, cfg, updated if post is not None else {})
    render.check_brief(d)
    theme, assets, _ = render.pack_data(cfg["pack"])
    brand = {"theme": theme, **assets}
    for shape in cfg["shapes"]:
        _checkpoint(stop)
        tag = render.suffix(shape, cfg["pack"])
        out = d / f"clip{tag}.mp4"
        data_file = d / f"data{tag}.json"
        saved = _read(data_file, {})
        if (not out.is_file() or out.stat().st_mtime < final_path.stat().st_mtime
                or (data_file.is_file() and data_file.stat().st_mtime_ns > out.stat().st_mtime_ns)
                or saved.get("scale", 1) != render.scale(cfg)
                or saved.get("disclosure") != campaign.disclosure(brief)
                or any(saved.get(k) != brand.get(k) for k in ("theme", "fonts", "logo"))):
            say(f"{task}: rendering {shape} ({cfg['pack']})")
            render.render(d, shape, cfg["pack"])
    return waiting


def run(project: Path, judge: Judge, *, only: set[int] | None = None, say=print, stop=None) -> dict:
    with network.scope(project):
        return _run(project, judge, only=only, say=say, **({"stop": stop} if stop else {}))


def _run(project: Path, judge: Judge, *, only: set[int] | None = None, say=print, stop=None) -> dict:
    from myzing.layout.detector import MissingModelError
    project = Path(project).resolve()
    if isinstance(judge, Judge):
        judge.validate = lambda task, value: _check_answer(project, task, value) \
            if task == "scout" or task.endswith("-plan") else None
    if getattr(judge, "backend", "host") == "claude":
        network.Network(project).check("Claude judge")
    src, cfg = _read(project / "source.json"), _read(project / "factory.json")
    if not src or not cfg:
        raise FactoryError(f"{project} is not a factory project; start one with 'zing factory new'")
    media = Path(src["media"])
    _write(project / "status.json", {"state": "running", "at": _now()})
    failed = {}
    try:
        _checkpoint(stop)
        render.warn_uhd(project, say)
        try:
            moments = _moments(project, judge, media, cfg, say, **({"stop": stop} if stop else {}))
        except NeedsAnswer:
            return _finish(project, judge, "waiting")
        words = _read(project / "words.json", [])
        for i, m in enumerate(moments, 1):
            _checkpoint(stop)
            if only and i not in only:
                continue
            try:
                _clip(project, i, m, judge, media, cfg, words, say, **({"stop": stop} if stop else {}))
            except _Stopped:
                raise
            except MissingModelError as exc:
                raise FactoryError(str(exc)) from exc
            except Exception as exc:                  # one bad clip never sinks the episode
                failed[f"clip{i:02d}"] = str(exc)[:300]
                say(f"clip{i:02d}: failed: {exc}")
        _checkpoint(stop)
        review.build(project, cfg["pack"])
        return _finish(project, judge, "waiting" if judge.pending() else "done", failed)
    except _Stopped:
        return _finish(project, judge, "stopped", failed)
    except Exception as exc:
        _write(project / "status.json", {"state": "failed", "error": str(exc)[:500], "at": _now()})
        raise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finish(project: Path, judge: Judge, state: str, failed: dict | None = None) -> dict:
    _write(project / "status.json", {"state": state, "failed": failed or {}, "at": _now()})
    return status(project, judge)


def run_error(result: dict) -> str:
    failed = result.get("failed", {})
    if result.get("state") != "done" or not failed or any(c.get("renders") for c in result.get("clips", [])):
        return ""
    reason = " ".join(str(next(iter(failed.values()))).split())
    noun = "clip" if len(failed) == 1 else "clips"
    return f"No clips rendered. {len(failed)} {noun} failed. {reason}".strip()


def status(project: Path, judge: Judge | None = None) -> dict:
    """Assemble the full report for ``zing factory status``. ``status.json`` is a lock-step marker only."""
    project = Path(project).resolve()
    judge = judge or Judge(project)
    cfg = _read(project / "factory.json", {})
    src = _read(project / "source.json", {})
    data = load_moments(project)
    moments = data.get("moments", [])
    clips = []
    for i, m in enumerate(moments, 1):
        d = project / f"clip{i:02d}"
        vis = d / "visuals"
        requests = _read(vis / "requests.json") or _read(d / "plan-raw.json", {}).get("visual_requests", [])
        manifest, picks = _read(vis / "manifest.json", {}), _read(vis / "picks.json", {}).get("picks", {})
        hook = (_read(d / "plan.json") or {}).get("hook") or m["hook"]
        clips.append({"clip": f"clip{i:02d}", "hook": hook.replace("*", ""), "start": m["start"], "end": m["end"],
                      **({"scout_hook": m["hook"]} if hook != m["hook"] else {}),
                      "added": (_read(d / "receipt.json") or {}).get("share"),
                      "context_flags": len((_read(d / "context.json") or {}).get("flags", [])),
                      "brief_flags": len((_read(d / "brief_check.json") or {}).get("flags", [])),
                      "brief_errors": (_read(d / "brief_check.json") or {}).get("errors", []),
                      "renders": sorted(p.name for p in d.glob("clip*.mp4")) if d.is_dir() else [],
                      "visual_requests": [{**r, "candidate_count": len(manifest.get(r["id"], [])),
                                           "pick": picks.get(r["id"], {}).get("pick"),
                                           "candidates": [{**c, "index": j} for j, c in enumerate(manifest.get(r["id"], []))]}
                                          for r in requests],
                      "copy": (d / "post.json").is_file(), **({"by": "hand"} if m.get("by") == "hand" else {})})
    bench = [{"hook": m["hook"].replace("*", ""), "why": m.get("why", ""), "topic": m.get("topic", ""),
              "start": m["start"], "end": m["end"]} for m in data.get("bench", [])]
    return {"project": str(project), **(_read(project / "status.json") or {"state": "new"}), "settings": cfg,
            "source": src, "rights": cfg.get("rights", "unknown"),
            "pending": judge.pending(), "clips": clips, "bench": bench, "usage": judge.usage(),
            "network": network.summary(project),
            **({"rank": _read(project / "rank.json")} if (project / "rank.json").is_file() else {}),
            "review": str(project / "index.html") if (project / "index.html").is_file() else None}


def _check_answer(project: Path, task: str, value: dict) -> None:
    if not isinstance(value, dict):
        raise ValueError("the answer must be a JSON object")
    kind = task.split("-")[-1]
    if kind == "scout":
        cfg = _read(project / "factory.json", {})
        segments = _read(project / "transcript.json", [])
        scout.check(value, segments[-1]["e"] if segments else None, brief=campaign.read(project),
                    mode=cfg.get("mode", "context"))
    elif kind == "plan":
        plan.check(value)
    elif kind == "copy":
        missing = [k for k in postcopy.FIELDS if not isinstance(value.get(k), str)]
        if missing:
            raise ValueError(f"copy answer is missing {', '.join(missing)}")
    elif kind == "context":
        context.check(value, "", [])


def answer(project: Path, task: str, text: str | dict) -> dict:
    """Record an answer for a pending task (validated like the claude judge's answers)."""
    from .judge import parse
    try:
        value = text if isinstance(text, dict) else parse(text)
        _check_answer(Path(project), task, value)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:       # the prompt stays pending for another try
        raise FactoryError(f"answer for {task} rejected: {exc}") from exc
    Judge(Path(project)).save(task, value)
    if task.endswith("-context"):
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
        for p in project.glob("clip[0-9][0-9]"):
            shutil.rmtree(p, ignore_errors=True)
        for folder in ("answers", "pending"):
            for p in (project / folder).glob("clip[0-9][0-9]-*"):
                p.unlink(missing_ok=True)
    elif task == "jev":
        (project / "answers" / "jev.json").unlink(missing_ok=True)
        (project / "rank.json").unlink(missing_ok=True)
    elif kind == "plan":
        Judge(project).forget(f"{clip}-pick")
        shutil.rmtree(d / "visuals", ignore_errors=True)
        shutil.rmtree(d / "mattes", ignore_errors=True)
        (d / "plan.json").unlink(missing_ok=True)
        (d / "receipt.json").unlink(missing_ok=True)
        _forget_context(d)
    elif kind == "pick":
        (d / "visuals" / "picks.json").unlink(missing_ok=True)
        (d / "plan.json").unlink(missing_ok=True)
        (d / "receipt.json").unlink(missing_ok=True)
        _forget_context(d, Judge(project))
    elif kind == "copy":
        (d / "post.json").unlink(missing_ok=True)
    elif kind == "context":
        (d / "context.json").unlink(missing_ok=True)
    if kind in ("plan", "pick", "copy"):
        (d / "brief_check.json").unlink(missing_ok=True)
