"""Confirmed studio plans delegate to Zing's existing APIs."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from . import adapters
from .flow import brief_answers, next_step
from .models import read_json, write_json


def _paths(value):
    """Collect existing output artifacts, not inline media, from producer metadata."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"path", "video", "plan", "timeline", "report", "comparison", "recipe", "comparison_path",
                       "index_path", "contact_sheet", "prompt_path", "card_json", "card_md", "card_png", "decode", "receipt_path"}:
                if isinstance(item, str) and Path(item).is_file():
                    found.append(str(Path(item).resolve()))
            elif isinstance(item, (dict, list)):
                found.extend(_paths(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_paths(item))
    return list(dict.fromkeys(found))


def _warnings(value):
    found = []
    if isinstance(value, dict):
        found.extend(w for w in value.get("warnings", []) if isinstance(w, str))
        for key, item in value.items():
            if key != "warnings" and isinstance(item, (dict, list)):
                found.extend(_warnings(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_warnings(item))
    return list(dict.fromkeys(found))


def _public_metadata(value):
    """Keep detailed director/music evidence in its linked plans, not tool prose."""
    from myzing.match.evidence import user_warnings
    if isinstance(value, dict):
        return {key: user_warnings(item) if key == "warnings" and isinstance(item, list)
                else _public_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_public_metadata(item) for item in value]
    return value


def no_reference(a, root, progress):
    from myzing import storage
    from myzing.project import api as projects
    from myzing.brief.api import save_brief, brief_result
    from myzing.brief.models import Brief
    from myzing.study.api import study
    from myzing.director.api import plan_drafts
    from myzing.style_recipe import StyleRecipe, ObservationProvenance, Unknown
    from .evidence import media_files

    files = media_files(a["clips"], root)
    if not files:
        raise ValueError("No supported local clips. Add videos to the clip folder and resume.")
    progress("Inventory clips")
    if (root / "project.json").exists():
        manifest = projects.load_project(root)
        if projects.resolve_path(manifest.clips_root, root) != Path(a["clips"]):
            raise ValueError("This project inventories a different folder; use a fresh project.")
        projects.scan_project(root)
    else:
        # The inventory schema requires a file reference. This bookkeeping
        # pointer is explicitly not used as a style reference or studied twice.
        projects.init_project(str(files[0]), a["clips"], root)
    adapters.register_music(root, a["music"])
    brief = save_brief(root, Brief.from_answers(brief_answers(a)))
    recommendation = brief_result(root, brief)
    manifest = projects.load_project(root)
    for asset in manifest.assets:
        if asset.state != "ready" or not asset.probe or not asset.probe.width:
            continue
        source = projects.resolve_path(asset.path, root)
        progress(f"Study {source.name} (local models only)")
        study(str(source), workspace=root, raw_mode=True, local_models_only=True,
              model_workspace=storage.resolve_workspace(), phase_callback=progress)
    recipe = StyleRecipe(ObservationProvenance(str(root / "brief.json"), detector="myzing.studio.brief-style/1"),
                         unknowns=[Unknown("reference_style", "No reference was requested; style comes from the saved brief.")],
                         warnings=[f"{a['tone']} is a chosen tone, not a measured property of the footage. Source color is unchanged."])
    write_json(root / "studio-recipe.json", recipe.to_dict())
    progress("Plan A/B/C with measured clip studies and the brief")
    planned = plan_drafts(root, root / "studio-recipe.json", root / "drafts",
                          studio_options={"no_reference": True, "tone": a["tone"], "captions": a["captions"]})
    if planned["status"] != "ready":
        return {**planned, "shortages": planned["summary"]["shortages"], "recommendation": recommendation}
    deliveries, failures = {}, []
    attempt = Path(tempfile.mkdtemp(prefix="deliveries-", dir=root))
    for label, plan in planned["plans"].items():
        progress(f"Render draft {label}: {', '.join(a['aspects'])}")
        try:
            deliveries[label] = adapters.deliver(plan, attempt / f"draft-{label}.mp4", a["aspects"])
        except (ValueError, OSError, RuntimeError) as exc:
            failures.append({"step": f"render-{label}", "error": str(exc)})
    return {"status": "ready" if not failures else "partial" if deliveries else "failed",
            "plans": planned, "deliveries": deliveries, "failures": failures, "recommendation": recommendation}


def run_confirmed(answers, *, progress=None):
    """Internal execution API; callers must obtain explicit plan confirmation."""
    progress = progress or (lambda text: None)
    response = next_step(answers)
    if response["status"] != "plan":
        raise ValueError("Complete the studio questions and confirm the plan before running.")
    a, plan = response["answers"], response["plan"]
    root, path = Path(a["project"]), a["path"]
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    progress("Starting " + plan["title"])
    if path == "a":
        from myzing.match.jobs import execute
        from .jobs import busy_lock
        with busy_lock(root):
            result = execute({"reference": a["reference"], "clips": a["clips"], "out": str(root),
                              "answers": brief_answers(a), "resume": (root / "match-state.json").is_file(),
                              "allow_download": a.get("allow_download", False),
                              "studio_options": {"captions": a["captions"], "music": a["music"]}},
                             progress=progress, locked=True)
    elif path == "b":
        result = no_reference(a, root, progress)
    elif path == "c":
        from myzing.still.api import create_stills, pick_still
        attempt = Path(tempfile.mkdtemp(prefix="stills-", dir=root))
        rows = {}
        for aspect in a["aspects"]:
            progress(f"Measure photos and render six {aspect} concepts")
            folder = attempt / aspect.replace(":", "x")
            made = create_stills(a["photos"], a["topic"], folder, aspect=aspect)
            selected = max(made["summary"], key=lambda c: c["score"].get("readability", 0))
            progress(f"Export the selected {aspect} still (highest readability score; humor needs your review)")
            rows[aspect] = {"concepts": made, "selected": pick_still(folder, selected["id"])}
        result = {"status": "ready", "stills": rows}
    elif path == "d":
        attempt = Path(tempfile.mkdtemp(prefix="style-", dir=root))
        result = adapters.explain_video(a["source"], attempt, progress=progress)
        result["status"] = "ready" if result.get("ok") else "failed"
    elif path == "e":
        from myzing.music.advice import check_tracks
        progress("Analyze tracks and explain their suitability")
        advice = check_tracks(a["tracks"], **({"plan": a["context"]} if a["context"] != "none"
                              else {"length": a["length"], "speech": a["speech"]}))
        attempt = Path(tempfile.mkdtemp(prefix="music-", dir=root))
        write_json(attempt / "advice.json", advice)
        result = {"status": "ready", "advice": advice, "report": str(attempt / "advice.json")}
    else:
        attempt = Path(tempfile.mkdtemp(prefix="deliveries-", dir=root))
        progress("Rebuild framing, render, and decode each delivery")
        result = adapters.deliver(a["source"], attempt / "edit.mp4", a["aspects"])
    if path in "ab" and a.get("draft", "keep all") != "keep all":
        from myzing.project.choices import choose_draft
        label = a["draft"]
        if path == "a":
            row = next((r for key, r in result.get("drafts", {}).items() if key.split(".")[0] == label and r.get("status") == "ready"), None)
            selected = row.get("plan") if row else None
        else:
            selected = result.get("plans", {}).get("plans", {}).get(label)
        if selected:
            result["choice"] = choose_draft(root, label, draft_file=selected)
    result = _public_metadata(result)
    outputs = _paths(result)
    from myzing.match.evidence import user_warnings
    from myzing.project.api import hash_file
    warnings = user_warnings(list(dict.fromkeys([*plan["warnings"], *_warnings(result)])))
    # The producer may have delivered video without the requested captions.
    if path in "ab" and a["captions"] == "phone":
        from myzing.composition import Composition
        small = []
        for output in outputs:
            if Path(output).suffix == ".json" and "plan" in Path(output).stem:
                try:
                    p = Composition.from_dict(read_json(output))
                    if not p.captions:
                        warnings.append(f"Blocked captions: {output} contains no timed caption events. Speech is unknown or unavailable; review the studies.")
                    small.extend(c.style.size * 1080 / min(p.width, p.height) for c in p.captions
                                 if c.style and c.style.size < min(p.width, p.height) / 30)
                except ValueError:
                    pass
        if small:
            warnings.append(f"Phone captions need review: {len(small)} delivered caption events were reduced below a 36px size at a 1080px short side (smallest {min(small):.1f}px). Placement safety can reduce readability; inspect the videos at phone size.")
    next_actions = {
        "a": ["Review the draft videos and their match reports.", "Choose A, B or C with zing plan choose.", "Want another shape? Run zing studio and choose 6."],
        "b": ["Review A/B/C before choosing with zing plan choose.", "Try a music track: run zing studio and choose 5.", "Want another shape? Run zing studio and choose 6."],
        "c": ["Open the contact sheet and check the joke and text placement.", "Pick another concept with zing still pick <folder> --id <id>.", "Try a more specific topic in a fresh studio session."],
        "d": ["Open the style card and review its measured observations.", "Run zing studio and choose 1 to use this video as the reference."],
        "e": ["Compare the reasons and listen to the suggested excerpts.", "Try another local track.", "Use a chosen track: run zing studio and choose 1 or 2."],
        "f": ["Watch the new delivery and check its crop.",
              "Want another shape? Run zing studio, choose 6 and give it the original plan."],
    }[path]
    status = result.get("status", "failed")
    if status in ("failed", "shortage", "cancelled"):
        # Nothing finished to review: point at the blocker and the saved session.
        resume = f'zing studio --resume "{root}"'
        next_actions = [{"cancelled": f"Continue where you stopped: {resume}",
                         "shortage": f"Fix the blocker named above, then continue: {resume}",
                         "failed": f"Fix the error above, then retry: {resume}"}[status],
                        "On the plan screen, b goes back to change an answer."]
    result = {"version": 1, "ok": result.get("status") == "ready", "status": result.get("status", "failed"),
              **({"error": result["error"]} if result.get("error") else {}),
              "project": str(root), "outputs": outputs, "warnings": warnings, "result": result,
              "next_actions": next_actions, "seconds": round(time.monotonic() - started, 3)}
    result["output_sha256"] = {p: hash_file(Path(p)) for p in outputs}
    from .presentation import creator_summary
    result["creator_summary"] = creator_summary(result, a, plan["evidence"])
    write_json(root / "studio-result.json", result)
    return result
