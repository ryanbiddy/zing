"""Paths in, plans and comparison out. Planning never starts a render or study."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from statistics import median

from myzing.brief.api import load_brief
from myzing.project.api import load_project
from myzing.project.locking import project_lock
from myzing.style_recipe import StyleRecipe

from .inventory import inventory
from .models import PlanningShortage, shortage
from .plans import MUSIC_CANNOT_CARRY, attach_report, make_plan, music_projection, render_projection
from .selection import (ALTERNATIVE, band_distance, candidates, choose, constraints, different, envelope,
                        reference_band, shot_lengths)

PRODUCER = "myzing.director/1"
MANAGED = {"comparison.json", *(f"plan-{label}{suffix}.json" for label in "ABC"
                                  for suffix in ("", ".edl", ".edl.music"))}


def _json(data):
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def _atomic(path, payload):
    fd, name = tempfile.mkstemp(prefix=".plan-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _publish(out, payloads, report, protected):
    out.mkdir(parents=True, exist_ok=True)
    with project_lock(out):
        previous = out / "comparison.json"
        owned = False
        if previous.is_file() and not previous.is_symlink():
            try:
                owned = json.loads(previous.read_text(encoding="utf-8")).get("producer") == PRODUCER
            except (ValueError, UnicodeError):
                pass
        for name in sorted(MANAGED):
            path = out / name
            if path.is_symlink() or path.resolve() in protected or (path.exists() and not path.is_file()):
                raise ValueError(f"Refusing to replace protected output {path}; choose another --out folder.")
            if path.exists() and not owned:
                raise ValueError(f"Output {path} already exists without a P17 ownership report; choose another --out folder.")
        # If interrupted while replacing a set, an old 'ready' report must not
        # advertise a mixture of old and new plans as a completed trio.
        _atomic(previous, _json({"version": 1, "producer": PRODUCER, "status": "writing", "plans": {}}))
        for name, payload in sorted(payloads.items()):
            _atomic(out / name, payload)
        # Remove only this producer's reserved artifacts, after path checks.
        for name in sorted(MANAGED - {"comparison.json"} - payloads.keys()):
            (out / name).unlink(missing_ok=True)
        _atomic(previous, _json(report))


def plan_drafts(project: str | Path, recipe: str | Path, out: str | Path, *, seed: int = 0, repair_asr: bool = True,
                studio_options: dict | None = None) -> dict:
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if studio_options is not None:
        from myzing.studio.adapters import validate_options
        validate_options(studio_options)
    root = Path(project).expanduser().resolve()
    recipe_path = Path(recipe).expanduser().resolve()
    output = Path(out).expanduser().resolve()
    manifest = load_project(root)
    brief = load_brief(root / "brief.json")
    style_recipe = StyleRecipe.from_json(recipe_path.read_text(encoding="utf-8-sig"))
    if type(repair_asr) is not bool:
        raise ValueError("repair_asr must be a boolean")
    clips, inventory_notes = inventory(root, repair_asr=repair_asr)
    excluded = [f"Excluded {Path(c.path).name} ({c.asset_id}, {c.status}): {warning}"
                for c in clips if c.status != "ready" for warning in c.warnings]
    excluded += [w for c in clips for w in c.warnings if w.startswith(("ASR repair", "ASR quarantine"))]
    report = {"version": 1, "producer": PRODUCER, "seed": seed, "status": "shortage",
              "brief": brief.to_dict(), "inventory": [c.to_dict() for c in clips],
              "inventory_warnings": inventory_notes, "plans": {}, "shortages": []}
    payloads = {}
    try:
        if not any(c.status == "ready" for c in clips):
            shortage("study_required", "No project clip has a usable study.",
                     f'Run zing study <clip> --raw --workspace "{root}" for each needed clip.')
        keep, forbidden = constraints(brief, manifest, clips)
        if studio_options and studio_options.get("target_length_mode") == "usable":
            from dataclasses import replace
            from .selection import usable_length
            usable = usable_length(clips, keep, forbidden)
            if usable <= 0:
                shortage("target_length", "No usable footage remains after trimming.",
                         "Review the excluded spans or add usable footage.")
            brief = replace(brief, target_length_seconds=min(60, usable))
            report["brief"] = brief.to_dict()
            report["target_length"] = {"mode": "usable", "usable_seconds": usable,
                                       "target_seconds": brief.target_length_seconds,
                                       "reason": "Default follows usable footage after whole-word silence and exclusion trims."}
        required_seconds = sum(b - a for spans in keep.values() for a, b in spans)
        if required_seconds > brief.target_length_seconds + 2 / 30:
            shortage("must_keep_length", f"Whole-word must-keeps require {required_seconds:.3f}s, beyond the brief target.",
                     "Lengthen the brief or shorten its must-keep spans.")
        style = envelope(style_recipe)
        if studio_options is not None:
            from myzing.studio.adapters import style_envelope
            style = style_envelope(style, studio_options)
        # Keep a previously feasible A when adding timing-aware trims. Expanding
        # the search should repair failed alternatives without replacing a
        # passing primary edit merely because its candidate beam changed.
        preferred_a = None
        initial_pool, initial_required = candidates(clips, keep, forbidden, style, brief.target_length_seconds,
                                                    expand_timing=False)
        try:
            initial = choose(initial_pool, initial_required, clips, style, brief.target_length_seconds, 30, seed,
                             allow_reordering="[allow source reordering]" in brief.purpose.casefold(),
                             prefer_bands=False)["A"]
            lengths = shot_lengths(initial, clips)
            values = ((style.first_cut, lengths[0] if len(lengths) > 1 else None),
                      (style.median_shot, median(lengths)))
            if not any(c.dangling_clauses for c in initial) and all(
                band_distance(value, reference_band(target, style)) <= 1e-8
                for target, value in values
            ):
                preferred_a = initial
        except PlanningShortage:
            pass  # New timing trims may make a previously unavailable trio feasible.
        pool, required = candidates(clips, keep, forbidden, style, brief.target_length_seconds)
        timing_evidence = {}
        selected = choose(pool, required, clips, style, brief.target_length_seconds, 30, seed,
                          allow_reordering="[allow source reordering]" in brief.purpose.casefold(),
                          timing_evidence=timing_evidence, preferred_a=preferred_a)
        # Decode used sources for framing and caption safety. This is local layout
        # analysis, with no study/ASR, model downloads, or reference lookup.
        from myzing.layout.framing import analyze_subjects
        subject_evidence = {}
        picture_evidence = {}
        used = {c.asset_id for sequence in selected.values() for c in sequence}
        for asset in manifest.assets:
            probe = asset.probe
            if asset.id not in used or probe is None or not probe.width or not probe.height:
                continue
            study = next(s for s in clips if s.asset_id == asset.id)
            # Only the trims any draft uses (plus margins), so source length
            # never exhausts the analysis budget or decodes unused footage.
            ranges = [(c.start, c.end) for sequence in selected.values() for c in sequence if c.asset_id == asset.id]
            subject_evidence[asset.id] = analyze_subjects(Path(study.path), study.duration, root / "framing-work",
                                                         [s.start for s in study.shots], ranges=ranges)
            if brief.picture_crop != "off":
                from myzing.layout.picture import analyze_picture
                from myzing.render.framing import display_dimensions
                stream = next((s for s in probe.streams if s.get("codec_type") == "video"), {})
                size = display_dimensions({"width": probe.width, "height": probe.height,
                                           "tags": {"rotate": probe.rotation}, **stream})
                picture_evidence[asset.id] = analyze_picture(study.path, ranges, size)
        report["picture_analysis"] = picture_evidence
        report["subject_analysis"] = {key: {"tracks": [t.to_dict() for t in tracks], "warnings": notes}
                                      for key, (tracks, notes) in subject_evidence.items()}
        report["envelope"] = style.to_dict()
        report["search"] = {"candidate_count": len(pool), "method": "deterministic bounded beam; 96 states per expansion",
                            "distinctness": "Different opening content with <50% overlap, or >=max(1s, reference median, 20% target) changed footage.",
                            "duration_tolerance_seconds": 2 / 30}
        relaxed = next(iter(timing_evidence["A"].values()))["search"].get("distinctness_relaxed")
        if relaxed:
            # Fewer than three distinct in-band edits: timing bands were kept first.
            report["search"]["distinctness_relaxed"] = relaxed
        music_cache = {}
        for label, sequence in selected.items():
            plan, evidence = make_plan(label, sequence, clips, style_recipe, recipe_path.parent,
                                       style, brief, manifest, root, seed, keep, forbidden,
                                       subject_evidence=subject_evidence, music_cache=music_cache, picture_evidence=picture_evidence,
                                       timing_selection=timing_evidence[label],
                                       **({"caption_mode": "none" if studio_options.get("speech_model") == "skip" else studio_options.get("captions")} if studio_options is not None else {}))
            if studio_options and studio_options.get("speech_model") == "skip":
                from myzing.study.speech_models import SKIP_NOTE
                evidence["continuity"] = {"version": 1, "status": "unavailable", "score": None, "basis": SKIP_NOTE}
                evidence["captions"] = {"status": "unavailable", "basis": SKIP_NOTE}
                plan.warnings.append(SKIP_NOTE)
            evidence["audio_moment_candidates"] = [
                {"asset_id": c.asset_id, **moment}
                for c in clips if c.status == "ready"
                for moment in c.audio_tags.get("moment_candidates", [])
            ]
            evidence["differs_from"] = {
                other: {"opening_changed": sequence[0].identity != alternative[0].identity,
                        "this_opening": {"asset_id": sequence[0].asset_id, "start": sequence[0].start, "end": sequence[0].end},
                        "other_opening": {"asset_id": alternative[0].asset_id, "start": alternative[0].start, "end": alternative[0].end},
                        "source_choices_changed": sorted(c.identity for c in sequence) != sorted(c.identity for c in alternative),
                        "meaningfully_different": different(sequence, alternative, brief.target_length_seconds,
                                                            style.median_shot or 2.0)}
                for other, alternative in selected.items() if other != label
            }
            plan = attach_report(plan, evidence)
            legacy, blockers = render_projection(plan)
            sidecar = None
            if legacy is None:
                # A music bed is the usual blocker: keep picture and dialogue
                # in the v1 derivative and hand the music to a sidecar.
                music_legacy, sidecar, music_blockers = music_projection(plan, label)
                if music_legacy is not None:
                    legacy = music_legacy
            evidence["v1"] = {"representable": legacy is not None, "blockers": blockers,
                              "evidence_retained_in": [f"plan-{label}.json", "comparison.json"],
                              "projection": "Only brief and warnings are separated into the retained v2 evidence; all rendering instructions are checked by lower_to_v1."}
            if sidecar is not None:
                evidence["v1"].update(
                    scope="picture and dialogue; the music bed is in the sidecar",
                    music_removed=[t["id"] for t in sidecar["tracks"]],
                    music_sidecar=f"plan-{label}.edl.music.json", cannot_carry=MUSIC_CANNOT_CARRY,
                    projection=("Brief, warnings and the music track are separated; picture, captions and source "
                                "audio are checked by lower_to_v1. The sidecar carries the music for an editor."))
            # Record lowering in the plan itself too, with no dependency on out.
            plan = attach_report(plan, evidence)
            payloads[f"plan-{label}.json"] = plan.to_json(indent=2) + "\n"
            if legacy is not None:
                payloads[f"plan-{label}.edl.json"] = _json(legacy.to_dict())
            if sidecar is not None:
                payloads[f"plan-{label}.edl.music.json"] = _json(sidecar)
            report["plans"][label] = evidence
        # Alternatives and undelivered drafts are named wherever plans are listed.
        report["alternatives"] = {label: p["alternative"]["reason"] for label, p in report["plans"].items()
                                  if p.get("alternative")}
        if relaxed and relaxed["missing_drafts"]:
            report["missing_drafts"] = {"drafts": relaxed["missing_drafts"], "reason": relaxed["reason"]}
        report["status"] = "ready"
    except PlanningShortage as exc:
        report["shortages"] = [exc.shortage.to_dict()]
        report["plans"] = {}
        payloads = {}
    from myzing.project.paths import resolve_path
    protected = {recipe_path, root / "project.json", root / "brief.json"}
    protected.update(resolve_path(a.path, root).resolve() for a in manifest.assets)
    protected.update(Path(c.study_path).resolve() for c in clips if c.study_path)
    _publish(output, payloads, report, protected)
    return {"status": report["status"], "comparison_path": str(output / "comparison.json"),
            "plans": {label: str(output / f"plan-{label}.json") for label in report["plans"]},
            "v1_edls": {label: str(output / f"plan-{label}.edl.json") for label in report["plans"]
                        if report["plans"][label]["v1"]["representable"]},
            "music_sidecars": {label: str(output / report["plans"][label]["v1"]["music_sidecar"])
                               for label in report["plans"] if report["plans"][label]["v1"].get("music_sidecar")},
            "alternatives": report.get("alternatives", {}), "missing_drafts": report.get("missing_drafts"),
            "summary": {"drafts": len(report["plans"]), "shortages": report["shortages"],
                        **({"target_length": report["target_length"]} if "target_length" in report else {}),
                        # Low-resolution advice first: it changes what to render.
                        "warnings": [*dict.fromkeys(p["resolution"]["summary"] for p in report["plans"].values()
                                                    if p["resolution"]["limited"]),
                                     *(f"{label}: {ALTERNATIVE}: {reason}." for label, reason
                                       in report.get("alternatives", {}).items()),
                                     *([report["missing_drafts"]["reason"]] if report.get("missing_drafts") else []),
                                     *inventory_notes, *excluded],
                        "resolution": {label: {key: p["resolution"][key] for key in
                                               ("limited", "output", "summary", "recommendation")}
                                       for label, p in report["plans"].items()},
                        "source_asr": [{"asset_id": c.asset_id, "file": Path(c.path).name, **c.asr_repair}
                                       for c in clips if c.asr_repair.get("repairs") or c.asr_repair.get("quarantined")],
                        "clips_needing_study": [c.asset_id for c in clips if c.status == "needs_study"],
                        "clips_needing_scan": [c.asset_id for c in clips if c.status == "needs_scan"],
                        "deviations": {label: p["deviations"] for label, p in report["plans"].items()}}}
