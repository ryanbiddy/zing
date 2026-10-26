"""Draft-wide caption bands measured on sparse, cropped source frames.

Clutter = 0.6 edge density (>0.08 luma gradient) + 0.4 local texture
(mean absolute residual from a 5x5 box blur, normalized by 0.10).
A band is clean at <=0.18. Readability uses the tenth percentile of linear
sRGB luma contrast ratios; below 4.5:1 strengthen the permitted outline.
These thresholds are editorial estimates, not accessibility certification.
"""

from dataclasses import replace
from functools import lru_cache
import json
import subprocess

from myzing.layout.types import Box, EventLayout, FaceTrack, Keyframe, Mask, box_at
from myzing.layout.chooser import check_overlap
from myzing.layout.caption_safety import is_face, remember
from myzing.layout.framing import centered_framing, swept_output_box

CLEAN = .18
CONTRAST = 4.5


@lru_cache(maxsize=96)
def sample_frame(source, time, framing_json, width, height):
    """Decode one snapshot through the renderer's crop/blur/pad graph; no movie."""
    import numpy as np
    from myzing.composition.framing import Framing
    from myzing.render.framing import framing_filter
    framing = Framing.from_dict(json.loads(framing_json)) if framing_json else None
    sw, sh = 270, round(270 * height / width / 2) * 2
    filters = framing_filter(framing, width, height, 30) + f",scale={sw}:{sh},format=rgb24[out]"
    result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", str(time),
        "-protocol_whitelist", "file,pipe", "-i", source, "-filter_complex", filters,
        "-map", "[out]", "-frames:v", "1", "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True, timeout=30, check=False)
    if result.returncode or len(result.stdout) != sw*sh*3:
        raise ValueError("caption frame sampling failed: " + result.stderr.decode(errors="replace")[-200:])
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(sh, sw, 3)


def measure_band(frames, box, fill):
    import numpy as np
    clutter, contrasts, edges, textures = [], [], [], []
    rgb = np.array([int(fill[i:i+2], 16) for i in (1,3,5)]) / 255.
    def linear(x):
        return np.where(x <= .04045, x/12.92, ((x+.055)/1.055)**2.4)
    fill_luma = float(linear(rgb) @ np.array([.2126,.7152,.0722]))
    for frame in frames:
        h,w = frame.shape[:2]
        patch = frame[int(box.y*h):max(int(box.y*h)+2, int(box.bottom*h)),
                      int(box.x*w):max(int(box.x*w)+2, int(box.right*w))].astype(float)/255.
        luma = patch @ np.array([.2126,.7152,.0722])
        gradient = np.hypot(*np.gradient(luma))
        edge = float((gradient > .08).mean())
        padded = np.pad(luma, 2, mode='edge')
        smooth = sum(padded[y:y+luma.shape[0], x:x+luma.shape[1]] for y in range(5) for x in range(5))/25
        texture = min(1., float(np.abs(luma-smooth).mean())/.10)
        background = linear(patch) @ np.array([.2126,.7152,.0722])
        ratio = (np.maximum(fill_luma, background)+.05)/(np.minimum(fill_luma, background)+.05)
        clutter.append(.6*edge+.4*texture)
        contrasts.append(float(np.percentile(ratio, 10)))
        edges.append(edge)
        textures.append(texture)
    # Worst sampled shot, rather than a median that hides one foreground mic.
    return {"clutter_score": max(clutter), "edge_density": max(edges), "texture": max(textures),
            "contrast_ratio": min(contrasts), "samples": len(frames)}


def obstacles_for(plan, subjects, sizes):
    obstacles = []
    for clip in plan.clips:
        framing = clip.framing
        if framing is None and clip.asset_id in sizes:
            framing = centered_framing('fit', *sizes[clip.asset_id], plan.width, plan.height)
        if framing is None:
            continue
        for track in subjects.get(clip.asset_id, []):
            if not is_face(track):
                continue
            a, b = max(clip.src_in, track.keyframes[0].time), min(clip.src_out, track.keyframes[-1].time)
            if b <= a:
                continue
            from myzing.layout.types import union
            box = union([box_at(track.keyframes,a), box_at(track.keyframes,b),
                         *[k.box for k in track.keyframes if a < k.time < b]])
            out = swept_output_box(box, framing, [a-clip.src_in,b-clip.src_in,
                *[k.time for k in framing.keyframes if a-clip.src_in < k.time < b-clip.src_in]], plan.width, plan.height)
            if out:
                obstacles.append(FaceTrack(track.id, [Keyframe(clip.timeline_start+a-clip.src_in,out),
                                                     Keyframe(clip.timeline_start+b-clip.src_in,out)]))
    return obstacles


def strengthen(plan, caption, contrast, reference):
    if contrast >= CONTRAST:
        return False
    # Reference: <=20% estimated ink height; presets retain bounded strokes.
    cap = min(20., caption.style.size*(.14 if reference else .07 if caption.preset == 'punch' else .05))
    options = plan.brief.caption_options if plan.brief else {}
    if options and any(k in options for k in ('outline_width','outline_color')):
        return False
    rgb = [int(caption.style.color[i:i+2],16)/255 for i in (1,3,5)]
    color = '#000000' if sum(rgb)/3 >= .5 else '#FFFFFF'
    changed = caption.style.outline_width < cap or caption.style.outline_color != color
    caption.style = replace(caption.style, outline_width=max(caption.style.outline_width,cap), outline_color=color)
    return changed


def place(plan, subjects, sizes, *, safety_context=None, frames=None):
    if not plan.captions:
        return {"status": "no captions"}
    moving = any(c.layout and c.layout.path and any(k.box != c.layout.path[0].box for k in c.layout.path)
                 for c in plan.captions)
    if any(c.layout is None or c.style is None for c in plan.captions):
        return {"status": "unmeasured", "reason": "Caption geometry or style unavailable."}
    try:
        if frames is None:
            frames = []
            for clip in plan.clips:
                for fraction in (.1,.5,.9):
                    local = clip.duration*fraction
                    f = clip.framing
                    if f and f.keyframes:
                        from myzing.composition.framing import CropKeyframe
                        x,y = f.center_at(local)
                        f = replace(f, center_x=x, center_y=y, keyframes=[CropKeyframe(0,x,y)], speaker_turns=[])
                    frames.append(sample_frame(clip.src, clip.source_at(clip.timeline_start+local),
                                  json.dumps(f.to_dict(), sort_keys=True) if f else '', plan.width, plan.height))
        if not frames:
            raise ValueError("No sampled source frames")
        import numpy  # Optional existing dependency; keep missing analysis explicit.
    except (ImportError, OSError, ValueError, subprocess.SubprocessError) as exc:
        note = f"Caption band unmeasured: {exc}"
        plan.warnings.append(note)
        return {"status": "unmeasured", "reason": note}
    from myzing.composition.aspects import SAFE_INSETS, aspect_for
    left, top, right, bottom = SAFE_INSETS[aspect_for(plan.width, plan.height)]
    reference = bool(plan.brief and plan.brief.caption_mode == 'reference')
    if moving:
        rows = []
        for caption in plan.captions:
            values = [measure_band(frames,k.box,caption.style.color) for k in caption.layout.as_path()]
            contrast = min(v['contrast_ratio'] for v in values)
            rows.append({'caption_id':caption.id,'bands':[k.box.to_dict() for k in caption.layout.as_path()],
                         'clutter_score':max(v['clutter_score'] for v in values),'contrast_ratio':contrast,
                         'outline_strengthened':strengthen(plan,caption,contrast,reference)})
        plan.warnings.append('Estimated caption bands: style motion retained; contrast measured at path keyframes against sampled cropped frames, with bounded outline adjustments.')
        return {'status':'style motion retained','bands':rows,'contrast_threshold':CONTRAST}
    original = plan.captions[0].layout.as_path()[0].box
    # The old 16%-high envelope was a search reserve, not visible caption ink.
    # Reserve two lines at the existing size plus strokes; do not make a face
    # collision inevitable by treating that oversized reserve as printed text.
    height = min(max(c.layout.as_path()[0].box.height for c in plan.captions),
                 max((2.4*c.style.size + 2*c.style.outline_width +
                      (2*c.style.highlight_box_padding if c.style.highlight_box_color else 0))/plan.height
                     for c in plan.captions))
    width = min(max(c.layout.as_path()[0].box.width for c in plan.captions), 1-left-right)
    x = max(left, min(original.x, 1-right-width))
    preferred = original.center[1]
    centers = sorted({preferred, *[i/100 for i in range(round((top+height/2)*100), round((1-bottom-height/2)*100)+1, 2)]})
    obstacles = obstacles_for(plan, subjects, sizes)
    masks = [Mask('top',Box(0,0,1,top)), Mask('bottom',Box(0,1-bottom,1,bottom))]
    # Reference masks can be stricter than generic platform reserves.
    facts = next((json.loads(w[len('CAPREF evidence: '):]) for w in plan.warnings if w.startswith('CAPREF evidence: ')), {})
    masks.extend(Mask.from_dict(m) for m in facts.get('caption_masks', []))
    candidates = []
    for center in centers:
        if center-height/2 < top-1e-8 or center+height/2 > 1-bottom+1e-8:
            continue
        box = Box(x, center-height/2, width, height)
        check = check_overlap([Keyframe(0,box),Keyframe(max(c.timeline_end for c in plan.clips),box)], obstacles, masks)
        values = [measure_band(frames, box, fill) for fill in {c.style.color for c in plan.captions}]
        scores = dict(values[0], contrast_ratio=min(v['contrast_ratio'] for v in values))
        candidates.append(dict(scores, center=center, box=box.to_dict(), safe=check.safe))
    safe = [c for c in candidates if c['safe']]
    clean = [c for c in safe if c['clutter_score'] <= CLEAN]
    if not safe:
        plan.warnings.append('Estimated caption band: no single face-safe band fits the allowed region; existing placement retained for review.')
        return {"status": "no safe band", "candidates": candidates}
    if reference and clean:
        chosen = min(clean, key=lambda c:(abs(c['center']-preferred), c['clutter_score']))
    else:
        chosen = min(safe, key=lambda c:(c['clutter_score'], abs(c['center']-preferred)))
    box = Box.from_dict(chosen['box'])
    strengthened = False
    for caption in plan.captions:
        strengthened |= strengthen(plan,caption,chosen['contrast_ratio'],reference)
        check = check_overlap([Keyframe(caption.start,box),Keyframe(caption.end,box)], obstacles,masks)
        caption.layout = EventLayout(caption.id,caption.start,caption.end,'estimated-draft-band',check,box=box)
        remember(safety_context, caption, obstacles, masks)
        if caption.id in plan.accepted_unsafe_layouts and check.safe:
            plan.accepted_unsafe_layouts.remove(caption.id)
    moved = abs(chosen['center']-preferred) > 1e-8
    plan.warnings[:] = [w for w in plan.warnings if 'reference position overlaps supplied faces/masks' not in w]
    note = (f"Estimated caption band: center {chosen['center']:.1%}, clutter {chosen['clutter_score']:.3f}, "
            f"luma contrast {chosen['contrast_ratio']:.2f}:1 (threshold {CONTRAST}:1); "
            f"{'moved from '+format(preferred,'.1%') if moved else 'reference/preferred position retained'}; "
            f"outline {'strengthened within style limits' if strengthened else 'retained'}.")
    plan.warnings.append(note)
    return {"status": "Estimated", **chosen, "preferred_center": preferred, "moved": moved,
            "outline_strengthened": strengthened, "clean_threshold": CLEAN, "contrast_threshold": CONTRAST,
            "candidates": candidates}
