"""OpenScreen dwell port + Screenize scene chaining, adapted for offline video.

Upstream revisions, copyright and changes: docs/SCREEN-DEMO.md and
docs/licenses/screen-*.txt. No upstream runtime is needed.
"""

from __future__ import annotations

import math

from .models import ScreenPlan, Zoom


def dwell_candidates(events):
    """Port of detectZoomDwellCandidates (OpenScreen, MIT).

    Keep 450-2600ms, 0.02 movement, strength ranking, 1800ms spacing.
    Adaptation: a missing >100ms sample also ends a run, avoiding fake dwells.
    """
    samples = sorted((e for e in events if e["type"] == "cursor"), key=lambda e: e["t"])
    runs, current = [], []
    for sample in samples:
        if current and (sample["t"]-current[-1]["t"] > .1 or
                        math.hypot(sample["x"]-current[-1]["x"], sample["y"]-current[-1]["y"]) > .02):
            runs.append(current)
            current = []
        current.append(sample)
    runs.append(current)
    candidates = []
    for run in runs:
        if len(run) < 2:
            continue
        duration = run[-1]["t"]-run[0]["t"]
        if .45-1e-6 <= duration <= 2.6+1e-6:
            candidates.append({"kind": "dwell", "t": (run[0]["t"]+run[-1]["t"])/2,
                               "x": sum(e["x"] for e in run)/len(run), "y": sum(e["y"] for e in run)/len(run),
                               "duration": duration, "confidence": .75})
    accepted = []
    for candidate in sorted(candidates, key=lambda c: (-c["duration"], c["t"])):
        if all(abs(candidate["t"]-c["t"]) >= 1.8 for c in accepted):
            accepted.append(candidate)
    return sorted(accepted, key=lambda c: c["t"])


def zoom_candidates(events, activity, idle, duration):
    candidates = dwell_candidates(events) if events else list(activity)
    candidates += [{"kind": "click", "t": e["t"], "x": e["x"], "y": e["y"], "confidence": .95}
                   for e in events if e["type"] == "click"]
    scenes = []
    for c in sorted(candidates, key=lambda e: e["t"]):
        if not 0 <= c["t"] < duration or any(s["start"] <= c["t"] <= s["end"] for s in idle):
            continue
        a, b = max(0, c["t"]-.8), min(duration, c["t"]+1.2)
        # Do not initiate/hold a zoom across a detected idle interval.
        for span in idle:
            if span["end"] <= c["t"]:
                a = max(a, span["end"])
            elif span["start"] >= c["t"]:
                b = min(b, span["start"])
        if b-a < .3:
            continue
        scene = Zoom(a, b, c["x"], c["y"], [c], c["confidence"])
        # Screenize mergeScenes: <0.05 distance AND <0.5s gap.
        if scenes and math.hypot(scene.x-scenes[-1].x, scene.y-scenes[-1].y) < .05 and a-scenes[-1].end < .5:
            prev = scenes[-1]
            prev.end = max(prev.end, b)
            prev.evidence.extend(scene.evidence)
            prev.confidence = max(prev.confidence, scene.confidence)
        else:
            if scenes and scenes[-1].end > a:
                boundary = max(scenes[-1].start+.1, (scenes[-1].evidence[-1]["t"]+c["t"])/2)
                scenes[-1].end = min(scenes[-1].end, boundary)
                scene.start = scenes[-1].end
            scenes.append(scene)
    # Very fast switches cannot support both a 150ms transition and 100ms
    # hold. Keep their clicks in the plan, but omit those camera suggestions.
    return [s for s in scenes if s.end-s.start >= .25 and s.start <= s.evidence[-1]["t"]]


def protected_idle(spans, events, words, duration):
    """Keep reading handles, and exclude any input or known speech from speedup."""
    protected = [(e["t"]-.6, e["t"]+.8) for e in events if e["type"] in {"click", "key", "activity"}]
    protected += [(w["start"]-.3, w["end"]+.3) for w in words]
    result = []
    for span in spans:
        pieces = [(max(0, span["start"])+.6, min(duration, span["end"])-.6)]
        for x, y in protected:
            new = []
            for a, b in pieces:
                if y <= a or x >= b:
                    new.append((a, b))
                else:
                    new.extend(((a, min(x, b)), (max(y, a), b)))
            pieces = new
        for a, b in pieces:
            if b-a >= .8:
                result.append({"start": a, "end": b, "evidence": "freezedetect"})
    return sorted(result, key=lambda s: s["start"])


def time_segments(plan):
    """Continuous source/output map. Compression never drops active frames."""
    segments, source, output = [], 0., 0.
    for idle in [*plan.idle, {"start": plan.duration, "end": plan.duration}]:
        for a, b, speed in ((source, idle["start"], 1), (idle["start"], idle["end"], plan.idle_speed)):
            if b > a:
                length = (b-a)/speed
                segments.append({"start": a, "end": b, "speed": speed, "out_start": output, "out_end": output+length})
                output += length
        source = idle["end"]
    return segments


def output_time(segments, source):
    for s in segments:
        if source <= s["end"]:
            return s["out_start"]+(source-s["start"])/s["speed"]
    return segments[-1]["out_end"]


def dimensions(aspect, short_side=720):
    if aspect not in {"16:9", "1:1", "9:16"}:
        raise ValueError("Screen delivery aspect: choose 16:9, 1:1 or 9:16.")
    if type(short_side) is not int or short_side < 144 or short_side > 2160 or short_side % 18:
        raise ValueError("--short-side must be a multiple of 18 between 144 and 2160.")
    a, b = map(int, aspect.split(":"))
    return round(short_side*a/min(a,b)), round(short_side*b/min(a,b))


def camera(plan, width, height):
    """Fit whole UI regions; cut on actions when a pan would be empty or slow."""
    from .framing import element_camera
    return element_camera(plan, width, height)


def crop_window(plan, cam, key):
    return tuple(key["window"])
