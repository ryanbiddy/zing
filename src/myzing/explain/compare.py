"""Compare measurements with explicit tolerances; missing evidence stays unknown."""

from myzing.match.evidence import _metric


def compare_cards(reference, other):
    a, b = reference.sections, other.sections
    def metric(x, y, tolerance, basis):
        # Same primitive and numeric envelope as the match report.
        result = _metric(x, y, tolerance, basis)
        result["status"] = "unknown" if x is None or y is None else "differs" if result["status"] == "miss" else "close"
        return result
    def get(sections, section, *keys):
        value = sections[section].facts
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value
    def pair(section, keys, tolerance, basis):
        return metric(get(a, section, *keys), get(b, section, *keys), tolerance, basis)
    pace = get(a, "pacing", "shot_seconds", "median")
    metrics = {
        "pacing": {"median_shot_seconds": pair("pacing", ["shot_seconds", "median"], (pace or 0)*.1, "Match report: median shot seconds; 10% envelope.")},
        "framing": {"aspect": pair("framing", ["aspect"], .02, "Absolute display aspect difference; 0.02 envelope."),
                    "face_height_percent": pair("framing", ["face_height_percent"], 5, "Median sampled face height; 5 percentage points.")},
        "audio": {"speech_share": pair("audio", ["speech_share"], .1, "VAD speech share; 10 percentage points."),
                  "bpm": pair("audio", ["tempo", "bpm"], 5, "Supported global tempo; 5 BPM."),
                  "lufs": pair("audio", ["loudness", "integrated_lufs"], 3, "Integrated mix level; 3 LU.")},
    }
    ca, cb = get(a, "color", "luma_percentiles"), get(b, "color", "luma_percentiles")
    delta = max(abs(x-y) for x, y in zip(ca, cb)) if ca and cb else None
    metrics["color"] = {"luma": {**metric(0, delta, .15, "Match report: max encoded luma percentile delta; unrelated scenes, not pixel error."), "target": ca, "observed": cb, "max_delta": delta}}
    ga, gb = get(a, "captions", "caption_geometry_summary"), get(b, "captions", "caption_geometry_summary")
    iou = None
    if ga and gb:
        x, y = ga["box"], gb["box"]
        intersection = max(0, min(x[2], y[2])-max(x[0], y[0]))*max(0, min(x[3], y[3])-max(x[1], y[1]))
        union = (x[2]-x[0])*(x[3]-x[1])+(y[2]-y[0])*(y[3]-y[1])-intersection
        iou = intersection/union if union else 0
    metrics["captions"] = {"placement": {**metric(1, iou, .2, "Match report: median sampled caption box IoU >= 0.8; sparse geometry proxy."), "target_box": ga, "observed_box": gb}}
    ta, tb = get(a, "transitions", "events"), get(b, "transitions", "events")
    types = sorted({e["signature"] for e in (ta or [])+(tb or [])})
    # Rates, not raw counts: a 6 s draft can never hold a 20 s reference's count.
    # One event in the shorter clip is the smallest difference a rate can show.
    da, db = reference.duration_seconds, other.duration_seconds
    metrics["transitions"] = {}
    if ta is not None and tb is not None and da > 0 and db > 0:
        for kind in types:
            ra = sum(e["signature"] == kind for e in ta) * 60 / da
            rb = sum(e["signature"] == kind for e in tb) * 60 / db
            metrics["transitions"][kind] = {**metric(ra, rb, max(.25 * ra, 60 / min(da, db)),
                                                     "Detected signatures per minute; tolerance is 25% of the reference rate "
                                                     "or one event in the shorter clip. No claim of identical timing or effects."),
                                            "unit": "per minute"}
    result = {}
    for section, values in metrics.items():
        if section == "pacing" and any(c.sections["pacing"].facts.get("v6_additional_cut_times") for c in (reference, other)):
            for m in values.values():
                m.update(status="unknown", reason="Shot and transition detectors disagree; inspect the reported boundaries.")
        states = [m["status"] for m in values.values()]
        result[section] = {"status": "differs" if "differs" in states else "unknown" if not states or "unknown" in states else "close",
                           "metrics": values, "scope": "Only the listed measurements; unknown properties remain unknown."}
        if section == "transitions" and not states and ta is not None and tb is not None and not types and da > 0 and db > 0:
            result[section].update(status="close", reason="no transition signatures detected in either video.")
        elif not states:
            result[section]["reason"] = "a required measurement is missing."
    return {"against": other.source, "against_sha256": other.source_sha256, "sections": result}
