"""Local observations for the interview, including a bounded reference preview."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess


def cached_probe(path, cache):
    """One metadata probe per file version in an interview, including failures."""
    from myzing.project.probe import probe_file

    path = Path(path).resolve()
    stat = path.stat()
    key = ("studio_probe", str(path), stat.st_size, stat.st_mtime_ns)
    if key not in cache:
        try:
            cache[key] = (probe_file(path).to_dict(), None)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            cache[key] = ({}, str(exc))
    return cache[key]


def media_files(folder, exclude=None):
    from myzing.project.probe import MEDIA_EXTENSIONS

    # Match accepts a tree; avoid links and generated output subdirectories.
    import os
    import stat
    paths = []
    for directory, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink()
                         and not (getattr((Path(directory) / d).lstat(), "st_file_attributes", 0)
                                  & stat.FILE_ATTRIBUTE_REPARSE_POINT)
                         and (exclude is None or (Path(directory) / d).resolve() != Path(exclude).resolve()))
        paths.extend(Path(directory) / n for n in sorted(names)
                     if Path(n).suffix.lower() in MEDIA_EXTENSIONS and not (Path(directory) / n).is_symlink())
    return sorted(paths)


def collect(answers, cache=None):
    """Cache by file stats only within one interview; MCP calls retain no state."""
    cache = cache if cache is not None else {}
    result = {"measured": [], "unknowns": [], "clips": [], "duration": None,
              "orientations": {}, "audio_streams": 0, "warnings": []}
    reference = answers.get("reference")
    if answers.get("path") == "a" and reference:
        if "://" not in reference and Path(reference).is_file():
            from .reference import quick_read
            stat = Path(reference).stat()
            from myzing.reference_range import parse
            start, end = parse(**{k: answers[k] for k in ("ref_start", "ref_end", "reference_range") if k in answers})
            trim = {k: v for k, v in dict(ref_start=start, ref_end=end).items() if v is not None}
            key = ("reference", reference, stat.st_size, stat.st_mtime_ns, start, end)
            if key not in cache:
                if cache.get("progress"):
                    cache["progress"]("Reading the reference...")
                cache[key] = quick_read(reference, **trim)
                if cache.get("progress"):
                    cache["progress"](cache[key]["reason"])
                    for warning in cache[key].get("warnings", [])[:1]:
                        cache["progress"](warning)
            result["reference"] = cache[key]
            result["measured" if cache[key].get("duration") else "unknowns"].append(cache[key]["reason"])
            result["warnings"].extend(cache[key].get("warnings", []))
        else:
            result["unknowns"].append("Reference quick read unavailable until the saved or remote reference is resolved after confirmation; style is unknown.")
    files = media_files(answers["clips"], answers.get("project")) if answers.get("clips") else []
    source = answers.get("source")
    if source and Path(source).is_file() and Path(source).suffix.lower() != ".json":
        files.append(Path(source))
    elif source and Path(source).suffix.lower() == ".json":
        try:
            from .adapters import load_edit
            plan = load_edit(source)
            result["orientations"] = {"landscape" if plan.width > plan.height else "portrait" if plan.height > plan.width else "square": 1}
            result["duration"] = max((clip.timeline_end for clip in plan.clips), default=0)
            result["measured"].append(f"Saved plan: {plan.width}x{plan.height}, {result['duration']:g} seconds.")
        except (OSError, ValueError, RuntimeError) as exc:
            result["unknowns"].append(f"Saved plan dimensions unavailable: {exc}")
    for path in files:
        try:
            probe, error = cached_probe(path, cache)
            if error is not None:
                result["unknowns"].append(f"Cannot probe {path.name}: {error}")
                continue
            if not probe.get("width") or not probe.get("height"):
                continue
            result["clips"].append({"path": str(path.resolve()), **probe})
        except (OSError, ValueError, RuntimeError) as exc:
            result["unknowns"].append(f"Cannot probe {path.name}: {exc}")
    clips = result["clips"]
    if clips:
        result["orientations"] = dict(Counter(c["orientation"] or "unknown" for c in clips))
        durations = [c["duration"] for c in clips if c["duration"] is not None]
        result["duration"] = sum(durations) if len(durations) == len(clips) else None
        result["audio_streams"] = sum(bool(c["has_audio"]) for c in clips)
        result["measured"].append(f"Probed {len(clips)} videos: " + ", ".join(f"{n} {o}" for o, n in result["orientations"].items()) + ".")
        if result["duration"] is not None:
            result["measured"].append(f"{result['duration']:g} source seconds before trims; usable moments are unknown.")
        low = [Path(c["path"]).name for c in clips if min(c["width"], c["height"]) < 1080]
        if low:
            result["warnings"].append("Low-resolution source(s): " + ", ".join(low) + "; HD delivery can look soft.")
    elif not result["measured"]:
        result["unknowns"].append("Video dimensions, duration and speech are unknown until local files can be probed.")
    result["unknowns"].append("An audio stream does not establish speech. Safe crops and caption placement need subject analysis.")
    if answers.get("photos"):
        try:
            from myzing.still.inventory import inventory
            folder = Path(answers["photos"])
            key = ("photos", str(folder), tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                                                for p in sorted(folder.iterdir()) if p.is_file()))
            if key not in cache:
                cache[key] = inventory(folder)
            photos, notes = cache[key]
            result["photos"] = [{"path": p.path, "width": p.width, "height": p.height} for p in photos]
            result["measured"].append(f"Measured {len(photos)} distinct local photos; topic and humor remain your choices.")
            result["warnings"].extend(notes)
        except (ImportError, ValueError, OSError, RuntimeError) as exc:
            result["unknowns"].append(f"Photo evidence unavailable: {exc}")
    project = Path(answers.get("project", ""))
    if answers.get("project") and (project / "project.json").is_file():
        from myzing.brief.api import load_brief
        from myzing.brief.recommend import recommend
        try:
            if (project / "brief.json").is_file():
                rec = recommend(project, load_brief(project / "brief.json"))
                result["brief_recommendation"] = rec
                result["measured"].extend(rec["basis"])
                result["unknowns"].extend(rec["missing"])
        except (OSError, ValueError, RuntimeError) as exc:
            result["unknowns"].append(f"Saved brief recommendation unavailable: {exc}")
    return result


def speech_model_note():
    """Studio studies never download models; say so before a long run that needs one.

    Clips with speech need timed words (or measured silence) before the
    director can cut them on word boundaries. Without a local speech model
    they are excluded after the studies, which a creator should hear first.
    """
    try:
        from myzing import doctor
        check = doctor.check_whisper()
    except Exception:  # an unreadable cache is not evidence either way
        return None
    data = check.data or {}
    if data.get("cached"):
        return None
    if not data.get("model"):
        return ("Speech transcription is not installed (myzing[study]), and needs explicit setup consent. "
                "Clips with speech can be left out of A/B/C; run zing doctor before confirming.")
    return (f"The speech model {data['model']!r} is not downloaded, and needs explicit setup consent. "
            "Clips with speech can be left out of A/B/C. Choose speech setup in studio or run zing doctor --speech-model small.en, "
            "or set ZING_WHISPER_MODEL to a local model folder.")


def saved_references_available():
    """Do not probe the default peer. An explicit URL or valid lease is required."""
    from myzing import uoink_bridge as bridge

    if not bridge._token():
        return False
    try:
        resolved = bridge.suite_peer.resolve_uoink_base()
        if not resolved.configured:
            return False
        status, manifest = bridge.suite_peer._get_json(
            bridge.credential_safe_url(resolved.base) + "/.well-known/suite-service.json")
        return (status == 200 and bridge.suite_peer._manifest_defect(manifest) is None
                and manifest["service"]["id"] == "uoink"
                and bridge.SEARCH_CAPABILITY in manifest["service"]["capabilities"])
    except (OSError, ValueError, RuntimeError):
        return False
