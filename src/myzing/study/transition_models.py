"""Small endpoint reconstruction tests for experimental transition evidence.

These deliberately require quiet handles. Moving shots that do not fit a model
remain unknown; frame difference or radial flow alone is not an edit label.
"""

from __future__ import annotations

def sample(frame: bytes, width: int, height: int) -> list[float]:
    return [frame[y * width + x] for y in range(0, height, 2) for x in range(0, width, 2)]


def distance(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def exposure_residual(a: list[float], b: list[float]) -> float:
    """Residual after affine luminance adjustment, normalized to endpoint change."""
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    variance = sum((x - ma) ** 2 for x in a)
    gain = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / max(variance, 1)
    fitted = [max(0, min(255, mb + gain * (x - ma))) for x in a]
    return distance(fitted, b) / max(distance(a, b), 1)


def dissolve_error(a: list[float], b: list[float], frames: list[list[float]]) -> float:
    delta = [y - x for x, y in zip(a, b)]
    norm = sum(d * d for d in delta)
    scale = max(distance(a, b), 1)
    errors, fractions = [], []
    for frame in frames:
        alpha = sum((v - x) * d for v, x, d in zip(frame, a, delta)) / max(norm, 1)
        fractions.append(alpha)
        blend = distance(frame, [x + alpha * d for x, d in zip(a, delta)])
        # FFmpeg's stochastic "dissolve" selects pixels from either endpoint.
        selection = sum(min(abs(v - x), abs(v - y)) for v, x, y in zip(frame, a, b)) / len(a)
        errors.append(min(blend, selection) / scale)
    if not fractions or any(y < x - 0.03 for x, y in zip(fractions, fractions[1:])):
        return 1.0
    return max(errors)


def wipe_error(a: list[float], b: list[float], frames: list[list[float]],
               width: int, height: int) -> tuple[float, str | None]:
    best = (1.0, None)
    scale = max(distance(a, b), 1)
    for vertical, reverse, direction in ((False, False, "right"), (False, True, "left"),
                                          (True, False, "down"), (True, True, "up")):
        length = height if vertical else width
        errors, boundaries = [], []
        for frame in frames:
            costs_a, costs_b = [0.0] * length, [0.0] * length
            for index, (v, x, y) in enumerate(zip(frame, a, b)):
                coord = index // width if vertical else index % width
                if reverse:
                    coord = length - 1 - coord
                costs_a[coord] += abs(v - x)
                costs_b[coord] += abs(v - y)
            error = sum(costs_a)
            candidate = (error, 0)
            for coord in range(length):
                error += costs_b[coord] - costs_a[coord]
                candidate = min(candidate, (error, coord + 1))
            errors.append(candidate[0] / len(a) / scale)
            boundaries.append(candidate[1] / length)
        if (boundaries and max(boundaries) - min(boundaries) >= 0.5
                and all(y >= x - 0.03 for x, y in zip(boundaries, boundaries[1:]))):
            score = max(errors)
            if score < best[0]:
                best = (score, direction)
    return best


def zoom_error(a: list[float], b: list[float], width: int, height: int) -> tuple[float, float]:
    """Fit centered magnification to endpoints, with bilinear resampling."""
    best = (1.0, 1.0)
    scale = max(distance(a, b), 1)
    for step in range(10, 71, 2):
        zoom = 1 + step / 100
        error = 0.0
        for y in range(height):
            sy = (y - height / 2) / zoom + height / 2
            iy, fy = int(sy), sy % 1
            for x in range(width):
                sx = (x - width / 2) / zoom + width / 2
                ix, fx = int(sx), sx % 1
                value = ((1 - fy) * ((1 - fx) * a[iy * width + ix] + fx * a[iy * width + min(ix + 1, width - 1)])
                         + fy * ((1 - fx) * a[min(iy + 1, height - 1) * width + ix]
                                 + fx * a[min(iy + 1, height - 1) * width + min(ix + 1, width - 1)]))
                error += abs(value - b[y * width + x])
        score = error / len(a) / scale
        if score < best[0]:
            best = score, zoom
    return best
