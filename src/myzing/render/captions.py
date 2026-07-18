"""ASS authoring for static and word-timed pop captions."""

from __future__ import annotations

from pathlib import Path

from myzing.schemas import CaptionSpec


SAFE_BOX_1080X1920 = (65, 270, 880, 1248)
POSITION_Y_1080X1920 = {
    "top": 350,
    "center": 760,
    "lower": 1068,
    "bottom": 1168,
}


class CaptionDependencyError(RuntimeError):
    """The render extra required for ASS generation is not installed."""


def caption_anchor(position: str, width: int, height: int) -> tuple[int, int]:
    left, _, right, _ = SAFE_BOX_1080X1920
    x = round(((left + right) / 2) * width / 1080)
    y = round(POSITION_Y_1080X1920[position] * height / 1920)
    return x, y


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

    font_size = max(24, round(height * 0.046875))
    outline = max(2, round(height / 480))
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
            for word in caption.words:
                duration_ms = max(1, _milliseconds(word.end - word.start))
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
                        end=_milliseconds(word.end),
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
