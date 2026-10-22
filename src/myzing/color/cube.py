"""Strict SDR .cube reader/writer; red varies fastest on disk."""

from dataclasses import dataclass
from pathlib import Path
import re

from .looks import apply_transform
from .models import Contract, Transform
from .science import np, rgb_array


@dataclass
class Cube(Contract):
    size: int
    values: list[list[float]]
    title: str = "Zing matched approximation"
    domain_min: list[float] = None
    domain_max: list[float] = None
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        self.domain_min = [0.0] * 3 if self.domain_min is None else self.domain_min
        self.domain_max = [1.0] * 3 if self.domain_max is None else self.domain_max
        if type(self.size) is not int or not 2 <= self.size <= 65:
            raise ValueError("LUT_3D_SIZE must be an integer from 2 to 65")
        if self.domain_min != [0.0] * 3 or self.domain_max != [1.0] * 3:
            raise ValueError("only SDR DOMAIN_MIN 0 0 0 / DOMAIN_MAX 1 1 1 is supported")
        if any(c in self.title for c in '\n\r"'):
            raise ValueError("cube title cannot contain quotes or newlines")
        values = rgb_array(self.values)
        if values.shape != (self.size ** 3, 3):
            raise ValueError(f"cube requires exactly {self.size ** 3} RGB rows")


def make_cube(transform: Transform, size: int = 33) -> Cube:
    if type(size) is not int or not 2 <= size <= 65:
        raise ValueError("cube size must be an integer from 2 to 65")
    axis = np.linspace(0, 1, size)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    rgb = np.stack((r, g, b), axis=-1).reshape(-1, 3)
    return Cube(size, apply_transform(rgb, transform).tolist(), f"Zing {transform.look} approximation")


def write_cube(cube: Cube, path: Path | str) -> Path:
    cube.__post_init__()
    path = Path(path)
    header = (f'TITLE "{cube.title}"\nLUT_3D_SIZE {cube.size}\n'
              'DOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n')
    rows = "".join(" ".join(f"{v:.10f}" for v in row) + "\n" for row in cube.values)
    path.write_text(header + rows, encoding="utf-8", newline="\n")
    return path


def read_cube(path: Path | str) -> Cube:
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("cube exceeds the 32 MiB SDR LUT limit")
    headers, rows = {}, []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line.startswith("TITLE "):
            line = line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        key = fields[0]
        if key in ("TITLE", "LUT_3D_SIZE", "DOMAIN_MIN", "DOMAIN_MAX"):
            if rows or key in headers:
                raise ValueError(f"cube line {number}: duplicate or misplaced {key}")
            rest = line[len(key):].strip()
            if key == "TITLE":
                quoted = re.fullmatch(r'"([^"\r\n]*)"\s*(?:#.*)?', rest)
                if quoted is None:
                    raise ValueError("cube TITLE must be quoted")
                headers[key] = quoted.group(1)
            elif key == "LUT_3D_SIZE":
                headers[key] = int(rest)
                if not 2 <= headers[key] <= 65:
                    raise ValueError("LUT_3D_SIZE must be from 2 to 65")
            else:
                headers[key] = [float(v) for v in fields[1:]]
        else:
            if "LUT_3D_SIZE" not in headers or len(fields) != 3:
                raise ValueError(f"cube line {number}: unsupported header or malformed RGB row")
            try:
                rows.append([float(v) for v in fields])
            except ValueError as exc:
                raise ValueError(f"cube line {number}: unsupported header or invalid RGB") from exc
            if len(rows) > headers["LUT_3D_SIZE"] ** 3:
                raise ValueError("cube has too many RGB rows")
    if "LUT_3D_SIZE" not in headers:
        raise ValueError("cube is missing LUT_3D_SIZE")
    return Cube(headers["LUT_3D_SIZE"], rows, headers.get("TITLE", "Untitled"),
                headers.get("DOMAIN_MIN"), headers.get("DOMAIN_MAX"))


def apply_cube(rgb, cube: Cube):
    """Trilinear interpolation, also selected explicitly in the FFmpeg path."""
    x = rgb_array(rgb) * (cube.size - 1)
    lo = np.floor(x).astype(int)
    hi = np.minimum(lo + 1, cube.size - 1)
    f = x - lo
    table = np.asarray(cube.values).reshape(cube.size, cube.size, cube.size, 3)
    out = np.zeros_like(x)
    for blue in (0, 1):
        for green in (0, 1):
            for red in (0, 1):
                bits = np.array([red, green, blue])
                idx = np.where(bits, hi, lo)
                weight = np.prod(np.where(bits, f, 1 - f), axis=-1)
                out += table[idx[..., 2], idx[..., 1], idx[..., 0]] * weight[..., None]
    return np.clip(out, 0, 1)  # convex interpolation can round to 1 + epsilon
