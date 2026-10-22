"""Standalone local match-to-recipe workflow."""

import json
import tempfile
from pathlib import Path

from myzing import __version__, storage

from . import COLOR_SPACE, COLOR_VERSION, ColorError, require_numpy


def resolve_reference(reference):
    path = Path(reference).expanduser()
    if path.is_file():
        return path.resolve(), None
    try:
        storage.validate_slug(str(reference))
        breakdown = storage.load_breakdown(str(reference))
    except (ValueError, FileNotFoundError) as exc:
        raise ColorError(f"Reference is neither a local video nor a saved breakdown slug: {reference}. Run zing study first.") from exc
    media = (storage.resolve_relpath(str(reference), breakdown.meta.media_path)
             if breakdown.meta.media_path else storage.find_media(str(reference)))
    if media is None or not media.is_file():
        raise ColorError(f"Breakdown {reference} has no local media. Restore its media file or supply a local video.")
    return media.resolve(), breakdown.shots


def match_video(reference, clip, out, *, samples=12):
    require_numpy()
    from .cube import apply_cube, make_cube, write_cube
    from .match import rank_looks
    from .measure import measure_video, quality_warnings
    from .media import local_video, sha256
    from .models import Recipe
    from .preview import contact_sheet
    from .stats import statistics

    reference_path, shots = resolve_reference(reference)
    clip_path = local_video(clip)
    out = Path(out).expanduser().resolve()
    if any((out / name).exists() for name in ("look.cube", "recipe.json")):
        raise ColorError(f"Color outputs already exist in {out}. Choose a new --out folder.")
    ref, _, reference_pixels = measure_video(reference_path, count=samples, shots=shots)
    measured_clip, _, clip_pixels = measure_video(clip_path, count=samples)
    result = rank_looks(reference_pixels, clip_pixels, confidence=min(ref.confidence, measured_clip.confidence))
    cube = make_cube(result.chosen.transform)
    graded = statistics(apply_cube(clip_pixels, cube))
    warnings = list(dict.fromkeys(ref.warnings + measured_clip.warnings + result.warnings + quality_warnings(graded)))
    if quality_warnings(graded):
        result.confidence = min(result.confidence, 0.2)
    out.mkdir(parents=True, exist_ok=True)
    cube_path = write_cube(cube, out / "look.cube")
    preview_root = Path.cwd() / "zing-workspace" / "color"
    preview_root.mkdir(parents=True, exist_ok=True)
    preview_dir = Path(tempfile.mkdtemp(prefix=f"{measured_clip.sha256[:8]}-", dir=preview_root))
    preview = contact_sheet(ref, measured_clip, cube_path, preview_dir)
    recipe = Recipe(ref, measured_clip, result, graded, str(cube_path), sha256(cube_path),
                    str(preview), COLOR_SPACE, warnings, __version__, COLOR_VERSION)
    payload = json.dumps(recipe.to_dict(), indent=2, allow_nan=False) + "\n"
    recipe_path = out / "recipe.json"
    # Publish the complete recipe only after the LUT and preview succeed.
    staged = out / "recipe.json.tmp"
    staged.write_text(payload, encoding="utf-8")
    staged.replace(recipe_path)
    return recipe
