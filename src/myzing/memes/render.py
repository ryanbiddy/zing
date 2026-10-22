"""Pillow still compositor; geometry and imports remain stdlib-only at rest."""

from __future__ import annotations

import math
import os
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from myzing import storage
from . import MemeError, PILLOW_HINT
from .score import viral_score
from .templates import fetch_blank, get_template
from .validate import check_texts

ASPECTS = {"16:9": (1200, 675), "1:1": (1080, 1080),
           "4:5": (1080, 1350), "9:16": (1080, 1920)}
ASPECT_ALIASES = {"x-landscape": "16:9", "square": "1:1", "portrait": "4:5", "story": "9:16"}
FONTS_DIR = Path(__file__).resolve().parents[1] / "_data" / "fonts"
MAX_PIXELS = 40_000_000


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def pixels(self) -> tuple[int, int, int, int]:
        return (round(self.x), round(self.y), round(self.x + self.width), round(self.y + self.height))


@dataclass(frozen=True)
class TextLayer:
    text: str
    box: Rect
    font: str = "anton"
    font_size: float = 6.8  # percentage of output width
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: float = .5  # Canvas line width, percentage of output width
    background: str | None = None
    shadow: bool = False
    rotation: float = 0
    uppercase: bool = False
    align: str = "center"


def require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
    except ImportError as exc:
        raise MemeError(PILLOW_HINT) from exc
    return Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def output_size(aspect: str, source: tuple[int, int]) -> tuple[int, int]:
    aspect = ASPECT_ALIASES.get(aspect, aspect)
    if aspect in ASPECTS:
        return ASPECTS[aspect]
    if aspect != "original":
        raise MemeError("aspect must be 16:9, 1:1, 4:5, 9:16, or original")
    sw, sh = source
    if sw <= 0 or sh <= 0:
        raise MemeError("Source dimensions must be positive.")
    width = min(1920, max(1200, sw))
    height = max(1, round(width * sh / sw))
    if width * height > MAX_PIXELS:
        raise MemeError("Original aspect exceeds the 40 megapixel render limit; choose an aspect preset.")
    return width, height


def fit_rect(source: tuple[int, int], target: Rect, fit: str) -> Rect:
    if fit not in ("cover", "contain"):
        raise MemeError("fit must be cover or contain")
    sw, sh = source
    if sw <= 0 or sh <= 0 or target.width <= 0 or target.height <= 0:
        raise MemeError("Source and target dimensions must be positive.")
    scale = (max if fit == "cover" else min)(target.width / sw, target.height / sh)
    w, h = sw * scale, sh * scale
    return Rect(target.x + (target.width - w) / 2, target.y + (target.height - h) / 2, w, h)


def normalized_regions(regions: list[list[float]]) -> list[Rect]:
    if not isinstance(regions, list) or not 1 <= len(regions) <= 6:
        raise MemeError("regions must contain 1-6 [x, y, width, height] boxes")
    result = []
    for box in regions:
        if not isinstance(box, (list, tuple)) or len(box) != 4 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box
        ):
            raise MemeError("Each region must contain four finite numbers.")
        x, y, w, h = box
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
            raise MemeError("Regions must fit within normalized image coordinates 0..1.")
        result.append(Rect(x, y, w, h))
    return result


def layout_boxes(layout: str, count: int, size: tuple[int, int], *,
                 regions: list[list[float]] | None = None, image_rect: Rect | None = None) -> list[Rect]:
    w, h = size
    if layout == "classic":
        if not 1 <= count <= 2:
            raise MemeError("classic layout accepts 1-2 text boxes")
        boxes = [[.04, .03, .92, .23], [.04, .74, .92, .23]][:count]
    elif layout == "caption":
        if not 1 <= count <= 3:
            raise MemeError("caption layout accepts 1-3 text boxes")
        boxes = [[.04, .02 + i * .22 / count, .92, .22 / count] for i in range(count)]
    elif layout == "labels":
        if regions is None:
            if not 1 <= count <= 6:
                raise MemeError("labels layout accepts 1-6 text boxes")
            cols = min(count, 3)
            rows = math.ceil(count / cols)
            regions = [[(i % cols + .06) / cols, (.45 + i // cols) / rows,
                        .88 / cols, .25 / rows] for i in range(count)]
        if len(regions) != count:
            raise MemeError("Provide exactly one region per text box (including empty boxes).")
        frame = image_rect or Rect(0, 0, w, h)
        result = []
        for region in normalized_regions(regions):
            left = max(0, frame.x + region.x * frame.width)
            top = max(0, frame.y + region.y * frame.height)
            right = min(w, frame.x + (region.x + region.width) * frame.width)
            bottom = min(h, frame.y + (region.y + region.height) * frame.height)
            if right - left < 24 or bottom - top < 24:
                raise MemeError("A label region was cropped away or is too small; use contain or a larger region.")
            result.append(Rect(left, top, right - left, bottom - top))
        return result
    else:
        raise MemeError("layout must be classic, caption, or labels")
    if regions is not None:
        raise MemeError("Custom regions require the labels layout.")
    return [Rect(x * w, y * h, bw * w, bh * h) for x, y, bw, bh in boxes]


def resolve_font(name: str) -> str:
    """Bundled aliases, explicit paths, or system font file/family names."""
    aliases = {"anton": "Anton-Regular.ttf", "sans": "IBMPlexSans.ttf", "ibm plex sans": "IBMPlexSans.ttf"}
    if name.casefold() in aliases:
        return str(FONTS_DIR / aliases[name.casefold()])
    path = Path(name).expanduser()
    if path.is_file():
        return str(path.resolve())
    # Pillow searches native font directories too. Resolve common family/file
    # names explicitly to make e.g. Impact work on case-sensitive systems.
    roots = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path.home() / ".fonts", Path.home() / ".local/share/fonts",
             Path("/usr/share/fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts")]
    wanted = name.casefold().replace(" ", "")
    for root in roots:
        if root.is_dir():
            for candidate in sorted(root.rglob("*")):
                if candidate.suffix.lower() in (".ttf", ".otf", ".ttc") and (
                    candidate.stem.casefold().replace(" ", "") == wanted
                    or candidate.name.casefold() == name.casefold()
                ):
                    return str(candidate)
    raise MemeError(f"Font {name!r} was not found; use anton, sans, or a font file path.")


def wrap_text(text: str, font: Any, max_width: float) -> list[str]:
    """Wrap hard lines and break overlong words without silently dropping text."""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if font.getlength(candidate) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            for char in word:
                if line and font.getlength(line + char) > max_width:
                    lines.append(line)
                    line = ""
                line += char
        lines.append(line)
    return lines


def _draw_layer(canvas: Any, layer: TextLayer) -> dict:
    Image, ImageDraw, ImageFilter, ImageFont, _ = require_pillow()
    if layer.align not in ("left", "center", "right"):
        raise MemeError("Text alignment must be left, center, or right.")
    if not math.isfinite(layer.rotation) or abs(layer.rotation) > 180:
        raise MemeError("rotation must be between -180 and 180 degrees")
    text = layer.text.upper() if layer.uppercase else layer.text
    font_path = resolve_font(layer.font)
    stroke = max(1, round(canvas.width * layer.stroke_width / 200)) if layer.stroke_width > 0 else 0
    start = max(10, min(round(canvas.width * layer.font_size / 100), round(layer.box.height * .8)))
    for font_size in range(start, 9, -1):
        font = ImageFont.truetype(font_path, font_size)
        padding = max(4, math.ceil(font_size * .18)) + stroke
        available = layer.box.width - 2 * padding
        if available <= 0:
            continue
        # Shrink normal words before splitting them ("emergency" must not
        # become "emergen / cy"). Long unbroken tokens still wrap safely.
        if any(len(word) <= 24 and font.getlength(word) > available for word in text.split()):
            continue
        lines = wrap_text(text, font, available)
        heights = [font.getbbox(line or " ")[3] - font.getbbox(line or " ")[1] for line in lines]
        line_height = max(math.ceil(font_size * 1.04), max(heights) + stroke * 2)
        widths = [font.getlength(line) for line in lines]
        block_width = math.ceil(max(widths)) + 2 * padding
        block_height = len(lines) * line_height + 2 * padding
        if block_width <= layer.box.width and block_height <= layer.box.height and len(lines) <= 8:
            break
    else:
        raise MemeError("Text does not fit its box at a readable size; shorten it or enlarge the region.")
    patch = Image.new("RGBA", (block_width, block_height))
    if layer.background:
        ImageDraw.Draw(patch).rounded_rectangle((0, 0, block_width - 1, block_height - 1),
                                               radius=max(2, font_size * .18), fill=layer.background)
    ink = Image.new("RGBA", patch.size)
    draw = ImageDraw.Draw(ink)
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = {"left": padding, "center": (block_width - widths[i]) / 2,
             "right": block_width - padding - widths[i]}[layer.align]
        y = padding + i * line_height + (line_height - heights[i]) / 2
        draw.text((round(x - bbox[0]), round(y - bbox[1])), line, font=font,
                  fill=layer.color, stroke_width=stroke, stroke_fill=layer.stroke_color)
    if layer.shadow:
        shadow = Image.new("RGBA", patch.size, (0, 0, 0, 0))
        alpha = ink.getchannel("A").filter(ImageFilter.GaussianBlur(font_size * .16)).point(lambda v: round(v * .55))
        shadow.putalpha(alpha)
        patch.alpha_composite(shadow, (0, round(font_size * .08)))
    patch.alpha_composite(ink)
    if layer.rotation:
        patch = patch.rotate(-layer.rotation, resample=Image.Resampling.BICUBIC, expand=True)
        ink = ink.rotate(-layer.rotation, resample=Image.Resampling.BICUBIC, expand=True)
        patch.thumbnail((max(1, int(layer.box.width)), max(1, int(layer.box.height))), Image.Resampling.LANCZOS)
        ink = ink.resize(patch.size, Image.Resampling.LANCZOS)
    left = round(layer.box.x + (layer.box.width - patch.width) / 2)
    top = round(layer.box.y + (layer.box.height - patch.height) / 2)
    canvas.alpha_composite(patch, (left, top))
    ink_box = ink.getbbox()
    return {"text": layer.text, "box": list(layer.box.pixels()), "font_size": font_size,
            "wrapped_lines": lines,
            "text_bbox": [ink_box[0] + left, ink_box[1] + top, ink_box[2] + left, ink_box[3] + top] if ink_box else None}


def draw_composition(source: Any, *, size: tuple[int, int], layers: list[TextLayer],
                     fit: str = "cover", background: str = "#181818",
                     viewport: Rect | None = None, caption: bool = False) -> tuple[Any, list[dict]]:
    Image, _, _, _, _ = require_pillow()
    if source.mode != "RGBA":
        source = source.convert("RGBA")
    w, h = size
    viewport = viewport or Rect(0, 0, w, h)
    rect = fit_rect(source.size, viewport, fit)
    canvas = Image.new("RGBA", size, background)
    # Crop before resizing for cover: extreme source ratios must not allocate
    # a giant off-canvas intermediate image.
    sw, sh = source.size
    scale = rect.width / sw
    crop = (max(0, (viewport.x - rect.x) / scale), max(0, (viewport.y - rect.y) / scale),
            min(sw, (viewport.x + viewport.width - rect.x) / scale),
            min(sh, (viewport.y + viewport.height - rect.y) / scale))
    if fit == "cover":
        fitted = source.resize((round(viewport.width), round(viewport.height)), Image.Resampling.LANCZOS, box=crop)
        canvas.alpha_composite(fitted, (round(viewport.x), round(viewport.y)))
    else:
        fitted = source.resize((max(1, round(rect.width)), max(1, round(rect.height))), Image.Resampling.LANCZOS)
        canvas.alpha_composite(fitted, (round(rect.x), round(rect.y)))
    if caption:
        from PIL import ImageDraw
        ImageDraw.Draw(canvas).rectangle((0, 0, w, round(h * .26) - 1), fill="white")
    reports = []
    for index, layer in enumerate(layers):
        if layer.text.strip():
            reports.append({"index": index, **_draw_layer(canvas, layer)})
    return canvas.convert("RGB"), reports


def render_meme(texts: list[str], *, image: str = "", template: str = "",
                layout: str = "", aspect: str = "1:1", out: str = "", fit: str = "",
                font: str = "", regions: list[list[float]] | None = None,
                plate: bool = False, shadow: bool = False, rotation: float = 0,
                offline: bool = False, overwrite: bool = False) -> dict:
    if bool(image) == bool(template):
        raise MemeError("Provide exactly one of image or template.")
    selected = get_template(template) if template else None
    layout = layout or ("labels" if selected else "classic")
    fit = fit or ("contain" if selected else "cover")
    aspect = ASPECT_ALIASES.get(aspect, aspect)
    output_size(aspect, (1200, 675))  # validate before network/filesystem writes
    if fit not in ("cover", "contain"):
        raise MemeError("fit must be cover or contain")
    if isinstance(rotation, bool) or not isinstance(rotation, (int, float)) or not math.isfinite(rotation) or abs(rotation) > 180:
        raise MemeError("rotation must be between -180 and 180 degrees")
    for name, value in (("plate", plate), ("shadow", shadow), ("offline", offline),
                        ("overwrite", overwrite)):
        if not isinstance(value, bool):
            raise MemeError(f"{name} must be boolean")
    count = selected["box_count"] if selected else (len(regions) if regions is not None else None)
    validation = check_texts(texts, box_count=count)
    if not validation["valid"]:
        raise MemeError(" ".join(p["message"] for p in validation["problems"]))
    texts = validation["texts"]
    if selected and layout == "labels" and regions is None:
        texts += [""] * (selected["box_count"] - len(texts))
        regions = selected["box_layout"]
    layout_boxes(layout, len(texts), (1080, 1080), regions=regions)
    font = resolve_font(font or ("sans" if layout == "caption" else "anton"))
    Image, _, _, _, ImageOps = require_pillow()
    target = (Path(out).expanduser() if out else storage.workspace_root() / "memes" / "renders" / f"meme-{uuid4().hex[:12]}.png").resolve()
    formats = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
    if target.suffix.lower() not in formats:
        raise MemeError("Output must end in .png, .jpg, .jpeg, or .webp.")
    source_path = fetch_blank(template, allow_download=not offline) if selected else Path(image).expanduser().resolve()
    if source_path.resolve() == target:
        raise MemeError("Output must differ from the source image path.")
    if target.exists() and not overwrite:
        raise MemeError(f"{target} already exists; choose another --out or pass overwrite.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source_path) as opened:
                if opened.width * opened.height > MAX_PIXELS:
                    raise MemeError("Source exceeds the 40 megapixel limit; resize it first.")
                source = ImageOps.exif_transpose(opened).convert("RGBA")
        size = output_size(aspect, source.size)
        w, h = size
        bar = round(h * .26)
        viewport = Rect(0, bar, w, h - bar) if layout == "caption" else Rect(0, 0, w, h)
        rect = fit_rect(source.size, viewport, fit)
        boxes = layout_boxes(layout, len(texts), size, regions=regions, image_rect=rect)
        layers = [TextLayer(text, box, font=font, color="black" if layout == "caption" else "white",
                            stroke_width=0 if layout == "caption" else .5,
                            background="#000000b0" if plate and layout != "caption" else None,
                            shadow=shadow, rotation=rotation, uppercase=layout == "classic")
                  for text, box in zip(texts, boxes)]
        result, reports = draw_composition(source, size=size, layers=layers, fit=fit,
                                           viewport=viewport, caption=layout == "caption")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as stream:
                temp = Path(stream.name)
                result.save(stream, format=formats[target.suffix.lower()], quality=94)
            os.replace(temp, target)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        if isinstance(exc, MemeError):
            raise
        raise MemeError(f"Could not render {source_path}: {exc}") from exc
    return {"path": str(target), "source_path": str(source_path), "width": w, "height": h,
            "layout": layout, "aspect": aspect, "fit": fit, "boxes": reports,
            "validation": validation,
            "viral_lens": viral_score(texts, aspect=aspect, contrast=[True] * len(texts)),
            "warnings": (["Generic catalog regions: inspect placement or supply custom regions."]
                         if selected and selected["layout_kind"] == "generic_rows" else [])}
