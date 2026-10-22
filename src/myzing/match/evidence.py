"""Compare observations of the rendered file with the reusable recipe."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median

from myzing.project.api import hash_file
from myzing.study.proc import run


def user_warnings(warnings):
    """The director's serialized evidence stays in plans, not warning prose."""
    return list(dict.fromkeys(w for w in warnings if not w.startswith("P17 planning evidence:")))


def decode(path, plan):
    probe = run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
                 "-of", "json", str(path)], timeout=180)
    if probe.returncode:
        raise ValueError("ffprobe failed: " + probe.stderr)
    data = json.loads(probe.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if not video or int(video.get("nb_read_frames", 0)) <= 0:
        raise ValueError("Render has no decoded video frames")
    if (video["width"], video["height"]) != (plan.width, plan.height):
        raise ValueError("Rendered dimensions differ from the plan")
    expected = max(c.timeline_end for c in plan.clips)
    fps = plan.fps.numerator / plan.fps.denominator
    duration = float(video.get("duration", data["format"]["duration"]))
    if abs(duration - expected) > 2 / fps + .001:
        raise ValueError(f"Rendered duration {duration:g}s differs from planned {expected:g}s")
    frames = int(video["nb_read_frames"])
    if abs(frames - round(expected * fps)) > 2:
        raise ValueError(f"Only {frames} frames decoded for {expected:g}s at {fps:g} fps")
    checked = run(["ffmpeg", "-v", "error", "-xerror", "-err_detect", "explode", "-i", str(path),
                   "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"], timeout=180)
    if checked.returncode:
        raise ValueError("Full audio/video decode failed: " + checked.stderr)
    return {"version": 1, "path": str(path), "sha256": hash_file(path), "full_decode": True,
            "frames": frames, "duration": duration, "width": video["width"], "height": video["height"],
            "audio_streams": sum(s["codec_type"] == "audio" for s in data["streams"])}


def geometry_stats(geometry):
    """Only caption tracks, never background signage or all OCR detections."""
    samples = [s for t in geometry.get("tracks", []) if t["kind"] == "caption" for s in t["samples"]]
    boxes = [s.get("ink_box") or s.get("box") for s in samples]
    boxes = [b for b in boxes if b and len(b) == 4]
    if not boxes:
        return None
    return {"box": [median(b[i] for b in boxes) for i in range(4)], "samples": len(boxes),
            "coverage": geometry.get("coverage", {}), "basis": "median sampled caption-track box; normalized edges"}


def _metric(target, observed, tolerance, basis, *, approximate=False):
    if target is None or observed is None:
        status = "approximate"
        reason = "Missing measurement; no match established."
    else:
        status = "miss" if abs(target - observed) > tolerance else "approximate" if approximate else "pass"
        reason = "Within tolerance." if status != "miss" else "Outside tolerance."
    return {"status": status, "target": target, "observed": observed, "tolerance": tolerance,
            "basis": basis, "reason": reason}


def report(recipe, rendered, geometry, color, verification, plan):
    facts = {f.name: f.value for f in recipe.measured}
    durations = facts.get("shot_durations", [])
    observed_durations = [s.duration for s in rendered.shots]
    target = median(durations) if durations else None
    shots_unmeasured = any("shot" in w.lower() and any(word in w.lower() for word in ("fallback", "skipped", "failed"))
                           for w in [*recipe.warnings, *rendered.warnings])
    dimensions = {
        "shot_pace": _metric(target, median(observed_durations) if observed_durations else None,
                             (target or 0) * .1, "Median shot seconds measured from rendered pixels; 10% envelope.",
                             approximate=shots_unmeasured),
        "first_cut": _metric(durations[0] if len(durations) > 1 else None,
                             rendered.shots[1].start if len(rendered.shots) > 1 else None,
                             2 / rendered.meta.fps, "First detected output cut vs reference; two output frames.",
                             approximate=shots_unmeasured),
    }
    if durations and rendered.shots and not shots_unmeasured and (len(durations) == 1 or len(rendered.shots) == 1):
        dimensions["first_cut"].update(
            status="pass" if len(durations) == len(rendered.shots) == 1 else "miss",
            reason="Compare observed cut presence: both are continuous, or one has cuts the other lacks.")
    captions = [v for k, v in facts.items() if k.startswith("captions[")]
    onset = _metric(min((c["start"] for c in captions), default=None),
                    min((c.start for c in rendered.captions), default=None), .1,
                    "First OCR caption onset; sparse sampling cannot establish one-frame switches.", approximate=True)
    length = _metric(median(c["end"] - c["start"] for c in captions) if captions else None,
                     median(c.end - c.start for c in rendered.captions) if rendered.captions else None, .1,
                     "Median OCR event duration; texts differ between reference and draft.", approximate=True)
    dimensions["caption_timing"] = {"status": "miss" if "miss" in (onset["status"], length["status"]) else "approximate",
                                    "onset": onset, "event_duration": length,
                                    "reason": "ASR accuracy and per-word switch error need human-labeled speech; unmeasured here."}
    target_geo, output_geo = facts.get("caption_geometry.summary"), geometry_stats(geometry)
    placement = {"status": "approximate", "target": target_geo, "observed": output_geo,
                 "reason": "Caption geometry unavailable; placement match unmeasured."}
    if target_geo and output_geo:
        a, b = target_geo["box"], output_geo["box"]
        intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
        iou = intersection / union if union else 0
        placement.update(status="approximate" if iou >= .8 else "miss", median_box_iou=iou,
                         reason="Different text and sparse samples: box IoU is a style proxy, not known-font fidelity.")
    dimensions["caption_placement"] = placement
    target_color = facts.get("color.luma_percentiles")
    output_color = color.get("aggregate", {}).get("luma_percentiles") if color else None
    delta = max(abs(a - b) for a, b in zip(target_color, output_color)) if target_color and output_color else None
    dimensions["color"] = {"status": "miss" if delta is not None and delta > .15 else "approximate",
                           "target": target_color, "observed": output_color, "max_luma_percentile_delta": delta,
                           "tolerance": .15, "reason": "Unpaired scene distributions in encoded Rec.709; human review required. "
                           "This is not a paired Delta E 2000 test or recovery of an original LUT."}
    dimensions["typography"] = {"status": "approximate", "reason": "Pinned substitutes or disclosed system defaults; original font unknown."}
    return {"version": 1, "scope": "Measurements of the rendered draft, not planned values or a release certification.",
            "render": verification, "dimensions": dimensions,
            "warnings": user_warnings([*recipe.warnings, *rendered.warnings, *plan.warnings]),
            "recipe_unknowns": [u.to_dict() for u in recipe.unknowns],
            "rendered_study": rendered.to_dict(), "rendered_color": color}


def markdown(summary):
    def link(path):
        try:
            return Path(path).relative_to(summary["project"]).as_posix()
        except ValueError:
            return Path(path).as_posix()
    lines = [f"# Match comparison", "", summary["summary"], "",
             "Ready means rendered, fully decoded, inspected, and reported. Match grades describe measured style; they do not certify accuracy.", "",
             "| Draft | State | Shot pace | First cut | Caption timing | Placement | Color |",
             "|---|---|---|---|---|---|---|"]
    for label, row in summary["drafts"].items():
        grades = row.get("dimensions", {})
        cells = [grades.get(k, {}).get("status", "—") for k in
                 ("shot_pace", "first_cut", "caption_timing", "caption_placement", "color")]
        lines.append("| " + " | ".join([label, row["status"], *cells]) + " |")
    for label, row in summary["drafts"].items():
        if row["status"] == "ready":
            lines += ["", f"{label}: [video](<{link(row['video'])}>) · [plan](<{link(row['plan'])}>) · "
                      f"[timeline](<{link(row['timeline'])}>) · [match report](<{link(row['report'])}>)"]
    if summary.get("director_comparison"):
        lines += ["", f"[Full planning evidence](<{link(summary['director_comparison'])}>)"]
    if summary.get("shortages"):
        lines += ["", "Director shortages:", "", "```json", json.dumps(summary["shortages"], indent=2), "```"]
    for failure in summary.get("failures", []):
        lines += ["", f"Failed step `{failure['step']}`: {failure['error']}", f"Log: {failure['log']}"]
    if summary.get("warnings"):
        lines += ["", "Disclosures:", "", *[f"- {w}" for w in summary["warnings"]]]
    lines += ["", "Choose after review: `zing plan choose <project-folder> --draft A`.", ""]
    return "\n".join(lines)
