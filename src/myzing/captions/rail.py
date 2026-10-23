"""One metric-based rail for every caption in a shot, including animation."""

from dataclasses import replace

from myzing.layout.chooser import check_overlap
from myzing.layout.types import Box, EventLayout, FaceTrack, Keyframe, Mask, union
from myzing.layout.framing import centered_framing, swept_output_box
from myzing.composition.aspects import SAFE_INSETS, aspect_for

from .metrics import metrics
from .presets import line_width


def place_presets(plan, subjects, source_dimensions):
    insets = SAFE_INSETS[aspect_for(plan.width, plan.height)]
    l,t,r,b = insets
    masks = [Mask("left", Box(0,0,l,1)), Mask("right", Box(1-r,0,r,1)),
             Mask("top", Box(0,0,1,t)), Mask("bottom", Box(0,1-b,1,b))]
    previous = None
    for clip in plan.clips:
        captions = [c for c in plan.captions if c.preset and clip.timeline_start <= c.start < clip.timeline_end]
        if not captions:
            continue
        obstacles = []
        framing = clip.framing
        if framing is None and clip.asset_id in source_dimensions:
            framing = centered_framing("fit", *source_dimensions[clip.asset_id], plan.width, plan.height)
        if framing:
            from myzing.layout.types import box_at
            for track in subjects.get(clip.asset_id, []):
                a, z = max(clip.src_in, track.keyframes[0].time), min(clip.src_out, track.keyframes[-1].time)
                if z <= a:
                    continue
                source_box = union([box_at(track.keyframes,a),box_at(track.keyframes,z),
                                    *[k.box for k in track.keyframes if a < k.time < z]])
                box = swept_output_box(source_box, framing, [0,clip.duration,*[k.time for k in framing.keyframes]], plan.width,plan.height)
                if box:
                    obstacles.append(FaceTrack(track.id,[Keyframe(clip.timeline_start,box),Keyframe(clip.timeline_end,box)],track.confidence))
        clean = captions[0].preset == "clean"
        rails = ([.74,.78,.70,.66,.20] if clean else [.70,.66,.74,.62,.20]) if plan.height > plan.width else ([.89,.84,.20] if clean else [.84,.78,.20])
        if previous is not None:
            rails = [previous, *[v for v in rails if v != previous]]
        dimensions = []
        for c in captions:
            f = metrics(c.font.path,c.font.sha256)
            pad = max(c.style.outline_width, c.style.highlight_box_padding if c.preset == "box" else 0)
            w = max(line_width(s,f,c.style,c.preset) for s in c.text.splitlines()) + 2*pad
            h = f.line_height(c.style.size)*len(c.text.splitlines()) + 2*pad
            dimensions.append((w*1.05,h*1.05))
        chosen = None
        for scale in (1.,.95,.90,.85,.80):
            w,h = max(w for w,h in dimensions)*scale/plan.width, max(h for w,h in dimensions)*scale/plan.height
            for rail in rails:
                y = rail-h if clean else rail-h/2
                if min(.5-w/2,y) < 0 or max(.5+w/2,y+h) > 1:
                    continue
                box = Box(.5-w/2,y,w,h)
                check = check_overlap([Keyframe(clip.timeline_start,box),Keyframe(clip.timeline_end,box)],obstacles,masks)
                candidate = (box,check,scale,rail)
                if chosen is None or check.safe:
                    chosen = candidate
                if check.safe:
                    break
            if chosen and chosen[1].safe:
                break
        if chosen is None:
            raise ValueError("Caption preset cannot fit this frame; choose clean or a larger output.")
        box, check, scale, previous = chosen
        for c in captions:
            c.layout = EventLayout(c.id,c.start,c.end,"caption-preset-shot-rail",check,box=box,scale=scale,
                warnings=[] if check.safe else ["No caption rail avoids all supplied faces and UI masks; review this shot."])
        if not check.safe:
            plan.warnings.append(f"{clip.id}: no safe caption preset rail; review the marked layout.")
