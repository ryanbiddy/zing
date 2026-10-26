"""Versioned P17 evidence and shortage records; Composition remains unchanged."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from myzing.contracts import Record
from myzing.schemas import Shot, Word


@dataclass
class ClipStudy(Record):
    asset_id: str
    path: str
    sha256: str
    duration: float
    status: str
    study_path: str | None = None
    words: list[Word] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)
    keepers: list[dict[str, Any]] = field(default_factory=list)
    dead_air: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    asr_repair: dict[str, Any] = field(default_factory=dict)
    audio_tags: dict[str, Any] = field(default_factory=dict)
    text_geometry: dict[str, Any] = field(default_factory=dict)
    version: int = 1


@dataclass
class Shortage(Record):
    code: str
    missing: str
    remedy: str
    asset_ids: list[str] = field(default_factory=list)
    version: int = 1
    suggestions: list[dict[str, Any]] = field(default_factory=list)


class PlanningShortage(ValueError):
    def __init__(self, shortage: Shortage):
        self.shortage = shortage
        super().__init__(f"{shortage.code}: {shortage.missing} {shortage.remedy}")


def shortage(code: str, missing: str, remedy: str, *asset_ids: str):
    raise PlanningShortage(Shortage(code, missing, remedy, list(asset_ids)))
