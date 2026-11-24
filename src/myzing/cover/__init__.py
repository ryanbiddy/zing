"""Render a local video frame as a cover."""
from importlib.resources import files
from pathlib import Path


class CoverError(ValueError):
    """An actionable cover input or rendering error."""


def cover_directory(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise CoverError("Supply a nonempty cover directory.")
    return Path(value).expanduser()


def data_path(*parts: str) -> Path:
    return Path(str(files("myzing").joinpath("_data", "cover", *parts)))
