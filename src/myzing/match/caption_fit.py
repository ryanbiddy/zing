"""Fit complete clause captions using the renderer's actual libass ink probe."""

from dataclasses import replace
from pathlib import Path
import tempfile

from myzing.composition import CaptionStyle
from myzing.project.api import hash_file
from myzing.render.font_files import ass_em_scale, private_font
from myzing.render.positioned_captions import _measure, caption_runs


def _wrap(parts, limit):
    lines = [""]
    for part in parts:
        if lines[-1] and len(lines[-1]) + 1 + len(part) > limit:
            lines.append(part)
        else:
            lines[-1] = (lines[-1] + " " + part).strip()
    return "\n".join(lines)


def _source_dimensions(plan):
    """Display sizes of unframed assets, so the default fit's picture is known."""
    import subprocess
    from myzing.render.framing import probe_dimensions
    sizes = {}
    for asset in plan.assets:
        if any(c.asset_id == asset.id and c.framing is None for c in plan.clips):
            try:
                sizes[asset.id] = probe_dimensions(Path(asset.path))
            except (OSError, ValueError, subprocess.SubprocessError):
                continue  # Unknown size keeps the full-width floor.
    return sizes


def _fit(caption, style, scale, width, height, font, em, plan, root, sizes=None):
    """(style, None) when the wrapped caption fits its box at >= 24 px, else (None, reason)."""
    for _ in range(10):
        measured = replace(style, size=style.size * scale, outline_width=style.outline_width * scale)
        left, top, right, bottom = _measure(caption, measured, font, caption_runs(caption),
            plan.width, plan.height, root, "ffmpeg", "ass", em)
        padding = max(8 * scale if style.box_color else 0,
                      2 * style.highlight_box_padding * scale if style.highlight_box_color else 0)
        if right - left + padding <= width and bottom - top + padding <= height:
            return style, None
        size = style.size * min(width / (right - left + padding), height / (bottom - top + padding)) * .95
        from myzing.layout.readability import phone_minimum
        # The same picture-relative floor place_captions applies.
        minimum = (phone_minimum(plan, caption, sizes)
                   if plan.brief and plan.brief.caption_mode == "phone" else 24)
        if size * scale < minimum:
            return None, (f"Caption {caption.id} cannot fit as a readable complete clause; shorten the selected "
                          "speech or enlarge its layout.")
        style = replace(style, size=size)
    return None, f"Caption {caption.id} exceeded the bounded ink-fit search; review its layout."


def fit_captions(plan, folder):
    if not plan.captions:
        return
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    sizes = _source_dimensions(plan) if plan.brief and plan.brief.caption_mode == "phone" else {}
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
            style = caption.style or CaptionStyle(max(24, min(plan.width, plan.height) / 20), outline_width=2)
            boxes = [k.box for k in caption.layout.as_path()] if caption.layout else []
            width = min((b.width for b in boxes), default=.8) * plan.width
            height = min((b.height for b in boxes), default=.2) * plan.height
            scale = caption.layout.scale if caption.layout else 1.
            # The default line length comes first, so captions that fit keep
            # their wrap and size. A narrow box (a 9:16 source fit into 16:9)
            # re-wraps to shorter lines before the size may drop below 24 px.
            limit = 52 if plan.width >= plan.height else 30
            longest = max((len(part) for part in parts), default=0)
            while True:
                caption.text = _wrap(parts, limit)
                fitted, failure = _fit(caption, style, scale, width, height, font, em, plan, root, sizes)
                if fitted is not None:
                    caption.style = fitted
                    break
                if limit <= longest:
                    raise ValueError(failure)
                limit = max(longest, int(limit * .85))
    plan.warnings.append("Complete clause captions use explicit visual wraps and libass-measured sizes; caption width and typography may differ from the reference.")
