"""Exact output-frame arithmetic using the inventory's Rational contract."""

from fractions import Fraction
import math

from myzing.contracts import typed
from myzing.project.models import Rational


def rate_fraction(fps: Rational) -> Fraction:
    typed(fps, Rational, "fps")
    fps.__post_init__()
    return Fraction(fps.numerator, fps.denominator)


def frame_time(index: int, fps: Rational) -> Fraction:
    """Exact start time of a zero-based output frame, in seconds."""
    if type(index) is not int or index < 0:
        raise ValueError("frame index must be a non-negative integer")
    return index / rate_fraction(fps)


def frame_index(seconds: float | Fraction, fps: Rational, *, rounding: str = "floor") -> int:
    """Floor by default; ceil or nearest (ties forward) must be explicit.

    Decimal float spelling is preserved; 29.97 is never guessed to be 30000/1001.
    These are output CFR indices, not source VFR timestamps.
    """
    if not isinstance(seconds, Fraction):
        typed(seconds, float, "seconds")
        seconds = Fraction(str(seconds))
    if seconds < 0:
        raise ValueError("seconds must be non-negative")
    value = seconds * rate_fraction(fps)
    if rounding == "floor":
        return math.floor(value)
    if rounding == "ceil":
        return math.ceil(value)
    if rounding == "nearest":
        return math.floor(value + Fraction(1, 2))
    raise ValueError("rounding must be floor, ceil, or nearest")
