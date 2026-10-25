"""CARD1 contracts, independent of the legacy schemas."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from copy import deepcopy


class Record:
    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError(f"Unsupported {type(self).__name__} version")
        # Reject NaN/Infinity, foreign objects and non-JSON payloads at the boundary.
        json.dumps(asdict(self), allow_nan=False)

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
            raise ValueError(f"Missing or unsupported {cls.__name__} version")
        return cls(**deepcopy(value))


@dataclass
class Section(Record):
    title: str
    facts: dict = field(default_factory=dict)
    confidence: dict = field(default_factory=dict)
    unknowns: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    # One short sentence for readers: what no measurement of an export can reveal.
    # The complete, itemized limitations stay in `unknowns`.
    not_knowable: str = ""
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.title, str) or not self.title:
            raise ValueError("Section needs a title")
        if not isinstance(self.not_knowable, str):
            raise ValueError("not_knowable must be a string")
        if not isinstance(self.facts, dict) or not isinstance(self.confidence, dict):
            raise ValueError("Facts and confidence must be separate objects")
        for values in (self.unknowns, self.lines):
            if not isinstance(values, list) or not all(isinstance(s, str) for s in values):
                raise ValueError("Section prose must be a list of strings")


@dataclass
class HookMetric(Record):
    """A hook observation always travels with its method and evidence basis."""

    method: str
    basis: str
    value: object = None
    status: str = "unknown"
    unit: str = ""
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if not self.method or not self.basis:
            raise ValueError("Hook metrics need a method and basis")
        if self.status not in {"measured", "judgment", "unknown", "not_applicable"}:
            raise ValueError("Unsupported hook metric status")
        if (self.value is None) != (self.status in {"unknown", "not_applicable"}):
            raise ValueError("Unknown hook metrics must have no value; observations need a value")


@dataclass
class StyleCard(Record):
    source: str
    source_sha256: str
    duration_seconds: float
    sections: dict[str, Section]
    recipe_path: str
    commands: list[str]
    summary: list[str]
    warnings: list[str] = field(default_factory=list)
    comparison: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if isinstance(self.duration_seconds, bool) or not isinstance(self.duration_seconds, (int, float)) or self.duration_seconds < 0:
            raise ValueError("Card duration must be a nonnegative number")
        if not isinstance(self.sections, dict) or not all(isinstance(v, Section) for v in self.sections.values()):
            raise ValueError("Card sections must be Section records")
        for section in self.sections.values():
            section.__post_init__()
        if len(self.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.source_sha256):
            raise ValueError("Card needs a lowercase source SHA-256")
        if not 3 <= len(self.summary) <= 6 or not all(isinstance(s, str) and "\n" not in s for s in self.summary):
            raise ValueError("Card summary needs 3-6 one-line strings")

    @classmethod
    def from_dict(cls, value):
        value = deepcopy(value)
        value["sections"] = {k: Section.from_dict(v) for k, v in value["sections"].items()}
        return super().from_dict(value)
