"""Prepare licensed pictures as local paper photos or white-edged cutouts."""
from __future__ import annotations

import math
import re
import subprocess
import tempfile
from pathlib import Path

from myzing.factory.tools import FactoryError, ffmpeg, run

from . import StoryError, heads


def _valid_box(box) -> bool:
    try:
        return (isinstance(box, (list, tuple)) and len(box) == 4
                and all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in box)
                and box[0] >= 0 and box[1] >= 0 and box[2] > 0 and box[3] > 0)
    except OverflowError:
        return False


def image_errors(image: dict) -> list[str]:
    """Use the photo rights gate before opening an image or creating files."""
    errors = [message.replace("photo", "image") for message in heads.photo_errors(image)]
    if not isinstance(image, dict):
        return errors
    if image.get("cut", "photo") not in ("photo", "sticker"):
        errors.append("image cut must be photo or sticker")
    if "box" in image:
        box = image["box"]
        if not _valid_box(box):
            errors.append("image box must be [x, y, width, height] with nonnegative x/y and positive width/height")
    return errors


def prepared_path(image_id: str, image: dict) -> str:
    return f"images/{image_id}-{image.get('cut', 'photo')}.png"


def _photo(source: Path, output: Path) -> Path:
    """Convert one still locally, without importing OpenCV or NumPy."""
    try:
        encoder = ffmpeg()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".image-", dir=output.parent) as scratch:
            temporary = Path(scratch) / "picture.png"
            run(encoder, "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", source,
                "-frames:v", 1, "-vf", "scale=w='min(1600,iw)':h='min(1600,ih)':force_original_aspect_ratio=decrease",
                "-threads", 1, "-f", "image2", "-c:v", "png", temporary,
                capture_output=True, timeout=60)
            temporary.replace(output)
    except FactoryError as exc:
        raise StoryError(str(exc)) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoryError(f"Cannot prepare image {source.name}. Check that it is a picture FFmpeg can read.") from exc
    return output


def cut_sticker(source: Path, output: Path, *, box=None) -> Path:
    """Seed GrabCut with a centre rectangle, then use the head sticker's edge."""
    cv2, np = heads._image_tools()
    try:
        image = cv2.imdecode(np.frombuffer(source.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, cv2.error) as exc:
        raise StoryError(f"Cannot read image {source.name}.") from exc
    if image is None:
        raise StoryError(f"Cannot read image {source.name}.")
    height, width = image.shape[:2]
    if width < 4 or height < 4:
        raise StoryError(f"Image {source.name} is too small to cut into a sticker.")
    if box is None:
        x, y = max(1, round(width * .08)), max(1, round(height * .08))
        box = [x, y, width - 2 * x, height - 2 * y]
    if not _valid_box(box):
        raise StoryError("Image box must be [x, y, width, height].")
    x, y, w, h = (int(value) for value in box)
    if x < 0 or y < 0 or w < 2 or h < 2 or x + w > width or y + h > height:
        raise StoryError(f"Box for {source.name} must fit inside its {width}x{height} image.")
    factor = min(1.0, heads.WORK_SIZE / max(width, height))
    small = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    left, top = max(1, round(x * factor)), max(1, round(y * factor))
    right, bottom = min(sw - 1, round((x + w) * factor)), min(sh - 1, round((y + h) * factor))
    if right <= left or bottom <= top:
        raise StoryError(f"Box for {source.name} is too small to cut. Use a larger box.")
    mask = np.zeros((sh, sw), np.uint8)
    try:
        cv2.grabCut(small, mask, (left, top, right - left, bottom - top),
                    np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64), 6, cv2.GC_INIT_WITH_RECT)
    except cv2.error as exc:
        raise StoryError(f"Cannot separate the subject in {source.name}. Set a tighter image box or choose another picture.") from exc
    foreground = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground)
    if count <= 1:
        raise StoryError(f"No subject pixels remain in {source.name}. Set an image box around the subject.")
    foreground = np.where(labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA]), 255, 0).astype(np.uint8)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    alpha = cv2.resize(foreground, (width, height), interpolation=cv2.INTER_LINEAR)
    ys, xs = np.where(alpha > 0)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    canvas = heads._paper_sticker(image[y0:y1, x0:x1], alpha[y0:y1, x0:x1], cv2, np)
    return heads._write_sticker(canvas, output, cv2)


def generate(directory: Path, story: dict, *, sheet: bool = False) -> list[dict]:
    """Prepare every declared image after checking all metadata and paths."""
    from .contract import local_photo

    directory = Path(directory)
    definitions = story.get("images", {})
    if not isinstance(definitions, dict):
        raise StoryError("images must be an object keyed by image ID")
    jobs, errors = [], []
    for image_id, image in definitions.items():
        if not isinstance(image_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,59}", image_id):
            errors.append(f"image id {image_id!r} must use lowercase letters, digits, '_' or '-'")
            continue
        problems = image_errors(image)
        errors.extend(f"image {image_id}: {problem}" for problem in problems)
        if problems:
            continue
        try:
            source = local_photo(directory, image["path"])
            output = local_photo(directory, prepared_path(image_id, image))
            if not source.is_file():
                raise StoryError("image file is missing")
            jobs.append((image_id, image, source, output))
        except StoryError as exc:
            errors.append(f"image {image_id}: {str(exc).replace('photo', 'image')}")
    if errors:
        raise StoryError("\n".join(errors))
    sources = {source for _, _, source, _ in jobs}
    for member in story.get("cast", {}).values():
        for photo in member.get("photos", []):
            sources.add(local_photo(directory, photo["path"]))
    for image_id, _, _, output in jobs:
        if output in sources:
            errors.append(f"image {image_id}: prepared file would replace an original picture; rename the original and update its path")
    if sheet and local_photo(directory, "images/sheet.png") in sources:
        errors.append("images/sheet.png is an original picture; rename it and update its path before making a sheet")
    if errors:
        raise StoryError("\n".join(errors))
    result = []
    for image_id, image, source, output in jobs:
        cut = image.get("cut", "photo")
        if cut == "sticker":
            cut_sticker(source, output, box=image.get("box"))
        else:
            _photo(source, output)
        result.append({"image_id": image_id, "path": image["path"], "image": prepared_path(image_id, image),
                       "cut": cut, "credit": image["credit"], "license": image["license"],
                       "source_url": image["source_url"], "rights": heads.photo_rights(image)})
    if sheet:
        heads._write_sheet(directory, result, folder="images")
    return result
