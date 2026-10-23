"""Versioned still records, independent of the shared composition schemas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from myzing.memes import MemeError


@dataclass(kw_only=True)
class Record:
    version: int = 1

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise MemeError(f"Unsupported {type(self).__name__} version: {self.version}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        if not isinstance(data, dict):
            raise MemeError(f"{cls.__name__} must be a JSON object")
        try:
            return cls(**data)
        except TypeError as exc:
            raise MemeError(f"Invalid {cls.__name__}: {exc}") from exc


@dataclass
class Photo(Record):
    id: str
    path: str
    sha256: str
    width: int
    height: int
    size_bytes: int
    description: str
    colors: list[str]
    orientation: str
    edge_density: float
    band_density: float
    faces: list[dict]
    face_method: str
    warnings: list[str] = field(default_factory=list)
    # Estimated subject box (normalized [x, y, w, h]) for crops when no
    # prominent face is found; None for flat photos or older indexes.
    subject: list[float] | None = None
    # Decoding report (myzing.memes.photo.PhotoSource): original and working
    # sizes, decoder and orientation source; None for older indexes.
    source: dict | None = None
    # Model-free distinct-region estimate (myzing.memes.subject); protected
    # from text when confident and no prominent face. None for older indexes.
    subject_estimate: dict | None = None
    # Mean luma 0..1 and text read by local OCR ("" = none found; None = OCR
    # unavailable or an older index). Offline lines may use both.
    brightness: float | None = None
    text: str | None = None


@dataclass
class Concept(Record):
    id: str
    photo: str
    title: str
    texts: list[str]
    why: str
    provider: str
    layout: str
    regions: list[list[float]] | None
    score: dict
    alt_text: str
    warnings: list[str]
    path: str = ""
    render: dict = field(default_factory=dict)
    outputs: list[dict] = field(default_factory=list)
    # Resolved framing. Indexes written before framing existed used contain.
    fit: str = "contain"
    focus: list[float] | None = None


@dataclass
class StillIndex(Record):
    topic: str
    aspect: str
    photos: list[Photo]
    concepts: list[Concept]
    contact_sheet: dict
    prompt_path: str = "meme-writer.md"
    warnings: list[str] = field(default_factory=list)
    selected: str | None = None
    # Explicit user protect boxes (normalized source [x, y, w, h]); pick re-checks them.
    protect: list[list[float]] | None = None

    @classmethod
    def from_dict(cls, data: dict):
        if not isinstance(data, dict):
            raise MemeError("StillIndex must be a JSON object")
        values = dict(data)
        for key, kind in (("photos", Photo), ("concepts", Concept)):
            if not isinstance(values.get(key), list):
                raise MemeError(f"StillIndex {key} must be an array")
            values[key] = [kind.from_dict(item) for item in values[key]]
        return super().from_dict(values)
