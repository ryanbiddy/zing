"""Rebuild source framing and caption geometry while retaining the edit clock."""

from copy import deepcopy
from dataclasses import replace

from myzing.composition.aspects import aspect_for
from .framing import place_captions, select_framing


def adapt_plan(composition, width, height, source_dimensions, subjects, *, requested="auto",
               max_upscale=2.5, cuts=None, pictures=None):
    plan = deepcopy(composition)
    old_short = min(plan.width, plan.height)
    plan.width, plan.height = width, height
    plan.accepted_unsafe_layouts = []  # Acceptance of the old geometry cannot transfer.
    if plan.brief:
        plan.brief.aspect = aspect_for(width, height)
        plan.brief.aspects = []
        plan.brief.framing = requested
        plan.brief.framing_max_upscale = max_upscale
    for caption in plan.captions:
        caption.layout = None
        if caption.style:
            # Scale with the short side, clamped to CaptionStyle's 1-512 px
            # size and 0-20 px outline contract at extreme --short-side values.
            factor = min(width, height) / old_short
            caption.style = replace(caption.style, size=min(512, max(1, caption.style.size * factor)),
                                    outline_width=min(20, max(0, caption.style.outline_width * factor)))
    clips = []
    rate = plan.fps.numerator / plan.fps.denominator
    for clip in plan.clips:
        boundaries = [clip.src_in]
        # Splitting transition legs would invalidate their linked handles.
        # Auto coverage checks instead fall back to full-picture blurfill.
        if not plan.transitions and requested in ("auto", "reframe", "zoomfill"):
            for cut in sorted((cuts or {}).get(clip.asset_id, [])):
                if cut - boundaries[-1] >= 1 / rate and clip.src_out - cut >= 1 / rate:
                    boundaries.append(cut)
        boundaries.append(clip.src_out)
        for i, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            part = replace(clip, id=clip.id if len(boundaries) == 2 else f"{clip.id}-delivery-shot-{i+1}",
                           src_in=start, src_out=end, timeline_start=clip.timeline_start + start - clip.src_in,
                           framing=None)
            from .picture import select_picture_framing
            part.framing = select_picture_framing(requested, *source_dimensions[clip.asset_id], width, height,
                                          part, subjects.get(clip.asset_id, []), max_upscale=max_upscale, fps=rate,
                                          speech_words=plan.speech_words, picture=(pictures or {}).get(clip.asset_id),
                                          policy=plan.brief.picture_crop if plan.brief else "auto")
            clips.append(part)
    plan.clips = clips
    preset = next((c.preset for c in plan.captions if c.preset), None)
    if preset:
        from myzing.captions.presets import apply_preset
        apply_preset(plan, preset, vad=False)
    place_captions(plan, subjects, source_dimensions)
    plan.warnings.append(f"Delivery {aspect_for(width, height)}: source framing and caption layout replanned; "
                         "generic UI reserves are conservative defaults, not a platform guarantee.")
    plan.__post_init__()
    return plan
