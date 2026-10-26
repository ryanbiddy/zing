"""Explicit phone caption preference, separate from recovered typography."""

import math

PHONE_MAX_WORDS = 4
PHONE_MERGE_WORDS = 6
PHONE_MIN_SECONDS = .5
READING_CPS = 20.0  # Same guidance as render.validation.CAPTION_MAX_CPS.


def recover_placement(plan, caption, *, minimum=None, obstacles=None, masks=(), source_dimensions=None):
    """Reserve a legible, inset text plate when subject avoidance is impossible.

    Preserve collision evidence. Generated drafts may disclose subject overlap;
    they never waive output bounds or the renderer's actual glyph-fit check.
    """
    from dataclasses import replace
    from myzing.composition import CaptionStyle
    from myzing.composition.aspects import SAFE_INSETS, aspect_for
    from .types import Box, EventLayout, Keyframe
    from .chooser import check_overlap
    left, top, right, bottom = SAFE_INSETS[aspect_for(plan.width, plan.height)]
    width = 1 - left - right - .02
    height = min(.36, 1 - top - bottom - .02)
    box = Box(left + .01, 1 - bottom - .01 - height, width, height)
    if minimum is None:
        minimum = phone_minimum(plan, caption, source_dimensions) if plan.brief and plan.brief.caption_mode == "phone" else 24.
    style = caption.style or CaptionStyle(minimum, outline_width=2)
    caption.style = replace(style, size=max(minimum, style.size), box_color="#111111", color="#FFFFFF")
    from .types import OverlapCheck
    if obstacles is None:
        # A serialized old plan may lack the tracks used to place it. Retain
        # its unsafe evidence; never certify new geometry from an empty probe.
        prior = caption.layout.overlap if caption.layout else None
        overlap = prior if prior and not prior.safe else OverlapCheck(
            False, mask_names=["unmeasured-subject-avoidance"])
        overlap = replace(overlap, method="prior-placement-only",
                          scope="fallback plate unchecked; original face tracks/masks unavailable")
        reason = "previous unsafe evidence retained" if prior and not prior.safe else "subject avoidance remains unverified"
        warnings = [f"Caption {caption.id}: fallback plate face overlap is unmeasured because original "
                    f"tracks/masks are unavailable; {reason}. Review this draft."]
    else:
        overlap = check_overlap([Keyframe(caption.start, box), Keyframe(caption.end, box)], list(obstacles), list(masks))
        overlap = replace(overlap, scope="output fallback plate; supplied face tracks and original masks over caption interval")
        warnings = []
        if overlap.face_ids:
            warnings.append(f"Caption {caption.id}: fallback plate overlaps face tracks "
                            f"{', '.join(overlap.face_ids)} during {caption.start:g}-{caption.end:g}s (measured).")
        if overlap.mask_names:
            warnings.append(f"Caption {caption.id}: fallback plate overlaps reserved masks "
                            f"{', '.join(overlap.mask_names)} (measured). Review this draft.")
    caption.layout = EventLayout(caption.id, caption.start, caption.end, "readable-placement-fallback", overlap,
                                box=box, warnings=warnings)
    if caption.id in plan.accepted_unsafe_layouts:
        plan.accepted_unsafe_layouts.remove(caption.id)
    if not overlap.safe:
        plan.accepted_unsafe_layouts.append(caption.id)
    prefix = f"Caption {caption.id}: fallback plate "
    plan.warnings[:] = [w for w in plan.warnings if not w.startswith(prefix)]
    plan.warnings.extend(warnings)



def phone_size(width, height, picture_width=None):
    """Minimum em size in output pixels for a 400px-wide phone presentation.

    Portrait: at least 8% of visible picture width and 7% of output width
    (32px when full-width at 400px). Square/wide: 6.5% of picture width,
    bounded by the short side so landscape captions do not dominate.
    """
    picture_width = width if picture_width is None else picture_width
    if height > width:
        return min(512., max(.08*picture_width, .07*width))
    return min(512., .065*min(picture_width, height))


def picture_width(plan, start, end, source_dimensions=None):
    """Narrowest visible picture, in output pixels, among clips shown in [start, end).

    Shared by caption placement, match's ink fit and studio's report, so the
    phone floor uses one picture width everywhere. A clip without framing is
    the default centered fit when its source size is known, else full width.
    """
    from .framing import centered_framing, visible_content
    widths = []
    for clip in plan.clips:
        if clip.timeline_end <= start or clip.timeline_start >= end:
            continue
        framing = clip.framing
        if framing is None and clip.asset_id in (source_dimensions or {}):
            framing = centered_framing("fit", *source_dimensions[clip.asset_id], plan.width, plan.height)
        widths.append(plan.width if framing is None else visible_content(framing, plan.width, plan.height).width * plan.width)
    return min(widths, default=plan.width)


def phone_minimum(plan, caption, source_dimensions=None):
    return phone_size(plan.width, plan.height, picture_width(plan, caption.start, caption.end, source_dimensions))


def phone_word_groups(words):
    """Balanced spoken groups of at most four words, without one-word flashes.

    A clause of n words splits into ceil(n/4) near-equal groups (5 words make
    3+2, never 4+1). A group on screen for less than PHONE_MIN_SECONDS joins its
    shorter neighbour while the joined group keeps at most six words.
    """
    words = list(words)
    if not words:
        return []
    from myzing.captions.grouping import display_boundaries
    _, numeric = display_boundaries([w.text for w in words])
    units = []
    for i,word in enumerate(words):
        if i in numeric:
            units[-1].append(word)
        else:
            units.append([word])
    words = units
    count = math.ceil(len(words) / PHONE_MAX_WORDS)
    sizes = [len(words) // count + (1 if i < len(words) % count else 0) for i in range(count)]
    groups, cursor = [], 0
    for size in sizes:
        groups.append(words[cursor:cursor + size])
        cursor += size

    def seconds(group):
        return group[-1][-1].end - group[0][0].start

    merged = True
    while merged and len(groups) > 1:
        merged = False
        for index, group in enumerate(groups):
            if seconds(group) >= PHONE_MIN_SECONDS:
                continue
            neighbours = [j for j in (index - 1, index + 1)
                          if 0 <= j < len(groups) and len(groups[j]) + len(group) <= PHONE_MERGE_WORDS]
            if not neighbours:
                continue
            other = min(neighbours, key=lambda j: (seconds(groups[j]), j))
            a, b = sorted((index, other))
            groups[a:b + 1] = [groups[a] + groups[b]]
            merged = True
            break
    return [[word for unit in group for word in unit] for group in groups]


def hold_short_events(captions, end_limit):
    """Hold each event to max(PHONE_MIN_SECONDS, characters / READING_CPS).

    Only following silence is used: an event never extends into the next event
    or past end_limit, and word timings are untouched. Returns the number of
    events that still miss the hold for lack of silence.
    """
    ordered = sorted(captions, key=lambda c: (c.start, c.end))
    short = 0
    for caption, following in zip(ordered, [*ordered[1:], None]):
        need = max(PHONE_MIN_SECONDS, len(caption.text.replace("\n", "")) / READING_CPS)
        if caption.end - caption.start >= need - 1e-9:
            continue
        limit = end_limit if following is None else min(end_limit, following.start)
        caption.end = max(caption.end, min(limit, caption.start + need))
        short += caption.end - caption.start < need - 1e-9
    return short
