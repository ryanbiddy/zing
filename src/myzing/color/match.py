"""Bounded deterministic look/strength/correction search on distributions."""

from dataclasses import replace

from .cube import apply_cube, make_cube
from .looks import apply_transform, look_bank, transform_for
from .models import Candidate, MatchResult
from .science import np
from .stats import bounded_pixels, distance, statistics


def rank_looks(reference_rgb, clip_rgb, *, confidence=0.85, warnings=()) -> MatchResult:
    # Same sampling for target and candidates; no pixel correspondence is used.
    ref = statistics(bounded_pixels(reference_rgb, 2048))
    clip = bounded_pixels(clip_rgb, 2048)
    baseline, _ = distance(statistics(clip), ref)
    candidates = []
    for look in look_bank():
        cache = {}

        def evaluate(values):
            key = tuple(round(float(v), 7) for v in values)
            if key not in cache:
                t = transform_for(look, key[0], exposure_ev=key[1], temperature=key[2], tint=key[3])
                score, components = distance(statistics(apply_transform(clip, t)), ref)
                cache[key] = (score, components, t)
            return cache[key]

        strengths = [0.0] if look == "neutral" else np.linspace(0, 1, 11)
        starts = sorted((evaluate((s, 0, 0, 0)) for s in strengths), key=lambda v: v[0])[:2]
        solutions = []
        for initial in starts:
            best = initial
            t = initial[2]
            values = np.array([t.strength, 0.0, 0.0, 0.0])
            for scale in (1, 0.5, 0.25, 0.125, 0.0625):
                steps = np.array([0.1, 0.125, 0.03, 0.03]) * scale
                for _ in range(4):
                    improved = False
                    for dim in range(4):
                        if dim == 0 and look == "neutral":
                            continue
                        for direction in (-1, 1):
                            trial = values.copy()
                            trial[dim] += direction * steps[dim]
                            trial = np.clip(trial, [0, -0.5, -0.06, -0.06], [1, 0.5, 0.06, 0.06])
                            result = evaluate(trial)
                            if result[0] < best[0] - 1e-14:
                                best, values, improved = result, trial, True
                    if not improved:
                        break
            solutions.append(best)
        score, components, transform = min(solutions, key=lambda v: v[0])
        # Rank the actual exported 33^3 transform, including interpolation.
        score, components = distance(statistics(apply_cube(clip, make_cube(transform))), ref)
        if score > baseline:
            # Keep the identity available even if interpolation erases a tiny
            # analytic improvement, or corrections overfit the sampled pixels.
            transform = transform_for(look, 0)
            score, components = distance(statistics(clip), ref)
        candidates.append(Candidate(transform, score, components, [
            f"Exported LUT distribution distance {score:.8f}; ungraded baseline {baseline:.8f}.",
            f"Strength {transform.strength:.4f}; exposure {transform.exposure_ev:+.4f} EV; "
            f"white-balance gains controlled by {transform.temperature:+.4f}/{transform.tint:+.4f}.",
        ]))
    candidates.sort(key=lambda c: (c.score, c.transform.look != "neutral", c.transform.look))
    chosen = candidates[0]
    notes = list(warnings)
    notes.append("Matched approximation. Different scenes need human review; this score is not pixel Delta E.")
    # No evidence is allowed to force a grade worse than doing nothing.
    if candidates[1].score - chosen.score < max(1e-6, chosen.score * 0.1):
        notes.append("Several looks have similar scores; look identity is ambiguous.")
        confidence = min(confidence, 0.5)
    if chosen.score > 0.02:
        notes.append("Large residual palette/tone difference; the bank may not fit these scenes.")
        confidence = min(confidence, 0.35)
    if abs(chosen.transform.exposure_ev) >= 0.499 or max(
        abs(chosen.transform.temperature), abs(chosen.transform.tint)
    ) >= 0.0599:
        notes.append("A correction reached its bound; review the input color space and lighting.")
        confidence = min(confidence, 0.5)
    chosen = replace(chosen, reasons=chosen.reasons + [
        "Lowest measured distribution distance in the procedural bank and bounded search."
    ])
    candidates[0] = chosen
    return MatchResult(candidates, chosen, baseline, confidence, notes)
