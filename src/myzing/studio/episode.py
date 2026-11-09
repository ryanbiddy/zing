"""The episode interview and its factory hand-off."""
from __future__ import annotations

import math
import shutil
from pathlib import Path

from . import evidence
from .models import read_json, write_json

SHAPES = ("9x16", "1x1", "4x5", "16x9")


def normalize(key, value):
    from .flow import _path, clean_path_text

    if key == "episode":
        text = clean_path_text(value) if isinstance(value, str) else ""
        if text.startswith("uoink:"):
            from myzing.project.references import item_ref
            return item_ref(text)
        if "://" in text:
            raise ValueError("Use a local episode file. Use zing from-uoink for a saved item, or download the episode first.")
        return _path(text, key)
    if key == "transcript":
        if value in (None, "", "none"):
            return "none"
        path = _path(value, key)
        if Path(path).suffix.lower() not in {".srt", ".vtt", ".json"}:
            raise ValueError("Choose an SRT, VTT or word JSON transcript, or none.")
        return path
    if key == "clips":
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value)
        if type(value) is not int or not 1 <= value <= 12:
            raise ValueError("Choose 1 to 12 moments to scout.")
    elif key == "shapes":
        if isinstance(value, str):
            value = [s.strip() for s in value.split(",")]
        if (not isinstance(value, list) or not value or any(s not in SHAPES for s in value)
                or len(set(value)) != len(value)):
            raise ValueError("Choose any of 9x16, 1x1, 4x5 and 16x9, separated by commas.")
    elif key == "judge":
        if value not in ("claude", "host"):
            raise ValueError("Choose claude or host for the judge.")
    elif key == "no_open":
        if isinstance(value, str) and value.lower() in {"yes", "no", "true", "false"}:
            value = value.lower() in {"yes", "true"}
        if type(value) is not bool:
            raise ValueError("no_open must be yes or no.")
    return value


def _media(value, cache):
    if value.startswith("uoink:"):
        from myzing.handoff import _kept_media
        key = ("episode", value)
        if key not in cache:
            cache[key] = _kept_media(value)
        path, _ = cache[key]
        if path is None:
            raise ValueError("Uoink has no kept episode. Use zing from-uoink, or download the episode first.")
        return path.resolve()
    return Path(value)


def next_step(a, cache):
    from .flow import PATHS, default_project, question

    root = Path(a.get("project") or default_project())
    facts = {"measured": [], "unknowns": [], "warnings": []}
    media, duration, sibling = None, None, None
    if "episode" in a:
        media = _media(a["episode"], cache)
        probe, error = evidence.cached_probe(media, cache)
        duration = probe.get("duration")
        if error or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("Could not measure the episode duration. Check the file and run zing doctor.")
        if not any(st.get("codec_type") == "video" and not (st.get("disposition") or {}).get("attached_pic")
                   for st in probe.get("streams", [])):
            raise ValueError("The clip factory needs a video file. Audio-only episodes are not supported yet.")
        if duration < 60:
            raise ValueError("The episode must be at least 60 seconds long.")
        facts["measured"].append(f"Episode duration is {duration:g} seconds.")
        sibling = next((p for ext in (".srt", ".vtt", ".json") if (p := media.with_suffix(ext)).is_file()), None)
    reserved = {root / name for name in ("studio-session.json", "studio-result.json", "studio-job.json",
                                        "source.json", "factory.json", "transcript.json", "words.json", "network.jsonl")}
    for value in (media, a.get("transcript")):
        if value and value != "none" and Path(value) in reserved:
            raise ValueError(f"Output would replace input {value}. Choose a different project folder.")
    judge = "claude" if shutil.which("claude") else "host"
    queue = [
        question("episode", "Which local video file holds the episode? A uoink:<id> also works.", None,
                 "Choose the full episode. It must be at least 60 seconds long.", facts, required=True),
        question("transcript", "Transcript file? Type a path, or none to let Zing transcribe.", str(sibling) if sibling else "none",
                 "A transcript with the same name is beside the episode. Zing checks that it lines up with the video." if sibling else
                 "No matching transcript was found. The factory transcribes when you press Run.", facts),
        question("clips", "How many moments should I scout?", 3, "Three is a small first run to review. Choose 1 to 12.", facts),
        question("shapes", "Which shapes? Separate several with commas.", ["9x16"],
                 "Start with vertical clips for Shorts.", facts, SHAPES),
        question("judge", "Who should answer the review prompts?", judge,
                 "Claude Code is on PATH and can answer the prompts." if judge == "claude" else
                 "You or your agent answer prompts on the review page or with zing factory answer.", facts,
                 ("claude", "host")),
        question("project", "Where should I save the project?", str(root), "Keep this episode in its own project folder.", facts),
    ]
    for q in queue:
        if q.id not in a:
            return {"status": "question", "question": q.to_dict(), "answers": a}
    plan = {"version": 1, "path": "g", "title": PATHS["g"], "episode": str(media), "duration": duration,
            "transcript": a["transcript"], "clips": a["clips"], "shapes": a["shapes"], "judge": a["judge"],
            "project": str(root), "output_folder": str(root), "aspects": a["shapes"],
            "steps": ["Create the factory project", "Open the review page", "Press Run to scout and render clips"],
            "estimate": {"seconds": None, "basis": "Rendering starts when you press Run.", "source_seconds": duration},
            "downloads": [], "warnings": [], "evidence": facts, "confirmation_required": True,
            "execution": [{"tool": "zing_studio_run", "arguments": {"answers": a, "confirmed": True},
                           "after": "Confirm this plan, then call factory_run and poll factory_status with the returned project."}]}
    return {"status": "plan", "plan": plan, "answers": a}


def create(a, plan):
    from myzing.factory import pipeline

    root, media = Path(a["project"]), Path(plan["episode"])
    reused = (root / "factory.json").is_file()
    if reused:
        saved = read_json(root / "source.json")
        if not isinstance(saved, dict) or not isinstance(saved.get("media"), str):
            raise ValueError("This project has no saved episode. Choose a different project folder.")
        if Path(saved.get("media", "")).resolve() != media:
            raise ValueError("This project holds another episode. Choose a different project folder.")
    else:
        allowed = {"studio-session.json", "studio-result.json", "match-job"}
        if root.exists() and any(p.name not in allowed for p in root.iterdir()):
            raise ValueError("This folder holds other work. Choose a fresh project folder.")
        pipeline.init(root, media, transcript=None if a["transcript"] == "none" else Path(a["transcript"]),
                      name=media.stem, rights="unknown", moments=a["clips"], shapes=a["shapes"],
                      **({"uoink_ref": a["episode"]} if a["episode"].startswith("uoink:") else {}))
    result = {"version": 1, "ok": True, "status": "ready", "path": "g", "project": str(root), "reused": reused,
              "next_actions": [f'zing factory status "{root}"'],
              "hint": "Call factory_run with the project, then poll factory_status. Answer pending prompts and run again.",
              "execution": [{"tool": tool, "arguments": {"project": str(root)}} for tool in ("factory_run", "factory_status")]}
    write_json(root / "studio-result.json", result)
    return result
