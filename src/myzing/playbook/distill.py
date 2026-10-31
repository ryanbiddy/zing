"""Deterministic contrast statistics and a strict publication allowlist."""
from __future__ import annotations

import hashlib
import math
import random
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median

from .common import SCHEMA_VERSION, library, number, read_json, safe_name, write_json
from .measure import FEATURES, Feature
from .notes import ENUMS, cached


@dataclass(frozen=True)
class Thresholds:
    min_n: int = 20
    min_delta: float = 0.33
    min_rate_diff: float = 0.15
    min_consistency: float = 0.6
    min_channel_n: int = 3
    min_channels: int = 8
    multiple_testing: str = "bonferroni"
    bootstrap_samples: int = 2000
    seed: int = 42

    def validate(self):
        if self.min_n < 1 or self.min_channel_n < 1 or self.min_channels < 1 or self.bootstrap_samples < 100:
            raise ValueError("sample thresholds must be positive; bootstrap-samples must be >= 100")
        if any(not number(v) or not 0 <= v <= 1 for v in (self.min_delta, self.min_rate_diff, self.min_consistency)):
            raise ValueError("effect and consistency thresholds must be in 0..1")
        if self.multiple_testing not in ("bonferroni", "none"):
            raise ValueError("multiple-testing must be bonferroni or none")


def cliffs_delta(worked: list[float], didnt: list[float]) -> float:
    ordered = sorted(didnt)
    return sum(bisect_left(ordered, v) - (len(ordered) - bisect_right(ordered, v)) for v in worked) / (len(worked) * len(didnt))


def percentile(values, fraction):
    position = (len(values) - 1) * fraction
    lo = int(position)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def stratified(clusters, statistic):
    """Mean within-channel effect: worked and didnt are contrasted inside each channel,
    so channel-level differences (host, length, audience) never enter the effect."""
    return mean(statistic(a, b) for a, b in clusters)


def bootstrap(clusters, statistic, samples, seed, confidence=.95):
    """Resample channel pairs intact; Shorts share a host, editor and audience."""
    rng = random.Random(seed)
    effects = [statistic(a, b) for a, b in clusters]
    tail = (1 - confidence) / 2
    means = sorted(mean(rng.choices(effects, k=len(effects))) for _ in range(resamples(samples, confidence)))
    return [percentile(means, tail), percentile(means, 1 - tail)]


def resamples(samples, confidence):
    # Bonferroni-sized tails need enough resamples to have a percentile at all.
    return max(samples, math.ceil(10 / ((1 - confidence) / 2)))


def eligible_clusters(rows, min_n):
    grouped = {}
    for row in rows:
        sides = grouped.setdefault(row["channel"], {"worked": [], "didnt": []})
        if row["value"] is not None:
            sides[row["set"]].append(row["value"])
    return {channel: (sides["worked"], sides["didnt"])
            for channel, sides in sorted(grouped.items())
            if min(len(sides["worked"]), len(sides["didnt"])) >= min_n}


def rate_difference(a, b):
    return mean(a) - mean(b)


def consistency(rows, direction, categorical, min_n):
    channels = sorted({r["channel"] for r in rows})
    eligible, excluded, aligned = [], [], []
    # Align on the same per-channel statistic the effect averages.
    statistic = rate_difference if categorical else cliffs_delta
    for channel in channels:
        a = [r["value"] for r in rows if r["channel"] == channel and r["set"] == "worked" and r["value"] is not None]
        b = [r["value"] for r in rows if r["channel"] == channel and r["set"] == "didnt" and r["value"] is not None]
        if min(len(a), len(b)) < min_n:
            excluded.append(channel)
            continue
        eligible.append(channel)
        if statistic(a, b) * direction > 0:
            aligned.append(channel)
    return {"eligible": len(eligible), "excluded": len(excluded), "aligned": len(aligned),
            "consistency": len(aligned) / len(eligible) if eligible else None,
            "eligible_channels": eligible, "excluded_channels": excluded}


def guidance(feature, sign, category):
    numeric = {
        "duration": ("shorter Shorts", "longer Shorts"),
        "avg_shot_duration": ("shorter shots", "longer shots"),
        "time_to_first_cut": ("an earlier first cut", "a later first cut"),
        "time_to_first_word": ("an earlier first spoken word", "a later first spoken word"),
        "time_to_first_caption": ("earlier captions", "later captions"),
        "speech_ratio": ("less runtime with speech", "more runtime with speech"),
        "caption_words_visible_mode": ("fewer caption words at once", "more caption words at once"),
        "caption_all_caps_share": ("less all-caps caption text", "more all-caps caption text"),
        "words_per_second_first_3s": ("fewer spoken words in the opening three seconds", "more spoken words in the opening three seconds"),
        "source_aspect": ("a narrower frame shape", "a wider frame shape"),
        "face_presence_share": ("faces in fewer text-bearing samples", "faces in more text-bearing samples"),
        "largest_face_area_share": ("smaller faces in text-bearing samples", "larger faces in text-bearing samples"),
        "speaker_count": ("fewer speakers", "more speakers"),
    }
    if feature in numeric:
        suggestion = numeric[feature][sign > 0]
    elif feature in ("music_present", "caption_presence"):
        more = (sign > 0) == category
        suggestion = ("music" if feature == "music_present" else "captions") + (" more often" if more else " less often")
    else:
        label = {
            "hook_type": f"{category} hooks",
            "first_two_seconds_visual": f"{category} visuals in the opening two seconds",
            "payoff_position": "clips without a clear payoff" if category == "none" else f"{category} payoffs",
            "caption_style": "caption-free edits" if category == "none" else f"{category} captions",
            "energy": f"{category} energy",
            "cut_feel": f"{category} cut pacing",
            "caption_position_mode": f"captions in the {category} position",
        }[feature]
        suggestion = f"{label} {'more' if sign > 0 else 'less'} often"
    return f"Test {suggestion}. This pattern separated worked from didnt Shorts; it is an association, not a causal rule."


def compare(feature, source, spec, rows, thresholds, category=None, tests_run=1):
    categorical = spec.kind == "categorical"
    if categorical:
        rows = [{**r, "value": int(r["value"] == category) if r["value"] is not None else None} for r in rows]
    clusters = eligible_clusters(rows, thresholds.min_channel_n)
    a = [v for a, _ in clusters.values() for v in a]
    b = [v for _, b in clusters.values() for v in b]
    stat = rate_difference if categorical else cliffs_delta
    effect = stratified(list(clusters.values()), stat) if clusters else None
    confidence = 1 - .05 / max(1, tests_run) if thresholds.multiple_testing == "bonferroni" else .95
    ci = bootstrap(list(clusters.values()), stat, thresholds.bootstrap_samples, thresholds.seed, confidence) if clusters else None
    sign = 1 if effect is not None and effect > 0 else -1 if effect is not None and effect < 0 else 0
    channels = consistency(rows, sign, categorical, thresholds.min_channel_n)
    result = {"feature": feature, "source": source, "kind": spec.kind, "unit": spec.unit,
              "direction": "higher" if sign > 0 else "lower" if sign < 0 else "none",
              "effect_type": "within-channel rate_difference" if categorical else "within-channel cliffs_delta",
              "effect": effect, "ci": ci, "ci_level": confidence, "ci_method": "channel-cluster percentile bootstrap",
              "bootstrap_samples_used": resamples(thresholds.bootstrap_samples, confidence) if clusters else 0,
              "test_run": bool(clusters), "n": {"worked": len(a), "didnt": len(b)}, "channels": channels}
    if categorical:
        result.update(category=category, rates={"worked": mean(a) if a else None, "didnt": mean(b) if b else None},
                      counts={"worked": sum(a), "didnt": sum(b)})
    else:
        result["medians"] = {"worked": median(a) if a else None, "didnt": median(b) if b else None}
    reasons = []
    if len(clusters) < thresholds.min_channels:
        reasons.append("too few eligible channels")
    if min(len(a), len(b)) < thresholds.min_n:
        reasons.append("insufficient n")
    cutoff = thresholds.min_rate_diff if categorical else thresholds.min_delta
    if effect is None or abs(effect) < cutoff:
        reasons.append("effect below threshold")
    # An endpoint within float noise of zero includes zero.
    if ci is None or not (ci[0] > 1e-9 or ci[1] < -1e-9):
        reasons.append("CI includes zero or unavailable")
    if channels["consistency"] is None or channels["consistency"] < thresholds.min_consistency:
        reasons.append("insufficient within-channel consistency")
    result["status"] = "no separation" if reasons else "kept"
    result["reasons"] = reasons
    if not reasons:
        result["guidance"] = guidance(feature, sign, category)
    return result


def distill(root: Path, *, version="v0", thresholds: Thresholds | None = None) -> dict:
    safe_name(version)
    thresholds = thresholds or Thresholds()
    thresholds.validate()
    data = library(root)
    entries = sorted(data["entries"], key=lambda e: e["id"])
    hashes = {"library.json": hashlib.sha256((root / "library.json").read_bytes()).hexdigest()}
    features, notes = {}, {}
    feature_path = root / "features.json"
    if feature_path.exists():
        feature_data = read_json(feature_path)
        if feature_data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported features schema")
        hashes["features.json"] = hashlib.sha256(feature_path.read_bytes()).hexdigest()
        for row in feature_data["entries"]:
            if row["id"] in features:
                raise ValueError("duplicate feature ID")
            features[row["id"]] = row if row.get("status") == "measured" else {}
    for entry in entries:
        path = root / "notes" / f"{entry['id']}.json"
        if path.exists():
            hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            record = cached(path, entry["id"])
            if record:
                notes[entry["id"]] = record["rubric"]
    estimated = {name: Feature("categorical", name, "category", choices) for name, choices in ENUMS.items()}
    estimated["speaker_count"] = Feature("numeric", "speaker_count", "speakers")
    comparisons = []
    for source, specs, values in (("measured", FEATURES, features), ("estimated", estimated, notes)):
        for name, spec in sorted(specs.items()):
            rows = []
            for entry in entries:
                value = values.get(entry["id"], {}).get(name)
                if spec.kind == "numeric":
                    value = value if number(value) else None
                else:
                    value = value if any(type(value) is type(c) and value == c for c in spec.categories) else None
                rows.append({"channel": entry["channel"], "set": entry["set"], "value": value})
            categories = (True,) if spec.unit == "boolean" else spec.categories
            for category in categories if spec.kind == "categorical" else (None,):
                comparisons.append((name, source, spec, rows, category))
    # Count every effect/interval actually computed, even if a later keep gate
    # fails. All-missing/ineligible comparisons remain visible but run no test.
    tests_run = sum(bool(eligible_clusters(rows, thresholds.min_channel_n))
                    for _, _, _, rows, _ in comparisons)
    tested = [compare(name, source, spec, rows, thresholds, category, tests_run)
              for name, source, spec, rows, category in comparisons]
    kept = sorted((p for p in tested if p["status"] == "kept"), key=lambda p: (-abs(p["effect"]), p["feature"], str(p.get("category"))))
    dropped = [p for p in tested if p["status"] != "kept"]
    counts = Counter(e["set"] for e in entries)
    result = {"schema_version": SCHEMA_VERSION, "version": version, "scope": "YouTube podcast/interview Shorts",
              "patterns": kept, "no_separation": dropped, "inputs_sha256": hashes, "thresholds": asdict(thresholds),
              "tests_run": tests_run,
              "ci_level": 1 - .05 / max(1, tests_run) if thresholds.multiple_testing == "bonferroni" else .95,
              "sample_sizes": {"worked": counts["worked"], "didnt": counts["didnt"], "channels": len({e["channel"] for e in entries}),
                               "measured": sum(bool(features.get(e["id"])) for e in entries), "estimated": len(notes)},
              "originals": [e["url"] for e in entries],
              "caveats": ["YouTube podcast Shorts only; format membership is curated, not verified by listing.",
                          "Views are a noisy proxy for attention, not a causal outcome.",
                          "Estimated means model judgment; missing measurements are excluded per feature.",
                          "Cluster bootstrap resamples channels with both sides intact: Shorts share a host, editor and audience.",
                          f"Multiple-testing correction: {thresholds.multiple_testing}; finite bootstrap tails are approximate. Confirm on a fresh cohort.",
                          "Unknown upload dates use the newest-N proxy, not verified 14-day age."]}
    write_json(root / f"playbook-{version}.json", result)
    (root / f"WHATS-WORKING-{version}.md").write_text(report(result), encoding="utf-8")
    return result


def report(data):
    sample = data["sample_sizes"]
    lines = [f"# What's working — {data['version']}", "",
             f"{sample['worked']} worked / {sample['didnt']} didnt Shorts across {sample['channels']} channels; "
             f"{sample['measured']} measured, {sample['estimated']} with blind model notes.", "",
             f"{len(data['patterns'])} patterns passed every threshold. These are ideas to test in the next edit.", ""]
    lines.extend([f"Tests actually run: {data['tests_run']}; correction: {data['thresholds']['multiple_testing']}; "
                  f"cluster CI level: {100 * data['ci_level']:.4f}%.", ""])
    for p in data["patterns"][:5]:
        lines.append(f"- {p['guidance']} {numbers(p)}")
    if not data["patterns"]:
        lines.append("No pattern cleared the evidence bar. Keep the current editing defaults.")
    lines.extend(["", "## What didn't separate", ""])
    # Compact read; the JSON preserves every category, number and rejection reason.
    for p in sorted(data["no_separation"], key=lambda p: -abs(p["effect"] or 0))[:6]:
        label = p["feature"].replace("_", " ") + (f" = {str(p['category']).lower()}" if "category" in p else "")
        lines.append(f"- {label}: {numbers(p)} {'; '.join(p['reasons'])}.")
    lines.extend(["", f"All {len(data['no_separation'])} dropped or unavailable comparisons and the full kept list are in playbook-{data['version']}.json.", ""])
    t = data["thresholds"]
    lines.append(f"Bar: n ≥ {t['min_n']} per side; |Cliff's delta| ≥ {t['min_delta']} or |rate difference| ≥ {t['min_rate_diff']}; "
                 f"adjusted cluster CI excludes zero; channel consistency ≥ {t['min_consistency']}. "
                 f"At least {t['min_channels']} eligible channels, each with {t['min_channel_n']} observations per side.")
    lines.extend(["", "## Caveats", "", " ".join(data["caveats"]), ""])
    return "\n".join(lines)


def numbers(p):
    effect = f"{p['effect']:.3f}" if p["effect"] is not None else "unavailable"
    ci = f"[{p['ci'][0]:.3f}, {p['ci'][1]:.3f}]" if p["ci"] else "unavailable"
    ch = p["channels"]
    return (f"({p['source']}; n={p['n']['worked']}/{p['n']['didnt']}; {p['effect_type']}={effect}; "
            f"{100 * p['ci_level']:.4f}% cluster CI {ci}; channels {ch['aligned']}/{ch['eligible']} agree, {ch['excluded']} excluded.)")
