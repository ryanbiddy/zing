"""One metric-based rail for every caption in a shot, including animation."""

from dataclasses import replace

from myzing.layout.chooser import check_overlap
from myzing.layout.types import Box, EventLayout, FaceTrack, Keyframe, Mask, union
from myzing.layout.framing import centered_framing, swept_output_box
from myzing.composition.aspects import SAFE_INSETS, aspect_for

from .metrics import metrics
from .presets import line_widths, phone_floor


def place_presets(plan, subjects, source_dimensions):
    insets = SAFE_INSETS[aspect_for(plan.width, plan.height)]
    l,t,r,b = insets
    center = (l + 1-r)/2
    masks = [Mask("left", Box(0,0,l,1)), Mask("right", Box(1-r,0,r,1)),
             Mask("top", Box(0,0,1,t)), Mask("bottom", Box(0,1-b,1,b))]
    previous = None
    for clip in plan.clips:
        captions = [c for c in plan.captions if c.preset and clip.timeline_start <= c.start < clip.timeline_end]
        if not captions:
            continue
        obstacles = []
        clip_masks = list(masks)
        framing = clip.framing
        if framing is None and clip.asset_id in source_dimensions:
            framing = centered_framing("fit", *source_dimensions[clip.asset_id], plan.width, plan.height)
        if framing:
            from myzing.layout.types import box_at
            tracks = subjects.get(clip.asset_id, [])
            selection = (framing.picture or {}).get("subject_selection", {})
            if selection.get("focused"):
                # The stage has already made a disclosed dominant-face decision.
                # Incidental HOG scenery must not reserve the entire caption band.
                excluded = set(selection.get("outside_stage_tracks", []) + selection.get("incidental_tracks", []))
                tracks = [track for track in tracks if track.id not in excluded]
            for track in tracks:
                a, z = max(clip.src_in, track.keyframes[0].time), min(clip.src_out, track.keyframes[-1].time)
                if z <= a:
                    continue
                source_box = union([box_at(track.keyframes,a),box_at(track.keyframes,z),
                                    *[k.box for k in track.keyframes if a < k.time < z]])
                box = swept_output_box(source_box, framing, [0,clip.duration,*[k.time for k in framing.keyframes]], plan.width,plan.height)
                if box:
                    obstacles.append(FaceTrack(track.id,[Keyframe(clip.timeline_start,box),Keyframe(clip.timeline_end,box)],track.confidence))
            for i,region in enumerate((framing.picture or {}).get("chrome_regions", [])):
                source_box = Box(*region["bounds_normalized"])
                box = swept_output_box(source_box, framing, [0,clip.duration,*[k.time for k in framing.keyframes]], plan.width,plan.height)
                if box:
                    clip_masks.append(Mask(f"{region['kind']}-{i}",box))
        clean = captions[0].preset == "clean"
        rails = ([.74,.78,.70,.66,.20] if clean else [.70,.66,.74,.62,.20]) if plan.height > plan.width else ([.89,.84,.20] if clean else [.84,.78,.20])
        if previous is not None:
            rails = [previous, *[v for v in rails if v != previous]]
        dimensions = []
        for c in captions:
            f = metrics(c.font.path,c.font.sha256)
            pad = max(c.style.outline_width, c.style.highlight_box_padding if c.preset == "box" else 0)
            w = max(line_widths(c,f,c.style)) + 2*c.style.outline_width
            h = f.line_height(c.style.size)*len(c.text.splitlines()) + 2*pad
            overshoot = 1.05 if c.preset == "punch" else 1.
            dimensions.append((w*overshoot,h*overshoot))
        chosen = None
        # Shrinking to clear a face never goes below DOGFOOD1's phone floor.
        floor = phone_floor(plan, clip.timeline_start, clip.timeline_end, captions[0].preset, source_dimensions)
        size = min(c.style.size for c in captions)
        scales = [s for s in (1.,.95,.90,.85,.80) if size*s >= min(floor, size)-1e-6]
        for scale in scales:
            w,h = max(w for w,h in dimensions)*scale/plan.width, max(h for w,h in dimensions)*scale/plan.height
            # Try the preferred bands first, then the exact free boundaries
            # above/below cards, tiles and faces. No arbitrary unsafe acceptance.
            gap = 2/plan.height
            boxes = [m.box for m in clip_masks] + [t.keyframes[0].box for t in obstacles]
            extra = [t+h if clean else t+h/2, 1-b if clean else 1-b-h/2]
            for obstacle in boxes:
                extra.extend((obstacle.y-gap if clean else obstacle.y-gap-h/2,
                              obstacle.bottom+gap+h if clean else obstacle.bottom+gap+h/2))
            search = [*rails,*sorted(set(extra),key=lambda v: abs(v-rails[0]))]
            for rail in search:
                y = rail-h if clean else rail-h/2
                if min(center-w/2,y) < 0 or max(center+w/2,y+h) > 1:
                    continue
                box = Box(center-w/2,y,w,h)
                check = check_overlap([Keyframe(clip.timeline_start,box),Keyframe(clip.timeline_end,box)],obstacles,clip_masks)
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
        blockers = ", ".join([t.id for t in obstacles] + [m.name for m in clip_masks])
        explanation = (f"No readable caption band fits: {len(search)} vertical positions, size floor {floor:.1f}px; "
                       f"blocked by {blockers}. Shorten the phrase, choose clean captions, or reserve a caption band.")
        for c in captions:
            c.layout = EventLayout(c.id,c.start,c.end,"caption-preset-shot-rail",check,box=box,scale=scale,
                warnings=([f"Caption band moved to {box.y:.3f}-{box.bottom:.3f} of output height to avoid supplied subjects/chrome."]
                          if check.safe and previous != rails[0] else []) if check.safe else [explanation])
        if not check.safe:
            plan.warnings.append(f"{clip.id}: {explanation}")
