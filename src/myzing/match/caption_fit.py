"""Fit complete clause captions using the renderer's actual libass ink probe."""

from dataclasses import replace
from pathlib import Path
import tempfile

from myzing.composition import CaptionStyle
from myzing.project.api import hash_file
from myzing.render.font_files import ass_em_scale, private_font
from myzing.render.positioned_captions import _measure, caption_runs


def fit_captions(plan, folder):
    if not plan.captions:
        return
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as temporary:
        root = Path(temporary)
        (root / "fonts").mkdir()
        for caption in plan.captions:
            font, em = "Arial", 1.
            if caption.font:
                source = Path(caption.font.path)
                if hash_file(source) != caption.font.sha256:
                    raise ValueError("Caption font changed; restore the pinned font before fitting.")
                font, payload = private_font(source.read_bytes())
                (root / "fonts" / (font + ".ttf")).write_bytes(payload)
                em = ass_em_scale(payload)
            # Preserve each ASR word's text atomically, including multi-token
            # words. Explicit visual wraps do not cut or reorder speech.
            parts = [w.text.strip() for w in caption.words] or caption.text.split()
            limit = 52 if plan.width >= plan.height else 30
            lines = [""]
            for part in parts:
                if lines[-1] and len(lines[-1]) + 1 + len(part) > limit:
                    lines.append(part)
                else:
                    lines[-1] = (lines[-1] + " " + part).strip()
            caption.text = "\n".join(lines)
            style = caption.style or CaptionStyle(max(24, min(plan.width, plan.height) / 20), outline_width=2)
            boxes = [k.box for k in caption.layout.as_path()] if caption.layout else []
            width = min((b.width for b in boxes), default=.8) * plan.width
            height = min((b.height for b in boxes), default=.2) * plan.height
            scale = caption.layout.scale if caption.layout else 1.
            for _ in range(10):
                measured = replace(style, size=style.size * scale, outline_width=style.outline_width * scale)
                left, top, right, bottom = _measure(caption, measured, font, caption_runs(caption),
                    plan.width, plan.height, root, "ffmpeg", "ass", em)
                padding = 8 * scale if style.box_color else 0
                if right - left + padding <= width and bottom - top + padding <= height:
                    caption.style = style
                    break
                size = style.size * min(width / (right - left + padding), height / (bottom - top + padding)) * .95
                if size * scale < 24:
                    raise ValueError(f"Caption {caption.id} cannot fit as a readable complete clause; shorten the selected speech or enlarge its layout.")
                style = replace(style, size=size)
            else:
                raise ValueError(f"Caption {caption.id} exceeded the bounded ink-fit search; review its layout.")
    plan.warnings.append("Complete clause captions use explicit visual wraps and libass-measured sizes; caption width and typography may differ from the reference.")
