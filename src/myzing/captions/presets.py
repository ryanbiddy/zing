"""Apply explicit presets without changing the legacy style path."""

from dataclasses import replace
import unicodedata

from myzing.composition import CaptionStyle, CompositionCaption
from myzing.timing import transform_word

from . import PRESETS
from .grouping import display_boundaries, separator, STOPWORDS, group_words, join, nospace, token, numeric_token
from .metrics import font_asset, metrics


BASE_SIZE = {"punch": 97, "box": 81, "clean": 59}  # Output px at a 1080 px short side.
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
    words = list(words)
    _, numeric = display_boundaries([w.text for w in words])
    out = []
    for index, word in enumerate(words):
        text = unicodedata.normalize("NFC", word.text.strip())
        previous_text = out[-1].text if out else ""
        # Glue detached clitics ("I" "'m") and compound hyphens ("well" "-" "known",
        # "well" "-known"); never a finished possessive ("students'" "work"), a
        # quote token ("'n'"), a dash after punctuation ("end." "-next") or "-5".
        compound = (text == "-" and previous_text[-1:].isalnum()
                    or (previous_text.endswith("-") and previous_text[-2:-1].isalnum() and text[:1].isalnum())
                    or (len(text) > 1 and text[0] == "-" and text[1].isalpha() and previous_text[-1:].isalnum()))
        if out and (text in ("'s", "’s", "'re", "’re", "'ve", "’ve", "'ll", "’ll", "'d", "’d", "'m", "’m", "n't", "n’t")
                    or compound):
            previous = out.pop()
            merged = transform_word(previous, previous.start, max(previous.end, word.end),
                                    "caption_attach_punctuation", attached=word.text)
            out.append(replace(merged, text=previous.text + text))
            continue
        if (out and text and not any(ch.isalnum() for ch in text)
                and text not in "$£€¥₹" and index not in numeric
                and not (text in (",", ".") and out[-1].text[-1:].isdigit())
                and separator(out[-1].text, text)):
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
    gaps = sum(bool(space) for space in display_boundaries(texts)[0])
    total += space * gaps
    # Joined numeric tokens share a display run; padding must not reinsert a
    # visible space into "$3,000" while their original timings stay separate.
    runs = bool(texts) + gaps
    return total + (2*style.highlight_box_padding*runs if name == "box" else 0)


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
    return [pad + sum(font.width(t, style.size) + (pad + space if gap else 0) for t, gap, _ in slots)
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


def _piece(text, p, q, display, hyphenate=False, suffix=""):
    """Display form of a piece; pop presets mark every non-final break."""
    value = display(text[p:q])
    if q < len(text) and (hyphenate or
            (text[q-1].isalpha() and text[q].isalpha() and not nospace(text[q-1]))):
        value += "-"
    elif q == len(text):
        value += suffix
    return value


def split_word(text, fits, display=str, *, hyphenate=False, suffix=""):
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
        possible = [q for q in boundaries if q > p and fits(_piece(text, p, q, display, hyphenate, suffix))]
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


def _split_suffix(word):
    """Recover display-only hyphens when a delivery reapplies the preset."""
    for adjustment in reversed((word.timing or {}).get("adjustments", [])):
        if adjustment.get("method") == "caption_long_word_split":
            if "display_suffix" in adjustment:
                return adjustment["display_suffix"]
            # Plans written before display_suffix still identify each part.
            part, _, count = adjustment.get("part", "").partition("/")
            return "-" if part.isdigit() and count.isdigit() and int(part) < int(count) else ""
    return ""


def fit_long_words(words, display, measure, available, *, scales=(1.,), outline=0., keep_whole=True):
    """Prefer whole words, then solo scaling, then splits at the readable floor.

    scales are descending factors relative to the current style, including its
    phone floor. Clean retains its existing prefix-aware splitting policy.
    """
    kept, shown, solo, notes = [], [], {}, []
    _, numeric = display_boundaries([w.text for w in words])
    protected = set(numeric) | {i-1 for i in numeric}
    for index, word in enumerate(words):
        suffix = _split_suffix(word) if keep_whole else ""
        value = display(word.text) + suffix
        if index in protected or numeric_token(word.text):
            if index not in numeric:
                stop = index+1
                while stop in numeric:
                    stop += 1
                if measure([display(w.text) for w in words[index:stop]]) > available:
                    raise ValueError("A joined number cannot fit at this caption size; reduce the size within readable limits or choose clean.")
            kept.append(word)
            shown.append(value)
            continue
        prefix = []
        for prev in reversed(kept):
            if token(prev) not in STOPWORDS:
                break
            prefix.insert(0, display(prev.text))
        width = measure([value] if keep_whole else [*prefix, value])
        if width <= available:
            kept.append(word)
            shown.append(value)
        else:
            factor = 1.
            if keep_whole:
                factor = next((s for s in scales if width*s <= available + 2*outline*(1-s)), None)
                if factor is not None:
                    solo[len(kept)] = factor
                    kept.append(word)
                    shown.append(value)
                    notes.append(f"Word {value!r} is shown alone at {factor:.0%} scale to fit the caption line.")
                    continue
                factor = min(scales)
                prefix = []
            spans = split_word(word.text,
                lambda piece: measure([*prefix, piece])*factor <= available + 2*outline*(1-factor),
                display, hyphenate=keep_whole, suffix=suffix)
            t = word.start
            for i, (p, q) in enumerate(spans):
                end = word.end if i+1 == len(spans) else word.start + (word.end-word.start)*q/len(word.text)
                visible = _piece(word.text, p, q, display, keep_whole, suffix)
                details = {"display_suffix": visible[len(display(word.text[p:q])):]} if keep_whole else {}
                part = transform_word(word, t, end, "caption_long_word_split", corrected=True,
                                      part=f"{i+1}/{len(spans)}", **details)
                if keep_whole:
                    solo[len(kept)] = factor
                kept.append(replace(part, text=word.text[p:q]))
                shown.append(visible)
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
    # Choose one size before grouping any shot. Only an indivisible display
    # word/number can lower it; multiword groups must regroup at this size.
    floor = max((phone_floor(plan, c.timeline_start, c.timeline_end, name) for c in plan.clips), default=0.)
    minimum = floor or min(style.size, 24.)
    target = max(style.size, minimum)
    normalized = normalize_words([w for c in original for w in c.words])
    from .grouping import display_units
    units = display_units([display(w.text) + _split_suffix(w) for w in normalized])
    largest = max((words_width([word], face, style, name) for word in units), default=0.)
    rail = rail_width(plan.width, plan.height) / (1.05 if name == "punch" else 1.)
    if largest + 2*style.outline_width > rail:
        target = max(minimum, min(target, style.size * rail / (largest + 2*style.outline_width)))
    factor = target / style.size
    style = replace(style, size=target, outline_width=min(20, style.outline_width*factor),
                    highlight_box_padding=min(64, style.highlight_box_padding*factor),
                    highlight_box_radius=min(64, style.highlight_box_radius*factor))
    if factor < 1:
        notes.append(f"Whole draft caption size reduced to {target:.2f}px for its widest word; phone floor preserved.")
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
        # Group at the already chosen draft size. Clean may wrap to two
        # lines; pop styles use smaller word groups. Floor splits retain timing.
        overshoot = 1.05 if name == "punch" else 1.
        available = rail_width(plan.width, plan.height)/overshoot - 2*style.outline_width
        cap = (30 if plan.height > plan.width else 42) if name == "clean" else None
        def measure(texts):
            return (float("inf") if cap and len(join(texts)) > cap
                    else words_width(texts, face, style, name))
        fitted, shown, solo, long_notes = fit_long_words(source_words, display, measure, available,
            scales=(1.,), outline=style.outline_width, keep_whole=name != "clean")
        shown_words = [replace(w, text=s) for w, s in zip(fitted, shown)]
        grouped = group_words(shown_words, measure, available, preset=name, portrait=plan.height > plan.width,
                              start=clip.timeline_start, end=clip.timeline_end, fps=fps, solo=solo)
        groups, lines, starts, ends, warnings = grouped
        notes.extend(long_notes + warnings)
        index = {id(w): i for i, w in enumerate(shown_words)}
        for part, visual, start, end in zip(groups, lines, starts, ends):
            spoken = [fitted[index[id(w)]] for w in part]
            spoken[0] = _sync(spoken[0], max(spoken[0].start, start), spoken[0].end)
            spoken[-1] = _sync(spoken[-1], spoken[-1].start, min(spoken[-1].end, end))
            result.append(CompositionCaption(id=f"{clip.id}-{name}-{len(result)+1}",
                text="\n".join(visual), start=start, end=end, words=spoken,
                all_caps=name != "clean", word_timed=name != "clean", position="lower",
                font=font, style=replace(style), preset=name))
    if not result and original:
        raise ValueError("Caption presets need timed words; transcribe the local source first.")
    plan.captions = result
    plan.accepted_unsafe_layouts = []
    plan.warnings.extend(note for note in dict.fromkeys(notes) if note not in plan.warnings)
