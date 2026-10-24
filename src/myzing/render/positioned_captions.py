"""V2 ASS compilation with measured ink bounds and timed phrase highlights.

V1's serializer is intentionally separate. Newlines are explicit; overflowing
text fails with a wrapping remedy instead of silently moving outside safe boxes.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from myzing.composition import CaptionStyle, Composition, CompositionCaption, frame_index, frame_time
from myzing.layout.types import Box, box_at
from myzing.project.models import Rational

from .captions import caption_anchor
from .font_files import ass_em_scale
from .pipeline import RenderError
from .validation import EDLValidationError


def escape_ass(text: str) -> str:
    # ASS does NOT have a \\ escape. A zero-width word joiner prevents the
    # following N/n/h/brace from being interpreted as an escape after a literal
    # backslash. Braces themselves use libass's documented literal escapes.
    return (text.replace("\r\n", "\n").replace("\r", "\n")
            .replace("\\", "\\\u2060").replace("{", r"\{").replace("}", r"\}")
            .replace("\n", r"\N"))


def caption_runs(caption: CompositionCaption) -> list[tuple[str, int | None]]:
    """Retain phrase whitespace/punctuation and associate exact word spans."""
    text = caption.text.upper() if caption.all_caps else caption.text
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
        raise EDLValidationError(f"caption {caption.id}: unsupported control character in text")
    if not caption.word_timed:
        return [(text, None)]
    runs = []
    cursor = 0
    for index, word in enumerate(caption.words):
        value = word.text.upper() if caption.all_caps else word.text
        start = text.find(value, cursor)
        if start < 0:
            raise EDLValidationError(
                f"caption {caption.id}: word {word.text!r} does not match phrase text in order; "
                "correct the phrase or word text before rendering",
            )
        runs.extend([(text[cursor:start], None), (value, index)])
        cursor = start + len(value)
    runs.append((text[cursor:], None))
    return [(value, index) for value, index in runs if value]


def _color(value: str) -> str:
    return "&H" + value[5:7] + value[3:5] + value[1:3] + "&"


def _n(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _stamp(cs: int) -> str:
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def frame_centisecond(index: int, fps: Rational) -> int:
    """An ASS boundary after frame index-1 and at/before frame index.

    Choose the first centisecond strictly after the preceding frame, using
    rational arithmetic. Subtracting a centisecond from a rounded timestamp
    can instead select the preceding frame, or collapse two word boundaries.
    The renderer supports ASS rates up to 100 fps.
    """
    current = frame_time(index, fps)
    boundary = 0 if index == 0 else int(frame_time(index - 1, fps) * 100) + 1
    if Fraction(boundary, 100) > current:
        raise EDLValidationError("ASS frame boundaries require fps at or below 100")
    return boundary


def caption_frame_timing(
    caption: CompositionCaption, fps: Rational, frame_limit: int,
) -> tuple[int, int, list[tuple[int, int]], list[str]]:
    """Schedule positive words in order, with at least one exclusive frame each.

    Starts move forward only as far as the preceding word requires. Ends keep
    their original frame unless one frame is needed. Extend the phrase when
    necessary, but fail rather than silently lose words beyond the video end.
    Source timings/provenance are never modified; warnings describe the render.
    """
    first = frame_index(caption.start, fps, rounding="ceil")
    last = max(first + 1, min(frame_limit, frame_index(caption.end, fps, rounding="ceil")))
    words, warnings = [], []
    previous = first
    for i, word in enumerate(caption.words if caption.word_timed else []):
        start = max(previous, frame_index(word.start, fps, rounding="ceil"))
        end = max(start + 1, min(frame_limit, frame_index(word.end, fps, rounding="ceil")))
        words.append((start, end))
        previous = end
        if (frame_time(start, fps), frame_time(end, fps)) != (Fraction(str(word.start)), Fraction(str(word.end))):
            warnings.append(
                f"caption {caption.id}: word {i + 1} {word.text!r} render timing "
                f"{word.start:g}-{word.end:g}s -> frames [{start}, {end}) at "
                f"{fps.numerator}/{fps.denominator} fps "
                "(frame quantization; minimum one frame; ordered without overlap)",
            )
    last = max(last, previous)
    if last > frame_limit:
        raise EDLValidationError(
            f"caption {caption.id}: one frame per word/caption needs output frames through {last - 1}, "
            f"but the video has {frame_limit} frames; extend the video or move the caption earlier",
        )
    if (frame_time(first, fps), frame_time(last, fps)) != (Fraction(str(caption.start)), Fraction(str(caption.end))):
        warnings.append(
            f"caption {caption.id}: render window {caption.start:g}-{caption.end:g}s -> "
            f"frames [{first}, {last}) at {fps.numerator}/{fps.denominator} fps "
            "(frame quantization; extend for words or clip to video end)",
        )
    return first, last, words, warnings


def _dialogue(start: int, end: int, text: str, *, layer: int = 1) -> str:
    return f"Dialogue: {layer},{_stamp(start)},{_stamp(end)},Default,,0,0,0,,{text}\n"


def _header(width: int, height: int, font: str = "Arial") -> str:
    return (
        "[Script Info]\nScriptType: v4.00+\nTitle: Zing Composition v2 captions\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        "\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},32,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n"
        "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _tags(caption: CompositionCaption, style: CaptionStyle, font: str, font_scale: float) -> str:
    align = {"left": 4, "center": 5, "right": 6}[caption.alignment]
    # A private family contains exactly one supplied face. Request a low weight
    # so libass cannot synthesize faux bold on a light face (\b0 means 400).
    bold = 1 if caption.font is None else 100
    return (rf"\fn{font}\fs{_n(style.size * font_scale)}\an{align}\q2\b{bold}\i0"
            rf"\bord{_n(style.outline_width)}\shad0\1c{_color(style.color)}"
            rf"\3c{_color(style.outline_color)}")


def _text(runs: list[tuple[str, int | None]], style: CaptionStyle, active: int | None = None,
          completed: set[int] = frozenset()) -> str:
    def color(index):
        if index is None:
            return style.color
        if index == active:
            return style.highlight
        return (style.after_color if index in completed else style.before_color) or style.color
    return "".join("{" + rf"\1c{_color(color(index))}" + "}" + escape_ass(value) for value, index in runs)


def _measure(caption: CompositionCaption, style: CaptionStyle, font: str,
             runs: list[tuple[str, int | None]], width: int, height: int,
             directory: Path, ffmpeg: str, caption_filter: str, font_scale: float,
             word_index: int | None = None) -> tuple[float, float, float, float]:
    """Measure libass ink+outline, relative to the ASS anchor, using raw gray.

    Calibration uses the actual registered font, shaping and explicit breaks.
    White probe colors expose dark outlines too. No image package is needed.
    """
    width, height = max(width * 2, 1024), max(height * 2, 512)
    x, y = width // 2, height // 2
    probe_style = replace(style, color="#FFFFFF", highlight="#FFFFFF", outline_color="#FFFFFF")
    probe_style = replace(probe_style, before_color=None, after_color=None)
    # Preserve the whole shaped phrase and its whitespace. Only the requested
    # word emits white ink; alpha/color changes do not alter glyph placement.
    probe_text = _text(runs, probe_style) if word_index is None else "".join(
        "{" + rf"\1c{_color('#FFFFFF' if i == word_index else '#000000')}"
        + rf"\3c{_color('#FFFFFF' if i == word_index else '#000000')}" + "}" + escape_ass(value)
        for value, i in runs)
    text = "{" + _tags(caption, probe_style, font, font_scale) + rf"\pos({x},{y})" + "}" + probe_text
    (directory / "caption-probe.ass").write_text(_header(width, height, font) + _dialogue(0, 100, text),
                                                encoding="utf-8", newline="\n")
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "verbose", "-f", "lavfi", "-i",
             f"color=black:s={width}x{height}:r=1:d=1", "-vf",
             f"{caption_filter}=filename='caption-probe.ass':fontsdir='fonts',format=gray",
             "-frames:v", "1", "-threads", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            cwd=directory, capture_output=True, check=False, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RenderError(f"caption {caption.id}: could not measure libass text: {exc}") from exc
    log = result.stderr.decode("utf-8", errors="replace")
    if result.returncode or len(result.stdout) != width * height:
        raise RenderError(f"caption {caption.id}: libass geometry probe failed: {log[-2000:]}")
    if caption.font is not None:
        selections = [line for line in log.splitlines() if "fontselect:" in line]
        if (not selections or any(font not in line.split("->")[-1] for line in selections)
                or "failed to find" in log or "Glyph " in log):
            raise EDLValidationError(
                f"caption {caption.id}: the supplied font cannot render all text without font substitution; "
                "supply a font containing every requested glyph",
            )
    mask = result.stdout.translate(bytes(0 if value < 16 else 1 for value in range(256)))
    left, right, top, bottom = width, -1, height, -1
    for row in range(height):
        pixels = mask[row * width:(row + 1) * width]
        first = pixels.find(b"\1")
        if first >= 0:
            left, right = min(left, first), max(right, pixels.rfind(b"\1") + 1)
            top, bottom = min(top, row), row + 1
    if right < 0:
        raise EDLValidationError(f"caption {caption.id}: text has no visible glyphs")
    if left <= 1 or top <= 1 or right >= width - 1 or bottom >= height - 1:
        raise EDLValidationError(f"caption {caption.id}: text exceeds frame bounds; add line breaks or reduce size")
    return left - x, top - y, right - x, bottom - y


def _motion(a: tuple[float, float], b: tuple[float, float], milliseconds: int, offset: int = 0) -> str:
    if a == b:
        return rf"\pos({_n(a[0])},{_n(a[1])})"
    return rf"\move({_n(a[0])},{_n(a[1])},{_n(b[0])},{_n(b[1])},{offset},{milliseconds})"


def _rounded_rectangle(w, h, radius):
    """ASS vector path; cubic corners work with libass on FFmpeg 6+."""
    r = min(radius, w / 2, h / 2)
    k = r * .55228475
    return (f"m {_n(r)} 0 l {_n(w-r)} 0 "
            f"b {_n(w-r+k)} 0 {_n(w)} {_n(r-k)} {_n(w)} {_n(r)} "
            f"l {_n(w)} {_n(h-r)} b {_n(w)} {_n(h-r+k)} {_n(w-r+k)} {_n(h)} {_n(w-r)} {_n(h)} "
            f"l {_n(r)} {_n(h)} b {_n(r-k)} {_n(h)} 0 {_n(h-r+k)} 0 {_n(h-r)} "
            f"l 0 {_n(r)} b 0 {_n(r-k)} {_n(r-k)} 0 {_n(r)} 0")


def generate_positioned_ass(composition: Composition, fonts: dict[str, tuple[str, bytes]],
                            directory: Path, ffmpeg: str, caption_filter: str) -> Path:
    """Compile ordered frame highlights and sample the original piecewise path."""
    font_dir = directory / "fonts"
    font_dir.mkdir(exist_ok=True)
    receipts = []
    for caption in composition.captions:
        if caption.id in fonts:
            name, data = fonts[caption.id]
            (font_dir / f"{name}.ttf").write_bytes(data)
            receipts.append({"event_id": caption.id, "source": caption.font.to_dict(),
                             "registered_family": name, "registered_file": f"fonts/{name}.ttf"})
    default_font = next(iter(fonts.values()))[0] if fonts else "Arial"
    lines = [_header(composition.width, composition.height, default_font)]
    measurements = {}
    preset_geometry = []
    frame_limit = frame_index(max(c.timeline_end for c in composition.clips), composition.fps, rounding="nearest")
    for caption in composition.captions:
        if caption.preset:
            from myzing.captions.render import compile_caption
            events, receipt = compile_caption(caption, composition, *fonts[caption.id], frame_limit)
            lines.extend(events)
            preset_geometry.append(receipt)
            continue
        width, height = composition.width, composition.height
        style = caption.style or CaptionStyle(
            max(24, round(min(width, height) / 12)), highlight="#FFDC00",
            outline_width=max(2, round(min(width, height) / 270)),
        )
        scale = caption.layout.scale if caption.layout else 1.0
        style = replace(style, size=style.size * scale, outline_width=style.outline_width * scale,
                        highlight_box_padding=style.highlight_box_padding * scale,
                        highlight_box_radius=style.highlight_box_radius * scale)
        font = fonts[caption.id][0] if caption.id in fonts else "Arial"
        font_scale = ass_em_scale(fonts[caption.id][1]) if caption.id in fonts else 1.0
        runs = caption_runs(caption)
        key = (font, style.size, style.outline_width, caption.alignment, tuple(runs))
        if key not in measurements:
            measurements[key] = _measure(caption, style, font, runs, width, height, directory, ffmpeg, caption_filter, font_scale)
        left, top, right, bottom = measurements[key]
        ink_width, ink_height = right - left, bottom - top
        padding = max(4 * scale if style.box_color is not None else 0,
                      style.highlight_box_padding if style.highlight_box_color else 0)
        word_bounds = {}
        if style.highlight_box_color and caption.word_timed:
            for index in range(len(caption.words)):
                word_key = (*key, index)
                if word_key not in measurements:
                    measurements[word_key] = _measure(caption, style, font, runs, width, height,
                                                       directory, ffmpeg, caption_filter, font_scale, index)
                word_bounds[index] = measurements[word_key]
        if caption.layout is not None:
            path = caption.layout.as_path()
            boxes = [k.box for k in path]
        else:
            x, y = caption_anchor(caption.position, width, height)
            bw, bh = (ink_width + 2 * padding) / width, (ink_height + 2 * padding) / height
            if bw > 1 or bh > 1 or x / width - bw / 2 < 0 or y / height - bh / 2 < 0 or x / width + bw / 2 > 1 or y / height + bh / 2 > 1:
                raise EDLValidationError(f"caption {caption.id}: text exceeds frame bounds; add line breaks or reduce size")
            boxes = [Box(x / width - bw / 2, y / height - bh / 2, bw, bh)]
            path = []
        if any(ink_width + 2 * padding > b.width * width + 1 or ink_height + 2 * padding > b.height * height + 1 for b in boxes):
            raise EDLValidationError(
                f"caption {caption.id}: text/outline/plate exceeds its layout box; "
                "add explicit line breaks, reduce size or replan the layout",
            )

        def box(time: float) -> Box:
            return box_at(path, time) if path else boxes[0]

        def anchor(time: float) -> tuple[float, float]:
            b = box(time)
            if caption.alignment == "left":
                x = b.x * width + padding - left
            elif caption.alignment == "right":
                x = b.right * width - padding - right
            else:
                x = b.center[0] * width - (left + right) / 2
            return x, b.center[1] * height - (top + bottom) / 2

        first, last, word_frames, _ = caption_frame_timing(caption, composition.fps, frame_limit)
        boundaries = {first, last}
        boundaries.update(t for word in word_frames for t in word)
        # Sample the ORIGINAL polyline before coalescing keyframes onto output
        # frames. Same-frame vertices all contribute to interpolation; the later
        # vertex governs the outgoing segment. No shortcut can cut a visible
        # corner, even when several reversals occur between two output frames.
        if any(k.box != boxes[0] for k in path):
            boundaries.update(range(first, last + 1))
        ordered = sorted(boundaries)
        for start_frame, end_frame in zip(ordered, ordered[1:]):
            start, end = (frame_centisecond(f, composition.fps) for f in (start_frame, end_frame))
            a_time, b_time = (frame_time(f, composition.fps) for f in (start_frame, end_frame))
            # ASS evaluates in integer milliseconds. Hold the exact sampled
            # position through that frame's evaluation, regardless of truncation.
            offset = math.ceil(a_time * 1000) - start * 10
            finish = math.ceil(b_time * 1000) - start * 10
            active = next((i for i, (a, b) in enumerate(word_frames) if a <= start_frame < b), None)
            completed = {i for i, (_, b) in enumerate(word_frames) if b <= start_frame}
            if style.highlight_box_color and word_frames:
                # The active-word plate holds through pauses until the next
                # word starts (and to the event end), so it never blinks off
                # mid-phrase. Only colors change; glyph geometry never does.
                active = max((i for i, (a, _) in enumerate(word_frames) if a <= start_frame), default=None)
                completed = set(range(active)) if active is not None else set()
            position = _motion(anchor(a_time), anchor(b_time), finish, offset)
            text = "{" + _tags(caption, style, font, font_scale) + position + "}" + _text(runs, style, active, completed)
            lines.append(_dialogue(start, end, text, layer=2 if style.highlight_box_color else 1))
            if active in word_bounds:
                wl, wt, wr, wb = word_bounds[active]
                pad = style.highlight_box_padding
                a, b = anchor(a_time), anchor(b_time)
                move = _motion((a[0] + wl - pad, a[1] + wt - pad),
                               (b[0] + wl - pad, b[1] + wt - pad), finish, offset)
                alpha = round(255 * (1 - style.highlight_box_opacity))
                plate = ("{" + rf"\an7\bord0\shad0\1c{_color(style.highlight_box_color)}\1a&H{alpha:02X}&\p1"
                         + move + "}" + _rounded_rectangle(wr-wl+2*pad, wb-wt+2*pad, style.highlight_box_radius))
                lines.append(_dialogue(start, end, plate, layer=1))
            if style.box_color is not None:
                a, b = box(a_time), box(b_time)
                move = _motion((a.x * width, a.y * height), (b.x * width, b.y * height), finish, offset)
                resize = (rf"\fscx100\fscy100\t({offset},{finish},"
                          rf"\fscx{_n(100 * b.width / a.width)}\fscy{_n(100 * b.height / a.height)})")
                plate = ("{" + rf"\an7\bord0\shad0\1c{_color(style.box_color)}\p1" + move + resize + "}"
                         + f"m 0 0 l {_n(a.width * width)} 0 {_n(a.width * width)} {_n(a.height * height)} 0 {_n(a.height * height)}")
                lines.append(_dialogue(start, end, plate, layer=0))
    if preset_geometry:
        (directory / "caption-geometry.json").write_text(json.dumps(preset_geometry, indent=2) + "\n", encoding="utf-8")
    output = directory / "captions.ass"
    output.write_text("".join(lines), encoding="utf-8", newline="\n")
    (directory / "caption-fonts.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8", newline="\n")
    return output
