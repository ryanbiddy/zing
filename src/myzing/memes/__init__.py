"""Deterministic still memes. Pillow is loaded only when rendering."""
from myzing.doctor import _install_command


class MemeError(ValueError):
    """An actionable input, dependency, or rendering error."""


PILLOW_HINT = f"Pillow is required for meme rendering. Run {_install_command('myzing[memes]')}"
