"""V2 SDR LUT preparation. Optional color dependencies are loaded on demand."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from myzing.color import COLOR_SPACE, ColorError
from myzing.color.media import check_color_space

from .validation import EDLValidationError


SUPPORTED_SPACES = frozenset(s.casefold() for s in (
    COLOR_SPACE, "SDR Rec.709/sRGB", "SDR Rec.709 display-referred RGB",
    "SDR Rec.709", "Rec.709", "bt709", "sRGB",
))


def prepare_lut(color, path: Path, clip_id: str):
    """Hash before parsing; retain exactly the bytes whose identity was checked."""
    label = f"clip {clip_id} LUT"
    if color.color_space.strip().casefold() not in SUPPORTED_SPACES:
        raise EDLValidationError(
            f"{label}: unsupported color_space {color.color_space!r}; use SDR Rec.709/sRGB. "
            "Convert LOG/HDR with an explicit camera/display transform before rendering."
        )
    if path.suffix.lower() != ".cube":
        raise EDLValidationError(f"{label}: expected a local .cube file")
    try:
        with path.open("rb") as source:
            data = source.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("cube exceeds the 32 MiB SDR LUT limit")
        if hashlib.sha256(data).hexdigest() != color.sha256:
            raise EDLValidationError(
                f"{label}: SHA-256 mismatch for {path}; restore the expected LUT or update its checksum"
            )
        from myzing.color.cube import Cube, parse_cube
        cube = parse_cube(data.decode("utf-8-sig"))
        if color.strength != 1:
            # Red varies fastest. Trilinear interpolation of this blended table
            # equals blending apply_cube(rgb) with rgb in display code values.
            n = cube.size
            values = []
            for i, row in enumerate(cube.values):
                identity = (i % n / (n - 1), i // n % n / (n - 1), i // (n * n) / (n - 1))
                values.append([x + color.strength * (y - x) for x, y in zip(identity, row)])
            cube = Cube(n, values, cube.title)
        return cube
    except (OSError, ValueError, ColorError) as exc:
        if isinstance(exc, EDLValidationError):
            raise
        raise EDLValidationError(f"{label}: {exc}") from exc


def validate_source_colors(validated) -> tuple[str, ...]:
    """A creative SDR LUT is not an HDR/LOG input transform, even at strength 0."""
    warnings = []
    for clip in validated.clips:
        try:
            warnings.extend(f"source {clip.path}: {w}" for w in check_color_space(clip.media.color_metadata))
        except ColorError as exc:
            raise EDLValidationError(
                f"source {clip.path}: {exc} The v2 renderer accepts already converted SDR footage; "
                "ColorTransform is a creative LUT, not an input color-space conversion."
            ) from exc
    return tuple(dict.fromkeys(warnings))


def write_luts(composition, cubes, paths, directory: Path) -> tuple[str | None, ...]:
    """Use controlled relative paths in filters; retain source and baked hashes."""
    from myzing.color.cube import write_cube

    (directory / "luts").mkdir(parents=True, exist_ok=True)
    filters, records = [], []
    for index, clip in enumerate(sorted(composition.clips, key=lambda c: c.timeline_start)):
        if clip.color is None:
            filters.append(None)
            continue
        filename = f"luts/clip-{index:04d}.cube"
        baked = write_cube(cubes[clip.id], directory / filename)
        color = clip.color
        filters.append(filename if color.strength else None)
        records.append({
            "clip_id": clip.id, "source_path": str(paths[clip.id]), "source_sha256": color.sha256,
            "strength": color.strength, "color_space": color.color_space, "stage": color.stage,
            "baked_path": filename, "baked_sha256": hashlib.sha256(baked.read_bytes()).hexdigest(),
            "applied": color.strength != 0, "interpolation": "trilinear",
        })
    (directory / "color-transforms.json").write_text(
        json.dumps({"version": 1, "transforms": records}, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    return tuple(filters)
