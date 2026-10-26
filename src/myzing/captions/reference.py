"""Reference caption groups and disclosed appearance/placement estimates."""

from collections import Counter
from dataclasses import replace
from statistics import median, quantiles

from myzing.composition import CaptionStyle
from myzing.layout.types import Box, EventLayout, Keyframe
from .grouping import display_boundaries, join


def word_band(widths):
    if not widths:
        return {"median": 1, "lower": 1, "upper": 1, "measured": False}
    low, _, high = quantiles(widths, n=4, method="inclusive") if len(widths) > 1 else [widths[0]] * 3
    return {"median": max(1, round(median(widths))), "lower": low, "upper": high,
            "measured": True, "basis": "median and interquartile range of caption-only word counts"}


def groups(words, target):
    """Keep timed tokens and numeric display units intact."""
    _, numeric = display_boundaries([w.text for w in words])
    units = []
    for i, word in enumerate(words):
        if i in numeric:
            units[-1].append(word)
        else:
            units.append([word])
    result, current, count = [], [], 0
    for unit in units:
        size = len(join(w.text for w in unit).split())
        if current and count + size > target:
            result.append(current)
            current, count = [], 0
        current.extend(unit)
        count += size
    if current:
        result.append(current)
    return result


def appearance(geometry):
    """Aggregate only detections belonging to caption tracks, never title ink."""
    tracks = [t for t in geometry.get("tracks", []) if t["kind"] == "caption"]
    indices = {(s["sample_index"], i) for t in tracks for s in t["samples"]
               for i in s.get("detection_indices", [])}
    frames = geometry.get("frames", [])
    samples = [frames[f]["detections"][i].get("appearance", {}) for f, i in sorted(indices)]
    result = {}
    def plausible_outline(sample):
        stroke, ink = sample.get("stroke_width_fraction"), sample.get("text_height")
        return stroke is None or ink is None or stroke <= .2 * ink
    rejected = sum(not plausible_outline(s) for s in samples)
    if rejected:
        result["outline_rejected_samples"] = rejected
        result["outline_quality_rule"] = "Stroke wider than 20% of glyph ink height may be background; excluded from appearance transfer."
    plates = [s["plate_present"] for s in samples if s.get("plate_present") is not None
              and s.get("plate_confidence", 0) >= .5]
    if plates:
        result["plate_present"] = sum(plates) > len(plates)/2
    for source, dest in (("fill", "color"), ("outline", "outline_color"), ("plate_color", "box_color")):
        values = [s[source]["rgb"] for s in samples if s.get(source) and s[source].get("confidence", 0) >= .5
                  and (source != "outline" or plausible_outline(s))
                  and (source != "plate_color" or (s.get("plate_present") is True and result.get("plate_present", True)))]
        if values:
            result[dest] = "#" + "".join(f"{round(median(v[i] for v in values)):02X}" for i in range(3))
    strokes = [s["stroke_width_fraction"] for s in samples
               if s.get("stroke_width_fraction") is not None and s.get("stroke_confidence", 0) >= .5 and plausible_outline(s)]
    if strokes:
        result["outline_fraction"] = median(strokes)
    alignments = [t["alignment"] for t in tracks if t.get("alignment_confidence", 0) >= .5
                  and t.get("alignment") in ("left", "center", "right")]
    if alignments:
        result["alignment"] = Counter(alignments).most_common(1)[0][0]
    return result


def place(plan, recipe, subjects, source_dimensions):
    """Keep reference anchors; disclose collisions without inventing a plate."""
    from myzing.layout.chooser import check_overlap
    from myzing.layout.framing import centered_framing, swept_output_box
    from myzing.layout.types import FaceTrack, box_at, union
    from myzing.layout.caption_safety import is_face
    import json
    prefix = "CAPREF evidence: "
    if recipe is not None:
        facts = {f.name: f.value for f in recipe.measured
                 if f.name.startswith("captions[") or f.name in ("caption_appearance", "caption_geometry.summary")}
        if recipe.approximations.layout:
            facts["caption_masks"] = [m.to_dict() for m in recipe.approximations.layout.masks]
        plan.warnings[:] = [w for w in plan.warnings if not w.startswith(prefix)]
        plan.warnings.append(prefix + json.dumps(facts, sort_keys=True))
    else:
        facts = next((json.loads(w[len(prefix):]) for w in plan.warnings if w.startswith(prefix)), {})
    measured = facts.get("caption_appearance", {})
    geometry = facts.get("caption_geometry.summary", {}).get("box")
    from myzing.layout.types import Mask
    masks = [Mask.from_dict(m) for m in facts.get("caption_masks", [])]
    for caption in plan.captions:
        short = min(plan.width, plan.height)
        style = CaptionStyle(max(24, short / 18), color=measured.get("color", "#FFFFFF"),
                             outline_color=measured.get("outline_color", "#000000"),
                             outline_width=min(20, measured.get("outline_fraction", 2 / plan.height) * plan.height),
                             box_color=measured.get("box_color"))
        # Word timing does not imply a yellow highlight in a white reference.
        style = replace(style, highlight=style.color)
        caption.style = CaptionStyle.from_dict({**style.to_dict(), **(plan.brief.caption_options or {})})
        if plan.brief.caption_options:
            plan.warnings.append(f"Caption {caption.id}: explicit caption_options override measured reference appearance: {', '.join(sorted(plan.brief.caption_options))}.")
        caption.alignment = measured.get("alignment", "center")
        x, y = (.5, {"top": .16, "center": .5, "lower": 2/3, "bottom": .88}[caption.position])
        if geometry:
            x, y = (geometry[0] + geometry[2])/2, (geometry[1] + geometry[3])/2
        if caption.layout:
            box = caption.layout.as_path()[0].box
        else:
            width = min(.84, 2*x, 2*(1-x))
            if geometry and caption.alignment == "left":
                x, width = geometry[0], min(.84, 1-geometry[0]-.02)
            elif geometry and caption.alignment == "right":
                width = min(.84, geometry[2]-.02)
                x = geometry[2]-width
            else:
                x -= width/2
            height = min(.16, 2*y, 2*(1-y))
            box = Box(x, y-height/2, width, height)
        obstacles = []
        for clip in plan.clips:
            start, end = max(caption.start, clip.timeline_start), min(caption.end, clip.timeline_end)
            if end <= start:
                continue
            framing = clip.framing
            if framing is None and clip.asset_id in source_dimensions:
                framing = centered_framing("fit", *source_dimensions[clip.asset_id], plan.width, plan.height)
            if framing is None:
                continue
            for track in subjects.get(clip.asset_id, []):
                if not is_face(track):
                    continue
                a, b = max(clip.source_at(start), track.keyframes[0].time), min(clip.source_at(end), track.keyframes[-1].time)
                if b <= a:
                    continue
                source = union([box_at(track.keyframes, a), box_at(track.keyframes, b),
                                *[k.box for k in track.keyframes if a < k.time < b]])
                output = swept_output_box(source, framing, [start-clip.timeline_start, end-clip.timeline_start,
                    *[k.time for k in framing.keyframes if start-clip.timeline_start < k.time < end-clip.timeline_start]], plan.width, plan.height)
                if output:
                    obstacles.append(FaceTrack(track.id, [Keyframe(start, output), Keyframe(end, output)]))
        path = caption.layout.path if caption.layout else []
        overlap = check_overlap(path or [Keyframe(caption.start, box), Keyframe(caption.end, box)], obstacles, masks)
        overlap = replace(overlap, scope="reference caption band; supplied source face tracks only; faces unmeasured when tracks absent")
        warnings = [] if overlap.safe else [f"Caption {caption.id}: reference position overlaps supplied faces/masks; retained for review without adding a plate."]
        caption.layout = EventLayout(caption.id, caption.start, caption.end, "reference-caption-band", overlap,
                                    box=None if path else box, path=path, warnings=warnings)
        if not overlap.safe:
            plan.accepted_unsafe_layouts.append(caption.id)
            plan.warnings.extend(warnings)
        missing = [k for k in ("color", "outline_color", "outline_fraction", "alignment") if k not in measured]
        if missing:
            plan.warnings.append(f"Caption {caption.id}: Estimated {', '.join(missing)}; defaults are white with black 2px outline and centered alignment. No unmeasured plate added.")
        if measured.get("outline_rejected_samples"):
            plan.warnings.append(f"Caption {caption.id}: {measured['outline_rejected_samples']} reference stroke samples excluded by glyph-relative quality check; {measured['outline_quality_rule']}")
        plan.warnings.append(f"Caption {caption.id}: Estimated font em size {style.size:g}px (short side / 18, minimum 24px); original font size is unmeasured.")
        if not geometry:
            plan.warnings.append(f"Caption {caption.id}: Estimated anchor within measured {caption.position} position category; exact position band unavailable.")
        band = word_band([value["words_visible"] for key, value in facts.items() if key.startswith("captions[")])
        count = len(caption.text.split())
        if not band["lower"] <= count <= band["upper"]:
            plan.warnings.append(f"Caption {caption.id}: {count} words outside reference band {band['lower']:g}-{band['upper']:g}; source boundary or indivisible timed token.")
