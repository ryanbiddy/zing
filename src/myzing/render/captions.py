"""ASS authoring for static and word-timed pop captions."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from myzing.schemas import CaptionSpec

from .validation import output_preset


ANCHOR_GUIDES = {
    "vertical": {
        "x": Fraction(7, 16),
        "top": Fraction(350, 1920),
        "center": Fraction(760, 1920),
        "lower": Fraction(1068, 1920),
        "bottom": Fraction(1168, 1920),
    },
    "landscape": {
        "x": Fraction(1, 2),
        "top": Fraction(3, 20),
        "center": Fraction(1, 2),
        "lower": Fraction(3, 4),
        "bottom": Fraction(17, 20),
    },
    "square": {
        "x": Fraction(1, 2),
        "top": Fraction(3, 20),
        "center": Fraction(1, 2),
        "lower": Fraction(3, 4),
        "bottom": Fraction(17, 20),
    },
}


class CaptionDependencyError(RuntimeError):
    """The render extra required for ASS generation is not installed."""


def caption_anchor(position: str, width: int, height: int) -> tuple[int, int]:
    guide = ANCHOR_GUIDES[output_preset(width, height)]
    return round(guide["x"] * width), round(guide[position] * height)


def _ass_text(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r\n", r"\N")
        .replace("\r", r"\N")
        .replace("\n", r"\N")
    )


def _display_text(text: str, all_caps: bool) -> str:
    return text.upper() if all_caps else text


def _milliseconds(seconds: float) -> int:
    return round(seconds * 1000)


def generate_ass(
    captions: list[CaptionSpec],
    width: int,
    height: int,
    output_path: Path,
) -> Path:
    """Serialize caption events through pysubs2, including raw karaoke tags."""
    try:
        import pysubs2
    except ImportError as exc:
        raise CaptionDependencyError(
            'pysubs2 is required for rendering; install with: pip install "myzing[render]"'
        ) from exc

    subs = pysubs2.SSAFile()
    subs.info["Title"] = "Zing deterministic captions"
    subs.info["PlayResX"] = str(width)
    subs.info["PlayResY"] = str(height)
    subs.info["WrapStyle"] = "2"
    subs.info["ScaledBorderAndShadow"] = "yes"

    short_edge = min(width, height)
    font_size = max(24, round(short_edge / 12))
    outline = max(2, round(short_edge / 270))
    common = dict(
        fontname="Arial",
        fontsize=font_size,
        bold=True,
        outlinecolor=pysubs2.Color(0, 0, 0),
        backcolor=pysubs2.Color(0, 0, 0, 128),
        borderstyle=1,
        outline=outline,
        shadow=0,
        alignment=pysubs2.Alignment.MIDDLE_CENTER,
    )
    subs.styles["Caption"] = pysubs2.SSAStyle(
        primarycolor=pysubs2.Color(255, 255, 255),
        secondarycolor=pysubs2.Color(255, 255, 255),
        **common,
    )
    subs.styles["Karaoke"] = pysubs2.SSAStyle(
        primarycolor=pysubs2.Color(255, 220, 0),
        secondarycolor=pysubs2.Color(255, 255, 255),
        **common,
    )

    for caption in captions:
        x, y = caption_anchor(caption.position, width, height)
        position_tag = rf"\an5\pos({x},{y})"
        if caption.word_timed:
            for index, word in enumerate(caption.words):
                duration_ms = max(1, _milliseconds(word.end - word.start))
                visible_end = (
                    caption.words[index + 1].start
                    if index + 1 < len(caption.words)
                    else caption.end
                )
                karaoke_cs = max(1, round(duration_ms / 10))
                pop_ms = min(80, max(1, duration_ms // 3))
                settle_ms = min(160, max(pop_ms + 1, duration_ms * 2 // 3))
                tags = (
                    position_tag
                    + rf"\fscx100\fscy100"
                    + rf"\t(0,{pop_ms},\fscx118\fscy118)"
                    + rf"\t({pop_ms},{settle_ms},\fscx100\fscy100)"
                    + rf"\kf{karaoke_cs}"
                )
                text = _ass_text(_display_text(word.text, caption.all_caps))
                subs.events.append(
                    pysubs2.SSAEvent(
                        start=_milliseconds(word.start),
                        end=_milliseconds(visible_end),
                        style="Karaoke",
                        text="{" + tags + "}" + text,
                    )
                )
        else:
            text = _ass_text(_display_text(caption.text, caption.all_caps))
            subs.events.append(
                pysubs2.SSAEvent(
                    start=_milliseconds(caption.start),
                    end=_milliseconds(caption.end),
                    style="Caption",
                    text="{" + position_tag + "}" + text,
                )
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(output_path, encoding="utf-8", format_="ass")
    return output_path
