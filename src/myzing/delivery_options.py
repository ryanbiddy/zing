"""Shared opt-in CLI overrides for render, match and studio."""


def short_side(value):
    import argparse
    if value == "auto":
        return value
    try:
        return int(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("use auto or a multiple of 18 such as 720 or 1080") from None


def add_options(parser):
    parser.add_argument("--short-side", type=short_side, help="delivery short side: auto or a multiple of 18, e.g. 720")
    parser.add_argument("--caption-options", help='JSON CaptionStyle overrides, e.g. {"highlight_box_color":"#FFD23F","highlight":"#0A0A0A"}')
    parser.add_argument("--caption-mode", choices=["reference", "phone", "punch", "box", "clean", "none"])
    parser.add_argument("--picture-crop", choices=["auto", "on", "off"], help="crop static broadcast chrome when confident; on requires a confident picture")
    budget = parser.add_mutually_exclusive_group()
    budget.add_argument("--target-mb", type=float, help="target file size in decimal MB, x264 two-pass")
    budget.add_argument("--video-bitrate-kbps", type=float, help="x264 two-pass average video bitrate, kb/s")


def overrides(args):
    import json
    from myzing.brief.models import Brief
    values = {name: getattr(args, name) for name in ("caption_options", "caption_mode", "picture_crop", "target_mb", "video_bitrate_kbps", "short_side")
              if getattr(args, name, None) is not None}
    if "caption_options" in values:
        values["caption_options"] = json.loads(values["caption_options"])
    Brief.from_answers(values)
    return values


def apply_plan(plan, values, *, base_dir=None):
    from dataclasses import replace
    from myzing.brief.models import Brief
    from myzing.composition import CaptionStyle
    from myzing.composition.encoding import DeliveryEncoding
    if not values:
        return
    values = dict(values)
    if "target_mb" in values:
        values["video_bitrate_kbps"] = None
    elif "video_bitrate_kbps" in values:
        values["target_mb"] = None
    plan.brief = replace(plan.brief or Brief(), **values)
    if "target_mb" in values or "video_bitrate_kbps" in values:
        plan.delivery = DeliveryEncoding(values.get("target_mb"), values.get("video_bitrate_kbps"))
    if values.get("caption_mode") in ("phone", "reference"):
        for caption in plan.captions:
            caption.preset = None
    if values.get("caption_mode") == "none":
        plan.captions = []
        plan.accepted_unsafe_layouts = []
    elif values.get("caption_mode") == "phone":
        from myzing.layout.readability import hold_short_events, phone_word_groups
        from myzing.captions.grouping import join
        groups = []
        for caption in plan.captions:
            parts = phone_word_groups(caption.words)
            if len(parts) <= 1:
                groups.append(caption)
                continue
            for index, words in enumerate(parts):
                groups.append(replace(caption, id=f"{caption.id}-phone-{index+1}",
                    text=join(w.text for w in words), words=words,
                    start=caption.start if index == 0 else words[0].start,
                    end=caption.end if index == len(parts) - 1 else words[-1].end, layout=None))
        if plan.clips:
            hold_short_events(groups, max(c.timeline_end for c in plan.clips))
        plan.captions = groups
        plan.accepted_unsafe_layouts = []
    preset = values.get("caption_mode")
    if preset not in ("punch", "box", "clean") and "caption_mode" not in values and values.get("caption_options"):
        preset = next((c.preset for c in plan.captions if c.preset), None)
    if preset in ("punch", "box", "clean"):
        from myzing.captions.presets import apply_preset
        apply_preset(plan, preset, base_dir=base_dir)
    for caption in plan.captions:
        if values.get("caption_options") and not caption.preset:
            caption.style = CaptionStyle.from_dict({**(caption.style or CaptionStyle(60)).to_dict(), **values["caption_options"]})
            if caption.style.highlight_box_color and caption.words:
                caption.word_timed = True
