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
from pathlib import Path

from myzing.composition import CaptionStyle, Composition, CompositionCaption
from myzing.layout.types import Box, box_at

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


def _text(runs: list[tuple[str, int | None]], style: CaptionStyle, active: int | None = None) -> str:
    return "".join("{" + rf"\1c{_color(style.highlight if index is not None and index == active else style.color)}"
                   + "}" + escape_ass(value) for value, index in runs)


def _measure(caption: CompositionCaption, style: CaptionStyle, font: str,
             runs: list[tuple[str, int | None]], width: int, height: int,
             directory: Path, ffmpeg: str, caption_filter: str, font_scale: float) -> tuple[float, float, float, float]:
    """Measure libass ink+outline, relative to the ASS anchor, using raw gray.

    Calibration uses the actual registered font, shaping and explicit breaks.
    White probe colors expose dark outlines too. No image package is needed.
    """
    width, height = max(width * 2, 1024), max(height * 2, 512)
    x, y = width // 2, height // 2
    probe_style = replace(style, color="#FFFFFF", highlight="#FFFFFF", outline_color="#FFFFFF")
    text = "{" + _tags(caption, probe_style, font, font_scale) + rf"\pos({x},{y})" + "}" + _text(runs, probe_style)
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


def _motion(a: tuple[float, float], b: tuple[float, float], milliseconds: int) -> str:
    if a == b:
        return rf"\pos({_n(a[0])},{_n(a[1])})"
    return rf"\move({_n(a[0])},{_n(a[1])},{_n(b[0])},{_n(b[1])},0,{milliseconds})"


def generate_positioned_ass(composition: Composition, fonts: dict[str, tuple[str, bytes]],
                            directory: Path, ffmpeg: str, caption_filter: str) -> Path:
    """Compile per-word event slices and piecewise linear paths into ASS."""
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
    for caption in composition.captions:
        width, height = composition.width, composition.height
        style = caption.style or CaptionStyle(
            max(24, round(min(width, height) / 12)), highlight="#FFDC00",
            outline_width=max(2, round(min(width, height) / 270)),
        )
        scale = caption.layout.scale if caption.layout else 1.0
        style = replace(style, size=style.size * scale, outline_width=style.outline_width * scale)
        font = fonts[caption.id][0] if caption.id in fonts else "Arial"
        font_scale = ass_em_scale(fonts[caption.id][1]) if caption.id in fonts else 1.0
        runs = caption_runs(caption)
        key = (font, style.size, style.outline_width, caption.alignment, tuple(runs))
        if key not in measurements:
            measurements[key] = _measure(caption, style, font, runs, width, height, directory, ffmpeg, caption_filter, font_scale)
        left, top, right, bottom = measurements[key]
        ink_width, ink_height = right - left, bottom - top
        padding = 4 * scale if style.box_color is not None else 0
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

        # Target the first output frame at/after each boundary. Use the last
        # centisecond strictly before it: concat's microsecond timebase and
        # libass's millisecond truncation can otherwise delay exact boundaries
        # by another frame (e.g. 1.8s reaches the filter as 1.799999s).
        from myzing.composition import frame_index, frame_time

        def cs(time: float) -> int:
            return max(0, math.ceil(frame_time(frame_index(time, composition.fps, rounding="ceil"), composition.fps) * 100) - 1)

        boundaries = {cs(caption.start), cs(caption.end)}
        boundaries.update(cs(k.time) for k in path)
        if caption.word_timed:
            boundaries.update(cs(t) for word in caption.words for t in (word.start, word.end))
        ordered = sorted(boundaries)
        for start, end in zip(ordered, ordered[1:]):
            if start == end:
                continue
            active = next((i for i, w in enumerate(caption.words)
                           if cs(w.start) <= start < cs(w.end)), None) if caption.word_timed else None
            position = _motion(anchor(start / 100), anchor(end / 100), (end - start) * 10)
            text = "{" + _tags(caption, style, font, font_scale) + position + "}" + _text(runs, style, active)
            lines.append(_dialogue(start, end, text))
            if style.box_color is not None:
                a, b = box(start / 100), box(end / 100)
                move = _motion((a.x * width, a.y * height), (b.x * width, b.y * height), (end - start) * 10)
                resize = (rf"\fscx100\fscy100\t(0,{(end - start) * 10},"
                          rf"\fscx{_n(100 * b.width / a.width)}\fscy{_n(100 * b.height / a.height)})")
                plate = ("{" + rf"\an7\bord0\shad0\1c{_color(style.box_color)}\p1" + move + resize + "}"
                         + f"m 0 0 l {_n(a.width * width)} 0 {_n(a.width * width)} {_n(a.height * height)} 0 {_n(a.height * height)}")
                lines.append(_dialogue(start, end, plate, layer=0))
    output = directory / "captions.ass"
    output.write_text("".join(lines), encoding="utf-8", newline="\n")
    (directory / "caption-fonts.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8", newline="\n")
    return output
