"""Shared opt-in CLI overrides for render, match and studio."""


def add_options(parser):
    parser.add_argument("--caption-options", help='JSON CaptionStyle overrides, e.g. {"highlight_box_color":"#FFD23F","highlight":"#0A0A0A"}')
    parser.add_argument("--caption-mode", choices=["reference", "phone", "none"])
    parser.add_argument("--picture-crop", choices=["auto", "on", "off"], help="crop static broadcast chrome when confident; on requires a confident picture")
    budget = parser.add_mutually_exclusive_group()
    budget.add_argument("--target-mb", type=float, help="target file size in decimal MB, x264 two-pass")
    budget.add_argument("--video-bitrate-kbps", type=float, help="x264 two-pass average video bitrate, kb/s")


def overrides(args):
    import json
    from myzing.brief.models import Brief
    values = {name: getattr(args, name) for name in ("caption_options", "caption_mode", "picture_crop", "target_mb", "video_bitrate_kbps")
              if getattr(args, name, None) is not None}
    if "caption_options" in values:
        values["caption_options"] = json.loads(values["caption_options"])
    Brief.from_answers(values)
    return values


def apply_plan(plan, values):
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
    if values.get("caption_mode") == "none":
        plan.captions = []
        plan.accepted_unsafe_layouts = []
    elif values.get("caption_mode") == "phone":
        from myzing.layout.readability import hold_short_events, phone_word_groups
        groups = []
        for caption in plan.captions:
            parts = phone_word_groups(caption.words)
            if len(parts) <= 1:
                groups.append(caption)
                continue
            for index, words in enumerate(parts):
                groups.append(replace(caption, id=f"{caption.id}-phone-{index+1}",
                    text=" ".join(w.text for w in words), words=words,
                    start=caption.start if index == 0 else words[0].start,
                    end=caption.end if index == len(parts) - 1 else words[-1].end, layout=None))
        if plan.clips:
            hold_short_events(groups, max(c.timeline_end for c in plan.clips))
        plan.captions = groups
        plan.accepted_unsafe_layouts = []
    for caption in plan.captions:
        if values.get("caption_options"):
            caption.style = CaptionStyle.from_dict({**(caption.style or CaptionStyle(60)).to_dict(), **values["caption_options"]})
            if caption.style.highlight_box_color and caption.words:
                caption.word_timed = True
