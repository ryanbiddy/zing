"""Element containment, portrait picture layout and action-timed camera cuts."""

from __future__ import annotations

import math

from .regions import union, intersects, contains


MARGIN = .06  # Each side of the source element, before delivery letterboxing.
MAX_SOURCE_ENLARGEMENT = 2.5  # Output pixels per source pixel, including pushes.


def center(box):
    return box[0]+box[2]/2, box[1]+box[3]/2


def pan_seconds(a, b):
    """Minimum quintic move time under the existing center-motion limits."""
    distance = max(abs(x-y) for x, y in zip(center(a), center(b)))
    return max(1.875*distance/.65, math.sqrt(5.774*distance/4))


def focus_groups(zooms, can_merge=None):
    groups = []
    for z in zooms:
        box = z.box or [0., 0., 1., 1.]
        if groups:
            previous = groups[-1]["box"]
            distance = math.dist(center(previous), center(box))
            travel = pan_seconds(previous, box)
            # Nearby targets share a stable containing viewport: a dead zone
            # over whole elements, with no excursion through empty space.
            merged = {**groups[-1], "box":union([previous,box]),
                      "zooms":[*groups[-1]["zooms"],z]}
            if distance <= .4 and travel <= .6 and (can_merge is None or can_merge(merged)):
                groups[-1] = merged
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
    when = min((e.get("start",e["t"]) for e in events), default=0.)
    ends = [s["end"] for s in idle if when-.3 <= s["end"] <= when]
    return (max(ends), "idle-end") if ends else (when, "activity/dwell")


def safe_window(focus, words, width, aspect, anchor_y=.5):
    """Place the crop in whitespace; intersecting words must be complete.

    Search only positions which contain the focus with its margin. A word
    edge changes validity, so testing these boundaries is sufficient.
    """
    x,y,w,h = focus
    ch = width/aspect
    mx,my = w*MARGIN,h*MARGIN
    xlo,xhi = x+w+mx-width,x-mx
    ylo,yhi = y+h+my-ch,y-my
    if xlo > xhi+1e-7 or ylo > yhi+1e-7:
        return None
    cx,cy = x+w/2-width/2,y+h/2-ch*anchor_y
    xs = [cx,xlo,xhi]
    ys = [cy,ylo,yhi]
    # A pixel of breathing room absorbs crop rounding and codec ringing.
    for a,b,c,d in words:
        xs.extend((a-1-width,a+c+1,a-1,a+c+1-width))
        ys.extend((b-1-ch,b+d+1,b-1,b+d+1-ch))
    xs = sorted({max(xlo,min(xhi,v)) for v in xs},key=lambda v:abs(v-cx))
    ys = sorted({max(ylo,min(yhi,v)) for v in ys},key=lambda v:abs(v-cy))
    best,score = None,float("inf")
    for left in xs:
        for top in ys:
            cost=(left-cx)**2+(top-cy)**2
            if cost>=score:
                continue
            view=[left,top,width,ch]
            if all(not intersects(view,word) or contains(view,word) for word in words):
                best,score=view,cost
    return best


def fitted_shot(plan, group, width, height, start, end):
    from myzing.layout.readability import phone_size
    box = group["box"]
    focus = [box[i]*[plan.width,plan.height,plan.width,plan.height][i] for i in range(4)]
    x,y,w,h = focus
    words = [list(b) for b in sorted({tuple(b) for z in group["zooms"]
                                    for b in z.box_evidence.get("words",[])})]
    guards = [[b[i]*[plan.width,plan.height,plan.width,plan.height][i] for i in range(4)]
              for b in words]
    portrait = height > width
    captioned = bool(plan.words) and plan.caption_preset != "none"
    available_w = width*(.94 if portrait or captioned else 1.)
    available_h = height*((.58 if captioned else .90) if portrait else (.72 if captioned else 1.))
    # The portrait stage is tall even for a shallow button. It can include
    # useful nearby context without shrinking the focus to a narrow strip.
    aspect = min(available_w/available_h,w/h) if portrait else width/height
    pw = max(2,round(min(available_w,available_h*aspect)/2)*2)
    ph = max(2,round(pw/aspect/2)*2)
    aspect = pw/ph
    picture_center = min(height*.43,height*.66-ph/2) if captioned and portrait else height*.38 if captioned else height*.5
    picture = {"x":round((width-pw)/4)*2,"y":math.floor((picture_center-ph/2)/2)*2,
               "width":pw,"height":ph}
    source_base = min(plan.width,plan.height*aspect)
    floor = phone_size(width,height,pw)
    scale = max(floor/plan.ui_text_px, .60*width/w if portrait else 0.)
    required = max(max(w,h*aspect)*(1+2*MARGIN),pw/MAX_SOURCE_ENLARGEMENT)
    # max_zoom is the preferred context zoom. Legibility may require more;
    # element containment remains mandatory when the two are incompatible.
    desired = max(required,min(source_base/plan.max_zoom,pw/scale))
    view = None
    # Try slightly tighter crops before giving up the text floor. Shrinking
    # changes which surrounding words need to fit, never the protected focus.
    widths = [desired+(required-desired)*i/20 for i in range(21)]
    # A complete neighboring word can need a wider crop than the preferred
    # context zoom, while still meeting both phone targets. Try that range
    # before expanding the focus union and conceding legibility.
    if pw/scale > desired:
        widths += [desired+(pw/scale-desired)*i/20 for i in range(1,21)]
    for cw in widths:
        view = safe_window(focus,guards,cw,aspect,.8 if portrait else .65)
        if view is not None:
            break
    if view is None:
        # Close over words cut by the viewport. This finite expansion keeps
        # every visible word intact; impossible phone floors are reported.
        expanded = list(focus)
        for _ in range(len(guards)+1):
            cw=max(required,max(expanded[2],expanded[3]*aspect)*(1+2*MARGIN))
            cx,cy=center(expanded)
            view=[cx-cw/2,cy-cw/aspect/2,cw,cw/aspect]
            crossed=[b for b in guards if intersects(view,b) and not contains(view,b)]
            if not crossed:
                break
            expanded=union([expanded,*crossed])
    base_w,base_h=view[2:]
    cx,cy=view[0]+base_w/2,view[1]+base_h/2
    # A contained 3.5% push is optional. Text edges veto it for the whole shot,
    # so no intermediate frame can cut a word during the arrival.
    count=max(1,round((end-start)*plan.fps))
    def keys_for(push):
        keys=[]
        for i in range(count):
            t=i/plan.fps
            q=min(1.,t/.6)
            ease=q*q*q*(10+q*(-15+6*q))
            zoom=1+push*ease
            cw,ch=base_w/zoom,base_h/zoom
            keys.append({"t":start+t,"x":cx/plan.width,"y":cy/plan.height,
                         "zoom":zoom,"window":[cx-cw/2,cy-ch/2,cw,ch]})
        return keys
    push=max(0.,min(.035,MAX_SOURCE_ENLARGEMENT*base_w/pw-1))
    keys=keys_for(push)
    padded_focus=[x-w*MARGIN,y-h*MARGIN,w*(1+2*MARGIN),h*(1+2*MARGIN)]
    if any(not contains(k["window"],padded_focus) or
           any(intersects(k["window"],b) and not contains(k["window"],b) for b in guards) for k in keys):
        keys=keys_for(0.)
    return {"start":start,"end":end,"box":box,"picture":picture,"word_boxes":words,
            "base_width":base_w,"base_height":base_h,"keys":keys,
            "zoom_cap":max(source_base/k["window"][2] for k in keys),
            "source_enlargement":pw/base_w,"source_enlargement_cap":MAX_SOURCE_ENLARGEMENT,
            "phone_text_floor":floor,"focus_width_fraction":w*pw/base_w/width,
            "estimated_pan_seconds":group["estimated_pan_seconds"]}


def element_camera(plan, width, height):
    from .planner import time_segments, output_time
    from myzing.layout.readability import phone_size

    time_map = time_segments(plan)
    duration = time_map[-1]["out_end"]
    frames = max(1, math.ceil(duration*plan.fps))
    # Evaluate the actual fitted picture, margins and word guards. A width
    # estimate alone can approve a union that falls below the phone floor.
    def legible(group):
        shot = fitted_shot(plan,group,width,height,0,1/plan.fps)
        return (plan.ui_text_px*shot["source_enlargement"] >= shot["phone_text_floor"]-1e-6
                and (height<=width or shot["focus_width_fraction"]>=.60-1e-6))
    groups = focus_groups(plan.zooms, can_merge=legible)
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
                     "reason": "distant-target" if group["distance"] > .4 else "pan-over-0.6s" if group["estimated_pan_seconds"] > .6 else "legibility"})
    shots, keys, notes = [], [], []
    for i, group in enumerate(kept):
        start = starts[i]/plan.fps
        end = (starts[i+1] if i+1 < len(starts) else frames)/plan.fps
        shot = fitted_shot(plan, group, width, height, start, end)
        for j, key in enumerate(shot["keys"]):
            key.update(shot=i, cut=bool(i and j == 0))
        keys.extend(shot["keys"])
        shots.append(shot)
        if plan.ui_text_px*shot["source_enlargement"] < shot["phone_text_floor"]-1e-6:
            notes.append("Focus text cannot reach the phone floor within the 2.5x source enlargement ceiling while keeping its complete line and visible words; record larger UI text or use a wider delivery. Size is estimated from --ui-text-px, not OCR-measured.")
        if height>width and shot["focus_width_fraction"]<.60-1e-6:
            notes.append("Focus cannot fill 60% of portrait width within the 2.5x source enlargement ceiling while keeping the complete element and visible words; its height or surrounding text may require a wider crop.")
    if any(z.box is None or z.box_evidence.get("kind") == "unknown-full-source" for z in plan.zooms):
        notes.append("UI element bounds are unknown for a focus scene; showing the whole source instead of cropping around its cursor.")
    return {"keys": keys, "shots": shots, "cuts": cuts,
            "segments": [{"kind": "hold", "start": s["start"], "end": s["end"]} for s in shots],
            "time_map": time_map, "duration": duration,
            "base_width": shots[0]["base_width"], "base_height": shots[0]["base_height"],
            "zoom_cap": max(s["zoom_cap"] for s in shots),
            "phone_text_floor": phone_size(width, height), "assumed_ui_text_px": plan.ui_text_px,
            "element_margin": MARGIN, "warnings": list(dict.fromkeys(notes))}
