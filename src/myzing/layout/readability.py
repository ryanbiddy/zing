"""Explicit phone caption preference, separate from recovered typography."""


def phone_size(width, height, picture_width=None):
    """Minimum em size in output pixels for a 400px-wide phone presentation.

    Portrait: at least 8% of visible picture width and 7% of output width
    (32px when full-width at 400px). Square/wide: 6.5% of picture width,
    bounded by the short side so landscape captions do not dominate.
    """
    picture_width = width if picture_width is None else picture_width
    if height > width:
        return min(512., max(.08*picture_width, .07*width))
    return min(512., .065*min(picture_width, height))
