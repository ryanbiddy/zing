"""Timing comparisons with separate plan, detector and footage evidence."""

from statistics import median

from myzing.style_ranges import timing_band, timing_distance


STATUS_LABELS = {"not_applicable": "not applicable for this footage",
                 "detector_disagreement": "detector disagreement"}


def status_label(status):
    return STATUS_LABELS.get(status, status.replace("_", " "))


def timing_metric(target, observed, durations, *, unmeasured=False):
    band = timing_band(target, durations)
    status = "approximate"
    if target is not None and observed is not None and not unmeasured:
        status = "pass" if band["lower"] - 1e-9 <= observed <= band["upper"] + 1e-9 else "miss"
    return {"status": status, "target": target, "observed": observed,
            "tolerance": band["tolerance"], "band": band, "basis": band["basis"],
            "reason": ("Shot detection unavailable; timing match unmeasured." if unmeasured
                       else timing_distance(observed, band))}


def _protected_spans(plan, planning):
    """Map whole clauses into output time, including speed maps and framing splits."""
    spans = []
    for clause in planning.get("continuity", {}).get("clauses", []):
        if not clause.get("selected_whole") or not clause.get("complete"):
            continue
        pieces = []
        for clip in plan.clips:
            if clip.asset_id != clause["asset_id"]:
                continue
            segments = [(s.src_in, s.src_out, s.rate) for s in clip.speed_map] or [(clip.src_in, clip.src_out, 1)]
            cursor = clip.timeline_start
            for start, end, rate in segments:
                low, high = max(start, clause["start"]), min(end, clause["end"])
                if low < high:
                    pieces.append((cursor + (low - start) / rate, cursor + (high - start) / rate))
                cursor += (end - start) / rate
        merged = []
        for low, high in sorted(pieces):
            if merged and low <= merged[-1][1] + 1e-6:
                merged[-1] = (merged[-1][0], max(high, merged[-1][1]))
            else:
                merged.append((low, high))
        spans.extend(merged)
    return spans


def timing_dimensions(durations, rendered, source_pacing, planning, plan, unmeasured):
    target = median(durations) if durations else None
    first_target = durations[0] if len(durations) > 1 else None
    pixel_durations = [s.duration for s in rendered.shots]
    mapped_durations = source_pacing.get("shot_durations_seconds", [])
    pixel_cuts = [s.start for s in rendered.shots[1:]]
    mapped_cuts = source_pacing.get("cut_positions_seconds")
    if mapped_cuts is None:
        mapped_cuts = [sum(mapped_durations[:i]) for i in range(1, len(mapped_durations))]
    # This is detector agreement precision, never the style tolerance.
    precision = 2 / (rendered.meta.fps or 30) + .001
    missing = [t for t in mapped_cuts if not any(abs(t - p) <= precision for p in pixel_cuts)]
    extra = [t for t in pixel_cuts if not any(abs(t - p) <= precision for p in mapped_cuts)]
    dimensions = {}
    for name, reference, pixel, mapped in (
        ("shot_pace", target, median(pixel_durations) if pixel_durations else None,
         median(mapped_durations) if mapped_durations else None),
        ("first_cut", first_target, pixel_cuts[0] if pixel_cuts else None,
         mapped_cuts[0] if mapped_cuts else None),
    ):
        measured = timing_metric(reference, pixel, durations, unmeasured=unmeasured)
        if name == "first_cut" and durations and pixel_durations and not unmeasured and (len(durations) == 1 or not pixel_cuts):
            measured.update(status="pass" if len(durations) == 1 and not pixel_cuts else "miss",
                            reason="Both videos are continuous." if len(durations) == 1 and not pixel_cuts
                            else "One video has cuts and the other is continuous.")
        result = dict(measured)
        if mapped_durations:
            planned = timing_metric(reference, mapped, durations)
            if name == "first_cut" and durations and (len(durations) == 1 or not mapped_cuts):
                continuous = len(durations) == 1 and not mapped_cuts
                planned.update(status="pass" if continuous else "miss",
                               reason="Reference and source-mapped plan are both continuous." if continuous
                               else "The reference and source-mapped plan differ in cut presence.")
            result.update(source_mapped=planned, rendered_pixels=measured, planned=mapped,
                          observed=pixel, reason=f"Plan: {planned['reason']} Rendered: {measured['reason']}")
            # A plan difference remains a difference even if a detector hides it.
            result["status"] = "miss" if planned["status"] == "miss" else measured["status"]
            disagree = ((pixel is None) != (mapped is None) or
                        (pixel is not None and mapped is not None and abs(pixel - mapped) > precision))
            if name == "shot_pace":
                disagree |= bool(missing or extra)
                result["cut_agreement"] = {"mapped_not_detected_seconds": missing,
                                           "detected_not_mapped_seconds": extra,
                                           "precision_seconds": precision}
            if planned["status"] == "pass" and not unmeasured and disagree:
                def number(n):
                    return "no cut" if n is None else f"{n:.3f} s"
                result.update(status="detector_disagreement", reason=
                    f"Detector disagreement: source-mapped plan {number(mapped)}; rendered detector {number(pixel)}. "
                    + planned["reason"] + " Cut events disagree; inspect the edit before judging a style miss.")
        dimensions[name] = result
        selection = planning.get("match", {}).get(
            "first_cut_seconds" if name == "first_cut" else "median_shot_seconds", {}).get("selection")
        if selection:
            result["selection"] = selection
            if result["status"] == "miss":
                result["reason"] += " " + selection["reason"]

    protected = _protected_spans(plan, planning)
    first = dimensions["first_cut"]
    band = first["band"]
    # A selected clause is evidence of a local constraint, not proof that
    # every opening available in the clip pool is impossible.
    if (first["status"] == "miss" and mapped_cuts and band["upper"] is not None
            and mapped_cuts[0] > band["upper"]
            and any(low <= band["lower"] and high >= band["upper"] for low, high in protected)):
        first.update(status="not_applicable", reason=
            f"Not applicable for this footage: the selected opening contains continuous speech across the "
            f"{band['lower']:.3f}-{band['upper']:.3f} s reference band. The first natural source cut is "
            f"{mapped_cuts[0]:.3f} s; an earlier edit would split a protected clause. A different opening may be possible.")
    pace = dimensions["shot_pace"]
    upper = pace["band"]["upper"]
    if pace["status"] == "miss" and upper is not None and mapped_durations:
        boundaries = [0, *mapped_cuts, sum(mapped_durations)]
        constrained = sum(any(min(b, high) - max(a, low) > upper for low, high in protected)
                          for a, b in zip(boundaries, boundaries[1:]))
        if constrained > len(mapped_durations) / 2:
            pace.update(status="not_applicable", reason=
                f"Not applicable for this footage: {constrained} of {len(mapped_durations)} selected shots "
                f"contain uninterrupted protected speech longer than the {upper:.3f} s upper reference bound. "
                "Matching this montage pace would split clauses; choose different footage or openings.")
    for result in dimensions.values():
        if result["status"] == "not_applicable" and result.get("selection"):
            result["reason"] += " " + result["selection"]["reason"]
    return dimensions


def dimension_notes(dimensions):
    """Shared plain-language disclosure for comparison and Studio finish screens."""
    return [f"{name.replace('_', ' ')}: {status_label(value['status'])}. {value.get('reason', '')}"
            for name, value in dimensions.items()
            if value.get("status") in ("not_applicable", "detector_disagreement", "miss")]
