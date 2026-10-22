"""Original procedural looks, distributed under Zing's MIT license."""

from .models import LookParameters, Transform
from .science import encode, linearize, np, rgb_array


def look_bank() -> dict[str, LookParameters]:
    """Fresh parameter objects so callers cannot mutate the global bank."""
    return {
        "neutral": LookParameters(),
        "warm": LookParameters(gamma=0.94, gain=[1.06, 1.0, 0.94],
                               highlights=[0.035, 0.008, -0.025]),
        "cool": LookParameters(gamma=1.06, gain=[0.94, 1.0, 1.07],
                               shadows=[-0.02, 0.006, 0.035]),
        "teal-orange": LookParameters(contrast=1.10, saturation=1.08,
                                      shadows=[-0.07, 0.035, 0.055],
                                      highlights=[0.08, 0.015, -0.06]),
        "faded-film": LookParameters(contrast=0.82, saturation=0.78, lift=0.045,
                                     shadows=[0.018, 0.008, 0.03]),
        "punchy": LookParameters(contrast=1.30, saturation=1.22, gamma=1.04),
        "desaturated": LookParameters(saturation=0.35, contrast=1.04),
        "golden-hour": LookParameters(gamma=0.90, saturation=1.13,
                                      gain=[1.08, 1.015, 0.88],
                                      shadows=[0.035, -0.012, -0.025],
                                      highlights=[0.08, 0.045, -0.06]),
    }


def transform_for(look: str, strength: float = 1.0, **corrections) -> Transform:
    bank = look_bank()
    if look not in bank:
        raise ValueError(f"unknown look {look!r}; choose from {', '.join(bank)}")
    return Transform(look, bank[look], strength, **corrections)


def apply_transform(rgb, transform: Transform):
    """Corrections in linear light, then creative code-value grade and blend.

    White-balance controls are bounded channel gains, not estimated kelvin.
    Exposure/WB are baked into the exported cube, once, before look strength.
    """
    x = rgb_array(rgb)
    t = transform
    p = t.parameters
    if t.exposure_ev or t.temperature or t.tint:
        gains = np.exp2([t.temperature, t.tint, -t.temperature])
        x = np.clip(encode(linearize(x) * (2 ** t.exposure_ev) * gains), 0, 1)
    if t.strength == 0:
        return x.copy()
    y = x @ np.array([0.2126, 0.7152, 0.0722])
    graded = np.maximum((x - 0.5) * p.contrast + 0.5, 0) ** p.gamma
    graded *= p.gain
    gy = graded @ np.array([0.2126, 0.7152, 0.0722])
    graded = gy[..., None] + p.saturation * (graded - gy[..., None])
    graded += (1 - y[..., None]) ** 2 * np.asarray(p.shadows)
    graded += y[..., None] ** 2 * np.asarray(p.highlights)
    graded = p.lift + (1 - p.lift) * graded
    return np.clip(x + t.strength * (graded - x), 0, 1)
