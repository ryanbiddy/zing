"""Small, deterministic suggestions with measured basis and explicit gaps."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median

from myzing.project.api import load_project, project_status, resolve_path
from .models import Brief


def _positive(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _names(values) -> str:
    values = list(values)
    return ", ".join(values[:4]) + (f" (+{len(values) - 4} more)" if len(values) > 4 else "")


def _reference(study, root: Path, basis: list, missing: list):
    if not study:
        missing.append("No studied reference breakdown is attached; shot pace and caption style are unknown.")
        return None
    try:
        if not isinstance(study, dict):
            raise ValueError("study must be an object")
        if study.get("state", "done") != "done":
            raise ValueError("reference study is not done")
        if "breakdown_path" in study:
            data = json.loads(resolve_path(study["breakdown_path"], root).read_text(encoding="utf-8-sig"))
        else:
            data = study.get("breakdown", study)
        if not isinstance(data, dict) or "meta" not in data or data.get("schema_version", 1) != 1:
            raise ValueError("expected a version 1 Breakdown with meta")
        shots, captions = data.get("shots", []), data.get("captions", [])
        durations = []
        for shot in shots:
            start, end = shot["start"], shot["end"]
            if type(start) not in (int, float) or not math.isfinite(start) or start < 0 or not _positive(end) or end <= start:
                raise ValueError("invalid shot interval")
            durations.append(end - start)
        pace = median(durations) if durations else None
        reference_basis, reference_missing = [], []
        if pace:
            reference_basis.append(f"Reference: {len(durations)} measured shots; median shot {pace:g} s.")
        else:
            reference_missing.append("Reference shot pace is unknown: no valid measured shot intervals.")
        if captions:
            positions, words, confidence, caps = Counter(), [], [], 0
            for caption in captions:
                position = caption["position"]
                count, score = caption["words_visible"], caption["confidence"]
                if (position not in ("top", "center", "lower", "bottom") or type(count) is not int or count < 1
                        or type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1
                        or type(caption["all_caps"]) is not bool):
                    raise ValueError("invalid caption observation")
                positions[position] += 1
                words.append(count)
                confidence.append(score)
                caps += caption["all_caps"]
            reference_basis.append(
                f"Reference captions (OCR): {len(captions)} observations, "
                f"positions {_names(f'{k} {v}' for k, v in sorted(positions.items()))}; "
                f"median {median(words):g} words visible, {caps}/{len(captions)} all caps; "
                f"mean reported confidence {mean(confidence):.2f}.")
        else:
            reference_missing.append("Reference caption style is unknown: no OCR caption observations.")
        reference_missing.extend(f"Reference study warning: {w}" for w in data.get("warnings", []))
        reference_missing.append("Exact font, animation and preset are not established by these measurements.")
        basis.extend(reference_basis)
        missing.extend(reference_missing)
        return pace
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        missing.append(f"Reference breakdown unavailable or invalid ({exc}); shot pace and caption style remain unknown.")
        return None


def recommend(project: str | Path, brief: Brief) -> dict:
    root = Path(project).expanduser().resolve()
    manifest, status = load_project(root), project_status(root)
    rows = {row["id"]: row for row in status["assets"]}
    basis, missing = [], []
    clips = [a for a in manifest.assets if a.probe and any(
        s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        for s in a.probe.streams)]
    ready = [a for a in clips if rows[a.id]["state"] not in ("missing", "unsupported")
             and not rows[a.id]["needs_scan"] and a.state == "ready"]
    basis.append(f"Inventory: {len(manifest.assets)} assets; {len(clips)} probed video clips, {len(ready)} currently usable by metadata.")
    orientations = Counter(a.probe.orientation or "unknown" for a in ready)
    basis.append("Usable clip orientations: " + (_names(f"{n} {o}" for o, n in sorted(orientations.items())) or "none") + ".")
    durations = [a.probe.duration for a in ready if _positive(a.probe.duration)]
    if durations:
        basis.append(f"Known usable durations: {sum(durations):g} source seconds across {len(durations)} clips; range {min(durations):g}-{max(durations):g} s (before trims; content not reviewed).")
    if len(durations) != len(ready):
        missing.append(f"Duration unknown for {len(ready) - len(durations)} usable clips.")
    if not ready:
        missing.append("No usable video clips. Add footage or resolve inventory problems, then run 'zing project scan'.")
    elif len(durations) == len(ready):
        if min(durations) >= 3:
            missing.append("No usable clip shorter than 3 s for a short hook; a trim would need content review.")
        if sum(durations) < brief.target_length_seconds:
            missing.append(f"Only {sum(durations):g} s of usable source duration for a {brief.target_length_seconds:g} s target; supply more footage or shorten the brief.")
    for state in ("missing", "unsupported"):
        assets = [r for r in rows.values() if r["state"] == state]
        if assets:
            missing.append(f"{state.capitalize()} assets ({len(assets)}): " + _names(
                r["path"] + (f" [{', '.join(r['flags'])}]" if r["flags"] else "") for r in assets) + ".")
    stale = [r["path"] for r in rows.values() if r["needs_scan"]]
    if stale:
        missing.append("Inventory needs a scan: " + _names(stale) + "; cached measurements excluded.")
    expected = {"9:16": "portrait", "1:1": "square", "16:9": "landscape"}[brief.aspect]
    other = [a.path for a in ready if a.probe.orientation != expected]
    if other:
        missing.append(f"Framing review needed for {brief.aspect}: {_names(other)}. Orientation alone cannot establish a safe crop.")
    for name in ("purpose", "audience", "platform"):
        if getattr(brief, name) == getattr(Brief(), name):
            missing.append(f"{name.capitalize()} is set to the disclosed default: {getattr(brief, name)}.")
    for role in ("music", "sfx"):
        choice = getattr(brief, role)
        basis.append(f"Your {role} choice: {choice['source']}.")
        for value in choice["files"]:
            asset = next((a for a in manifest.assets if a.id == value or a.path == value), None)
            path = resolve_path(asset.path if asset else value, root)
            if not path.is_file() or (asset and rows[asset.id]["state"] == "missing"):
                missing.append(f"Missing supplied {role} file: {value}.")
            elif not asset:
                missing.append(f"Supplied {role} file is not inventoried: {value}; audio compatibility is unknown.")
            elif rows[asset.id]["state"] == "unsupported" or rows[asset.id]["needs_scan"] or not asset.probe or not asset.probe.has_audio:
                missing.append(f"Supplied {role} file is unsupported, stale, or has no measured audio: {value}.")
        if choice["source"] == "keep original audio" and ready and not any(a.probe.has_audio for a in ready):
            missing.append(f"Original audio requested for {role}, but none of the usable clips has an audio stream.")
    constraints = brief.must_keep + brief.forbidden
    if any("phrase" in m for m in constraints):
        missing.append("Quoted moments are saved verbatim; phrase locations need timed transcripts and review.")
    if constraints:
        basis.append(f"Your constraints: {len(brief.must_keep)} must-keep, {len(brief.forbidden)} forbidden moments.")
        for moment in constraints:
            if "clip" in moment and moment["clip"] not in rows:
                missing.append(f"Saved moment refers to unknown clip {moment['clip']}; review the inventory.")
    # Count the union of source spans, so overlapping requests are not double
    # counted. This is a lower bound at original speed; phrases are unresolved.
    spans = {}
    for moment in brief.must_keep:
        if "start" in moment:
            spans.setdefault(moment["clip"], []).append((moment["start"], moment["end"]))
    required_seconds = 0.0
    for intervals in spans.values():
        end = 0.0
        for start, stop in sorted(intervals):
            required_seconds += max(0, stop - max(start, end))
            end = max(end, stop)
    if required_seconds > brief.target_length_seconds:
        missing.append(f"Must-keep ranges require {required_seconds:g} s at original speed, exceeding the {brief.target_length_seconds:g} s target; shorten the ranges or lengthen the brief.")
    pace = _reference(manifest.reference.study, root, basis, missing)
    summary = f"Start with a {brief.target_length_seconds:g} s, {brief.aspect} rough cut."
    if not ready:
        summary = "Resolve the missing or unsupported footage before planning the edit."
    else:
        if len(durations) == len(ready) and sum(durations) < brief.target_length_seconds:
            summary = (f"Shorten the {brief.target_length_seconds:g} s target or add footage first: "
                       f"only {sum(durations):g} s of usable source is inventoried for the {brief.aspect} edit.")
        if pace and brief.reference_match in ("recommend", "pacing only"):
            summary += f" Use the reference's {pace:g} s median shot as a pacing starting point, subject to your must-keep moments."
        else:
            summary += " Review the must-keep moments before choosing the opening."
    if brief.reference_match == "exact":
        summary += " Exact matching is your requested goal; current measurements cannot establish an exact match."
    return {"summary": summary, "basis": basis, "missing": missing,
            "scope": "Deterministic suggestions from inventory and attached reference observations; no model judgment or content review."}
