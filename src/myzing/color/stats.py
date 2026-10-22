"""Deterministic statistics over bounded pixel samples, in CIELAB D65."""

from .models import Statistics
from .science import np, rgb_array, rgb_to_lab

PERCENTILES = [1, 5, 25, 50, 75, 95, 99]


def bounded_pixels(rgb, count=4096):
    pixels = rgb_array(rgb).reshape(-1, 3)
    if len(pixels) <= count:
        return pixels
    return pixels[np.linspace(0, len(pixels) - 1, count, dtype=int)]


def palette(lab, count=8):
    """Median cut along the widest Lab axis, stable ties, no random seed."""
    boxes = [lab]
    while len(boxes) < count:
        candidates = [(float(np.ptp(box, axis=0).max()) * len(box), i)
                      for i, box in enumerate(boxes) if len(box) > 1]
        if not candidates:
            break
        _, index = max(candidates, key=lambda pair: (pair[0], -pair[1]))
        box = boxes.pop(index)
        axis = int(np.argmax(np.ptp(box, axis=0)))
        box = box[np.argsort(box[:, axis], kind="stable")]
        mid = len(box) // 2
        boxes[index:index] = [box[:mid], box[mid:]]
    return ([box.mean(axis=0).tolist() for box in boxes],
            [len(box) / len(lab) for box in boxes])


def statistics(rgb) -> Statistics:
    pixels = rgb_array(rgb).reshape(-1, 3)
    lab = rgb_to_lab(pixels)
    lp = np.percentile(lab[:, 0], PERCENTILES)
    ab = lab[:, 1:]
    ordered = lab[np.argsort(lab[:, 0], kind="stable")]
    # array_split handles tiny synthetic frames without NaNs.
    quartiles = [v for v in np.array_split(ordered, min(4, len(ordered))) if len(v)]
    tone = [v[:, 1:].mean(axis=0).tolist() for v in quartiles]
    tone += [tone[-1]] * (4 - len(tone))
    centers, weights = palette(lab)
    return Statistics(
        luma_percentiles=np.percentile(pixels @ [0.2126, 0.7152, 0.0722], PERCENTILES).tolist(),
        lightness_percentiles=lp.tolist(), contrast=float(lp[-2] - lp[1]),
        ab_mean=ab.mean(axis=0).tolist(), ab_spread=ab.std(axis=0).tolist(),
        ab_percentiles=np.percentile(ab, PERCENTILES, axis=0).T.tolist(),
        saturation=np.percentile(np.linalg.norm(ab, axis=1), [5, 25, 50, 75, 95]).tolist(),
        tone_ab=tone, palette=centers, palette_weights=weights,
        clipping={"black": float(np.mean(np.any(pixels <= 1 / 255, axis=1))),
                  "white": float(np.mean(np.any(pixels >= 254 / 255, axis=1)))},
        pixel_count=len(pixels),
    )


def distance(graded: Statistics, reference: Statistics) -> tuple[float, dict[str, float]]:
    """Weighted distribution distance, not pixel Delta E. See docs/color.md."""
    def mse(a, b, scale):
        return float(np.mean(((np.asarray(a) - np.asarray(b)) / scale) ** 2))

    pa, pb = np.asarray(graded.palette), np.asarray(reference.palette)
    pd = np.mean(((pa[:, None, :] - pb[None, :, :]) / [100, 128, 128]) ** 2, axis=-1)
    components = {
        "tone": 3 * mse(graded.lightness_percentiles, reference.lightness_percentiles, 100),
        "luma": mse(graded.luma_percentiles, reference.luma_percentiles, 1),
        "contrast": mse(graded.contrast, reference.contrast, 100),
        "chroma_distribution": 2 * mse(graded.ab_percentiles, reference.ab_percentiles, 128),
        "chroma_mean": 2 * mse(graded.ab_mean, reference.ab_mean, 128),
        "chroma_spread": mse(graded.ab_spread, reference.ab_spread, 128),
        "saturation": mse(graded.saturation, reference.saturation, 128),
        "split_tone": 2 * mse(graded.tone_ab, reference.tone_ab, 128),
        "palette": 0.25 * float(np.dot(pd.min(axis=1), graded.palette_weights)
                                + np.dot(pd.min(axis=0), reference.palette_weights)),
        "clipping": 0.2 * mse(list(graded.clipping.values()), list(reference.clipping.values()), 1),
    }
    return sum(components.values()), components
