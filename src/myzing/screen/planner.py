"""OpenScreen dwell port + Screenize scene chaining, adapted for offline video.

Upstream revisions, copyright and changes: docs/SCREEN-DEMO.md and
docs/licenses/screen-*.txt. No upstream runtime is needed.
"""

from __future__ import annotations

import math
from dataclasses import replace

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


def smooth_windows(plan, keys, cw, ch):
    """Smooth *visible rectangles*, including boundary clamping.

    Clamping a spring's center afterward can create an acceleration spike at
    a screen edge. A positive convolution of valid rectangles remains valid
    (the containment constraints are convex). Three box passes soften that
    boundary without overshoot; broaden only until actual camera bounds pass.
    """
    windows=[]
    for k in keys:
        w,h=cw/k["zoom"],ch/k["zoom"]
        x=max(w/2,min(plan.width-w/2,k["x"]*plan.width))
        y=max(h/2,min(plan.height-h/2,k["y"]*plan.height))
        windows.append((x,y,w))
    for radius in (3,5,8,12,18,30):
        values=windows
        for _ in range(3):
            # Prefix sums keep long recordings linear in frame count.
            padded=[values[0]]*radius+values+[values[-1]]*radius
            sums=[[0.,0.,0.]]
            for row in padded:
                sums.append([a+b for a,b in zip(sums[-1],row)])
            span=2*radius+1
            values=[tuple((sums[i+span][j]-sums[i][j])/span for j in range(3)) for i in range(len(values))]
        result=[{"t":k["t"],"x":v[0]/plan.width,"y":v[1]/plan.height,"zoom":cw/v[2]} for k,v in zip(keys,values)]
        safe=True
        for axis,vmax,amax in (("x",.65,4.),("y",.65,4.),("zoom",1.5,6.)):
            velocity=[(b[axis]-a[axis])*plan.fps for a,b in zip(result,result[1:])]
            acceleration=[(b-a)*plan.fps for a,b in zip(velocity,velocity[1:])]
            if max(map(abs,velocity),default=0)>vmax+1e-6 or max(map(abs,acceleration),default=0)>amax+1e-6:
                safe=False
        if safe:
            return result
    raise ValueError("Screen camera cannot satisfy motion bounds; reduce --max-zoom or split the recording into longer demonstrations.")


def camera(plan, width, height):
    """Chained transition/hold targets, integrated by a critical spring damper.

    Screenize adaptations: offline anticipation, >=0.1s holds, bounded velocity
    and acceleration, viewport dead zone. No target is inferred from key data.
    """
    from myzing.layout.readability import phone_size
    from myzing.layout.framing import centered_framing
    segments = time_segments(plan)
    duration = segments[-1]["out_end"]
    base = centered_framing("reframe",plan.width,plan.height,width,height)
    cw,ch = base.width,base.height
    # Limit extra magnification by context (1.8x default) and source sampling.
    # The phone floor is a LOWER text-size bound, not an upper zoom bound.
    cap = max(1., min(plan.max_zoom, 2.5*cw/width))
    needed = phone_size(width, height)/(plan.ui_text_px*width/cw)
    zoom = min(cap, max(1.35, needed))
    notes = []
    if width/cw > 2.5:
        notes.append("Filling this aspect already exceeds 2.5x source enlargement; extra zoom is disabled. Use a higher-resolution recording or a smaller delivery.")
    if needed > cap:
        notes.append(f"UI text estimate cannot reach the phone floor within the {cap:.2f}x zoom cap; record larger UI text. Text size is supplied/assumed, not OCR-measured.")
    scenes = [replace(z, start=output_time(segments, z.start), end=output_time(segments, z.end)) for z in plan.zooms]
    schedule = []
    for z in scenes:
        transition = min(.8, max(.15, z.end-z.start-.1))
        schedule.extend([{"kind": "transition", "start": z.start, "end": z.start+transition,
                          "x": z.x, "y": z.y, "zoom": zoom},
                         {"kind": "hold", "start": z.start+transition, "end": z.end,
                          "x": z.x, "y": z.y, "zoom": zoom}])
    keys, state, velocity = [], [.5, .5, 1.], [0., 0., 0.]
    # Portrait's initial framing follows the first known focus, matching the
    # existing source-space framing convention; it does not start off target.
    if scenes:
        state[:2] = [scenes[0].x, scenes[0].y]
    dt = 1/(plan.fps*4)
    last_target = state[:]
    for frame in range(math.ceil(duration*plan.fps)+1):
        t = min(duration, frame/plan.fps)
        active = next((z for z in scenes if z.start <= t < z.end), None)
        desired = [active.x, active.y, zoom] if active else [last_target[0], last_target[1], 1.]
        if active:
            # A small target change inside 8% of the current viewport holds.
            for axis, size, whole in ((0,cw,plan.width),(1,ch,plan.height)):
                if abs(desired[axis]-last_target[axis]) < .08*size/(whole*state[2]):
                    desired[axis] = last_target[axis]
        last_target = desired[:]
        for _ in range(4 if frame else 0):
            for i in range(3):
                accel = max(-4 if i < 2 else -6, min(4 if i < 2 else 6, 64*(desired[i]-state[i])-16*velocity[i]))
                vmax = .65 if i < 2 else 1.5
                velocity[i] = max(-vmax, min(vmax, velocity[i]+accel*dt))
                state[i] += velocity[i]*dt
        keys.append({"t": t, "x": state[0], "y": state[1], "zoom": max(1., state[2])})
    keys = smooth_windows(plan,keys,cw,ch)
    return {"keys": keys, "segments": schedule, "time_map": segments, "duration": duration,
            "base_width": cw, "base_height": ch, "zoom_cap": cap,
            "phone_text_floor": phone_size(width,height), "assumed_ui_text_px": plan.ui_text_px, "warnings": notes}


def crop_window(plan, cam, key):
    w, h = cam["base_width"]/key["zoom"], cam["base_height"]/key["zoom"]
    x = max(0, min(plan.width-w, key["x"]*plan.width-w/2))
    y = max(0, min(plan.height-h, key["y"]*plan.height-h/2))
    return x, y, w, h
