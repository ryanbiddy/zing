"""Version 1 brief answers. No inferred creative judgments or timestamps."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any


class BriefError(ValueError):
    """An answer or saved brief that the caller can correct."""


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BriefError(f"{name}: enter nonempty text, or omit the answer to use its default.")
    return value.strip()


def number(value: Any, name: str) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise BriefError(f"{name}: use a finite number of seconds.")
    return float(value)


def moments(value: Any, name: str) -> list[dict]:
    if not isinstance(value, list):
        raise BriefError(f'{name}: use a list of {{"clip": "ID or path", "start": 0, "end": 2}} '
                         'or {"phrase": "exact words"} objects.')
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise BriefError(f"{name}: each moment must be an object.")
        if set(item) in ({"phrase"}, {"clip", "phrase"}):
            entry = {"phrase": text(item["phrase"], name + ".phrase")}
            if "clip" in item:
                entry["clip"] = text(item["clip"], name + ".clip")
        elif set(item) == {"clip", "start", "end"}:
            start, end = number(item["start"], name), number(item["end"], name)
            if start < 0 or end <= start:
                raise BriefError(f"{name}: times must satisfy 0 <= start < end.")
            entry = {"clip": text(item["clip"], name + ".clip"), "start": start, "end": end}
        else:
            raise BriefError(f"{name}: give a quoted phrase (optionally with clip), or clip/start/end.")
        result.append(entry)
    return result


def audio(value: Any, name: str) -> dict:
    choices = ("supplied files", "none", "keep original audio")
    if not isinstance(value, dict) or set(value) - {"source", "files"}:
        raise BriefError(f'{name}: use {{"source": "none"}}, "keep original audio", or "supplied files" with files.')
    source = value.get("source")
    if source not in choices:
        raise BriefError(f"{name}.source: choose {', '.join(choices)}.")
    files = value.get("files", [])
    if not isinstance(files, list):
        raise BriefError(f"{name}.files: use a list of file paths or inventory IDs.")
    files = [text(p, name + ".files") for p in files]
    if (source == "supplied files") != bool(files):
        raise BriefError(f"{name}: supplied files needs at least one file; other choices cannot include files.")
    return {"source": source, "files": files}


@dataclass
class Brief:
    purpose: str = "Explore the footage"
    audience: str = "Not specified"
    platform: str = "Not specified"
    aspect: str = "9:16"
    target_length_seconds: float = 30.0
    must_keep: list[dict] = field(default_factory=list)
    forbidden: list[dict] = field(default_factory=list)
    caption_language: str = "original"
    exact_spellings: list[str] = field(default_factory=list)
    music: dict = field(default_factory=lambda: {"source": "keep original audio", "files": []})
    sfx: dict = field(default_factory=lambda: {"source": "none", "files": []})
    reference_match: str = "recommend"
    version: int = 1
    framing: str = field(default="auto", metadata={"omit_default": True})
    aspects: list[str] = field(default_factory=list, metadata={"omit_default": True})
    framing_max_upscale: float = field(default=2.5, metadata={"omit_default": True})

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise BriefError("Unsupported Brief version; expected version 1. Upgrade Zing if needed.")
        for name in ("purpose", "audience", "platform", "caption_language"):
            setattr(self, name, text(getattr(self, name), name))
        if self.aspect not in ("9:16", "1:1", "16:9"):
            raise BriefError("aspect: choose 9:16, 1:1, or 16:9.")
        if self.framing not in ("auto", "fit", "fill", "reframe", "blurfill"):
            raise BriefError("framing: choose auto, fit, fill, reframe, or blurfill.")
        if (not isinstance(self.aspects, list) or any(a not in ("16:9", "1:1", "9:16") for a in self.aspects)
                or len(set(self.aspects)) != len(self.aspects)):
            raise BriefError("aspects: use a unique list of 16:9, 1:1, and/or 9:16.")
        self.framing_max_upscale = number(self.framing_max_upscale, "framing_max_upscale")
        if not 1 <= self.framing_max_upscale <= 16:
            raise BriefError("framing_max_upscale: choose a linear enlargement limit from 1 to 16.")
        self.target_length_seconds = number(self.target_length_seconds, "target_length_seconds")
        if not 0 < self.target_length_seconds <= 60:
            raise BriefError("target_length_seconds: choose more than 0 and at most 60 seconds for v0.1.")
        self.must_keep = moments(self.must_keep, "must_keep")
        self.forbidden = moments(self.forbidden, "forbidden")
        if not isinstance(self.exact_spellings, list):
            raise BriefError("exact_spellings: use a list of names or terms with their exact spelling.")
        self.exact_spellings = [text(s, "exact_spellings") for s in self.exact_spellings]
        self.music, self.sfx = audio(self.music, "music"), audio(self.sfx, "sfx")
        if self.reference_match not in ("exact", "pacing only", "recommend"):
            raise BriefError("reference_match: choose exact, pacing only, or recommend.")
        for keep in self.must_keep:
            for avoid in self.forbidden:
                same_clip = keep.get("clip") == avoid.get("clip")
                if "phrase" in keep and "phrase" in avoid:
                    conflict = keep["phrase"] == avoid["phrase"] and (
                        same_clip or "clip" not in keep or "clip" not in avoid)
                else:
                    conflict = same_clip and "start" in keep and "start" in avoid and (
                        max(keep["start"], avoid["start"]) < min(keep["end"], avoid["end"]))
                if conflict:
                    raise BriefError("forbidden: this overlaps a must_keep moment. Change one of the constraints.")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.framing == "auto":
            result.pop("framing")
        if not self.aspects:
            result.pop("aspects")
        if self.framing_max_upscale == 2.5:
            result.pop("framing_max_upscale")
        return result

    @classmethod
    def from_answers(cls, answers: dict) -> Brief:
        if not isinstance(answers, dict):
            raise BriefError("answers: supply a JSON object; omit optional keys to use disclosed defaults.")
        allowed = {f.name for f in fields(cls)} - {"version"}
        # `zing brief new --help` shows a full brief, version included; accept
        # that shape back as long as the version is the one we write.
        if "version" in answers:
            if type(answers["version"]) is not int or answers["version"] != 1:
                raise BriefError("answers: version must be 1 (or omitted).")
            answers = {k: v for k, v in answers.items() if k != "version"}
        unknown = set(answers) - allowed
        if unknown:
            raise BriefError(f"Unknown answer(s): {', '.join(sorted(map(str, unknown)))}. See 'zing brief new --help'.")
        return cls(**answers)

    @classmethod
    def from_dict(cls, data: dict) -> Brief:
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise BriefError("Unsupported Brief version; expected version 1. Use --answers for unversioned answers.")
        missing = {f.name for f in fields(cls)} - {"framing", "aspects", "framing_max_upscale"} - set(data)
        if missing:
            raise BriefError(f"Incomplete saved brief: missing {', '.join(sorted(missing))}. Use --answers to apply defaults.")
        return cls.from_answers({k: v for k, v in data.items() if k != "version"})
