"""Small endpoint reconstruction tests for experimental transition evidence.

The exact endpoint models require quiet handles. The optical window model also
tests noise-tolerant spatial features and a translation null model. Moving shots
that do not fit remain unknown; frame difference alone is not an edit label.
"""

from __future__ import annotations


def pool(frame: bytes, width: int, height: int, step: int = 4) -> list[float]:
    """Area means suppress grain without aliasing a single sampled pixel."""
    return [sum(frame[j * width + i] for j in range(y, y + step)
                for i in range(x, x + step)) / (step * step)
            for y in range(0, height - step + 1, step)
            for x in range(0, width - step + 1, step)]


def structure_change(a: list[float], b: list[float], width: int, block: int = 6) -> float:
    """Mean block SSIM contrast/structure loss, independent of luminance offset.

    A stabilizer of (0.03 * 255)^2 keeps flat/noisy blocks from dominating.
    Luminance and histogram change are measured separately.
    """
    height = len(a) // width
    losses = []
    for y in range(0, height, block):
        for x in range(0, width, block):
            indices = [j * width + i for j in range(y, min(y + block, height))
                       for i in range(x, min(x + block, width))]
            ma, mb = (sum(v[i] for i in indices) / len(indices) for v in (a, b))
            va, vb = (sum((v[i] - m) ** 2 for i in indices) / len(indices)
                      for v, m in ((a, ma), (b, mb)))
            cov = sum((a[i] - ma) * (b[i] - mb) for i in indices) / len(indices)
            losses.append(max(0, min(1, (1 - (2 * cov + 58.5225) / (va + vb + 58.5225)) / 2)))
    return sum(losses) / len(losses)


def edge_change(a: list[float], b: list[float], width: int) -> float:
    """Symmetric unmatched edge fraction with a one-cell translation tolerance."""
    height = len(a) // width

    def edges(v):
        return {(x, y) for y in range(1, height - 1) for x in range(1, width - 1)
                if abs(v[y * width + x + 1] - v[y * width + x - 1])
                + abs(v[(y + 1) * width + x] - v[(y - 1) * width + x]) >= 24}

    ea, eb = edges(a), edges(b)
    if not ea or not eb:
        return float(bool(ea or eb))

    def unmatched(left, right):
        return sum(not any((x + dx, y + dy) in right for dx in (-1, 0, 1)
                           for dy in (-1, 0, 1)) for x, y in left) / len(left)

    return max(unmatched(ea, eb), unmatched(eb, ea))


def blend_fit(a: list[float], b: list[float], frames: list[list[float]]) -> tuple[float, list[float]]:
    """Worst optical-blend residual and projected fractions; no pixel selection."""
    delta = [y - x for x, y in zip(a, b)]
    norm = max(1, sum(d * d for d in delta))
    fractions, errors = [], []
    scale = max(distance(a, b), 1)
    for frame in frames:
        alpha = sum((v - x) * d for v, x, d in zip(frame, a, delta)) / norm
        fractions.append(alpha)
        errors.append(distance(frame, [x + alpha * d for x, d in zip(a, delta)]) / scale)
    return max(errors, default=1), fractions


def translation_error(a: list[float], b: list[float], width: int, radius: int = 4) -> float:
    """Best offset-invariant translation residual, normalized to unaligned change."""
    height = len(a) // width
    scale = max(distance(a, b), 1)
    best = 1.0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            differences = [b[y * width + x] - a[(y + dy) * width + x + dx]
                           for y in range(radius, height - radius)
                           for x in range(radius, width - radius)]
            offset = sum(differences) / len(differences)
            best = min(best, sum(abs(d - offset) for d in differences) / len(differences) / scale)
    return best


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
