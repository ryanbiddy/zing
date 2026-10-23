"""Reference-derived timing bands; editorial tolerance is separate from frame fidelity."""

from statistics import quantiles

FLOOR_SECONDS = .25
CAP_FRACTION = .5


def timing_band(target, durations):
    """Half the reference IQR plus max(250 ms, 20% of the target), capped.

    Inclusive linear quartiles work for small references too. One measured
    shot supplies no spread. The minimum is an editorial policy, not a
    perceptual confidence interval or a renderer timing allowance.

    The half-width never exceeds max(250 ms, half the target). Shot lengths
    are heavy-tailed, so an uncapped IQR term reaches zero on varied
    references: a 0.4-6 s montage's band admitted half and double its pace.
    """
    spread = 0.0
    if len(durations) > 1:
        q1, _, q3 = quantiles(durations, n=4, method="inclusive")
        spread = q3 - q1
    uncapped = max(FLOOR_SECONDS, .2 * (target or 0)) + spread / 2
    cap = max(FLOOR_SECONDS, CAP_FRACTION * (target or 0))
    margin = min(uncapped, cap)
    return {"lower": max(0.0, target - margin) if target is not None else None,
            "upper": target + margin if target is not None else None,
            "tolerance": margin, "reference_iqr_seconds": spread,
            "reference_shots": len(durations), "capped": uncapped > cap,
            "basis": "Half the reference shot-length IQR plus max(0.25 s, 20% of the target), "
                     "capped at max(0.25 s, 50% of the target)."}


def timing_distance(observed, band):
    if observed is None or band["lower"] is None:
        return "Missing measurement; no timing match established."
    low, high = band["lower"], band["upper"]
    interval = f"{low:.3f}-{high:.3f} s reference band"
    if observed < low - 1e-9:
        return f"{low - observed:.3f} s shorter than the {interval} (observed {observed:.3f} s)."
    if observed > high + 1e-9:
        return f"{observed - high:.3f} s longer than the {interval} (observed {observed:.3f} s)."
    return f"Inside the {interval} (observed {observed:.3f} s)."
