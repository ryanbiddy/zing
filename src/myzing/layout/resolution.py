"""Honest delivery-resolution advice for low-resolution sources.

A small source cannot fill a large vertical or square frame with a sharp
picture inside the enlargement limit (``framing_max_upscale``, default 2.5x).
The planner then keeps the limit and shows less sharp picture (zoomfill or
blurfill), or, for an explicit crop or same-aspect fit, enlarges past it.
This module states that up front with the numbers and names the honest
options: a lower delivery resolution that reaches the planner's own sharp
target without extra upscaling, or keeping the size with zoomfill/blurfill.
Upscaling, by Zing or by a platform player, never recovers detail.
"""

from __future__ import annotations

import math

from myzing.composition.aspects import aspect_for

TARGET_SHARE = .70  # zoomfill's design target for sharp picture height
MIN_SHORT_SIDE = 360  # never recommend a delivery below 360p
SAME_ASPECT = .01


def _kind(sw: int, sh: int, width: int, height: int) -> str:
    ratio = (sw / sh) / (width / height)
    return "same" if abs(ratio - 1) <= SAME_ASPECT else "wider" if ratio > 1 else "narrower"


def _target(kind: str) -> float:
    """Sharp height share the planner aims for with this source shape."""
    return TARGET_SHARE if kind == "wider" else 1.0


def _expected(sw: int, sh: int, width: int, height: int, limit: float) -> tuple[float, float]:
    """Best sharp height share and its enlargement within ``limit``, geometry only."""
    kind = _kind(sw, sh, width, height)
    if kind == "wider":
        if height / sh <= limit:
            return 1.0, height / sh  # a full-frame crop fits the limit
        floor_share = width * sh / (sw * height)  # whole picture fitted to the width
        share = max(floor_share, min(TARGET_SHARE, sh * limit / height))
        return share, share * height / sh
    scale = height / sh if kind == "narrower" else width / sw
    return 1.0, scale


def _short_side_for(sw: int, sh: int, width: int, height: int, short_side: int, limit: float) -> int:
    """Largest short side (a multiple of 18, at most the current one) that
    reaches the target share without exceeding ``limit``."""
    kind = _kind(sw, sh, width, height)
    rows = sh * limit / _target(kind)
    if kind == "same":
        rows = min(rows, sw * limit * height / width)
    best = math.floor(short_side * rows / height / 18) * 18
    return max(18, min(short_side, best))


def _assessment(framing, sw, sh, width, height):
    if framing is not None and framing.assessments:
        chosen = framing.assessments[-1]
        return chosen.mode, chosen.sharp_height_share, chosen.enlargement
    # Absent framing renders the default fit graph.
    scale = min(width / sw, height / sh)
    return "fit", min(1.0, sh * scale / height), scale


def resolution_advice(clips, source_dimensions: dict, width: int, height: int, *, max_upscale: float = 2.5,
                      command: str | None = None) -> dict:
    """Per-source numbers and one recommendation for a planned delivery.

    ``clips`` are composition clips with chosen ``framing``; ``source_dimensions``
    maps asset id to display (width, height). ``command`` is the render
    command a user would run (``--short-side`` is appended when lowering).
    """
    short = min(width, height)
    aspect = aspect_for(width, height)
    rows = {}
    for clip in clips:
        if clip.asset_id not in source_dimensions:
            continue
        sw, sh = source_dimensions[clip.asset_id]
        mode, share, enlargement = _assessment(clip.framing, sw, sh, width, height)
        row = rows.setdefault(clip.asset_id, {
            "asset_id": clip.asset_id, "source": [sw, sh], "source_megapixels": round(sw * sh / 1e6, 2),
            "full_frame_scale": round(max(width / sw, height / sh), 3),
            "target_sharp_height_share": _target(_kind(sw, sh, width, height)),
            "clips": 0, "modes": [], "sharp_height_share": 1.0, "enlargement": 0.0})
        row["clips"] += 1
        if mode not in row["modes"]:
            row["modes"].append(mode)
        row["sharp_height_share"] = round(min(row["sharp_height_share"], share), 4)
        row["enlargement"] = round(max(row["enlargement"], enlargement), 3)
    limited = []
    for row in rows.values():
        sw, sh = row["source"]
        target = row["target_sharp_height_share"]
        # Resolution-limited: at this size no framing reaches the sharp target
        # within the limit (geometry only). A shortfall caused by subject or
        # evidence-gap policy is not a resolution problem and is not flagged.
        best_share, best_scale = _expected(sw, sh, width, height, max_upscale)
        row["limited"] = bool(row["full_frame_scale"] > max_upscale + 1e-9 and (
            best_share < target - .005 or best_scale > max_upscale + 1e-9))
        row["short_side_for_target"] = _short_side_for(sw, sh, width, height, short, max_upscale)
        if row["limited"]:
            limited.append(row)
    advice = {"version": 1, "aspect": aspect, "output": [width, height], "short_side": short,
              "max_upscale": max_upscale, "limited": bool(limited), "sources": list(rows.values()),
              "recommendation": {"choice": "none", "reason": "Every source reaches its sharp target at this size."},
              "alternatives": [], "summary": ""}
    if not limited:
        return advice
    worst = min(limited, key=lambda r: (r["short_side_for_target"], r["asset_id"]))
    lower = worst["short_side_for_target"]
    sw, sh = worst["source"]
    numbers = (f"{sw}x{sh} source needs {worst['full_frame_scale']:.2f}x to fill {width}x{height} with a sharp "
               f"picture; within the {max_upscale:g}x limit the plan shows {worst['sharp_height_share']:.1%} sharp "
               f"height ({'/'.join(worst['modes'])}, {worst['enlargement']:.2f}x)")
    keep = {"choice": "keep_framing", "short_side": short, "output": [width, height],
            "expected_sharp_height_share": worst["sharp_height_share"], "expected_enlargement": worst["enlargement"],
            "framing": "zoomfill or blurfill",
            "reason": "Keep this delivery size: the sharp picture stays within the limit and the rest is blur."}
    if lower >= MIN_SHORT_SIDE and lower < short:
        new_width, new_height = (round(width * lower / short), round(height * lower / short))
        share, scale = _expected(sw, sh, new_width, new_height, max_upscale)
        recommendation = {
            "choice": "lower_resolution", "short_side": lower, "output": [new_width, new_height],
            "expected_sharp_height_share": round(share, 4), "expected_enlargement": round(scale, 3),
            "brief_answer": {"short_side": lower},
            "command": f"{command} --short-side {lower}" if command else f"--short-side {lower}",
            "reason": (f"Deliver {new_width}x{new_height}: {share:.0%} sharp height at {scale:.2f}x, no extra "
                       "upscaling. Players enlarge it to the screen; the detail is the same either way.")}
        advice["recommendation"], advice["alternatives"] = recommendation, [keep]
        choice = (f"Recommended: deliver {new_width}x{new_height} (--short-side {lower}, or brief "
                  f"short_side {lower} / \"auto\") for {share:.0%} sharp height at {scale:.2f}x; or keep "
                  f"{width}x{height} with zoomfill/blurfill.")
    else:
        advice["recommendation"] = keep
        choice = (f"Recommended: keep {width}x{height} with zoomfill/blurfill; a delivery small enough to reach the "
                  f"sharp target would be below {MIN_SHORT_SIDE}p.")
    advice["summary"] = (f"Low-resolution source for {aspect}: {numbers}. {choice} "
                         "Upscaling cannot recover detail.")
    return advice


def mark_auto_selected(advice: dict, first: dict) -> dict:
    """Record that short_side auto replaced ``first``'s size with this one."""
    w, h = advice["output"]
    advice["auto_selected"] = {"from": first["output"], "to": [w, h], "reason": first["recommendation"]["reason"]}
    advice["summary"] = (f"short_side auto delivered {w}x{h} instead of {first['output'][0]}x{first['output'][1]}. "
                         + first["summary"])
    return advice


def chosen_short_side(advice: dict, requested) -> int:
    """The short side a brief/flag of ``requested`` ('auto' or an int) resolves to."""
    if requested == "auto" and advice["recommendation"]["choice"] == "lower_resolution":
        return advice["recommendation"]["short_side"]
    return advice["short_side"]
