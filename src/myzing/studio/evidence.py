"""Read-only, local observations for the interview. Never starts a study."""

from __future__ import annotations

from collections import Counter
from pathlib import Path


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
    from myzing.project.probe import probe_file

    cache = cache if cache is not None else {}
    result = {"measured": [], "unknowns": [], "clips": [], "duration": None,
              "orientations": {}, "audio_streams": 0, "warnings": []}
    files = media_files(answers["clips"], answers.get("project")) if answers.get("clips") else []
    source = answers.get("source")
    if source and Path(source).is_file() and Path(source).suffix.lower() != ".json":
        files.append(Path(source))
    for path in files:
        try:
            stat = path.stat()
            key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
            if key not in cache:
                cache[key] = probe_file(path).to_dict()
            probe = cache[key]
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
    else:
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
