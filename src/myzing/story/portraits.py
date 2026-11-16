"""Square face crops from local photos, with no segmentation or mask."""
from __future__ import annotations

import importlib
import math
import sys
import tempfile
from pathlib import Path

from . import StoryError
from . import heads

PORTRAIT_SIZE = 600


def crop_box(size: tuple[int, int], face) -> tuple[int, int, int, int]:
    """Shift the square into the photo, shrinking only when an edge is too short."""
    width, height = size
    x, y, w, h = face
    side = min(width, height, max(1, round(1.9 * w)))
    left = max(0, min(width - side, round(x + w / 2 - side / 2)))
    top = max(0, min(height - side, round(y + h / 2 - .08 * h - side / 2)))
    return left, top, left + side, top + side


def crop_portrait(source: Path, output: Path, *, face=None, detection: dict | None = None) -> Path:
    """Write a 600 px JPEG. An explicit face box needs only Pillow."""
    source, output = Path(source), Path(output)
    try:
        image_api = importlib.import_module("PIL.Image")
        image_ops = importlib.import_module("PIL.ImageOps")
    except (ImportError, OSError) as exc:
        raise StoryError("Portraits need Pillow. Install 'myzing[factory]' and retry.") from exc
    try:
        with image_api.open(source) as opened:
            photo = image_ops.exif_transpose(opened).convert("RGB")
    except (OSError, ValueError) as exc:
        raise StoryError(f"Cannot read photo {source.name}.") from exc
    if face is None:
        cv2, np = heads._image_tools()
        details = {}
        # Pillow and the detector see the same orientation and pixel dimensions.
        pixels = cv2.cvtColor(np.asarray(photo), cv2.COLOR_RGB2BGR)
        face = heads._find_face(pixels, cv2, detection=details)
        if details.get("face_count", 0) > 1:
            print(f"{source.name}: found {details['face_count']} faces; using the largest. "
                  "Set photo.face to choose another.", file=sys.stderr)
            if detection is not None:
                detection.update(face_count=details["face_count"], face=list(face), selection="largest")
    if face is None:
        raise StoryError(f"No face found in {source.name}. Add a face box [x, y, width, height] to its photo.")
    if (not isinstance(face, (list, tuple)) or len(face) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in face)):
        raise StoryError("Photo face must be [x, y, width, height].")
    x, y, w, h = (int(value) for value in face)
    width, height = photo.size
    if x < 0 or y < 0 or w < 2 or h < 2 or x + w > width or y + h > height:
        raise StoryError(f"Face box for {source.name} must fit inside its {width}x{height} image.")
    portrait = photo.crop(crop_box(photo.size, (x, y, w, h))).resize(
        (PORTRAIT_SIZE, PORTRAIT_SIZE), image_api.Resampling.LANCZOS)
    temporary = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".portrait-", suffix=".jpg", delete=False) as stream:
            temporary = Path(stream.name)
            portrait.save(stream, format="JPEG", quality=95, subsampling=0)
        temporary.replace(output)
    except OSError as exc:
        raise StoryError(f"Cannot write portrait {output.name}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output


def generate(directory: Path, story: dict, *, sheet: bool = False) -> list[dict]:
    """Check every photo's rights before making any portraits."""
    return heads.generate(directory, {**story, "look": "headline"}, sheet=sheet)
