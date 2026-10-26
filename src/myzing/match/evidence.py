"""Compare observations of the rendered file with the reusable recipe."""

from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import median

from myzing.project.api import hash_file
from myzing.study.proc import run


_AT = re.compile(r"^At (\d+(?:\.\d+)?)s: (.*)$", re.S)
_SOURCE = re.compile(r"^source (.+?): (.*)$", re.S)


def group_disclosures(warnings: list[str], *, examples: int = 6) -> list[str]:
    """Collapse warnings that differ only by a timestamp or source prefix.

    comparison.json keeps every warning; the Markdown comparison is for a
    person, so one line per distinct message with a count and examples.
    """
    groups: dict[str, list[str]] = {}
    for warning in warnings:
        context, message = None, warning
        at = _AT.match(warning)
        source = None if at else _SOURCE.match(warning)
        if at:
            context, message = f"{float(at.group(1)):g}s", at.group(2)
        elif source:
            context, message = Path(source.group(1)).name, source.group(2)
        font = re.match(r"font candidates track ([^:]+): (.*)", message)
        if font:
            context = font.group(1)
            cause = re.sub(r"^.*?weight [^:]+: (?:ValueError: )?", "", font.group(2))
            message = "Font candidate: " + cause
        caption = re.match(r"caption (caption-\d+): (.*)", message)
        if caption:
            context, message = caption.groups()
        message = re.sub(r"caption geometry: \d+ coverage gap\(s\)", "caption geometry: sparse sampling coverage gaps", message)
        contexts = groups.setdefault(message, [])
        if context and context not in contexts:
            contexts.append(context)
    lines = []
    for message, contexts in groups.items():
        if len(contexts) > 1:
            shown = ", ".join(contexts[:examples])
            more = f", +{len(contexts) - examples} more" if len(contexts) > examples else ""
            lines.append(f"{message} ({len(contexts)}x: {shown}{more})")
        elif contexts:
            lines.append(f"{contexts[0]}: {message}")
        else:
            lines.append(message)
    return lines


def user_warnings(warnings):
    """The director's serialized evidence stays in plans, not warning prose."""
    return list(dict.fromkeys(w for w in warnings if not w.startswith(("P17 planning evidence:", "MUSIC1 evidence:", "CAPREF evidence:"))))


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


def report(recipe, rendered, geometry, color, verification, plan, audio_measurements=None, *, skin=None):
    facts = {f.name: f.value for f in recipe.measured}
    durations = facts.get("shot_durations", [])
    from myzing.director.plans import REPORT_PREFIX
    planning = next((json.loads(w[len(REPORT_PREFIX):]) for w in plan.warnings if w.startswith(REPORT_PREFIX)), {})
    source_pacing = planning.get("pacing_evidence", {})
    shots_unmeasured = any("shot" in w.lower() and any(word in w.lower() for word in ("fallback", "skipped", "failed"))
                           for w in [*recipe.warnings, *rendered.warnings])
    from .timing import timing_dimensions
    dimensions = timing_dimensions(durations, rendered, source_pacing, planning, plan, shots_unmeasured)
    captions = [v for k, v in facts.items() if k.startswith("captions[")]
    from myzing.study.text_roles import classify_text, caption_geometry
    output_roles = classify_text(rendered, geometry)
    caption_indices = {e["event_index"] for e in output_roles["events"] if e["role"] == "caption"}
    output_captions = [c for i, c in enumerate(rendered.captions) if i in caption_indices]
    from myzing.captions.reference import word_band
    band = word_band([c["words_visible"] for c in captions])
    target = band["median"] if captions else None
    dimensions["caption_words"] = _metric(target,
        median(c.words_visible for c in output_captions) if output_captions else None,
        0, "Caption-only word-count distribution outside reference IQR; medians retained as diagnostics.", approximate=True)
    words_metric = dimensions["caption_words"]
    words_metric["band"] = band
    if target is not None and words_metric["observed"] is not None:
        reference_outside = sum(not band["lower"] <= c["words_visible"] <= band["upper"] for c in captions) / len(captions)
        observed_outside = sum(not band["lower"] <= c.words_visible <= band["upper"] for c in output_captions) / len(output_captions)
        tolerance = .5 / len(output_captions)
        words_metric["outside_band_share"] = {"reference": reference_outside, "observed": observed_outside,
                                              "tolerance": tolerance}
        within = observed_outside <= reference_outside + tolerance
        words_metric.update(status="approximate" if within else "miss",
                            reason="Outside-band share does not exceed reference plus half-event tolerance." if within else
                                   "Too many caption groups outside the measured word-count band, regardless of median.")
    dimensions["caption_case"] = _metric(
        sum(c["all_caps"] for c in captions)/len(captions) if captions else None,
        sum(c.all_caps for c in output_captions)/len(output_captions) if output_captions else None,
        .5/len(output_captions) if output_captions else 0,
        "All-caps fraction of caption-only OCR events; half an output event rounding tolerance.", approximate=True)
    geometry = caption_geometry(geometry, output_roles)
    onset = _metric(min((c["start"] for c in captions), default=None),
                    min((c.start for c in output_captions), default=None), .1,
                    "First OCR caption onset; sparse sampling cannot establish one-frame switches.", approximate=True)
    length = _metric(median(c["end"] - c["start"] for c in captions) if captions else None,
                     median(c.end - c.start for c in output_captions) if output_captions else None, .1,
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
    sizes = [(c.style.size if c.style else max(24, min(plan.width, plan.height)/20))
             * (c.layout.scale if c.layout else 1.) for c in plan.captions]
    spread = max(sizes) - min(sizes) if sizes else 0.
    dimensions["caption_size"] = {"status": "pass" if sizes and spread <= .01 else "miss" if sizes else "not_applicable",
        "size_px": sizes[0] if sizes and spread <= .01 else None, "size_spread_px": round(spread, 6),
        "min_px": min(sizes) if sizes else None, "max_px": max(sizes) if sizes else None,
        "basis": "Effective planned font size, including layout scale; glyph heights vary by letter.",
        "reason": f"Caption font size spread: {spread:.2f}px across {len(sizes)} captions."}
    from .color import from_recipe
    dimensions["color"] = from_recipe(recipe, color)
    if recipe.color_mode == "source":
        dimensions["color"] = {"status": "not_applicable", "mode": "source",
                               "reason": "Source color retained; no color fit or LUT applied."}
    if skin is not None:
        # Same faces before/after each clip's own grade; not a reference comparison.
        dimensions["skin_preservation"] = skin
    dimensions["typography"] = {"status": "approximate", "reason": "Pinned substitutes or disclosed system defaults; original font unknown."}
    continuity = planning.get("continuity", {})
    if continuity:
        dimensions["continuity"] = {"status": {"flagged": "miss", "pass": "pass"}.get(continuity["status"], "not_applicable"),
                                    "reason": continuity["basis"], **{k: v for k, v in continuity.items() if k != "status"}}
    if any(a.kind == "music" for a in plan.audio):
        from myzing.music.ducking import DEFAULT_SPEECH_TO_MUSIC_LU as default
        target = planning.get("music", {}).get("speech_to_music_lu", default) if planning.get("music") else default
        measured = (audio_measurements or {}).get("speech_to_music_lu")
        dimensions["music_mix"] = _metric(target if measured is not None else None, measured, 3,
            "Isolated music and source stems in director speech windows; target 18-24 LU under speech.")
        if (planning.get("music") or {}).get("mode") == "music-led":
            dimensions["music_mix"] = _metric(-16,
                (audio_measurements or {}).get("music_integrated", {}).get("integrated_lufs"), 3,
                "Isolated music stem before final peak limiting; music-led planning target -16 LUFS.")
    return {"version": 1, "color_mode": recipe.color_mode, "scope": "Rendered measurements and mapped source-study cuts; no release certification.",
            "music": planning.get("music"), "audio_measurements": audio_measurements,
            "search_windows": planning.get("search_windows", {}),
            "source_pacing": source_pacing, "text_roles": output_roles,
            "pacing_flag": {"miss": "unmet", "pass": "met", "not_applicable": "not_applicable"}.get(
                dimensions["shot_pace"]["status"], "unverified"),
            "render": verification, "dimensions": dimensions,
            "warnings": user_warnings([*recipe.warnings, *rendered.warnings, *plan.warnings,
                *(["Skin preservation miss: " + skin["reason"]] if recipe.color_mode == "reference" and skin and skin["status"] == "miss" else [])]),
            "recipe_unknowns": [u.to_dict() for u in recipe.unknowns],
            "rendered_study": rendered.to_dict(), "rendered_color": color}


def markdown(summary):
    from .timing import dimension_notes, status_label
    def link(path):
        try:
            return Path(path).relative_to(summary["project"]).as_posix()
        except ValueError:
            return Path(path).as_posix()
    lines = [f"# Match comparison", "", summary["summary"], "",
             f"Color mode: {summary.get('color_mode', 'reference')}.", "",
             *[w + "\n" for w in summary.get("warnings", []) if w.startswith("Forced reframe retained")],
             "Render complete means fully decoded, inspected, and reported. Style match is separate; approximate dimensions remain unverified.", "",
             "| Draft | Render status | Failed style dimensions | Shot pace | First cut | Caption timing | Words/caption | Case | Placement | Color |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for label, row in summary["drafts"].items():
        grades = row.get("dimensions", {})
        cells = [status_label(grades.get(k, {}).get("status", "-")) for k in
                 ("shot_pace", "first_cut", "caption_timing", "caption_words", "caption_case", "caption_placement", "color")]
        failed = [k for k, v in grades.items() if v["status"] == "miss"]
        state = "render complete" if row["status"] == "ready" else row["status"]
        if row.get("alternative"):
            state += "; " + row["alternative"]["label"]
        lines.append("| " + " | ".join([label, state, ", ".join(failed) or "none established; unverified dimensions remain", *cells]) + " |")
    for label, row in summary["drafts"].items():
        if row["status"] == "ready":
            lines += ["", f"{label}: [video](<{link(row['video'])}>) · [plan](<{link(row['plan'])}>) · "
                      f"[timeline](<{link(row['timeline'])}>) · [match report](<{link(row['report'])}>)"]
            if row.get("alternative"):
                lines += ["", f"{label}: {row['alternative']['label']}: {row['alternative']['reason']}. "
                          "It never counts as a style match pass."]
            lines += ["", *dimension_notes(row.get("dimensions", {}))]
            caption_size = row.get("dimensions", {}).get("caption_size", {})
            if caption_size.get("status") == "pass":
                lines += ["", f"Captions: {caption_size['size_px']:.2f}px; size spread {caption_size['size_spread_px']:g}px."]
            color = row.get("dimensions", {}).get("color", {})
            if color.get("status") != "miss" and color.get("reason"):
                lines += ["", f"color: {color['status']}. {color['reason']}"]
            skin = row.get("dimensions", {}).get("skin_preservation", {})
            if skin.get("status") != "miss" and skin.get("reason"):
                lines += ["", f"skin preservation: {skin['status']}. {skin['reason']}"]
            for track in (row.get("music") or {}).get("tracks", []):
                lines += ["", f"Music: {Path(track['path']).name}. {track['reason']}",
                          track["advice"]["licensing"]]
            cuts = (row.get("music") or {}).get("cut_summary")
            if cuts:
                lines += ["", f"Music timing: {cuts['snapped']}/{cuts['total']} cuts snapped; "
                          f"{cuts['moment_locked']} locked to a moment, {cuts['already_aligned']} already aligned, "
                          f"{cuts['kept']} retained with per-cut reasons in the plan."]
            measured = row.get("audio_measurements")
            if measured:
                lines += ["", f"Measured music: {measured['music_speech_lufs']} LUFS in speech windows; "
                          f"{measured['music_gap_lufs']} LUFS in gaps; "
                          f"{measured['speech_to_music_lu']} LU below source speech. "
                          f"Mix: {measured['integrated']['integrated_lufs']} LUFS, "
                          f"{measured['integrated']['true_peak_dbtp']} dBTP. Unknown values remain unmeasured."]
    if summary.get("missing_drafts"):
        lines += ["", "Not delivered: " + summary["missing_drafts"]["reason"]]
    if summary.get("director_comparison"):
        lines += ["", f"[Full planning evidence](<{link(summary['director_comparison'])}>)"]
    if summary.get("reference_text_roles"):
        counts = summary["reference_text_roles"]["counts"]
        lines += ["", "Reference OCR roles (rules): " + ", ".join(f"{k}: {v}" for k, v in counts.items()) +
                  ". Only caption-role text informs caption style; uncertain text is excluded."]
    if summary.get("source_asr"):
        lines += ["", "Source ASR repairs (derived estimates; raw files unchanged):", ""]
        for item in summary["source_asr"]:
            repairs = [f"{r['text']!r} {r['original']['start']}-{r['original']['end']}s → {r['start']:.3f}-{r['end']:.3f}s"
                       for r in item["repairs"]]
            lines.append(f"- {item['file']}: " + "; ".join(repairs) +
                         f"; quarantined spans: {len(item['quarantined'])}. Full provenance is in comparison.json.")
    if summary.get("shortages"):
        lines += ["", "Director shortages:", "", "```json", json.dumps(summary["shortages"], indent=2), "```"]
    for failure in summary.get("failures", []):
        lines += ["", f"Failed step `{failure['step']}`: {failure['error']}", f"Log: {failure['log']}"]
    if summary.get("warnings"):
        lines += ["", "Disclosures (grouped; comparison.json lists each one):", "",
                  *[f"- {w}" for w in group_disclosures(summary["warnings"])
                    if not w.startswith("Forced reframe retained")]]
    lines += ["", "Choose after review: `zing plan choose <project-folder> --draft A`.", ""]
    return "\n".join(lines)
