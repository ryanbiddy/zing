"""Apply explicit presets without changing the legacy style path."""

from dataclasses import replace
import unicodedata

from myzing.composition import CaptionStyle, CompositionCaption
from myzing.timing import transform_word

from . import PRESETS
from .grouping import group_words
from .metrics import font_asset, metrics


def style_for(name, width):
    size = min(512, max(1, {"punch": 97, "box": 81, "clean": 59}[name] * width/1080))
    return CaptionStyle(size, highlight="#0A0A0A" if name == "box" else "#FFD23F",
                        outline_width=min(20, size*(.07 if name == "punch" else 0 if name == "box" else .025)),
                        highlight_box_color="#FFD23F" if name == "box" else None,
                        highlight_box_padding=min(64,size*.14), highlight_box_radius=min(64,size*.18))


def line_width(text, font, style, name):
    # Every box word reserves padding, including before/after highlighting.
    padding = 2*style.highlight_box_padding*len(text.split()) if name == "box" else 0
    return font.width(text, style.size) + padding


def rail_width(width, height):
    # Center x=.5 with the existing right-side vertical UI reserve at .84.
    return width * (.68 if height > width else .86)


def apply_preset(plan, name, *, vad=True, base_dir=None):
    if name not in PRESETS:
        raise ValueError("Caption preset: choose punch, box or clean.")
    font = font_asset(name)
    face = metrics(font.path, font.sha256)
    style = style_for(name, plan.width)
    options = plan.brief.caption_options if plan.brief else {}
    style = CaptionStyle.from_dict({**style.to_dict(), **options})
    original = list(plan.captions)
    result, notes = [], []
    for clip in plan.clips:
        # Group on shot boundaries; no caption can hold into the next shot.
        words = [w for c in original for w in c.words
                 if clip.timeline_start <= w.start < clip.timeline_end]
        words = sorted({(w.start, w.end, w.text): w for w in words}.values(), key=lambda w: w.start)
        words = [transform_word(w, w.start, min(w.end, clip.timeline_end), "caption_shot_clamp", corrected=True)
                 if w.end > clip.timeline_end else w for w in words]
        if not words:
            continue
        if vad:
            from .timing import clamp_words, speech_intervals
            from pathlib import Path
            source = Path(base_dir) / clip.src if base_dir is not None else clip.src
            spans, warning = speech_intervals(source)
            if warning:
                notes.append(warning)
            if spans is not None and not clip.speed_map:
                offset = clip.timeline_start-clip.src_in
                words, warnings = clamp_words(words, [(a+offset, b+offset) for a,b in spans])
                notes.extend(warnings)
        source_words = [replace(w, text=unicodedata.normalize("NFC", w.text.strip())) for w in words]
        words = [replace(w, text=w.text.upper()) for w in source_words] if name != "clean" else source_words
        source_by_display = {id(display): source for display, source in zip(words, source_words)}
        candidates = []
        for scale in (1., .95, .90, .85, .80):
            trial = replace(style, size=style.size*scale, outline_width=style.outline_width*scale,
                            highlight_box_padding=style.highlight_box_padding*scale,
                            highlight_box_radius=style.highlight_box_radius*scale)
            measure = lambda s: line_width(s, face, trial, name)
            try:
                grouped = group_words(words, measure,
                    (rail_width(plan.width, plan.height)-2*trial.outline_width)/1.05,
                    preset=name, portrait=plan.height > plan.width, end=clip.timeline_end,
                    fps=plan.fps.numerator/plan.fps.denominator)
            except ValueError:
                continue
            orphan_count = sum(len(part) == 1 for part in grouped[0])
            candidates.append((orphan_count, -scale, trial, grouped))
            if orphan_count == 0 or name == "clean":
                break
        if not candidates:
            raise ValueError(f"Caption {name} cannot fit a protected phrase at this width; choose clean or correct the transcript boundaries.")
        _, _, shot_style, (groups, lines, ends, warnings) = min(candidates, key=lambda row: row[:2])
        notes.extend(warnings)
        for part, visual, end in zip(groups, lines, ends):
            start = part[0].start
            if name == "clean" and end-start < 5/6:
                fps = plan.fps.numerator/plan.fps.denominator
                floor = max(clip.timeline_start, result[-1].end+2/fps if result else 0)
                start = min(start, max(floor, start-2/fps, end-5/6))
            result.append(CompositionCaption(id=f"{clip.id}-{name}-{len(result)+1}",
                text="\n".join(visual), start=start, end=end, words=[source_by_display[id(w)] for w in part],
                all_caps=name != "clean", word_timed=name != "clean", position="lower",
                font=font, style=replace(shot_style), preset=name))
    if not result and original:
        raise ValueError("Caption presets need timed words; transcribe the local source first.")
    plan.captions = result
    plan.accepted_unsafe_layouts = []
    plan.warnings.extend(note for note in dict.fromkeys(notes) if note not in plan.warnings)
