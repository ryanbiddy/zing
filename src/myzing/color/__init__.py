"""Local SDR look matching. Importing this package needs only the stdlib."""

COLOR_VERSION = "1.0.0"
COLOR_SPACE = (
    "SDR Rec.709/sRGB primaries, D65; display RGB code values treated as sRGB "
    "for CIELAB measurement. No camera LOG, HDR, or scene-linear transform."
)


class ColorError(RuntimeError):
    """An actionable color workflow failure."""


def require_numpy():
    try:
        import numpy
    except ImportError as exc:
        raise ColorError(
            'Color matching requires numpy. Install: python -m pip install "myzing[color]"'
        ) from exc
    return numpy
