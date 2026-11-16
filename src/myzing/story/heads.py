"""Make paper head stickers from local photos with explicit reuse rights."""
from __future__ import annotations

import importlib
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

from . import StoryError

HEAD_SIZE = 700
WORK_SIZE = 640
HAIR_ROOM = 0.62
SIDE_ROOM = 0.38
CHIN_ROOM = 0.16


def photo_rights(photo: dict) -> str:
    """Use factory's license policy without its blanket allowance for local files."""
    try:
        from myzing.factory.visuals import rights_for
    except ImportError as exc:
        raise StoryError("Photo rights checks need Pillow. Install 'myzing[factory]' and retry.") from exc
    path = photo.get("path")
    license = photo.get("license")
    return rights_for({"source": "story", "title": Path(path).name if isinstance(path, str) else "photo",
                       "creator": photo.get("credit"), "license": license if isinstance(license, str) else "",
                       "license_url": photo.get("license_url")})[0]


def photo_errors(photo: dict) -> list[str]:
    """Validate photo metadata before loading image tools or touching output files."""
    if not isinstance(photo, dict):
        return ["photo must be an object"]
    errors = []
    for key in ("path", "credit", "license", "source_url"):
        if not isinstance(photo.get(key), str) or not photo[key].strip():
            errors.append(f"photo requires {key}")
    if isinstance(photo.get("source_url"), str) and photo["source_url"].strip():
        try:
            source = urlsplit(photo["source_url"])
            if source.scheme not in ("https", "http") or not source.netloc:
                errors.append("photo source_url must be an http or https URL")
        except ValueError:
            errors.append("photo source_url must be an http or https URL")
    if isinstance(photo.get("path"), str) and re.match(r"^[a-z][a-z0-9+.-]*://", photo["path"], re.I):
        errors.append("photo path must be a local file")
    if "face" in photo:
        face = photo["face"]
        if (not isinstance(face, (list, tuple)) or len(face) != 4
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in face)
                or face[0] < 0 or face[1] < 0 or face[2] <= 0 or face[3] <= 0):
            errors.append("photo face must be [x, y, width, height] with nonnegative x/y and positive width/height")
    if not errors:
        try:
            if photo_rights(photo) not in ("cleared", "attribution"):
                errors.append("photo license must permit reuse and changes; NC, ND and unknown licenses are refused")
        except StoryError as exc:
            errors.append(str(exc))
    return errors


def _image_tools():
    try:
        return importlib.import_module("cv2"), importlib.import_module("numpy")
    except (ImportError, OSError) as exc:
        raise StoryError("Head cutouts need OpenCV and NumPy. Install 'myzing[factory]' and retry.") from exc


def _find_face(image, cv2):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / name))
        if cascade.empty():
            continue
        found = cascade.detectMultiScale(gray, 1.1, 6, minSize=(max(8, gray.shape[1] // 12),) * 2)
        if len(found):
            return max(found, key=lambda box: int(box[2]) * int(box[3]))
    return None


def cut_head(source: Path, output: Path, *, face=None) -> Path:
    """Cut the face, retain hair, and add a faceted white paper edge."""
    cv2, np = _image_tools()
    try:
        image = cv2.imdecode(np.frombuffer(Path(source).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, cv2.error) as exc:
        raise StoryError(f"Cannot read photo {Path(source).name}.") from exc
    if image is None:
        raise StoryError(f"Cannot read photo {Path(source).name}.")
    if face is None:
        face = _find_face(image, cv2)
    if face is None:
        raise StoryError(f"No face found in {Path(source).name}. Add a face box [x, y, width, height] to its photo.")
    if (len(face) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float, np.number))
                             or not math.isfinite(v) for v in face)):
        raise StoryError("Photo face must be [x, y, width, height].")
    x, y, w, h = (int(value) for value in face)
    height, width = image.shape[:2]
    if x < 0 or y < 0 or w < 2 or h < 2 or x + w > width or y + h > height:
        raise StoryError(f"Face box for {Path(source).name} must fit inside its {width}x{height} image.")

    hx0, hx1 = x - SIDE_ROOM * w, x + w + SIDE_ROOM * w
    hy0, hy1 = y - HAIR_ROOM * h, y + h + CHIN_ROOM * h
    margin = 0.35 * w
    rx0, ry0 = int(max(0, hx0 - margin)), int(max(0, hy0 - margin))
    rx1, ry1 = int(min(width, hx1 + margin)), int(min(height, hy1 + margin))
    roi = image[ry0:ry1, rx0:rx1].copy()
    scale = WORK_SIZE / max(roi.shape[:2])
    small = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]

    def point(px, py):
        return int((px - rx0) * scale), int((py - ry0) * scale)

    mask = np.full((sh, sw), cv2.GC_BGD, np.uint8)
    center = point((hx0 + hx1) / 2, (hy0 + hy1) / 2)
    axes = (int((hx1 - hx0) / 2 * scale), int((hy1 - hy0) / 2 * scale))
    cv2.ellipse(mask, center, (int(axes[0] * 1.18), int(axes[1] * 1.12)), 0, 0, 360, int(cv2.GC_PR_BGD), -1)
    cv2.ellipse(mask, center, axes, 0, 0, 360, int(cv2.GC_PR_FGD), -1)
    face_center = point(x + w / 2, y + h * 0.52)
    cv2.ellipse(mask, face_center, (int(w * 0.36 * scale), int(h * 0.46 * scale)),
                0, 0, 360, int(cv2.GC_FGD), -1)
    # Guarantee a background sample even for a face box at the edge of the photo.
    mask[0, :] = mask[-1, :] = cv2.GC_BGD
    mask[:, 0] = mask[:, -1] = cv2.GC_BGD
    try:
        cv2.grabCut(small, mask, None, np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64), 6, cv2.GC_INIT_WITH_MASK)
    except cv2.error as exc:
        raise StoryError(f"Cannot separate the head in {Path(source).name}. Try a tighter face box or another photo.") from exc
    foreground = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)

    limit = np.zeros_like(foreground)
    cv2.ellipse(limit, center, (int(axes[0] * 1.1), int(axes[1] * 1.02)), 0, 0, 360, 255, -1)
    limit[int((y + h + CHIN_ROOM * h - ry0) * scale):, :] = 0
    jaw = np.zeros_like(foreground)
    jaw_start = int((y + h * 0.62 - ry0) * scale)
    cv2.ellipse(jaw, (face_center[0], jaw_start),
                (int(w * 0.47 * scale), int(h * (0.42 + CHIN_ROOM) * scale)), 0, 0, 180, 255, -1)
    limit[jaw_start:, :] = 0
    foreground = cv2.bitwise_and(foreground, cv2.bitwise_or(limit, jaw))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground)
    if count <= 1:
        raise StoryError(f"No head pixels remain in {Path(source).name}. Check its face box.")
    foreground = np.where(labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA]), 255, 0).astype(np.uint8)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    # Flood from a padded background so a clipped photo cannot fill its whole rectangle.
    padded = cv2.copyMakeBorder(foreground, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    filled = padded.copy()
    cv2.floodFill(filled, np.zeros((sh + 4, sw + 4), np.uint8), (0, 0), 255)
    foreground = cv2.bitwise_or(padded, cv2.bitwise_not(filled))[1:-1, 1:-1]
    foreground = cv2.resize(foreground, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_LINEAR)
    kernel = max(3, int(w * 0.03)) | 1
    foreground = cv2.threshold(cv2.GaussianBlur(foreground, (kernel, kernel), 0), 127, 255, cv2.THRESH_BINARY)[1]
    ys, xs = np.where(foreground > 0)
    if not len(xs):
        raise StoryError(f"No head pixels remain in {Path(source).name}. Check its face box.")
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    head, alpha = roi[y0:y1, x0:x1], foreground[y0:y1, x0:x1]
    scale = HEAD_SIZE / max(head.shape[:2])
    head = cv2.resize(head, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    alpha = cv2.resize(alpha, (head.shape[1], head.shape[0]), interpolation=cv2.INTER_LINEAR)
    border_size, pad = max(6, int(HEAD_SIZE * 0.022)), max(6, int(HEAD_SIZE * 0.022)) * 3
    hh, hw = head.shape[:2]
    canvas = np.zeros((hh + 2 * pad, hw + 2 * pad, 4), np.uint8)
    matte = np.zeros(canvas.shape[:2], np.uint8)
    matte[pad:pad + hh, pad:pad + hw] = alpha
    matte = cv2.GaussianBlur(matte, (5, 5), 0)
    border = cv2.dilate(cv2.threshold(matte, 127, 255, cv2.THRESH_BINARY)[1],
                        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * border_size + 1,) * 2))
    contour = max(cv2.findContours(border, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], key=cv2.contourArea)
    contour = cv2.approxPolyDP(contour, HEAD_SIZE * 0.006, True)
    border = np.zeros_like(border)
    cv2.fillPoly(border, [contour], 255, lineType=cv2.LINE_AA)
    canvas[..., 3] = border
    blend = (matte.astype(np.float32) / 255)[..., None]
    rgb = np.full((*matte.shape, 3), 250, np.float32)
    rgb[pad:pad + hh, pad:pad + hw] = head
    canvas[..., :3] = (rgb * blend + 250 * (1 - blend)).astype(np.uint8)
    try:
        encoded, content = cv2.imencode(".png", canvas)
        if not encoded:
            raise StoryError("OpenCV could not encode the head PNG.")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".png.tmp")
        temporary.write_bytes(content.tobytes())
        temporary.replace(output)
    except OSError as exc:
        raise StoryError(f"Cannot write head sticker {output.name}: {exc}") from exc
    return output


def generate(directory: Path, story: dict) -> list[dict]:
    """Write heads/<cast-id>-<index>.png after checking every photo's rights."""
    from .contract import local_photo

    jobs, errors = [], []
    directory = Path(directory)
    for cast_id, member in story.get("cast", {}).items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", cast_id):
            errors.append(f"cast id {cast_id!r} must start with a letter and use letters, numbers, '_' or '-'")
            continue
        for index, photo in enumerate(member.get("photos", [])):
            problems = photo_errors(photo)
            errors.extend(f"{cast_id} photo {index}: {problem}" for problem in problems)
            if not problems:
                jobs.append((cast_id, index, photo))
    if errors:
        raise StoryError("\n".join(errors))
    result = []
    for cast_id, index, photo in jobs:
        source = local_photo(directory, photo["path"])
        head = f"heads/{cast_id}-{index}.png"
        cut_head(source, directory / head, face=photo.get("face"))
        result.append({"cast_id": cast_id, "index": index, "path": photo["path"], "head": head,
                       "credit": photo["credit"], "license": photo["license"],
                       "source_url": photo["source_url"], "rights": photo_rights(photo)})
    return result
