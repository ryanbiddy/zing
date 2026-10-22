"""Deterministic still memes. Pillow is loaded only when rendering."""


class MemeError(ValueError):
    """An actionable input, dependency, or rendering error."""


PILLOW_HINT = 'Pillow is required for meme rendering: python -m pip install "myzing[memes]"'
