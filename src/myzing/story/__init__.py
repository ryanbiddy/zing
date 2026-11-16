"""Paper sets, cutout puppets and narrated stories."""
from importlib import resources
from pathlib import Path

from myzing.factory.tools import FactoryError


class StoryError(FactoryError):
    """An actionable story failure."""


def data_path(*parts: str) -> Path:
    return Path(str((resources.files("myzing") / "_data" / "story").joinpath(*parts)))
