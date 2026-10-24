"""Element containment, portrait picture layout and action-timed camera cuts."""

from __future__ import annotations

import math

from .regions import union


MARGIN = .06  # Each side of the source element, before delivery letterboxing.


def center(box):
    return box[0]+box[2]/2, box[1]+box[3]/2


def pan_seconds(a, b):
    """Minimum quintic move time under the existing center-motion limits."""
    distance = max(abs(x-y) for x, y in zip(center(a), center(b)))
    return max(1.875*distance/.65, math.sqrt(5.774*distance/4))


def focus_groups(zooms):
    groups = []
    for z in zooms:
        box = z.box or [0., 0., 1., 1.]
        if groups:
            previous = groups[-1]["box"]
            distance = math.dist(center(previous), center(box))
            travel = pan_seconds(previous, box)
            # Nearby targets share a stable containing viewport: a dead zone
            # over whole elements, with no excursion through empty space.
            if distance <= .4 and travel <= .6:
                groups[-1]["box"] = union([previous, box])
                groups[-1]["zooms"].append(z)
                continue
        else:
            distance, travel = 0., 0.
        groups.append({"box": list(box), "zooms": [z], "distance": distance,
                       "estimated_pan_seconds": travel})
    return groups or [{"box": [0., 0., 1., 1.], "zooms": [], "distance": 0.,
                      "estimated_pan_seconds": 0.}]


def natural_time(group, idle):
    events = [e for z in group["zooms"] for e in z.evidence]
    clicks = [e["t"] for e in events if e["kind"] == "click"]
    if clicks:
        return min(clicks), "click"
    when = min((e["t"] for e in events), default=0.)
    ends = [s["end"] for s in idle if when-.3 <= s["end"] <= when]
    return (max(ends), "idle-end") if ends else (when, "activity/dwell")


def fitted_shot(plan, group, width, height, start, end):
    box = group["box"]
    x, y, w, h = (box[i]*[plan.width, plan.height, plan.width, plan.height][i]
                  for i in range(4))
    # Fit the complete element with breathing room. The picture's aspect
    # follows the element in portrait; tall targets can use the tall stage.
    portrait = height > width
    captioned = bool(plan.words) and plan.caption_preset != "none"
    available_w = width*(.94 if portrait or captioned else 1.)
    available_h = height*((.58 if captioned else .90) if portrait else (.72 if captioned else 1.))
    aspect = w/h if portrait else width/height
    picture_w = min(available_w, available_h*aspect)
    picture_h = picture_w/aspect
    pw, ph = max(2, round(picture_w/2)*2), max(2, round(picture_h/2)*2)
    aspect = pw/ph
    # Center the portrait picture in its upper stage, close to the lower
    # caption band. A tall picture starts higher to keep that band clear.
    picture_center = min(height*.43, height*.66-ph/2) if captioned and portrait else height*.38 if captioned else height*.5
    py = round((picture_center-ph/2)/2)*2
    picture = {"x": round((width-pw)/4)*2, "y": py, "width": pw, "height": ph}
    source_base = min(plan.width, plan.height*aspect)
    cap = max(1., min(plan.max_zoom, 2.5*source_base/pw))
    required = max(w, h*aspect)*(1+2*MARGIN)
    # Never increase magnification to meet the phone floor at the expense of
    # element coverage. Fit wins; insufficient source text gets a warning.
    final_w = max(required, source_base/cap, pw/2.5)
    final_h = final_w/aspect
    # A small, contained push-in gives the hold a soft arrival. Its start and
    # end both contain the region; every interpolated rectangle does too.
    base_w, base_h = final_w*1.035, final_h*1.035
    cx, cy = x+w/2, y+h/2
    keys = []
    count = max(1, round((end-start)*plan.fps))
    for i in range(count):
        t = i/plan.fps
        q = min(1., t/.6)
        ease = q*q*q*(10+q*(-15+6*q))
        zoom = 1+.035*ease
        cw, ch = base_w/zoom, base_h/zoom
        keys.append({"t": start+t, "x": cx/plan.width, "y": cy/plan.height,
                     "zoom": zoom, "window": [cx-cw/2, cy-ch/2, cw, ch]})
    return {"start": start, "end": end, "box": box, "picture": picture,
            "base_width": base_w, "base_height": base_h, "keys": keys,
            "zoom_cap": cap, "source_enlargement": pw/final_w,
            "estimated_pan_seconds": group["estimated_pan_seconds"]}


def element_camera(plan, width, height):
    from .planner import time_segments, output_time
    from myzing.layout.readability import phone_size

    time_map = time_segments(plan)
    duration = time_map[-1]["out_end"]
    frames = max(1, math.ceil(duration*plan.fps))
    groups = focus_groups(plan.zooms)
    starts, cuts, kept = [0], [], [groups[0]]
    for group in groups[1:]:
        when, reason = natural_time(group, plan.idle)
        frame = math.ceil(output_time(time_map, when)*plan.fps-1e-7)
        if frame <= starts[-1] or frame >= frames:
            continue
        starts.append(frame)
        kept.append(group)
        cuts.append({"t": frame/plan.fps, "source_t": when, "moment": reason,
                     "kind": "cut", "distance": group["distance"],
                     "estimated_pan_seconds": group["estimated_pan_seconds"],
                     "reason": "distant-target" if group["distance"] > .4 else "pan-over-0.6s"})
    shots, keys, notes = [], [], []
    for i, group in enumerate(kept):
        start = starts[i]/plan.fps
        end = (starts[i+1] if i+1 < len(starts) else frames)/plan.fps
        shot = fitted_shot(plan, group, width, height, start, end)
        for j, key in enumerate(shot["keys"]):
            key.update(shot=i, cut=bool(i and j == 0))
        keys.extend(shot["keys"])
        shots.append(shot)
        if plan.ui_text_px*shot["source_enlargement"] < phone_size(width, height):
            notes.append("Whole UI region cannot reach the phone text floor without clipping; zoomed out to fit it. Record larger UI text. Size is an estimate, not OCR-measured.")
    if any(z.box is None or z.box_evidence.get("kind") == "unknown-full-source" for z in plan.zooms):
        notes.append("UI element bounds are unknown for a focus scene; showing the whole source instead of cropping around its cursor.")
    return {"keys": keys, "shots": shots, "cuts": cuts,
            "segments": [{"kind": "hold", "start": s["start"], "end": s["end"]} for s in shots],
            "time_map": time_map, "duration": duration,
            "base_width": shots[0]["base_width"], "base_height": shots[0]["base_height"],
            "zoom_cap": max(s["zoom_cap"] for s in shots),
            "phone_text_floor": phone_size(width, height), "assumed_ui_text_px": plan.ui_text_px,
            "element_margin": MARGIN, "warnings": list(dict.fromkeys(notes))}
