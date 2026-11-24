"""Version 1 of cover.json. Report independent field errors in one pass."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
import math
import re
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from urllib.parse import urlsplit

from . import CoverError
from .frame import dimensions, inside
from .geometry import SIZES, placement


@dataclass(frozen=True)
class Face:
    cx: float
    cy: float
    fh: float


@dataclass(frozen=True)
class Frame:
    src: str
    w: int
    h: int
    face: Face


@dataclass(frozen=True)
class Source:
    name: str
    rights: str
    url: str | None = None
    date: str | None = None
    timestamp: float | None = None


@dataclass(frozen=True)
class Clipping:
    masthead: str
    kicker: str
    dateline: str
    body: str
    headline: str | None = None
    accent: str | None = None
    credit: str | None = None


@dataclass(frozen=True)
class Plate:
    top: str
    bottom: str
    tag: str | None = None


@dataclass(frozen=True)
class Number:
    figure: str
    label: str
    tag: str | None = None


@dataclass(frozen=True)
class Quote:
    text: str
    highlight: str
    by: list[str]


STYLES = {"clipping": Clipping, "plate": Plate, "number": Number, "quote": Quote}
# Limits follow the smallest regions: one masthead or plate line, up to three
# headline lines, a half-canvas quote, and two short lines of attribution.
CAPS = {
    "clipping": {"masthead": 28, "kicker": 96, "dateline": 64, "headline": 84,
                 "body": 8000, "credit": 64},
    "plate": {"top": 28, "bottom": 32, "tag": 64},
    "number": {"figure": 12, "label": 60, "tag": 64},
    "quote": {"text": 160, "highlight": 100, "by": 52},
}
OPTIONAL = {"headline", "accent", "credit", "tag"}
SPELLED = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()


@dataclass(frozen=True)
class Cover:
    version: int
    frame: Frame
    source: Source
    seed: int = 11
    said: str | None = None
    clipping: Clipping | None = None
    plate: Plate | None = None
    number: Number | None = None
    quote: Quote | None = None

    def to_dict(self) -> dict:
        def present(obj):
            return {k: present(v) if isinstance(v, dict) else v
                    for k, v in obj.items() if v is not None}
        return present(asdict(self))

    @classmethod
    def from_dict(cls, data: dict, directory: Path) -> Cover:
        cover, report = inspect(data, directory)
        if cover is None:
            raise CoverError(messages(report))
        return cover


TYPOGRAPHY = str.maketrans("‘’“”‐‑‒–—―−", "''\"\"---–––-")


def normalized(text: str) -> str:
    return " ".join(text.translate(TYPOGRAPHY).casefold().split())


def contains(text: str, phrase: str, *, clause_end=False) -> bool:
    phrase = normalized(phrase)
    if not re.search(r"\w", phrase):
        return False
    pattern = re.escape(phrase)
    if clause_end and phrase.endswith("."):
        pattern = re.escape(phrase[:-1]) + r"(?:\.|(?=[,;:–]))"
    # A decimal separator, an apostrophe or a hyphen inside a word is not a boundary,
    # and a number does not start after its own minus sign.
    sign = r"(?<![-–])" if re.match(r"[$£€¥.]?\d", phrase) else ""
    return bool(re.search(r"(?<!\w)(?<!\w['-])(?<!\d[.,])" + sign + pattern +
                          r"(?!\w|['-]\w|[.,:–]\d)", normalized(text)))


def displayed_highlight(text: str, highlight: str) -> str:
    start = text.translate(TYPOGRAPHY).find(highlight.translate(TYPOGRAPHY))
    return text[start:start + len(highlight)] if start >= 0 else ""


def finite(value) -> bool:
    return type(value) in (int, float) and abs(value) <= sys.float_info.max


def messages(report: dict) -> str:
    return "\n".join(f"{p['path']}: {p['message']}" for p in report["problems"])


@dataclass
class _Validation:
    problems: list[dict] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)

    def problem(self, path, message):
        self.problems.append({"path": path, "message": message})

    def object_at(self, path, value, allowed):
        if not isinstance(value, dict):
            self.problem(path, "Supply a JSON object.")
            return {}
        for key in sorted(value.keys() - set(allowed), key=str):
            self.problem(f"{path}.{key}", "Remove this unknown field. Use the plain text fields from 'zing cover styles'.")
        return value

    def string(self, path, value, cap=None):
        if not isinstance(value, str) or not value.strip():
            self.problem(path, "Supply nonempty plain text.")
            return ""
        if value.lstrip().startswith("[REPLACE"):
            self.problem(path, "Replace the bracketed starter text with the clip's real information.")
        if cap and len(value) > cap:
            self.problem(path, f"Shorten this field to {cap} characters or fewer.")
        return value

    def record(self, name, test, path, message):
        self.checks[name] = "passed" if test else "failed"
        if not test:
            self.problem(path, message)


def _frame(value, directory, v):
    previous = len(v.problems)
    fr = v.object_at("frame", value, ("src", "w", "h", "face"))
    src = v.string("frame.src", fr.get("src"))
    w, h = fr.get("w"), fr.get("h")
    for key in ("w", "h"):
        if type(fr.get(key)) is not int or not 1 <= fr[key] <= 0xffffffff:
            v.problem("frame." + key, "Set this to the positive integer pixel dimension of the frame.")
    if src:
        try:
            actual = dimensions(inside(directory, src))
            v.record("frame_dimensions", actual == (w, h), "frame", f"Set w and h to the file's {actual[0]} and {actual[1]} pixels.")
        except (OSError, ValueError, RuntimeError) as exc:
            v.problem("frame.src", str(exc))
    face = v.object_at("frame.face", fr.get("face"), ("cx", "cy", "fh"))
    cx, cy, fh = (face.get(k) for k in ("cx", "cy", "fh"))
    if not all(finite(n) and 0 < n <= 1 for n in (cx, cy, fh)) or cx >= 1 or cy >= 1:
        v.problem("frame.face", "Set cx and cy inside (0,1) and fh to the fraction of frame height occupied by the face.")
    elif type(w) is int and type(h) is int and 0 < w <= 0xffffffff and 0 < h <= 0xffffffff:
        half_width = fh * h / w / 2
        v.record("face_inside_frame", half_width <= min(cx, 1 - cx) + 1e-12 and fh / 2 <= min(cy, 1 - cy) + 1e-12,
               "frame.face", "Move the centre or reduce fh so the square face box fits inside the frame.")
    return Frame(src, w, h, Face(cx, cy, fh)) if len(v.problems) == previous else None


def _source(value, v):
    source = v.object_at("source", value, [f.name for f in fields(Source)])
    name = v.string("source.name", source.get("name"))
    rights = v.string("source.rights", source.get("rights"))
    v.checks["source_rights"] = "failed" if any(p["path"] == "source.rights" for p in v.problems) else "passed"
    for key in ("url", "date"):
        if key in source:
            v.string("source." + key, source[key])
    url = source.get("url")
    if isinstance(url, str) and url.strip():
        try:
            parts = urlsplit(url)
            valid_url = parts.scheme in ("http", "https") and bool(parts.hostname)
        except ValueError:
            valid_url = False
        if not valid_url:
            v.problem("source.url", "Give the http or https URL of the original footage.")
    elif "url" not in source and rights and not rights.startswith("[REPLACE"):
        if not re.search(r"\b(own|owned|self[- ]shot|filmed by (me|us))\b", rights, re.I):
            v.problem("source.url", "Add the original footage URL. For your own footage, write 'own' in source.rights.")
    if "timestamp" in source and not (finite(source["timestamp"]) and source["timestamp"] >= 0):
        v.problem("source.timestamp", "Use a finite, nonnegative time in seconds.")
    return source, name


def _style_fields(style, block, v):
    for key, cap in CAPS[style].items():
        if key not in block and key in OPTIONAL:
            continue
        if key == "by":
            lines = block.get(key)
            if not isinstance(lines, list) or not 1 <= len(lines) <= 2:
                v.problem("quote.by", "Supply a list of one or two attribution lines.")
            if isinstance(lines, list):
                for i, line in enumerate(lines):
                    v.string(f"quote.by[{i}]", line, cap)
        else:
            v.string(f"{style}.{key}", block.get(key), cap)
    accent = block.get("accent")
    if "accent" in block and not (isinstance(accent, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", accent)):
        v.problem("clipping.accent", "Use a six-digit hex colour such as #8c1d2c.")


_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_WORD_VALUES = {word: str(i) for i, word in enumerate(SPELLED)}
for tens, word in enumerate(_TENS, 2):
    _WORD_VALUES[word] = str(tens * 10)
    for units, unit in enumerate(SPELLED[1:10], 1):
        _WORD_VALUES[f"{word} {unit}"] = str(tens * 10 + units)
# Match the compound first so "twenty-four" contributes one value. "one-third" and
# "twenty-first" are not the figures 1 and 20.
_NUMBER_WORD = re.compile(
    r"(?<![a-z]-)\b(?:(?:" + "|".join(_TENS) + r")(?:[ –-](?:" + "|".join(SPELLED[1:10]) + r"))?|(?:" + "|".join(SPELLED) + r"))\b"
    r"(?!-(?:first|seconds?)\b)"
    r"(?![ -](?:thirds?|fourths?|fifths?|sixths?|sevenths?|eighths?|ninths?|tenths?|elevenths?|twelfths?"
    r"|hal(?:f|ves)|quarters?|\w+ieths?|\w+teenths?|(?:hundred|thousand|million|billion|trillion)ths?)\b)")
_BIG = {"thousand": 3, "million": 6, "billion": 9, "trillion": 12}
_MAGNITUDES = "hundred|" + "|".join(_BIG)
_SUFFIXES = {"k": "thousand", "m": "million", "b": "billion", "t": "trillion", "%": "percent"}
_SIGN = r"(?:(?<![^\s(])-)?"
_VALUE = "(" + _SIGN + r"\d+(?:[.,]\d+)*)"
# "COVID-19" does not say the figure 19.
_EDGES = r"(?<!\w)(?<![a-z]-)(?<!\d[.,])%s(?!\w|[.,]\d)"
_SPOKEN_FIGURE = re.compile(_EDGES % (_VALUE + r"([a-z]+|\s*%|\s+(?:" + _MAGNITUDES + r"|percent)\b)?"))
# On the cover a spaced letter is a scale ("15 M"). In speech "15 m" may be metres.
# Every run of digits drawn on the cover is checked, wherever it sits.
_DRAWN_FIGURE = re.compile(_VALUE + r"([a-z]+|\s*%|\s+(?:" + _MAGNITUDES + r"|percent|[kmbt])\b)?")
_PLAIN = r"\d+(?:\.\d+)?(?![.,]?\d|-\w|\s*(?:%|percent\b))"
_SPOKEN_RUN = re.compile(r"(?<!\w)(?<!\d[.,])" + _PLAIN + r"(?:(?: and)? (?:" + _PLAIN + "|" + _MAGNITUDES + r")\b)+")


def _fold(match):
    """Rewrite a spoken compound as one figure: "1 hundred and 4 thousand" is 104000."""
    words, out, i = match[0].split(), [], 0

    def number(k):
        return k < len(words) and words[k][0].isdigit()

    def group(k):
        """NUM [hundred [[and] NUM below 100]]. Return the value and the next index."""
        value, k = Decimal(words[k]), k + 1
        if k < len(words) and words[k] == "hundred":
            value, k = value * 100, k + 1
            tail = k + 1 if k < len(words) and words[k] == "and" else k
            if number(tail) and Decimal(words[tail]) < 100 and words[tail + 1:tail + 2] != ["hundred"]:
                value, k = value + Decimal(words[tail]), tail + 1
        return value, k

    while i < len(words):
        if not number(i):
            out.append(words[i])
            i += 1
            continue
        first, at, total, ceiling, joined = i, i, Decimal(0), None, False
        while True:
            value, after = group(at)
            scale = _BIG.get(words[after]) if after < len(words) else None
            # "2 billion and 500 million" is two figures. "2 thousand and 4" is one.
            if scale is not None and (ceiling is None or (scale < ceiling and value < 1000 and not joined)):
                ceiling, i = scale, after + 1
                total += value.scaleb(scale)
                joined = i < len(words) and words[i] == "and"
                at = i + 1 if joined else i
                if number(at) and value == value.to_integral_value():
                    continue
            elif ceiling is None:
                total, i = value, after
            # "2 thousand and 4" and "2 thousand 5 hundred" are one figure.
            # "5 million 2 years ago" is two.
            elif scale is None and ceiling == 3 and (value < 100 or (value < 1000 and not joined)):
                total, i = total + value, after
            break
        out.append(words[first] if i == first + 1 else format(total.normalize() + 0, "f"))
    return " ".join(out)


def _figures(text, *, spoken=False):
    text = re.sub(r"(?<![\w.])\.(?=\d)", "0.", normalized(text))
    if spoken:
        # "a hundred" is 100. "half a million" and "a hundred and a half" are not checked.
        text = re.sub(r"(?<!half )(?<!of )(?<!and )\ba (?=(?:" + _MAGNITUDES + r")\b(?! and a\b))", "1 ", text)
        text = _NUMBER_WORD.sub(lambda m: _WORD_VALUES[re.sub("[–-]", " ", m[0])], text)
        # "five-billion-dollar" and "50-percent" carry their scale.
        text = re.sub(r"(?:(?<=\d)|(?<=hundred))-(?=(?:" + _MAGNITUDES + r"|percent)\b)", " ", text)
        # "two and a half million" is not the figure 2.
        text = re.sub(r"\d+(?:\.\d+)?(?: (?:" + _MAGNITUDES + r"))? and a (?:half|quarter|third)\b", "", text)
        # "three point one four" is 3.14 and "point five" is 0.5.
        text = re.sub(r"(?:(?<=\d) |(?<!this )(?<!that )(?<!the )(?<!a )(?<!one )(?<!some )(?<!any )(?<!no )\b)point (\d+\b(?: \d\b)*)",
                      lambda m: ("" if m[0][0] == " " else "0") + "." + m[1].replace(" ", ""), text)
    text = re.sub(r"(?:\b(?:minus|negative) |(?<![^\s(])-)[$£€¥](?=\d)", "-", text)
    if spoken:
        text = re.sub(r"\b(?:minus|negative) (?=\d)", "-", text)
        text = _SPOKEN_RUN.sub(_fold, text)
    for match in (_SPOKEN_FIGURE if spoken else _DRAWN_FIGURE).finditer(text):
        value, suffix = match.groups("")
        if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", value):
            value = value.replace(",", "")
        suffix = suffix.strip()
        suffix = _SUFFIXES.get(suffix, suffix)
        yield value, suffix
        # Units can also be drawn in number.label. A scale changes the figure itself.
        if spoken and suffix and not re.fullmatch(_MAGNITUDES, suffix):
            yield value, ""


_SCALES = {"": 0, "hundred": 2, "thousand": 3, "million": 6, "billion": 9, "trillion": 12}


def _amount(value, suffix):
    """The number a figure stands for, so 15K, 15,000 and "fifteen thousand" agree."""
    if suffix not in _SCALES:
        return None
    try:
        return Decimal(value).scaleb(_SCALES[suffix]).normalize() + 0
    except InvalidOperation:
        return None


def _honesty(style, block, name, said, v):
    def content(key):
        value = block.get(key)
        return value if isinstance(value, str) else ""

    if style == "clipping":
        mast, body = content("masthead"), content("body")
        v.record("masthead_attribution", contains(name, mast) or contains(said, mast), "clipping.masthead",
                   "The page shows this name as the source of the story. Use the real source or a name the speaker actually says.")
        if said and body:
            v.record("body_in_transcript", contains(said, body, clause_end=True), "clipping.body", "Copy one continuous passage from said.")
        else:
            v.checks["body_in_transcript"] = "skipped (needs said and body)"
    if style == "quote":
        quote, highlight = content("text"), content("highlight")
        if quote and not said and not re.search(r"\w", quote):
            v.problem("quote.text", "Include at least one word from the speaker.")
        if highlight and quote:
            v.record("highlight_in_quote", bool(displayed_highlight(quote, highlight)), "quote.highlight", "Copy the highlighted words exactly from quote.text.")
        if said and quote:
            v.record("quote_in_transcript", contains(said, quote, clause_end=True), "quote.text", "Copy the speaker's exact words from said, without outer quotation marks.")
        else:
            v.checks["quote_in_transcript"] = "skipped (needs said and text)"
    if style == "number":
        figures = list(_figures(content("figure")))
        if not figures:
            v.problem("number.figure", "Use a figure with digits that the speaker says, or remove the number block.")
        if said and figures:
            spoken = set(_figures(said, spoken=True))
            amounts = {_amount(*pair) for pair in spoken} - {None}
            for value, suffix in figures:
                amount = _amount(value, suffix)
                found = (value, suffix) in spoken or (amount is not None and amount in amounts)
                figure = value + suffix
                v.record("figure_in_transcript_" + figure, found, "number.figure", f"Use a figure the speaker says. Could not find {figure} in said.")
        else:
            v.checks["figure_in_transcript"] = "skipped (needs said and a figure)"


def inspect(data, directory: Path, *, styles=None, sizes=None, scale=1) -> tuple[Cover | None, dict]:
    v = _Validation()
    warnings = []
    data = v.object_at("cover.json", data, [f.name for f in fields(Cover)])
    if type(data.get("version")) is not int or data["version"] != 1:
        v.problem("version", "Set version to the integer 1.")
    seed = data.get("seed", 11)
    if type(seed) is not int or not 0 <= seed <= 0xffffffff:
        v.problem("seed", "Use an integer from 0 to 4294967295.")
    frame = _frame(data.get("frame"), directory, v)
    source, name = _source(data.get("source"), v)
    said = v.string("said", data["said"]) if "said" in data else ""
    blocks = {}
    for style, cls in STYLES.items():
        if style in data:
            block = v.object_at(style, data[style], [f.name for f in fields(cls)])
            blocks[style] = block
            _style_fields(style, block, v)
            _honesty(style, block, name, said, v)
    if not blocks:
        v.problem("cover.json", "Add a clipping, plate, number or quote block.")
    for style in styles or blocks:
        if style not in blocks:
            v.problem(style, f"Add a {style} block or remove it from --style.")
        elif frame:
            for size in sizes or SIZES:
                crop = placement(frame, style, size)
                zoom = crop["zoom"] * scale
                if not all(math.isfinite(crop[key] * scale) for key in ("zoom", "w", "h", "x", "y")):
                    v.problem("frame.face", "Increase fh so the face crop has finite dimensions and coordinates.")
                    break
                if zoom > 2.5:
                    warnings.append({"path": f"{style}.{size}", "message": f"The face is enlarged {zoom:.2f}x. Use a higher-resolution frame for more detail."})
    v.checks["face_resolution"] = ("warning" if warnings else "passed") if frame else "skipped (needs a valid frame)"
    v.checks["contract"] = "failed" if v.problems else "passed"
    report = {"valid": not v.problems, "problems": v.problems, "warnings": warnings, "checks": v.checks}
    if v.problems:
        return None, report
    cover = Cover(1, frame, Source(**source), seed, said or None,
                  **{style: STYLES[style](**block) for style, block in blocks.items()})
    return cover, report


def load(directory: Path, **options) -> tuple[Cover | None, dict]:
    try:
        data = json.loads((directory / "cover.json").read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        return None, {"valid": False, "problems": [{"path": "cover.json", "message": f"Supply a readable JSON file. {exc}"}],
                      "warnings": [], "checks": {"contract": "failed"}}
    return inspect(data, directory, **options)
