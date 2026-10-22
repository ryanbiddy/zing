"""Paths in, plans and comparison out. Planning never starts a render or study."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from myzing.brief.api import load_brief
from myzing.project.api import load_project
from myzing.project.locking import project_lock
from myzing.style_recipe import StyleRecipe

from .inventory import inventory
from .models import PlanningShortage, shortage
from .plans import attach_report, make_plan, render_projection
from .selection import candidates, choose, constraints, envelope

PRODUCER = "myzing.director/1"
MANAGED = {"comparison.json", *(f"plan-{label}{suffix}.json" for label in "ABC" for suffix in ("", ".edl"))}


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


def plan_drafts(project: str | Path, recipe: str | Path, out: str | Path, *, seed: int = 0) -> dict:
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    root = Path(project).expanduser().resolve()
    recipe_path = Path(recipe).expanduser().resolve()
    output = Path(out).expanduser().resolve()
    manifest = load_project(root)
    brief = load_brief(root / "brief.json")
    style_recipe = StyleRecipe.from_json(recipe_path.read_text(encoding="utf-8-sig"))
    clips, inventory_notes = inventory(root)
    report = {"version": 1, "producer": PRODUCER, "seed": seed, "status": "shortage",
              "brief": brief.to_dict(), "inventory": [c.to_dict() for c in clips],
              "inventory_warnings": inventory_notes, "plans": {}, "shortages": []}
    payloads = {}
    try:
        if not any(c.status == "ready" for c in clips):
            shortage("study_required", "No project clip has a usable study.",
                     f'Run zing study <clip> --raw --workspace "{root}" for each needed clip.')
        keep, forbidden = constraints(brief, manifest, clips)
        required_seconds = sum(b - a for spans in keep.values() for a, b in spans)
        if required_seconds > brief.target_length_seconds + 2 / 30:
            shortage("must_keep_length", f"Whole-word must-keeps require {required_seconds:.3f}s, beyond the brief target.",
                     "Lengthen the brief or shorten its must-keep spans.")
        style = envelope(style_recipe)
        pool, required = candidates(clips, keep, forbidden, style, brief.target_length_seconds)
        selected = choose(pool, required, clips, style, brief.target_length_seconds, 30, seed)
        report["envelope"] = style.to_dict()
        report["search"] = {"candidate_count": len(pool), "method": "deterministic bounded beam; 96 states per expansion",
                            "distinctness": "Different opening content with <50% overlap, or >=max(1s, reference median, 20% target) changed footage.",
                            "duration_tolerance_seconds": 2 / 30}
        for label, sequence in selected.items():
            plan, evidence = make_plan(label, sequence, clips, style_recipe, recipe_path.parent,
                                       style, brief, manifest, root, seed, keep, forbidden)
            evidence["differs_from"] = {
                other: {"opening_changed": sequence[0].identity != alternative[0].identity,
                        "this_opening": {"asset_id": sequence[0].asset_id, "start": sequence[0].start, "end": sequence[0].end},
                        "other_opening": {"asset_id": alternative[0].asset_id, "start": alternative[0].start, "end": alternative[0].end},
                        "source_choices_changed": sorted(c.identity for c in sequence) != sorted(c.identity for c in alternative)}
                for other, alternative in selected.items() if other != label
            }
            plan = attach_report(plan, evidence)
            legacy, blockers = render_projection(plan)
            evidence["v1"] = {"representable": legacy is not None, "blockers": blockers,
                              "evidence_retained_in": [f"plan-{label}.json", "comparison.json"],
                              "projection": "Only brief and warnings are separated into the retained v2 evidence; all rendering instructions are checked by lower_to_v1."}
            # Record lowering in the plan itself too, with no dependency on out.
            plan = attach_report(plan, evidence)
            payloads[f"plan-{label}.json"] = plan.to_json(indent=2) + "\n"
            if legacy is not None:
                payloads[f"plan-{label}.edl.json"] = _json(legacy.to_dict())
            report["plans"][label] = evidence
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
            "summary": {"drafts": len(report["plans"]), "shortages": report["shortages"],
                        "clips_needing_study": [c.asset_id for c in clips if c.status == "needs_study"],
                        "clips_needing_scan": [c.asset_id for c in clips if c.status == "needs_scan"],
                        "deviations": {label: p["deviations"] for label, p in report["plans"].items()}}}
