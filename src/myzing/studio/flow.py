"""Stateless question/plan API shared by stdin and MCP. No production writes."""

from __future__ import annotations

import math
import os
import re
from pathlib import Path

from myzing.urls import is_http_url
from . import evidence
from .models import Question

PATHS = {
    "a": "Edit my clips to look like a reference video",
    "b": "Edit my clips (no reference): pick a style from the brief",
    "c": "A meme or still from photos plus a topic",
    "d": "Break down a video's style",
    "e": "Check music for an edit",
    "f": "Re-deliver an existing edit or plan",
}
KEYS = {"path", "project", "reference_kind", "reference", "reference_query", "allow_download",
        "clips", "photos", "topic", "platform", "aspects", "length", "tone", "captions",
        "music", "tracks", "source", "context", "speech", "draft"}
DELIVERY_KEYS = {"caption_options", "caption_mode", "picture_crop", "target_mb", "video_bitrate_kbps"}
KEYS |= DELIVERY_KEYS
ASPECTS = ["16:9", "1:1", "9:16"]


def options(values):
    return [{"value": value, "label": label} for value, label in
            (values.items() if isinstance(values, dict) else ((v, v) for v in values))]


def question(key, prompt, recommended, reason, facts, choices=(), required=False):
    return Question(key, prompt, options(choices), recommended, reason,
                    {k: facts[k] for k in ("measured", "unknowns", "warnings", "reference") if k in facts}, required)


def default_project():
    return default_project_in(Path("zing-workspace/studio"))


def default_project_in(base):
    """The first unused ``studio``/``studio-N`` folder name beside ``base``."""
    base = Path(base).expanduser().resolve()
    path, suffix = base, 2
    while path.exists():
        path = base.with_name(f"{base.name}-{suffix}")
        suffix += 1
    return str(path)


def agent_default_project():
    """MCP servers run from the client's working directory (often / or a system
    folder), so agent sessions default inside the Zing workspace instead."""
    from myzing import storage
    return default_project_in(storage.resolve_workspace() / "studio")


def reserve_project():
    """Terminal sessions claim their default folder at once with an exclusive mkdir.

    Two `zing studio` sessions started in one folder otherwise both choose the
    same unused name and overwrite each other's saved session.
    """
    previous = None
    while True:
        path = Path(default_project())
        try:
            path.mkdir(parents=True, exist_ok=False)
            return str(path)
        except FileExistsError:
            if path == previous:  # a pinned default name (tests or a wrapper) is reused as before
                return str(path)
            previous = path


def _is_default_project(root):
    from myzing import storage
    bases = {Path("zing-workspace").resolve(), storage.resolve_workspace()}
    return root.parent in bases and re.fullmatch(r"studio(-\d+)?", root.name) is not None


def _inside(folder, parent):
    return folder == parent or parent in folder.parents


def clean_path_text(value, *, posix=None):
    """Undo the quoting terminals add when a file is dragged in.

    Windows Explorer/Terminal wraps a path with spaces in double quotes, GNOME
    Terminal uses single quotes, and macOS Terminal escapes spaces with
    backslashes. Backslash escapes are only undone on POSIX, where a backslash
    is never a path separator, and only when the literal path does not exist.
    A leading double backslash is a pasted Windows share path, not an escape,
    so it is kept for the local-path check to refuse.
    """
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    else:
        text = text.strip('"')
    posix = os.name != "nt" if posix is None else posix
    if posix and "\\" in text and not text.startswith("\\\\") and not Path(text).expanduser().exists():
        text = re.sub(r"\\(.)", r"\1", text)
    return text


def _path(value, key, *, folder=False, exists=True):
    text = clean_path_text(value) if isinstance(value, str) else ""
    if not text or "://" in text or text.startswith(("\\\\", "//")):
        raise ValueError(f"{key}: supply a local {'folder' if folder else 'file'} path.")
    path = Path(text).expanduser().resolve()
    if exists and not (path.is_dir() if folder else path.is_file()):
        raise ValueError(f"{key}: {'folder' if folder else 'file'} does not exist: {path}")
    return str(path)


def normalize(key, value):
    if key in DELIVERY_KEYS:
        from myzing.brief.models import Brief
        Brief.from_answers({key: value})
        return value
    if key == "path":
        value = str(value).lower().strip()
        value = dict(zip("123456", PATHS)).get(value, value)
        if value not in PATHS:
            raise ValueError("Choose 1-6 or a-f.")
    elif key in {"project", "clips", "photos"}:
        value = _path(value, key, folder=True, exists=key != "project")
    elif key in {"source", "context"}:
        value = "none" if value == "none" and key == "context" else _path(value, key)
    elif key in {"music", "tracks"}:
        if key == "music" and value in ("original", "none"):
            return value
        values = value.split(";") if isinstance(value, str) else value
        if not isinstance(values, list) or not values or len(values) > 20:
            raise ValueError(f"{key}: supply 1-20 local paths, separated by semicolons.")
        value = [_path(v, key) for v in values]
    elif key == "reference":
        if isinstance(value, str) and (is_http_url(value) or value.startswith("uoink:")):
            from myzing.uoink_bridge import credential_safe_url
            credential_safe_url(value)
        else:
            value = _path(value, key)
    elif key == "aspects":
        if isinstance(value, str):
            value = ASPECTS[:] if value == "all" else [v.strip() for v in value.split(",")]
        if not isinstance(value, list) or not value or any(v not in ASPECTS for v in value) or len(set(value)) != len(value):
            raise ValueError("aspects: use 16:9, 1:1, 9:16, all, or a comma-separated selection.")
    elif key == "length":
        if isinstance(value, bool):
            raise ValueError("length: use seconds, greater than 0 and at most 60.")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError("length: enter a number of seconds.") from None
        if not math.isfinite(value) or not 0 < value <= 60:
            raise ValueError("length: use seconds, greater than 0 and at most 60.")
    elif key in {"allow_download", "speech"}:
        if isinstance(value, str) and value.casefold() in {"yes", "no", "true", "false"}:
            value = value.casefold() in {"yes", "true"}
        if type(value) is not bool:
            raise ValueError(f"{key}: enter yes or no.")
    elif key in {"reference_kind", "platform", "tone", "captions", "draft"}:
        allowed = {"reference_kind": ["file", "url", "uoink"],
                   "platform": ["original", "TikTok/Reels", "YouTube", "square", "all", "custom"],
                   "tone": ["natural", "calm", "energetic"],
                   "captions": ["none", "phone", "reference"], "draft": ["A", "B", "C", "keep all"]}[key]
        if value not in allowed:
            raise ValueError(f"{key}: choose {', '.join(allowed)}.")
    elif not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"{key}: enter 1-500 characters.")
    return value


def normalize_answers(answers):
    if not isinstance(answers, dict) or set(answers) - KEYS:
        raise ValueError("answers must be an object using studio question IDs; unknown keys: " +
                         str(sorted(set(answers) - KEYS) if isinstance(answers, dict) else "not an object"))
    result = {key: normalize(key, value) for key, value in answers.items()}
    from myzing.brief.models import Brief
    Brief.from_answers({key: result[key] for key in DELIVERY_KEYS if key in result})
    if "caption_mode" in result:
        result["captions"] = result["caption_mode"]
    return result


def brief_answers(answers):
    return {"purpose": answers["topic"] + f"; {answers['tone']} tone",
            "platform": answers["platform"], "aspect": answers["aspects"][0],
            "aspects": answers["aspects"], "target_length_seconds": answers["length"],
            "caption_language": "none" if answers["captions"] == "none" else "original",
            "music": {"source": "supplied files", "files": answers["music"]} if isinstance(answers["music"], list)
            else {"source": "none" if answers["music"] == "none" else "keep original audio"},
            "framing": "auto", "caption_mode": answers["captions"] if answers["captions"] in ("phone", "none") else "reference",
            **{key: answers[key] for key in DELIVERY_KEYS if key in answers}}


def next_step(answers=None, *, cache=None):
    """Return the next question or a reviewable plan. Never assumes consent."""
    a = normalize_answers(answers or {})
    empty = {"measured": [], "unknowns": ["Creative intent is unknown until you choose."], "warnings": []}
    if "path" not in a:
        q = question("path", "What are we making?", "a", "Choose a reference match if you have a video to aim for; your intent is still unknown.", empty, PATHS)
        return {"status": "question", "question": q.to_dict(), "answers": a}
    path = a["path"]
    a.setdefault("project", default_project())
    root = Path(a["project"])
    reserved = {root / name for name in ("studio-session.json", "studio-result.json", "studio-job.json", "studio-recipe.json")}
    for key in ("source", "reference", "context", "music", "tracks"):
        values = a.get(key, [])
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, str) and not is_http_url(value) and not value.startswith("uoink:") and Path(value).resolve() in reserved:
                raise ValueError(f"Output would replace input {value}; choose a different project folder.")
    for key in ("clips", "photos"):
        if key in a and root == Path(a[key]):
            raise ValueError("The output project must differ from the input folder.")
    if path == "d" and "source" in a and _inside(root, Path(a["source"]).parent):
        # Explain keeps its cards outside the video's folder. Move only the
        # automatic default; an explicitly chosen folder gets a plain refusal.
        if not _is_default_project(root):
            raise ValueError(f"Style breakdown writes outside the video's folder; choose an output folder that is not inside {Path(a['source']).parent}.")
        cwd = Path.cwd().resolve()
        candidates = [agent_default_project(), *([default_project_in(cwd.with_name(cwd.name + "-zing-studio"))] if cwd.name else [])]
        a["project"] = next((p for p in candidates if not _inside(Path(p), Path(a["source"]).parent)), a["project"])
        if _inside(Path(a["project"]), Path(a["source"]).parent):
            raise ValueError(f"Style breakdown writes outside the video's folder; choose an output folder that is not inside {Path(a['source']).parent}.")
        root = Path(a["project"])
    facts = evidence.collect(a, cache)
    queue = []

    def ask(key, prompt, default, why, choices=(), required=False):
        queue.append(question(key, prompt, default, why, facts, choices, required))

    if path == "a":
        kinds = {"file": "Use a local reference video", "url": "Download a reference URL (requires consent)"}
        if a.get("reference_kind") == "uoink" or "reference_kind" not in a:
            if evidence.saved_references_available():
                kinds["uoink"] = "Use a saved reference from Uoink"
            elif a.get("reference_kind") == "uoink":
                raise ValueError("Saved references are unavailable: configure a reachable Uoink peer or choose a local file.")
        # Local paths and URLs identify their own type. Only show a source menu
        # when a reachable saved-reference peer offers a meaningful third choice.
        if "uoink" in kinds and "reference" not in a:
            ask("reference_kind", "Where is the reference?", "file", "Local media needs no download.", kinds)
        if a.get("reference_kind") == "uoink":
            ask("reference_query", "What should I search your saved references for?", None,
                "Your search terms are unknown; only this query goes to the configured peer.", required=True)
            if "reference_query" in a and "reference" not in a:
                from myzing.uoink_bridge import search_references
                found = search_references(a["reference_query"])
                if not found.get("ok"):
                    raise ValueError(found.get("error", "Saved-reference search failed; go back and use a file."))
                items = {r["item_ref"]: r["title"] or r["item_ref"] for r in found["results"]}
                if not items:
                    raise ValueError("No saved references matched. Go back to change the query or use a local file.")
                ask("reference", "Which saved reference?", next(iter(items)),
                    "This is the peer's first search result; style suitability is unknown.", items)
        else:
            ask("reference", "Drag the reference video here or type its path (or URL):", None,
                "The reference is unknown; supply the video whose style you want to study.", required=True)
        if "reference" in a:
            kind = "url" if is_http_url(a["reference"]) else "uoink" if a["reference"].startswith("uoink:") else "file"
            if "reference_kind" in a and kind != a["reference_kind"]:
                raise ValueError("Reference does not match its selected source type; go back to change the source type.")
            read = facts.get("reference", {})
            if kind == "file" and read.get("no_video"):
                raise ValueError(f"reference: {Path(a['reference']).name} has no video stream, so there is no picture style to match. "
                                 "Choose a video file (option 5 checks music).")
            if kind == "file" and read.get("unreadable"):
                raise ValueError(f"reference: {Path(a['reference']).name} cannot be read as a video ({read['unreadable']}). "
                                 "Choose a complete video file.")
            if kind == "url":
                ask("allow_download", "Allow downloading this reference URL?", False,
                    "No download is allowed by default. Yes authorizes only this reference, never model downloads.", {False: "No", True: "Yes"})
                if a.get("allow_download") is False:
                    return {"status": "blocked", "error": "Download declined. Go back to use a local reference or save and quit.", "answers": a}
    if path in "ab":
        ask("clips", "Which folder holds your clips?", None,
            "Clip paths are unknown; local probes will measure size, duration and audio streams.", required=True)
    if path == "c":
        ask("photos", "Which folder holds your photos?", None,
            "Photo content is unknown; use a local folder of JPEG, PNG, WebP, BMP or TIFF files.", required=True)
    if path in "df":
        ask("source", "Video to break down?" if path == "d" else "Existing edit video or plan JSON?", None,
            "Supply a local file; a source plan preserves editable captions and original framing choices." if path == "f"
            else "Local media keeps the style breakdown offline; the video's style is unknown so far.", required=True)
    if path == "e":
        ask("tracks", "Which music tracks should I check? (paths separated by ;)", None,
            "Track suitability is unknown until local audio analysis runs.", required=True)
        ask("context", "Existing composition plan JSON for this edit, or none?", "none",
            "A plan supplies duration, cut pace and known speech; without one those facts need your answers.")
    if path in "abc":
        ask("topic", "What is this about?" if path != "c" else "What's the meme or still topic?", None,
            "The subject and purpose cannot be inferred from dimensions or filenames.", required=True)
    if path in "abcf":
        orientation = max(facts["orientations"], key=facts["orientations"].get) if facts["orientations"] else None
        reference = facts.get("reference", {})
        default_platform = "square" if path == "c" else "original"
        why = (facts["measured"][0] + " Keep the source shape unless you have a publishing target.") if facts["measured"] else "Publishing destination is unknown; this is a starting choice, not measured audience advice."
        if path == "c":
            why = f"{len(facts.get('photos', []))} photos measured; square is a starting layout choice. Your publishing destination is unknown."
        if path == "a" and reference.get("aspect"):
            orientation = reference.get("orientation") or {"16:9": "landscape", "9:16": "portrait", "1:1": "square"}.get(reference["aspect"], orientation)
            shape = {"portrait": "9:16", "landscape": "16:9", "square": "1:1"}.get(orientation)
            why = (f"Your reference is {reference['aspect']}. Keep its shape unless your destination needs another."
                   if reference["aspect"] == shape or shape is None else
                   f"Your reference is {reference['aspect']} ({orientation}); keeping its shape delivers {shape}. Change it if your destination needs another.")
        ask("platform", "Where will this go?", default_platform, why,
            {"TikTok/Reels": "TikTok / Reels (9:16)", "YouTube": "YouTube (16:9)", "square": "Feed (1:1)", "all": "All three shapes", "original": "Keep source / reference shape", "custom": "Custom shapes"})
        aspect = {"portrait": "9:16", "landscape": "16:9", "square": "1:1"}.get(orientation, "1:1" if path == "c" else "16:9")
        selected = {"TikTok/Reels": ["9:16"], "YouTube": ["16:9"], "square": ["1:1"], "all": ASPECTS}.get(a.get("platform"), [aspect])
        if a.get("platform") == "custom":
            ask("aspects", "Which shapes? (16:9, 1:1, 9:16 or all)", selected,
                "Choose your delivery set; auto framing checks crops before delivery.")
    if path in "ab" or (path == "e" and a.get("context", "none") == "none"):
        seconds = min((15, 20, 30, 45, 60), key=lambda n: abs(n - min(30, facts["duration"] / 3))) if facts["duration"] else 15
        ref = facts.get("reference", {}) if path == "a" else {}
        if ref.get("duration"):
            seconds = min(60, max(1, round(ref["duration"])))
        ask("length", "How many seconds?", seconds,
            (f"The reference is {ref['duration']:g} s; recommend {seconds:g} s to follow it." if seconds == round(ref["duration"]) else
             f"The reference is {ref['duration']:g} s; {seconds:g} s is the closest length studio supports (1-60 s).")
            if ref.get("duration") else
            f"{facts['duration']:g} source seconds; {seconds:g} s is a starting target. Distinct usable moments are unknown."
            if facts["duration"] else "Usable duration is unknown; 15 seconds is a disclosed starting target.")
    if path in "ab":
        ref = facts.get("reference", {}) if path == "a" else {}
        if path == "b":
            ask("tone", "What tone should it have?", "natural",
                "Semantic tone is unknown; natural is a restrained starting preference. Measured studies still determine draft candidates.", ["natural", "calm", "energetic"])
        ask("captions", "Add spoken captions?", "phone" if facts["audio_streams"] else "none",
            f"{facts['audio_streams']} probed videos have audio; speech and spelling are unknown. Phone captions need valid timed words; blocked captions will be reported."
            if facts["audio_streams"] else "No speech evidence is available; omit captions unless you want to try local transcription.",
            {"none": "No added captions", "phone": "Phone-readable spoken captions"})
        ask("music", "Music: original, none, or local track paths separated by ;?", "original" if facts["audio_streams"] else "none",
            "Keep the measured audio streams; supplied tracks will be rated and ducked only under known speech."
            if facts["audio_streams"] else "No source audio was measured; supply a local track if you want added music.",
            {"original": "Keep my clips' audio", "none": "No music bed (keep speech)"})
        if ref.get("duration"):
            for q in queue:
                if q.id == "captions":
                    q.recommended = "phone" if ref.get("text_present") and ref.get("speech_present") else "none"
                    text = ref.get("text_present")
                    q.reason = ("No text detected in sampled reference frames; start without added captions." if text is False else
                                "Text and speech observed; try spoken captions. Sampled text may be titles." if text and ref.get("speech_present") else
                                "Text observed but no speech detected; it is likely titles or signs, so start without spoken captions."
                                if text and ref.get("speech_present") is False else
                                "Spoken-caption evidence is unknown; start without added captions.")
                elif q.id == "music":
                    q.recommended = "original" if ref.get("has_audio") and ref.get("music_present") is not False else "none"
                    music = ref.get("music_present")
                    observed = ("Music observed in the reference (heuristic)." if music is True else
                                "No music detected in the reference (heuristic)." if music is False else
                                "Reference music is unknown.")
                    q.reason = observed + (" Keep your clips' audio to start; type local track paths to add music. The reference soundtrack is not copied."
                                           if q.recommended == "original" else " Start without a music bed; speech stays.")
    if path == "e" and a.get("context", "none") == "none":
        ask("speech", "Will someone be speaking over the music?", True,
            "Speech is unknown without an edit plan; checking as a speech bed is the conservative default.", {True: "Yes", False: "No"})
    for q in queue:
        if q.id not in a:
            return {"status": "question", "question": q.to_dict(), "answers": a}
    # Validate conditional prerequisites and any extra answer that could authorize IO.
    if path == "a" and "reference" not in a:
        raise ValueError("Choose a saved reference from the search results.")
    if a.get("allow_download") and (path != "a" or not is_http_url(a.get("reference", ""))):
        raise ValueError("allow_download applies only to the selected reference URL.")
    if path in "abcf" and "aspects" not in a:
        a["aspects"] = selected
    if path == "a":
        a.setdefault("tone", facts.get("reference", {}).get("tone", "natural"))
    return {"status": "plan", "plan": build_plan(a, facts), "answers": a}


def build_plan(a, facts):
    path, root = a["path"], Path(a["project"])
    steps = {
        "a": ["Inventory clips and save brief", "Study reference and clips offline", "Plan A/B/C and framing", "Render, decode and inspect each delivery"],
        "b": ["Inventory clips and save brief", "Study clips offline", "Choose a disclosed style from the brief; plan A/B/C", "Render and decode each delivery"],
        "c": ["Measure photos and create six concepts per shape", "Render contact sheets", "Export the highest readability-scored concept per shape"],
        "d": ["Measure cuts, transitions, captions, color and music where available", "Write style card as text, JSON and a preview"],
        "e": ["Measure local music", "Rank tracks and write reasons"],
        "f": ["Load the plan or probe the finished edit", "Rebuild framing for each requested shape", "Render and decode deliveries"],
    }[path]
    # A style breakdown delivers no video; source resolution is not its risk.
    warnings = [w for w in facts["warnings"] if not (path == "d" and w.startswith("Low-resolution source"))]
    if path in "ab":
        warnings.append("A/B/C can be blocked by footage shortages or invalid speech timing; no missing words or style measurements are invented.")
        if facts.get("audio_streams"):
            note = evidence.speech_model_note()
            if note:
                warnings.append(note)
    if path == "b":
        warnings.append("Style is a brief-based editorial choice, not a recovered reference look; source color stays unchanged.")
    if path == "c":
        warnings.append("Readability scores do not judge the joke. Face coverage is sampled or unknown; review the contact sheet.")
    if path == "f" and Path(a["source"]).suffix.lower() != ".json":
        warnings.append("This is a flattened video: baked-in captions and crops cannot be repositioned separately. Prefer the original plan when available.")
    seconds = facts.get("duration")
    estimate = {"seconds": None, "basis": "Runtime is unknown on this machine; studies and renders depend on source duration, models and hardware.",
                "source_seconds": seconds, "steps": len(steps)}
    # Existing tools stay the preferred execution surface where they cover the plan.
    if path == "a":
        execution = [{"tool": "match_start", "arguments": {"reference": a["reference"], "clips": a["clips"], "out": str(root),
                     "answers": brief_answers(a), "studio_options": {"captions": a["captions"], "music": a["music"]},
                     "allow_download": a.get("allow_download", False), "resume": (root / "match-state.json").is_file()}},
                     {"tool": "match_status", "arguments": {"project": str(root)}}]
    elif path == "c":
        execution = [{"tool": "still_concepts", "arguments": {"photos": a["photos"], "topic": a["topic"],
                     "out": str(root / ("stills-" + aspect.replace(":", "x"))), "aspect": aspect}}
                     for aspect in a["aspects"]]
        execution.append({"tool": "still_render", "after": "Choose a returned concept ID; review its contact sheet first."})
    elif path == "e":
        execution = [{"tool": "music_check", "arguments": {"tracks": a["tracks"],
                     **({"plan": a["context"]} if a["context"] != "none" else {"length": a["length"], "speech": a["speech"]})}}]
    else:
        execution = [{"tool": "zing_studio_run", "arguments": {"answers": a, "confirmed": True},
                      "after": "Only after the user confirms this plan; poll the returned project using zing_studio_run."}]
    return {"version": 1, "path": path, "title": PATHS[path], "output_folder": str(root),
            "aspects": a.get("aspects", []), "steps": steps, "estimate": estimate,
            "downloads": [a["reference"]] if a.get("allow_download") else [],
            "warnings": warnings, "evidence": facts, "execution": execution,
            "style": {key: a[key] for key in ("length", "tone", "captions", "music", *sorted(DELIVERY_KEYS)) if key in a},
            "confirmation_required": True}
