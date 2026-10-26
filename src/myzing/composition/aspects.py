"""Delivery names, dimensions and conservative UI insets owned by Zing."""

ASPECTS = ("16:9", "1:1", "9:16")
SUPPORTED_ASPECTS = (*ASPECTS, "4:5")
# left, top, right, bottom: generic delivery reserves, not platform guarantees.
SAFE_INSETS = {"9:16": (.06, .08, .16, .20), "1:1": (.05, .05, .05, .10),
               "4:5": (.05, .05, .05, .10),
               "16:9": (.05, .05, .05, .10)}


def parse_aspects(value):
    values = list(ASPECTS) if value == "all" else value.split(",") if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)) or not values or any(not isinstance(v, str) for v in values):
        raise ValueError("aspect: supply all or a list of 16:9,1:1,9:16")
    values = [v.strip().replace("x", ":") for v in values]
    if not values or any(v not in SUPPORTED_ASPECTS for v in values) or len(set(values)) != len(values):
        raise ValueError("aspect: choose each of 16:9, 1:1, 9:16 at most once")
    return values


def dimensions(aspect, short_side=1080):
    if type(short_side) is not int or not 18 <= short_side <= 4320 or short_side % 18:
        raise ValueError("short_side must be a multiple of 18 from 18 to 4320 (for exact, even 16:9 and 9:16 outputs)")
    if aspect == "4:5" and short_side % 8:
        raise ValueError("4:5 short_side must also be divisible by 8 for exact even dimensions")
    return {"4:5": (short_side, short_side * 5 // 4), "16:9": (short_side * 16 // 9, short_side), "1:1": (short_side, short_side),
            "9:16": (short_side, short_side * 16 // 9)}[aspect]


def aspect_for(width, height):
    for aspect in SUPPORTED_ASPECTS:
        w, h = map(int, aspect.split(":"))
        if width * h == height * w:
            return aspect
    raise ValueError("delivery aspect must be 16:9, 1:1, or 9:16")


def requested_aspects(plan, value=None):
    return parse_aspects(value) if value is not None else list(plan.brief.aspects) if plan.brief else []
