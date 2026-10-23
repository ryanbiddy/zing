"""COLOR2 distribution bands. Pure stdlib; no pixel correspondence is assumed.

Faces are deliberately absent here: comparing the reference's people with the
draft's people measures who is on screen, not the grade. Skin is checked only
against the same clip's ungraded source, in `match.skin`, as its own dimension.
"""

import math


POLICY = "color2-lab-v3"
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
}
MIN_SAMPLES = 4
MIN_CONFIDENCE = .5
# Scene content: a difference that exceeds the miss limit by no more than this
# many standard errors of the two videos' own shot-to-shot variation cannot be
# attributed to the grade, so it is approximate rather than a miss.
CONTENT_Z = 2.0
SAMPLE_KEYS = ("lightness_percentiles", "ab_mean", "saturation", "contrast", "tone_ab")


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


def _deltas(a, b):
    """Component distances between two statistics dicts (also used per sample)."""
    return {"lightness": max(abs(y-x) for x, y in zip(a["lightness_percentiles"], b["lightness_percentiles"])),
            "cast": math.dist(a["ab_mean"], b["ab_mean"]),
            "saturation": max(abs(y-x) for x, y in zip(a["saturation"], b["saturation"])),
            "contrast": abs(b["contrast"]-a["contrast"]),
            "tonal_cast": max(math.dist(x, y) for x, y in zip(a["tone_ab"], b["tone_ab"]))}


def _samples(measurement):
    """Per-sample statistics from a Measurement dict or a recipe's sample list."""
    rows = [s.get("stats", s) for s in measurement.get("samples") or [] if isinstance(s, dict)]
    return [s for s in rows if _valid(s)]


def _spread(samples, pooled):
    """Sample standard deviation of each component about the pooled statistics."""
    if len(samples) < 2:
        return {name: 0.0 for name in BANDS}, len(samples)
    rows = [_deltas(pooled, s) for s in samples]
    return {name: math.sqrt(sum(r[name] ** 2 for r in rows) / (len(rows) - 1)) for name in BANDS}, len(samples)


def compare_color(reference, observed):
    """Compare independently sampled sharp-picture distributions, not LUT identity."""
    reference, observed = reference or {}, observed or {}
    a, b = reference.get("aggregate"), observed.get("aggregate")
    result = {"version": 1, "policy": POLICY, "status": "approximate", "measurement_status": "unmeasured",
              "target": a, "observed": b, "components": {},
              "picture_area": observed.get("picture_area"), "max_luma_percentile_delta": None,
              "basis": "Unpaired CIELAB D65 scene distributions using sRGB transfer. A pass covers sampled color statistics only; "
                       "different subjects and lighting require review. Not paired Delta E or original-LUT recovery. "
                       "Faces are never compared with the reference's faces; skin_preservation checks each face "
                       "against its own ungraded source instead."}
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
    deltas = _deltas(a, b)
    details = {"lightness": {"percentile_deltas": dl}, "cast": {"a_delta": da, "b_delta": db},
               "saturation": {"percentile_deltas": dc}, "contrast": {"signed_delta": contrast},
               "tonal_cast": {"quartile_distances": tonal}}
    spread_a, n_a = _spread(_samples(reference), a)
    spread_b, n_b = _spread(_samples(observed), b)
    allowance = {name: CONTENT_Z * math.sqrt((spread_a[name] ** 2 / n_a if n_a > 1 else 0.0)
                                             + (spread_b[name] ** 2 / n_b if n_b > 1 else 0.0)) for name in BANDS}
    content_limited = []
    for name, delta in deltas.items():
        status = _status(delta, name)
        if status == "miss" and delta - allowance[name] <= BANDS[name][1]:
            # The videos' own shots differ this much: scene content, not the
            # grade, can explain it. Never a pass; the raw delta decides that.
            status = "approximate"
            content_limited.append(name)
        result["components"][name] = {"delta": delta, "pass_max": BANDS[name][0], "miss_above": BANDS[name][1],
                                      "status": status, "scene_variation_allowance": allowance[name],
                                      "content_limited": name in content_limited, **details[name]}
    result["scene_variation"] = {
        "z": CONTENT_Z, "reference_samples": n_a, "observed_samples": n_b,
        "reference_spread": spread_a, "observed_spread": spread_b, "allowance": allowance,
        "basis": "Shot-to-shot standard deviation of each component inside each video, as a standard error of the "
                 "pooled difference. A miss needs the difference to exceed the miss limit by more than this "
                 "allowance; the allowance never widens a pass."}
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
    result["reason"] = "; ".join(words) + "."
    if content_limited:
        names = ", ".join(n.replace("_", " ") for n in content_limited)
        result["reason"] += (f" Scene content differs: {names} exceed the miss limit by less than the shot-to-shot "
                             "variation inside the reference and the draft, so they stay approximate. Different "
                             "footage, not the grade, can explain them; compare the crops before regrading.")
    if not quality:
        result["reason"] += " Sparse, incomplete or low-confidence sampling cannot establish a pass."
    return result


def sample_stats(measurement):
    """The per-sample statistics compare_color needs, from a color Measurement."""
    return [{"timestamp": s.timestamp, **{k: getattr(s.stats, k) for k in SAMPLE_KEYS}} for s in measurement.samples]


def from_recipe(recipe, observed):
    facts = {f.name: f for f in recipe.measured if f.name.startswith("color.")}
    main = facts.get("color.lightness_percentiles")
    samples = facts.pop("color.sample_stats", None)
    reference = {"aggregate": {key[6:]: fact.value for key, fact in facts.items()},
                 "coverage": main.coverage.details if main else {}, "confidence": (main.confidence or 0) if main else 0,
                 "samples": samples.value if samples else []}
    return compare_color(reference, observed)
