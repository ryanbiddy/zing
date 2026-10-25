"""Plain editor wording for measured values. Every phrase maps to a number.

These helpers never add a measurement. They translate one that exists, and
return None when the input is missing so a caller can say "unknown".
"""

from __future__ import annotations

import math
import re


def seconds(value: float) -> str:
    """0.8 -> '0.80s', 19 -> '19.0s'."""
    return f"{value:.2f}s" if value < 10 else f"{value:.1f}s"


def signed(value: float) -> str:
    """'+7.0' / '-10.8'; a value that rounds to zero never prints as '-0.0'."""
    return f"{round(value, 1) + 0.0:+.1f}"


def time_span(start: float, end: float) -> str:
    """A zero-length event is a moment, not a range: 'at 0.80s'."""
    if end - start < 0.05:
        return f"at {start:.2f}s"
    return f"{start:.2f}-{end:.2f}s"


_ASPECTS = [(9/16, "9:16"), (4/5, "4:5"), (3/4, "3:4"), (2/3, "2:3"), (1.0, "1:1"), (4/3, "4:3"),
            (3/2, "3:2"), (16/9, "16:9"), (1.85, "1.85:1"), (2.0, "2:1"), (2.39, "2.39:1")]


def aspect_name(width: float, height: float) -> str:
    """'vertical 9:16', 'widescreen 16:9', 'portrait 0.77:1'."""
    ratio = width / height
    label = next((name for value, name in _ASPECTS if abs(ratio - value) / value <= .03), None)
    shape = "square" if abs(ratio - 1) <= .02 else "vertical" if ratio < 1 else "widescreen" if ratio >= 1.7 else "landscape"
    if label is None:
        label = f"{ratio:.2f}:1"
    return shape if label == "1:1" else f"{shape} {label}"


def pace_word(median_shot: float) -> str:
    if median_shot < 1.0:
        return "very fast"
    if median_shot < 2.5:
        return "fast"
    if median_shot < 5:
        return "steady"
    return "slow"


ZONE_PHRASES = {"top": "at the top", "center": "in the center", "lower": "in the lower third", "bottom": "at the bottom"}


def contrast_word(spread_l: float) -> str:
    """L* spread between dark and bright sampled pixels."""
    return "strong" if spread_l >= 70 else "moderate" if spread_l >= 45 else "low (flat)"


def saturation_word(median_chroma: float) -> str:
    if median_chroma < 3:
        return "black-and-white or nearly colorless"
    if median_chroma < 10:
        return "muted"
    if median_chroma < 30:
        return "natural"
    return "vivid"


# CIELAB hue angles of the sRGB primaries/secondaries; bins split halfway.
_HUES = [(4, 56, "red"), (56, 88, "orange"), (88, 120, "yellow"), (120, 166, "green"),
         (166, 251, "cyan-teal"), (251, 317, "blue")]


def color_cast(a: float, b: float) -> dict:
    """Name the mean a*/b* direction. Pure sRGB blue itself has a* +79, so a
    positive a* alone never means 'red': the hue angle decides the name."""
    chroma = math.hypot(a, b)
    if chroma < 2:
        return {"hue": None, "temperature": "neutral", "strength": "none", "chroma": chroma,
                "phrase": "neutral, with no clear color cast"}
    angle = math.degrees(math.atan2(b, a)) % 360
    hue = next((name for lo, hi, name in _HUES if lo <= angle < hi), "magenta-pink")
    temperature = "warm" if hue in ("red", "orange", "yellow") else "cool" if hue in ("cyan-teal", "blue") else "tint"
    strength = "slight" if chroma < 4 else "noticeable" if chroma < 12 else "strong"
    adverb = {"slight": "slightly", "noticeable": "noticeably", "strong": "strongly"}[strength]
    phrase = (f"{adverb} {temperature}, toward {hue}" if temperature != "tint"
              else f"a {strength} {hue} tint")
    return {"hue": hue, "hue_angle": angle, "temperature": temperature, "strength": strength,
            "chroma": chroma, "phrase": phrase}


_FORBIDDEN = set("→←↑↓↔~|\\{}<>=_^`�■□▪●•")
_EDGE = ".,:;!?'\"()[]-–—…*"


def _token_clean(token: str) -> bool | None:
    token = token.strip(_EDGE)
    if not token:
        return None
    if re.fullmatch(r"[\d.,:]*\d", token) or re.fullmatch(r"\d+[A-Za-z]{1,3}", token):
        return True  # numbers and unit-like tokens (16m, 4K, 30fps)
    parts = re.split(r"[-']", token)
    if not all(p.isalpha() for p in parts if p):
        return False  # M1, QD2, 5p0: letters and digits interleaved
    for part in filter(None, parts):
        if not (part.islower() or part.isupper() or part.istitle() or not part.isascii()):
            return False  # AVo, CoveR: case changes inside a word
        letters = part.lower()
        if letters.isascii() and not re.search(r"[aeiouy]", letters):
            if part.isupper() and len(part) <= 4:
                continue  # short acronyms (TV, NBC)
            if len(part) >= 3:
                return False  # Brne, Bln: OCR dropped the vowels
    return True


def plausible_text(text: str) -> bool:
    """True when OCR text reads like words a person would quote.

    Garbled reads mix digits into words, change case mid-word, lose vowels or
    contain arrows/tildes. This is a quotation filter for the readable card;
    card.json keeps every OCR string regardless.
    """
    if not text or any(c in _FORBIDDEN for c in text):
        return False
    tokens = [t for raw in text.split() for t in raw.split("/")]
    verdicts = [v for v in (_token_clean(t) for t in tokens) if v is not None]
    if not verdicts or sum(verdicts) / len(verdicts) < .85:
        return False
    return any(sum(c.isalpha() for c in t) >= 4 for t in tokens)


def word_count(text: str) -> int:
    """Alphabetic words of three or more letters (a readability rank for quotes)."""
    return sum(sum(c.isalpha() for c in t) >= 3 for raw in text.split() for t in raw.split("/"))


def quote(text: str, limit: int = 60) -> str:
    text = " ".join(text.split()).rstrip(",;:")
    return '"' + (text if len(text) <= limit else text[:limit - 1].rstrip() + "…") + '"'


def hook_lines(facts, *, has_audio_stream=None):
    """Four plain observations; methods and full bases stay in Markdown and JSON."""
    timings = []
    for key, label in (("time_to_first_word", "First word"), ("time_to_first_cut", "first cut"),
                       ("time_to_first_caption", "first caption")):
        value = facts[key]["value"]
        if key == "time_to_first_word" and value is None and has_audio_stream is False:
            timings.append("No speech")  # No audio track, not merely missing word timings.
        else:
            timings.append(f"{label} at {value:.1f}s" if value is not None else f"{label} unknown")
    lines = ["; ".join(timings) + "."]
    row = facts["opening_cut_rate"]
    if row["value"] is None:
        lines.append("Opening pace unknown: cuts were not measured.")
    else:
        v = row["value"]
        opening, rest = v["opening_cuts_per_10s"], v["rest_cuts_per_10s"]
        pace = "Opens faster" if opening > rest else "Opens slower" if opening < rest else "Steady opening"
        cuts = f"{opening:.1f} cuts per 10s" if v["opening_cuts"] else "no cuts"
        lines.append(f"{pace}: {cuts} in the first {v['opening_end_seconds']:.1f}s, then {rest:.1f} per 10s.")
        if "disagree" in row["basis"]:
            lines[-1] += " Cut detectors disagree."
    payoff = facts["payoff_spacing"]["value"]
    if payoff is not None:
        lines[-1] += (f" Labeled payoffs: median gap {payoff['median']:g}s "
                      f"(range {payoff['min']:g}-{payoff['max']:g}s).")
    row = facts["loop_seam"]
    # Frames are compared only under 60s, so a long video skips both checks.
    reason = "60s or longer" if row["status"] == "not_applicable" else "too little frame evidence"
    if row["value"] is None:
        lines.append(f"Loop not checked: {reason}.")
    elif row["value"]["loops_cleanly"]:
        lines.append("Ending matches the opening frame, so it loops cleanly by this pixel check; motion and audio untested.")
    else:
        lines.append("Ending does not match the opening frame, so it does not loop cleanly by this pixel check.")
    row = facts["flash_forward"]
    if row["value"] is None:
        lines.append(f"Flash-forward not checked: {reason}.")
    elif row["value"]["candidate"]:
        lines.append(f"Possible flash-forward: the opening image returns at {row['value']['matched_seconds']:.1f}s (pixel match only).")
    else:
        lines.append("No flash-forward match found in the sampled frames (pixel check only).")
    return lines
