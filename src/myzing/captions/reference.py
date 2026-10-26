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


def groups(words, band):
    """Partition one clause within the reference band, avoiding short tails."""
    from .presets import normalize_words
    words = normalize_words(words)
    if not isinstance(band, dict):
        band = {"median": band, "lower": min(2, band), "upper": band}
    target, low, high = band["median"], band["lower"], band["upper"]
    _, numeric = display_boundaries([w.text for w in words])
    units = []
    for i, word in enumerate(words):
        if i in numeric:
            units[-1].append(word)
        else:
            units.append([word])
    sizes = [len(join(w.text for w in unit).split()) for unit in units]
    if low <= sum(sizes) <= high:
        return [words] if words else []
    # A feasible in-band partition always beats one with an orphan. When an
    # exact band cannot tile the clause, minimize the disclosed deviation.
    n = len(units)
    costs, paths = [None] * n + [(0, 0, 0)], [None] * (n+1)
    for i in range(n-1, -1, -1):
        count = 0
        for j in range(i+1, n+1):
            count += sizes[j-1]
            if count > max(high, sizes[i]) and j > i+1:
                break
            deviation = max(low-count, 0, count-high)
            tail = costs[j]
            cost = (tail[0] + deviation, tail[1] + (count == 1 and low > 1),
                    tail[2] + (count-target)**2 + 1)
            if costs[i] is None or cost <= costs[i]:
                costs[i], paths[i] = cost, j
    result, i = [], 0
    while i < n:
        j = paths[i]
        result.append([w for unit in units[i:j] for w in unit])
        i = j
    return result


def appearance(geometry):
    """Aggregate only detections belonging to caption tracks, never title ink."""
    tracks = [t for t in geometry.get("tracks", []) if t["kind"] == "caption"]
    indices = {(s["sample_index"], i) for t in tracks for s in t["samples"]
               for i in s.get("detection_indices", [])}
    frames = geometry.get("frames", [])
    samples = []
    for f, i in sorted(indices):
        detection = frames[f]["detections"][i]
        sample = dict(detection.get("appearance", {}))
        ink = dict(sample.get("ink_evidence", {}))
        # v2 cached segmentation records stroke / OCR-proposal height. Recover
        # the exact pixel denominator without decoding or rerunning OCR.
        if ("stroke_to_ink_height" not in ink and ink.get("stroke_fraction")
                and sample.get("text_height") and detection.get("polygon") and frames[f].get("height")):
            from math import ceil, floor
            height = frames[f]["height"]
            ys = [p[1] * height for p in detection["polygon"]]
            proposal_height = ceil(max(ys)) - floor(min(ys))
            ink["stroke_to_ink_height"] = ink["stroke_fraction"] * proposal_height / (sample["text_height"] * height)
        sample["ink_evidence"] = ink
        samples.append(sample)
    result = {}
    heights = [s["text_height"] for s in samples if (s.get("text_height") or 0) > 0
               and s.get("geometry_confidence", 0) >= .5]
    if heights:
        result["text_height"] = median(heights)
    weights = [s["ink_evidence"]["stroke_to_ink_height"] for s in samples
               if s.get("geometry_confidence", 0) >= .5
               and s.get("ink_evidence", {}).get("component_count", 0) >= 3
               and 0 < s.get("ink_evidence", {}).get("stroke_to_ink_height", 0) <= .2]
    if weights:
        result["ink_stroke_ratio"] = median(weights)
        result["weight"] = 700 if result["ink_stroke_ratio"] >= .10 else 400
        result["weight_basis"] = (f"Measured fill stroke / ink height {result['ink_stroke_ratio']:.4f}; "
                                  f"weight {result['weight']} selected (regular below 0.10, bold otherwise; heuristic face selection).")
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
    from myzing.captions.metrics import DATA, font_asset, metrics
    from myzing.composition import FontAsset
    from hashlib import sha256
    masks = [Mask.from_dict(m) for m in facts.get("caption_masks", [])]
    weight = measured.get("weight", 700)
    face = font_asset("clean")
    if weight == 400:
        path = DATA / "IBMPlexSans.ttf"
        face = FontAsset(str(path), sha256(path.read_bytes()).hexdigest(), "OFL-1.1")
    font_metrics = metrics(face.path, face.sha256)
    face_name = "IBM Plex Sans Regular" if weight == 400 else "ZingCaption Bold (Inter derivative)"
    disclosure = (f"CAPREF typography: {measured.get('weight_basis', 'Estimated weight 700 bold: short-form default; reference weight unmeasured.')} "
                  f"{face_name}, OFL-1.1; face is a substitute, not a font match. "
                  "Estimated shadow treatment: shadow unmeasured; use an outline at least 6% of fill-ink height for legibility instead of a shadow (black unless outline color is measured).")
    plan.warnings[:] = [w for w in plan.warnings if not w.startswith("CAPREF typography:")]
    plan.warnings.append(disclosure)
    for caption in plan.captions:
        caption.font = replace(face)
        ink_fraction = measured.get("text_height") or (geometry[3]-geometry[1] if geometry else None)
        ink_height = ink_fraction * plan.height if ink_fraction else .03 * plan.height
        ink_em = font_metrics.ink_height(caption.text.upper() if caption.all_caps else caption.text, 1)
        size = min(512, max(24, ink_height / ink_em))
        outline = max(ink_height * .06, measured.get("outline_fraction", 0) * plan.height)
        style = CaptionStyle(size, color=measured.get("color", "#FFFFFF"),
                             outline_color=measured.get("outline_color", "#000000"),
                             outline_width=min(20, .2 * ink_height, outline),
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
            plan.warnings.append(f"Caption {caption.id}: Estimated {', '.join(missing)}; defaults are white with black legibility outline and centered alignment. No unmeasured plate added.")
        if measured.get("outline_rejected_samples"):
            plan.warnings.append(f"Caption {caption.id}: {measured['outline_rejected_samples']} reference stroke samples excluded by glyph-relative quality check; {measured['outline_quality_rule']}")
        basis = "Measured median text_height" if measured.get("text_height") else "Measured caption box height" if geometry else "Estimated 3% frame height"
        plan.warnings.append(f"Caption {caption.id}: {basis} targets {ink_height:.2f}px fill ink; Estimated substitute em {caption.style.size:.2f}px from pinned glyph bounds (24-512px limits); original font size is unmeasured.")
        if not geometry:
            plan.warnings.append(f"Caption {caption.id}: Estimated anchor within measured {caption.position} position category; exact position band unavailable.")
        band = word_band([value["words_visible"] for key, value in facts.items() if key.startswith("captions[")])
        count = len(caption.text.split())
        if count == 1:
            plan.warnings.append(f"Caption {caption.id}: single-word caption retained; source clause/clip boundary or indivisible token can prevent in-band grouping.")
        if not band["lower"] <= count <= band["upper"]:
            plan.warnings.append(f"Caption {caption.id}: {count} words outside reference band {band['lower']:g}-{band['upper']:g}; source boundary or indivisible timed token.")
