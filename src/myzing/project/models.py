"""Version 1 inventory contracts; independent of the composition schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class ProjectError(ValueError):
    """An invalid project or an operation the caller can remedy."""


class Record:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        _version(data, cls.__name__)
        try:
            return cls(**data)
        except TypeError as exc:
            raise ProjectError(f"Invalid {cls.__name__}: {exc}") from exc


def _version(data: dict, name: str) -> None:
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ProjectError(f"Unsupported {name} version; expected version 1. Upgrade Zing if needed.")


@dataclass
class SourceRecord(Record):
    origin: str
    supplied_by: str = "user"
    license: str = "user-supplied"
    version: int = 1


@dataclass
class ReferenceResolution(Record):
    state: str
    path: str | None = None
    sha256: str | None = None
    byte_length: int | None = None
    item_ref: str | None = None
    source_url: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    version: int = 1

    def __post_init__(self):
        if self.state not in {"resolved", "unresolved"}:
            raise ProjectError("Invalid reference resolution state.")
        if self.state == "resolved" and (
            not isinstance(self.path, str) or not self.path
            or not isinstance(self.sha256, str) or len(self.sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.sha256)
            or type(self.byte_length) is not int or self.byte_length < 0
        ):
            raise ProjectError("Resolved reference needs a path, SHA-256 and byte length.")


@dataclass
class Reference(Record):
    value: str
    kind: str  # url, file, uoink
    source: SourceRecord
    # Later match passes can attach a study without changing the input reference.
    study: dict[str, Any] | None = None
    state: str = "recorded"
    version: int = 1
    resolution: ReferenceResolution | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Reference:
        _version(data, cls.__name__)
        return super().from_dict({
            **data, "source": SourceRecord.from_dict(data["source"]),
            "resolution": (ReferenceResolution.from_dict(data["resolution"])
                           if data.get("resolution") is not None else None),
        })


@dataclass
class Rational(Record):
    numerator: int
    denominator: int
    version: int = 1

    def __post_init__(self):
        if self.numerator <= 0 or self.denominator <= 0:
            raise ProjectError("Frame rate numerator and denominator must be positive.")


@dataclass
class Probe(Record):
    duration: float | None
    streams: list[dict[str, Any]]
    format: dict[str, Any]
    width: int | None
    height: int | None
    rotation: float
    fps: Rational | None
    has_audio: bool
    orientation: str | None
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    version: int = 1

    @classmethod
    def from_dict(cls, data: dict) -> Probe:
        _version(data, cls.__name__)
        return super().from_dict({**data, "fps": Rational.from_dict(data["fps"]) if data["fps"] else None})


@dataclass
class Asset(Record):
    id: str
    path: str
    original_path: str
    sha256: str
    size: int
    mtime_ns: int
    source: SourceRecord
    probe: Probe | None
    state: str = "ready"  # ready, missing, unsupported
    revision: int = 1  # changes only when content changes, not on a touch/move
    previous_paths: list[str] = field(default_factory=list)
    error: str | None = None
    version: int = 1

    @classmethod
    def from_dict(cls, data: dict) -> Asset:
        _version(data, cls.__name__)
        return super().from_dict({
            **data,
            "source": SourceRecord.from_dict(data["source"]),
            "probe": Probe.from_dict(data["probe"]) if data["probe"] else None,
        })


@dataclass
class ProjectManifest(Record):
    reference: Reference
    clips_root: str
    source: SourceRecord
    assets: list[Asset] = field(default_factory=list)
    version: int = 1

    @classmethod
    def from_dict(cls, data: dict, project: Path | None = None) -> ProjectManifest:
        from .paths import resolve_path

        _version(data, cls.__name__)
        try:
            result = super().from_dict({
                **data,
                "reference": Reference.from_dict(data["reference"]),
                "source": SourceRecord.from_dict(data["source"]),
                "assets": [Asset.from_dict(a) for a in data["assets"]],
            })
            resolve_path(result.clips_root, project, entry="clips_root")
            resolve_path(result.source.origin, project, entry="source.origin")
            if result.reference.kind == "file":
                resolve_path(result.reference.value, project, entry="reference.value")
                resolve_path(result.reference.source.origin, project, entry="reference.source.origin")
            if result.reference.resolution and result.reference.resolution.path:
                resolve_path(result.reference.resolution.path, project, entry="reference.resolution.path")
            ids, paths = set(), set()
            for index, asset in enumerate(result.assets):
                entry = f"assets[{index}] ({asset.id})"
                for name in ("path", "original_path"):
                    resolve_path(getattr(asset, name), project, entry=f"{entry}.{name}")
                resolve_path(asset.source.origin, project, entry=f"{entry}.source.origin")
                if not isinstance(asset.previous_paths, list):
                    raise ProjectError(f"Invalid {entry}.previous_paths: expected a list of paths.")
                for previous_index, value in enumerate(asset.previous_paths):
                    resolve_path(value, project, entry=f"{entry}.previous_paths[{previous_index}]")
                if asset.id in ids or (asset.state != "missing" and asset.path in paths):
                    raise ProjectError("Project contains duplicate asset IDs or paths.")
                ids.add(asset.id)
                if asset.state != "missing":
                    paths.add(asset.path)
                if (not asset.path or not asset.id or asset.revision < 1
                        or asset.size < 0 or asset.state not in {"ready", "missing", "unsupported"}
                        or len(asset.sha256) != 64
                        or any(c not in "0123456789abcdef" for c in asset.sha256)):
                    raise ProjectError("Project contains an invalid asset record.")
            return result
        except (KeyError, TypeError, AttributeError) as exc:
            raise ProjectError(f"Invalid project manifest: {exc}. Restore a valid project.json.") from exc
