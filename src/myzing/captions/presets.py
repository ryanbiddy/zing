"""Apply explicit presets without changing the legacy style path."""

from dataclasses import replace
import unicodedata

from myzing.composition import CaptionStyle, CompositionCaption
from myzing.timing import transform_word

from . import PRESETS
from .grouping import STOPWORDS, group_words, join, nospace, token
from .metrics import font_asset, metrics


BASE_SIZE = {"punch": 97, "box": 81, "clean": 59}  # Output px at a 1080 px short side.
SHRINK = (1., .95, .90, .85, .80)
MINIMUM = {"punch": .3, "box": .3, "clean": 5/6}
_BREAK_AFTER = "/.-_?&=#:"


def clusters(text):
    """Conservative Unicode clusters: marks, selectors and ZWJ emoji stay whole."""
    parts = []
    for ch in text:
        mark = unicodedata.category(ch).startswith("M") or ch == "\u200d"
        modifier = 0x1F3FB <= ord(ch) <= 0x1F3FF
        flag = 0x1F1E6 <= ord(ch) <= 0x1F1FF
        if parts and (mark or modifier or parts[-1].endswith("\u200d") or
                      (flag and len(parts[-1]) == 1 and 0x1F1E6 <= ord(parts[-1]) <= 0x1F1FF)):
            parts[-1] += ch
        else:
            parts.append(ch)
    return parts


def normalize_words(words):
    """Attach standalone punctuation; expose no-space scripts to width grouping."""
    out = []
    for word in words:
        text = unicodedata.normalize("NFC", word.text.strip())
        if out and text and not any(ch.isalnum() for ch in text):
            previous = out.pop()
            sep = " " if any(unicodedata.category(ch) == "So" for ch in text) else ""
            merged = transform_word(previous, previous.start, max(previous.end, word.end),
                                    "caption_attach_punctuation", attached=word.text)
            out.append(replace(merged, text=previous.text+sep+text))
            continue
        pieces = clusters(text) if text and all(nospace(c) or not c.isalnum() for c in text) else [text]
        if len(pieces) == 1:
            out.append(replace(word, text=text))
            continue
        for i, piece in enumerate(pieces):
            a = word.start + (word.end-word.start)*i/len(pieces)
            b = word.start + (word.end-word.start)*(i+1)/len(pieces)
            out.append(replace(transform_word(word, a, b, "caption_script_split", part=i), text=piece))
    return out


def style_for(name, width, height=None):
    # Scale with the short side: a 16:9 frame must not get portrait-width type.
    short = width if height is None else min(width, height)
    size = min(512, max(1, BASE_SIZE[name] * short/1080))
    return CaptionStyle(size, highlight="#0A0A0A" if name == "box" else "#FFD23F",
                        outline_width=min(20, size*(.07 if name == "punch" else 0 if name == "box" else .025)),
                        highlight_box_color="#FFD23F" if name == "box" else None,
                        highlight_box_padding=min(64,size*(.09 if name == "box" else .14)), highlight_box_radius=min(64,size*.18))


def words_width(texts, font, style, name):
    """Advance width of display words laid out as fixed slots on one line."""
    space = font.width(" ", style.size)
    total = sum(font.width(t, style.size) for t in texts)
    total += sum(space for a, b in zip(texts, texts[1:]) if not (nospace(a[-1]) and nospace(b[0])))
    # Every box word reserves padding, including before/after highlighting.
    return total + (2*style.highlight_box_padding*len(texts) if name == "box" else 0)


def line_width(text, font, style, name):
    return words_width(text.split(), font, style, name)


def slot_lines(caption):
    """Per line, the word slots (display text, space before, word index).

    Slots come from the caption's words, not from splitting on spaces, so
    CJK lines without spaces and hyphenated word parts keep one slot per word.
    """
    words = [w.text.upper() if caption.all_caps else w.text for w in caption.words]
    lines, index = [], 0
    for line in caption.text.splitlines():
        found, cursor = [], 0
        while index < len(words):
            at = line.find(words[index], cursor)
            if at < 0 or line[cursor:at].strip(" -"):
                break
            found.append((at, index))
            cursor, index = at + len(words[index]), index + 1
        lines.append([(line[at:found[k+1][0] if k+1 < len(found) else len(line)].strip(),
                       k > 0 and line[at-1:at].isspace(), i) for k, (at, i) in enumerate(found)])
    if index != len(words) or not all(lines):
        raise ValueError(f"caption {caption.id}: preset words do not match the caption text; reapply the preset.")
    return lines


def line_widths(caption, font, style):
    space = font.width(" ", style.size)
    pad = 2*style.highlight_box_padding if caption.preset == "box" else 0
    return [sum(font.width(t, style.size) + pad + (space if gap else 0) for t, gap, _ in slots)
            for slots in slot_lines(caption)]


def rail_width(width, height):
    # Width of the existing asymmetric safe area; the rail uses its center.
    return width * (.78 if height > width else .90)


def phone_floor(plan, start, end, name, source_dimensions=None):
    """DOGFOOD1's phone size floor; Clean follows BBC subtitle sizes instead."""
    if name == "clean":
        return 0.
    from myzing.layout.readability import phone_size, picture_width
    return phone_size(plan.width, plan.height, picture_width(plan, start, end, source_dimensions))


def _piece(text, p, q, display):
    """Display form of text[p:q]; a hyphen marks a break between letters."""
    value = display(text[p:q])
    if q < len(text) and text[q-1].isalpha() and text[q].isalpha() and not nospace(text[q-1]):
        value += "-"
    return value


def split_word(text, fits, display=str):
    """(start, end) offsets of a word too wide even alone.

    Greedy by measured width, preferring a break after URL/compound punctuation
    in the second half of a part; CJK breaks between characters.
    """
    spans, p = [], 0
    boundaries, offset = [], 0
    for part in clusters(text):
        offset += len(part)
        boundaries.append(offset)
    while p < len(text):
        possible = [q for q in boundaries if q > p and fits(_piece(text, p, q, display))]
        if not possible:
            raise ValueError("A caption glyph cluster cannot fit at the phone floor; choose clean.")
        q = max(possible)
        if q < len(text):
            better = max((k for k in boundaries if p < k < q and text[k-1] in _BREAK_AFTER), default=None)
            if better is not None and better - p >= (q - p) / 2:
                q = better
        spans.append((p, q))
        p = q
    return spans


def fit_long_words(words, display, measure, available):
    """Keep every word inside the line by measured cluster splits, at the phone floor."""
    kept, shown, solo, notes = [], [], {}, []
    for word in words:
        value = display(word.text)
        prefix = []
        for prev in reversed(kept):
            if token(prev) not in STOPWORDS:
                break
            prefix.insert(0, display(prev.text))
        width = measure([*prefix, value])
        if width <= available:
            kept.append(word)
            shown.append(value)
        else:
            spans = split_word(word.text, lambda piece: measure([*prefix, piece]) <= available, display)
            t = word.start
            for i, (p, q) in enumerate(spans):
                end = word.end if i+1 == len(spans) else word.start + (word.end-word.start)*q/len(word.text)
                part = transform_word(word, t, end, "caption_long_word_split", corrected=True,
                                      part=f"{i+1}/{len(spans)}")
                kept.append(replace(part, text=word.text[p:q]))
                shown.append(_piece(word.text, p, q, display))
                t = end
            notes.append(f"Word {value!r} or its protected prefix is wider than the caption line; "
                         f"split into {len(spans)} parts with proportional timing.")
    return kept, shown, solo, notes


def _sync(word, start, end):
    """Display-only edge trim within SYNC; provenance keeps the spoken times."""
    if (start, end) == (word.start, word.end):
        return word
    return transform_word(word, start, end, "caption_display_sync", corrected=True)


def apply_preset(plan, name, *, vad=True, base_dir=None):
    if name not in PRESETS:
        raise ValueError("Caption preset: choose punch, box or clean.")
    font = font_asset(name)
    face = metrics(font.path, font.sha256)
    style = style_for(name, plan.width, plan.height)
    options = plan.brief.caption_options if plan.brief else {}
    style = CaptionStyle.from_dict({**style.to_dict(), **options})
    fps = plan.fps.numerator/plan.fps.denominator
    display = (lambda text: text) if name == "clean" else (lambda text: text.upper())
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
            from .timing import already_clamped, clamp_words, speech_intervals
            from pathlib import Path
            source = Path(base_dir) / clip.src if base_dir is not None else clip.src
            if not all(already_clamped(w) for w in words):
                spans, warning = speech_intervals(source)
                if warning:
                    notes.append(warning)
                if spans is not None and not clip.speed_map:
                    offset = clip.timeline_start-clip.src_in
                    words, warnings = clamp_words(words, [(a+offset, b+offset) for a,b in spans])
                    notes.extend(warnings)
        source_words = normalize_words(words)
        notes.extend(face.substitution_notes(display(w.text) for w in source_words))
        floor = phone_floor(plan, clip.timeline_start, clip.timeline_end, name)
        scales = [s for s in SHRINK if style.size*s >= floor-1e-6] or [min(512, floor)/style.size]
        scales = sorted(set([*scales, min(512, floor)/style.size] if floor else scales), reverse=True)
        candidates = []
        for scale in scales:
            trial = replace(style, size=min(512, style.size*scale), outline_width=min(20, style.outline_width*scale),
                            highlight_box_padding=min(64, style.highlight_box_padding*scale),
                            highlight_box_radius=min(64, style.highlight_box_radius*scale))
            # Box slot widths already include both plate paddings. Only Punch
            # overshoots during entry; reserving that overshoot for Box creates
            # needless one-word leftovers such as "WITH CHANNEL" / "5."
            pad = trial.outline_width
            overshoot = 1.05 if name == "punch" else 1.
            available = rail_width(plan.width, plan.height)/overshoot - 2*pad
            cap = (30 if plan.height > plan.width else 42) if name == "clean" else None
            measure = lambda texts, trial=trial: (float("inf") if cap and len(join(texts)) > cap
                                                   else words_width(texts, face, trial, name))
            fitted, shown, solo, long_notes = fit_long_words(source_words, display, measure, available)
            alone = {shown[i]: factor for i, factor in solo.items()}

            def fits(texts, measure=measure, alone=alone):
                width = measure(texts)
                return width*alone[texts[0]] if len(texts) == 1 and texts[0] in alone else width
            shown_words = [replace(w, text=s) for w, s in zip(fitted, shown)]
            try:
                grouped = group_words(shown_words, fits, available, preset=name, portrait=plan.height > plan.width,
                                      start=clip.timeline_start, end=clip.timeline_end, fps=fps, solo=solo)
            except ValueError:
                continue
            groups, _, starts, ends, _ = grouped
            short = sum(e-s < MINIMUM[name]-1e-6 and not (k+1 == len(groups) and e >= clip.timeline_end-1e-6)
                        for k, (s, e) in enumerate(zip(starts, ends)))
            orphan_count = sum(len(part) == 1 for part in groups)
            candidates.append(((len(long_notes), short, orphan_count, -scale), trial, fitted, shown_words, solo, grouped, long_notes))
            if short == 0 and (orphan_count == 0 or name == "clean"):
                break
        if not candidates:
            raise ValueError("Caption words cannot fit together at the phone size floor; choose clean or edit the transcript.")
        _, shot_style, fitted, shown_words, solo, grouped, long_notes = min(candidates, key=lambda row: row[0])
        groups, lines, starts, ends, warnings = grouped
        notes.extend(long_notes + warnings)
        index = {id(w): i for i, w in enumerate(shown_words)}
        for part, visual, start, end in zip(groups, lines, starts, ends):
            spoken = [fitted[index[id(w)]] for w in part]
            spoken[0] = _sync(spoken[0], max(spoken[0].start, start), spoken[0].end)
            spoken[-1] = _sync(spoken[-1], spoken[-1].start, min(spoken[-1].end, end))
            cue_style = shot_style
            factor = solo.get(index[id(part[0])]) if len(part) == 1 else None
            if factor:
                cue_style = replace(shot_style, size=shot_style.size*factor, outline_width=shot_style.outline_width*factor,
                                    highlight_box_padding=shot_style.highlight_box_padding*factor,
                                    highlight_box_radius=shot_style.highlight_box_radius*factor)
            result.append(CompositionCaption(id=f"{clip.id}-{name}-{len(result)+1}",
                text="\n".join(visual), start=start, end=end, words=spoken,
                all_caps=name != "clean", word_timed=name != "clean", position="lower",
                font=font, style=replace(cue_style), preset=name))
    if not result and original:
        raise ValueError("Caption presets need timed words; transcribe the local source first.")
    plan.captions = result
    plan.accepted_unsafe_layouts = []
    plan.warnings.extend(note for note in dict.fromkeys(notes) if note not in plan.warnings)
