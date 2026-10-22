"""Local multi-aspect rendering from one source composition, never a scaled MP4."""

import json
from copy import deepcopy
from pathlib import Path

from myzing.composition.aspects import dimensions, requested_aspects
from myzing.layout.delivery import adapt_plan
from myzing.layout.framing import analyze_subjects
from myzing.layout.media import probe_duration
from myzing.study.shots import detect_shots
from .composition import _path, _verify, render_composition, unsupported_features
from .framing import probe_dimensions
from .validation import EDLValidationError


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def delivery_plans(composition, aspects, directory, *, base_dir=None, framing=None, max_upscale=None,
                   short_side=1080, ffprobe="ffprobe"):
    """Hash local inputs first, measure once, then independently adapt each plan."""
    base_dir = Path(base_dir or Path.cwd()).resolve()
    directory = Path(directory).resolve()
    selected = requested_aspects(composition, aspects)
    if not selected:
        raise EDLValidationError("No delivery aspects supplied; use --aspect all or a brief aspects list")
    for aspect in selected:
        dimensions(aspect, short_side)
    plan = deepcopy(composition)
    plan.__post_init__()
    unsupported = unsupported_features(plan)
    if unsupported:
        raise EDLValidationError("Delivery renderer cannot adapt: " + "; ".join(unsupported))
    requested = framing or (plan.brief.framing if plan.brief else "auto")
    if requested not in ("auto", "fit", "fill", "reframe", "blurfill"):
        raise EDLValidationError("framing: choose auto, fit, fill, reframe, or blurfill")
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
    sizes, tracks, cuts, evidence = {}, {}, {}, {}
    for asset_id in sorted({c.asset_id for c in plan.clips}):
        path = paths[asset_id]
        sizes[asset_id] = probe_dimensions(path, ffprobe)
        duration = probe_duration(path)
        # The existing optional cut detector is local and model-free.
        shots = detect_shots(path, duration, plan.fps.numerator / plan.fps.denominator)
        cuts[asset_id] = [s.start for s in shots.shots]
        tracks[asset_id], warnings = analyze_subjects(path, duration, directory / "sampling", cuts[asset_id])
        evidence[asset_id] = {"display_dimensions": sizes[asset_id], "tracks": [t.to_dict() for t in tracks[asset_id]],
                              "cuts": cuts[asset_id], "warnings": [*shots.warnings, *warnings]}
    results = {aspect: adapt_plan(plan, *dimensions(aspect, short_side), sizes, tracks,
                                 requested=requested, max_upscale=limit, cuts=cuts) for aspect in selected}
    for result in results.values():
        result.warnings.extend(w for item in evidence.values() for w in item["warnings"])
    return results, {"version": 1, "sources": evidence, "framing": requested, "max_upscale": limit}


def render_deliveries(composition, output, *, aspects=None, base_dir=None, work_dir=None,
                      framing=None, max_upscale=None, short_side=1080, ffmpeg="ffmpeg", ffprobe="ffprobe"):
    output = Path(output).expanduser().resolve()
    work = Path(work_dir).resolve() if work_dir else output.parent / (output.stem + ".delivery-work")
    plans, evidence = delivery_plans(composition, aspects, work, base_dir=base_dir, framing=framing,
                                     max_upscale=max_upscale, short_side=short_side, ffprobe=ffprobe)
    report_path = output.with_name(output.stem + ".deliveries.json")
    rows = {}
    report = {"version": 1, "status": "rendering", "deliveries": rows, "analysis": evidence}
    protected = {Path(a.path).resolve() for p in plans.values() for a in p.assets}
    protected.update(Path(c.font.path).resolve() for p in plans.values() for c in p.captions if c.font)
    protected.update(Path(c.color.lut_path).resolve() for p in plans.values() for c in p.clips if c.color)
    destinations = [report_path]
    for aspect in plans:
        stem = output.stem + "." + aspect.replace(":", "x")
        destinations.extend([output.with_name(stem + ".mp4"), output.with_name(stem + ".json")])
    if any(p.resolve() in protected or p.is_symlink() for p in destinations):
        raise EDLValidationError("delivery output must not replace an input asset or symlink")
    _write(report_path, report)
    try:
        for aspect, plan in plans.items():
            stem = output.stem + "." + aspect.replace(":", "x")
            video, saved = output.with_name(stem + ".mp4"), output.with_name(stem + ".json")
            row = rows[aspect] = {"status": "rendering", "video": str(video), "plan": str(saved),
                                  "width": plan.width, "height": plan.height}
            _write(saved, plan.to_dict())
            result = render_composition(plan, video, base_dir=saved.parent, work_dir=work / aspect.replace(":", "x"),
                                        ffmpeg=ffmpeg, ffprobe=ffprobe)
            row.update(status="ready", warnings=list(result.warnings))
            _write(report_path, report)
        report["status"] = "ready"
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        _write(report_path, report)
        raise
    _write(report_path, report)
    return {"status": report["status"], "report": str(report_path), "deliveries": rows}
