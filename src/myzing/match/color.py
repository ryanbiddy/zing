"""COLOR2 distribution bands. Pure stdlib; no pixel correspondence is assumed."""

import math


POLICY = "color2-lab-v2"
# Calibrated on tools.eval.color2_fixture (RGB chart and encoded FFmpeg 6/8):
# +5% brightness: L<=3.7, C<=2.9; equal-luma blue/green: cast>=16;
# 65% desaturation: C>=42; 1.4x contrast: L>=15, contrast>=16;
# full teal-orange: C>=11, tonal cast>=8. See docs/color.md.
# Inner bands allow codec/sampling error. Outer bands identify conspicuous
# differences; the gap is deliberately approximate, never rounded to pass.
# These are editorial distribution limits, NOT perceptual Delta E thresholds.
BANDS = {
    "lightness": (4.0, 10.0),       # largest L* percentile difference
    "cast": (3.0, 8.0),             # distance between mean a*, b*
    "saturation": (4.0, 10.0),      # largest chroma percentile difference
    "contrast": (5.0, 12.0),        # difference in L* p95-p5
    "tonal_cast": (4.0, 8.0),       # largest a*, b* distance by L* quartile
    "skin_cast": (2.0, 5.0),        # face interiors: tighter than scene cast
}
MIN_SAMPLES = 4
MIN_CONFIDENCE = .5


def _status(delta, name):
    inner, outer = BANDS[name]
    return "pass" if delta <= inner else "miss" if delta > outer else "approximate"


def _valid(stats):
    """Legacy luma-only and malformed/nonfinite statistics cannot certify color."""
    if not isinstance(stats, dict):
        return False
    shapes = {"lightness_percentiles": 7, "ab_mean": 2, "saturation": 5, "tone_ab": 4}
    try:
        for name, size in shapes.items():
            values = stats[name]
            if len(values) != size:
                return False
            if name == "tone_ab":
                if any(len(row) != 2 for row in values):
                    return False
                values = [v for row in values for v in row]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                return False
        return math.isfinite(stats["contrast"])
    except (KeyError, TypeError, ValueError):
        return False


def _quality(measurement):
    coverage = measurement.get("coverage") or {}
    return (coverage.get("usable_samples", 0) >= MIN_SAMPLES
            and coverage.get("sample_fraction", 0) == 1
            and (not coverage.get("shots_supplied") or coverage.get("shot_fraction") == 1)
            and measurement.get("confidence", 0) >= MIN_CONFIDENCE)


def compare_color(reference, observed):
    """Compare independently sampled sharp-picture distributions, not LUT identity."""
    reference, observed = reference or {}, observed or {}
    a, b = reference.get("aggregate"), observed.get("aggregate")
    result = {"version": 1, "policy": POLICY, "status": "approximate", "measurement_status": "unmeasured",
              "target": a, "observed": b, "components": {},
              "picture_area": observed.get("picture_area"), "max_luma_percentile_delta": None,
              "skin": {"status": "unmeasured", "reason": "Comparable face interiors unavailable; skin protection unmeasured."},
              "basis": "Unpaired CIELAB D65 scene distributions using sRGB transfer. A pass covers sampled color statistics only; "
                       "different subjects and lighting require review. Not paired Delta E or original-LUT recovery."}
    if observed.get("status") == "unmeasured":
        result["reason"] = "No sample had a usable sharp picture area; color is unmeasured."
        return result
    if not _valid(a) or not _valid(b):
        result["reason"] = "Complete CIELAB measurements unavailable; color is unmeasured. Re-measure legacy luma-only reports."
        return result
    result["measurement_status"] = "measured"
    if a.get("luma_percentiles") and b.get("luma_percentiles"):
        result["max_luma_percentile_delta"] = max(abs(x-y) for x, y in zip(a["luma_percentiles"], b["luma_percentiles"]))
    da, db = [y-x for x, y in zip(a["ab_mean"], b["ab_mean"])]
    dl = [y-x for x, y in zip(a["lightness_percentiles"], b["lightness_percentiles"])]
    dc = [y-x for x, y in zip(a["saturation"], b["saturation"])]
    contrast = b["contrast"]-a["contrast"]
    tonal = [math.dist(x, y) for x, y in zip(a["tone_ab"], b["tone_ab"])]
    deltas = {"lightness": max(map(abs, dl)), "cast": math.hypot(da, db),
              "saturation": max(map(abs, dc)), "contrast": abs(contrast), "tonal_cast": max(tonal)}
    details = {"lightness": {"percentile_deltas": dl}, "cast": {"a_delta": da, "b_delta": db},
               "saturation": {"percentile_deltas": dc}, "contrast": {"signed_delta": contrast},
               "tonal_cast": {"quartile_distances": tonal}}
    for name, delta in deltas.items():
        result["components"][name] = {"delta": delta, "pass_max": BANDS[name][0], "miss_above": BANDS[name][1],
                                      "status": _status(delta, name), **details[name]}
    sa, sb = reference.get("skin") or {}, observed.get("skin") or {}
    if sa.get("ab_mean") and sb.get("ab_mean"):
        # Compare each face with the nearest reference face color, not the
        # reference average: a varied set of identical faces must still pass.
        # Also retain the mean shift so changing proportions remain visible.
        faces = sb.get("face_ab", [sb["ab_mean"]])
        targets = sa.get("face_ab", [sa["ab_mean"]])
        skin_delta = max(math.dist(sa["ab_mean"], sb["ab_mean"]),
                         max(min(math.dist(target, face) for target in targets) for face in faces))
        skin = {"delta": skin_delta, "pass_max": BANDS["skin_cast"][0], "miss_above": BANDS["skin_cast"][1],
                "status": _status(skin_delta, "skin_cast"), "a_delta": sb["ab_mean"][0]-sa["ab_mean"][0],
                "b_delta": sb["ab_mean"][1]-sa["ab_mean"][1], "reference": sa, "observed": sb,
                "reason": "Face-interior color proxy; different people, lighting, hair and makeup can differ. No skin identity inference."}
        result["skin"] = skin
        result["components"]["skin_cast"] = {k: v for k, v in skin.items() if k not in ("reference", "observed")}
    components = result["components"]
    statuses = [v["status"] for v in components.values()]
    result["status"] = "miss" if "miss" in statuses else "approximate" if "approximate" in statuses else "pass"
    quality = _quality(reference) and _quality(observed)
    result["coverage_sufficient_for_pass"] = quality
    if not quality and result["status"] == "pass":
        result["status"] = "approximate"
    words = [f"Lightness differs by at most {deltas['lightness']:.1f} L*",
             f"{'greener' if da < 0 else 'redder'} than the reference by about {abs(da):.1f} a*",
             f"{'bluer' if db < 0 else 'yellower'} by about {abs(db):.1f} b*",
             ("saturation within range" if components["saturation"]["status"] == "pass" else
              f"saturation differs by up to {deltas['saturation']:.1f} chroma units"),
             f"contrast {'lower' if contrast < 0 else 'higher'} by {abs(contrast):.1f} L*",
             f"tonal color shift up to {max(tonal):.1f} a*/b* units"]
    if "skin_cast" in components:
        words.append(f"face-interior cast differs by up to {skin_delta:.1f} a*/b* units ({result['skin']['status']})")
    result["reason"] = "; ".join(words) + "."
    if not quality:
        result["reason"] += " Sparse, incomplete or low-confidence sampling cannot establish a pass."
    return result


def from_recipe(recipe, observed):
    facts = {f.name: f for f in recipe.measured if f.name.startswith("color.")}
    main = facts.get("color.lightness_percentiles")
    reference = {"aggregate": {key[6:]: fact.value for key, fact in facts.items()},
                 "coverage": main.coverage.details if main else {}, "confidence": (main.confidence or 0) if main else 0,
                 "skin": facts["color.skin"].value if "color.skin" in facts else None}
    return compare_color(reference, observed)
