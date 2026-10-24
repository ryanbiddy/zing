"""OpenScreen dwell port + Screenize scene chaining, adapted for offline video.

Upstream revisions, copyright and changes: docs/SCREEN-DEMO.md and
docs/licenses/screen-*.txt. No upstream runtime is needed.
"""

from __future__ import annotations

import math

from .models import ScreenPlan, Zoom


def dwell_candidates(events):
    """OpenScreen's 450ms dwell adapted to attention, including long holds.

    A run stays within 1.2% of the frame and travels at most 2.5%/second
    over its window. A per-sample threshold alone mistakes slow pans for rests.
    Keep every stable run: duration ranking/1.8s spacing loses valid attention.
    """
    samples = sorted((e for e in events if e["type"] == "cursor"), key=lambda e: e["t"])
    runs, current, distance = [], [], 0.
    for sample in samples:
        if current:
            step = math.hypot(sample["x"]-current[-1]["x"], sample["y"]-current[-1]["y"])
            elapsed = sample["t"]-current[0]["t"]
            excursion = math.hypot(sample["x"]-current[0]["x"], sample["y"]-current[0]["y"])
            if (sample["t"]-current[-1]["t"] > .1 or excursion > .012 or
                    elapsed >= .15 and (distance+step)/elapsed > .025):
                runs.append(current)
                current, distance = [], 0.
            else:
                distance += step
        current.append(sample)
    runs.append(current)
    candidates = []
    for run in runs:
        if len(run) < 2:
            continue
        duration = run[-1]["t"]-run[0]["t"]
        if duration >= .45-1e-6:
            candidates.append({"kind": "dwell", "t": (run[0]["t"]+run[-1]["t"])/2,
                               "x": sum(e["x"] for e in run)/len(run), "y": sum(e["y"] for e in run)/len(run),
                               "start": run[0]["t"], "end": run[-1]["t"],
                               "duration": duration, "confidence": .75})
    return candidates


def attention_intervals(events, words=()):
    """Union of observed input/reading spans; a freeze cannot override these."""
    spans = [(e["t"]-.6, e["t"]+.8) for e in events if e["type"] in {"click", "key", "activity"}]
    spans += [(d["start"]-.15, d["end"]+.3) for d in dwell_candidates(events)]
    samples = sorted((e for e in events if e["type"] == "cursor"), key=lambda e: e["t"])
    # Even tiny travel matters when a cursor is too small for the pixel tiles.
    spans += [(a["t"]-.1, b["t"]+.1) for a,b in zip(samples,samples[1:])
              if math.hypot(b["x"]-a["x"], b["y"]-a["y"]) > 1e-7]
    spans += [(e.get("start", e["t"]), e.get("end", e["t"]))
              for e in events if e["type"] == "dwell"]
    spans += [(w["start"]-.3, w["end"]+.3) for w in words]
    merged = []
    for a,b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a,b))
    return merged


def zoom_candidates(events, activity, idle, duration):
    candidates = dwell_candidates(events) if events else list(activity)
    candidates += [{"kind": "click", "t": e["t"], "x": e["x"], "y": e["y"], "confidence": .95}
                   for e in events if e["type"] == "click"]
    scenes = []
    for c in sorted(candidates, key=lambda e: e["t"]):
        if not 0 <= c["t"] < duration:
            continue
        a, b = max(0, c.get("start", c["t"]-.8)), min(duration, c.get("end", c["t"]+1.2))
        # Positive attention always wins over a contradictory freeze span.
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
    protected = attention_intervals(events, words)
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
    """Fit focus content and complete words; cut when a pan would be empty or slow."""
    from .framing import element_camera
    return element_camera(plan, width, height)


def crop_window(plan, cam, key):
    return tuple(key["window"])
