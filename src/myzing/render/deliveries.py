"""Local multi-aspect rendering from one source composition, never a scaled MP4."""

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from myzing.composition.aspects import dimensions, requested_aspects
from myzing.layout.delivery import adapt_plan
from myzing.layout.framing import analyze_subjects
from myzing.layout.resolution import (auto_gain, chosen_short_side, mark_auto_declined, mark_auto_selected,
                                      resolution_advice)
from myzing.layout.media import probe_duration
from myzing.study.shots import detect_shots
from .composition import _path, _verify, render_composition, unsupported_features
from .framing import probe_dimensions
from .validation import EDLValidationError


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _key(path):
    return os.path.normcase(str(Path(path).resolve()))


def input_paths(composition, base_dir=None):
    """Every local file a delivery reads: assets, LUTs, caption and graphic fonts."""
    base_dir = Path(base_dir or Path.cwd()).resolve()
    paths = [_path(a.path, base_dir, f"asset {a.id}") for a in composition.assets]
    paths += [_path(c.color.lut_path, base_dir, f"clip {c.id} LUT") for c in composition.clips if c.color]
    paths += [_path(c.font.path, base_dir, f"caption {c.id} font") for c in composition.captions if c.font]
    paths += [_path(g.font.path, base_dir, f"graphic {g.id} font") for g in composition.graphics if g.font]
    return paths


def measure_sources(sources, directory, *, fps, ffprobe="ffprobe"):
    """Measure each source once over the union of its used trims.

    sources maps a resolved media path to (src_in, src_out) ranges. The
    result is keyed by normalized path so callers can share it across drafts.
    """
    directory = Path(directory).resolve()
    measured = {}
    for index, (path, ranges) in enumerate(sorted(sources.items(), key=lambda item: _key(item[0]))):
        path = Path(path)
        size = probe_dimensions(path, ffprobe)
        duration = probe_duration(path)
        # The existing optional cut detector is local and model-free.
        shots = detect_shots(path, duration, fps)
        cuts = [s.start for s in shots.shots]
        tracks, warnings = analyze_subjects(path, duration, directory / "sampling" / f"source-{index:03d}", cuts,
                                            ranges=list(ranges))
        from myzing.layout.picture import analyze_picture
        picture = analyze_picture(path, ranges, size)
        measured[_key(path)] = {"display_dimensions": size, "tracks": tracks, "cuts": cuts,
                                "picture": picture,
                                "ranges": sorted({(float(a), float(b)) for a, b in ranges}),
                                "warnings": [*shots.warnings, *warnings]}
    return measured


def used_ranges(plan):
    """Resolved source path -> used (src_in, src_out) trims for a plan with absolute paths."""
    paths = {a.id: a.path for a in plan.assets}
    result = {}
    for clip in plan.clips:
        result.setdefault(paths[clip.asset_id], []).append((clip.src_in, clip.src_out))
    return result


def delivery_plans(composition, aspects, directory, *, base_dir=None, framing=None, max_upscale=None,
                   short_side=None, ffprobe="ffprobe", measured=None, continue_on_error=False):
    """Hash local inputs first, measure once, then independently adapt each plan.

    measured may carry measure_sources results shared with other plans; any
    source it lacks is measured here over this plan's own trims. short_side
    is an int, "auto", or None for the brief's value (default 1080); auto
    lowers an aspect's size when its resolution advice recommends it.
    """
    base_dir = Path(base_dir or Path.cwd()).resolve()
    directory = Path(directory).resolve()
    selected = requested_aspects(composition, aspects)
    if not selected:
        raise EDLValidationError("No delivery aspects supplied; use --aspect all or a brief aspects list")
    if short_side is None:
        short_side = getattr(composition.brief, "short_side", 1080) if composition.brief else 1080
    for aspect in selected:
        dimensions(aspect, 1080 if short_side == "auto" else short_side)
    plan = deepcopy(composition)
    plan.__post_init__()
    unsupported = unsupported_features(plan)
    if unsupported:
        raise EDLValidationError("Delivery renderer cannot adapt: " + "; ".join(unsupported))
    requested = framing or (plan.brief.framing if plan.brief else "auto")
    if requested not in ("auto", "fit", "fill", "reframe", "zoomfill", "blurfill"):
        raise EDLValidationError("framing: choose auto, fit, fill, reframe, zoomfill, or blurfill")
    limit = max_upscale if max_upscale is not None else plan.brief.framing_max_upscale if plan.brief else 2.5
    from myzing.brief.models import Brief
    Brief(framing_max_upscale=limit)  # Shared finite/range validation before IO.
    paths = {}
    for asset in plan.assets:
        path = _path(asset.path, base_dir, f"asset {asset.id}")
        _verify(path, asset.sha256, f"asset {asset.id}")
        paths[asset.id] = path
        asset.path = str(path)
    for item in [*plan.clips, *plan.audio]:
        item.src = str(paths[item.asset_id])
    for clip in plan.clips:
        if clip.color:
            path = _path(clip.color.lut_path, base_dir, f"clip {clip.id} LUT")
            _verify(path, clip.color.sha256, f"clip {clip.id} LUT")
            clip.color.lut_path = str(path)
    for caption in plan.captions:
        if caption.font:
            path = _path(caption.font.path, base_dir, f"caption {caption.id} font")
            _verify(path, caption.font.sha256, f"caption {caption.id} font")
            caption.font.path = str(path)
    for graphic in plan.graphics:
        if graphic.font:
            path = _path(graphic.font.path, base_dir, f"graphic {graphic.id} font")
            _verify(path, graphic.font.sha256, f"graphic {graphic.id} font")
            graphic.font.path = str(path)
    measured = dict(measured or {})
    missing = {path: ranges for path, ranges in used_ranges(plan).items() if _key(path) not in measured}
    if missing:
        measured.update(measure_sources(missing, directory, fps=plan.fps.numerator / plan.fps.denominator,
                                        ffprobe=ffprobe))
    sizes, tracks, cuts, evidence, pictures = {}, {}, {}, {}, {}
    for asset_id in sorted({c.asset_id for c in plan.clips}):
        item = measured[_key(paths[asset_id])]
        sizes[asset_id], tracks[asset_id], cuts[asset_id] = item["display_dimensions"], item["tracks"], item["cuts"]
        policy = plan.brief.picture_crop if plan.brief else "auto"
        detected = item.get("picture", {})
        applied = policy != "off" and bool(detected.get("confident"))
        pictures[asset_id] = {**detected, "requested": policy, "applied": applied,
                             "decision": "crop to live picture" if applied else "preserve source: " +
                             ("disabled" if policy == "off" else detected.get("reason", "unmeasured"))}
        evidence[asset_id] = {"display_dimensions": sizes[asset_id], "tracks": [t.to_dict() for t in tracks[asset_id]],
                              "picture": pictures[asset_id],
                              "cuts": cuts[asset_id], "analyzed_ranges": [list(r) for r in item["ranges"]],
                              "warnings": item["warnings"]}
    results, resolution, failures = {}, {}, {}

    def adapt_one(aspect):
        size = dimensions(aspect, 1080 if short_side == "auto" else short_side)
        result = adapt_plan(plan, *size, sizes, tracks, requested=requested, max_upscale=limit, cuts=cuts, pictures=pictures)
        advice = resolution_advice(result.clips, sizes, *size, max_upscale=limit,
                                   command=f"zing render PLAN.json --aspect {aspect}")
        lower = chosen_short_side(advice, short_side)
        if lower != min(size):
            trial = dimensions(aspect, lower)
            lowered = adapt_plan(plan, *trial, sizes, tracks, requested=requested, max_upscale=limit, cuts=cuts, pictures=pictures)
            second = resolution_advice(lowered.clips, sizes, *trial, max_upscale=limit,
                                       command=f"zing render PLAN.json --aspect {aspect}")
            if auto_gain(advice, second):
                # Keep the lower size only when its planned picture improves.
                advice, size, result = mark_auto_selected(second, advice), trial, lowered
            else:
                mark_auto_declined(advice, second)
        if advice["limited"] or advice.get("auto_selected"):
            # Up front: the first thing a reader of the delivery plan sees.
            result.warnings.insert(0, advice["summary"])
        return result, advice

    for aspect in selected:
        try:
            results[aspect], resolution[aspect] = adapt_one(aspect)
        except (ValueError, OSError, RuntimeError) as exc:
            if not continue_on_error:
                raise
            failures[aspect] = delivery_failure(aspect, exc)
    for result in results.values():
        result.warnings.extend(w for item in evidence.values() for w in item["warnings"])
        # Composition schemas are shared: carry versioned detector evidence in
        # the existing machine-readable warning convention, also in the report.
        prefix = "zing.subject_analysis: "
        result.warnings = [w for w in result.warnings if not w.startswith(prefix)]
        result.warnings.append(prefix + json.dumps({"version": 1, "sources": evidence}, sort_keys=True))
    return results, {"version": 1, "sources": evidence, "framing": requested, "max_upscale": limit,
                     "short_side": short_side, "resolution": resolution, **({"failures": failures} if failures else {})}


def delivery_failure(aspect, error):
    reason = str(error)
    remedy = ("Choose clean captions or shorten the affected phrase, then retry this shape."
              if "caption" in reason.lower() else
              "Review the saved plan and source paths, fix the reported error, then retry this shape.")
    return {"status": "failed", "shape": aspect, "error": reason, "next_step": remedy}


def render_deliveries(composition, output, *, aspects=None, base_dir=None, work_dir=None,
                      framing=None, max_upscale=None, short_side=None, ffmpeg="ffmpeg", ffprobe="ffprobe",
                      inputs=(), continue_on_error=False):
    """Render each aspect; inputs are extra read-only paths (e.g. the source plan).

    Without work_dir the analysis/render work lives in a temporary folder next
    to the output and is removed afterwards; work_dir keeps it (--keep-work).
    """
    output = Path(output).expanduser().resolve()
    selected = requested_aspects(composition, aspects)
    report_path = output.with_name(output.stem + ".deliveries.json")
    destinations = [report_path]
    for aspect in selected:
        stem = output.stem + "." + aspect.replace(":", "x")
        # A measured music render also writes <stem>.music.json beside its MP4.
        destinations.extend([output.with_name(stem + ".mp4"), output.with_name(stem + ".json"),
                             output.with_name(stem + ".music.json"), output.with_name(stem + ".encoding.json")])
    # Refuse before any analysis: no delivery file may replace something it reads.
    protected = {_key(p): Path(p) for p in [*input_paths(composition, base_dir), *inputs]}
    for destination in destinations:
        hit = protected.get(_key(destination)) or next(
            (p for p in protected.values() if destination.exists() and p.exists() and os.path.samefile(destination, p)), None)
        if hit is not None:
            raise EDLValidationError(f"delivery output {destination} would overwrite input {hit}; "
                                     "choose a different -o/output path")
        if destination.is_symlink():
            raise EDLValidationError(f"delivery output {destination} is a symlink; choose a different -o/output path")
    if work_dir is not None:
        return _render_deliveries(composition, output, Path(work_dir).expanduser().resolve(), selected, report_path,
                                  base_dir, framing, max_upscale, short_side, ffmpeg, ffprobe, continue_on_error)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.stem}-delivery-", dir=output.parent) as temporary:
        return _render_deliveries(composition, output, Path(temporary), selected, report_path,
                                  base_dir, framing, max_upscale, short_side, ffmpeg, ffprobe, continue_on_error)


def quarantine_failed_delivery(row):
    """Keep diagnostic bytes out of the playable delivery filenames."""
    video = row.pop("video", None)
    if video and Path(video).is_file():
        failed = Path(video).with_suffix(Path(video).suffix + ".failed")
        Path(video).replace(failed)
        row["failed_artifact"] = str(failed)


def _render_deliveries(composition, output, work, selected, report_path, base_dir, framing, max_upscale,
                       short_side, ffmpeg, ffprobe, continue_on_error=False):
    plans, evidence = delivery_plans(composition, selected, work, base_dir=base_dir, framing=framing,
                                     max_upscale=max_upscale, short_side=short_side, ffprobe=ffprobe,
                                     continue_on_error=continue_on_error)
    rows = dict(evidence.get("failures", {}))
    report = {"version": 1, "status": "rendering", "deliveries": rows, "analysis": evidence}
    _write(report_path, report)
    try:
        for aspect, plan in plans.items():
            stem = output.stem + "." + aspect.replace(":", "x")
            video, saved = output.with_name(stem + ".mp4"), output.with_name(stem + ".json")
            row = rows[aspect] = {"status": "rendering", "video": str(video), "plan": str(saved),
                                  "width": plan.width, "height": plan.height,
                                  "resolution": evidence["resolution"][aspect]}
            _write(saved, plan.to_dict())
            try:
                result = render_composition(plan, video, base_dir=saved.parent, work_dir=work / aspect.replace(":", "x"),
                                            ffmpeg=ffmpeg, ffprobe=ffprobe)
            except Exception as exc:
                row.update(delivery_failure(aspect, exc))
                quarantine_failed_delivery(row)
                if not continue_on_error:
                    raise
                _write(report_path, report)
                continue
            row.update(status="ready", warnings=list(result.warnings))
            if getattr(result, "delivery_measurements", None) is not None:
                row["encoding"] = result.delivery_measurements
            if result.audio_measurements is not None:
                # Every aspect carries the source plan's music evidence and audio,
                # so its mix is measured against the same speech spans.
                row["music"] = str(video.with_suffix(".music.json"))
            _write(report_path, report)
        ready = sum(r["status"] == "ready" for r in rows.values())
        report["status"] = "ready" if ready == len(selected) else "partial" if ready else "failed"
        report["ready"], report["requested"] = ready, len(selected)
        report["failures"] = [dict(row, shape=shape) for shape,row in rows.items() if row["status"] == "failed"]
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        _write(report_path, report)
        raise
    _write(report_path, report)
    return {key: report[key] for key in ("status", "deliveries", "ready", "requested", "failures")} | {"report": str(report_path)}
