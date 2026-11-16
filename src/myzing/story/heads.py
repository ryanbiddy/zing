"""Make paper head stickers from local photos with explicit reuse rights."""
from __future__ import annotations

import importlib
import math
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from . import StoryError

HEAD_SIZE = 700
WORK_SIZE = 640
HAIR_ROOM = 0.62
SIDE_ROOM = 0.38
CHIN_ROOM = 0.16
# A real head sits inside the allowed area. When the cut presses against this
# share of the area's upper edge, background leaked in, so the cut is retried
# with less room around the face.
LEAK_EDGE_SHARE = 0.10
LEAK_ROOM_STEP = 0.78
LEAK_MIN_ROOM = 0.55
# Level the photo when the eyes sit this many degrees off level. Smaller is noise,
# larger is a wrong eye pair.
TILT_MIN = 4.0
TILT_MAX = 35.0


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


def _find_face(image, cv2, *, detection: dict | None = None):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def detect(name, pixels):
        cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / name))
        if cascade.empty():
            return []
        return [tuple(int(value) for value in box) for box in
                cascade.detectMultiScale(pixels, 1.1, 6, minSize=(max(8, gray.shape[1] // 12),) * 2)]

    found = detect("haarcascade_frontalface_default.xml", gray)
    if not found:
        found = detect("haarcascade_profileface.xml", gray)
        mirrored = detect("haarcascade_profileface.xml", cv2.flip(gray, 1))
        found.extend((gray.shape[1] - x - w, y, w, h) for x, y, w, h in mirrored)
        # A face found in both directions counts once. Keep the larger box.
        unique = []
        for box in sorted(found, key=lambda item: item[2] * item[3], reverse=True):
            x, y, w, h = box
            duplicate = False
            for ox, oy, ow, oh in unique:
                overlap = max(0, min(x + w, ox + ow) - max(x, ox)) * max(0, min(y + h, oy + oh) - max(y, oy))
                if overlap / (w * h + ow * oh - overlap) > .5:
                    duplicate = True
                    break
            if not duplicate:
                unique.append(box)
        found = unique
    if detection is not None:
        detection["face_count"] = len(found)
    return max(found, key=lambda box: box[2] * box[3]) if found else None


def _eye_tilt(image, face, cv2) -> float:
    """Degrees to turn the photo so the eyes sit level. Zero when unsure."""
    x, y, w, h = face
    gray = cv2.cvtColor(image[y:y + int(h * .62), x:x + w], cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_eye.xml"))
    if cascade.empty():
        return 0.0
    eyes = [tuple(int(v) for v in box) for box in
            cascade.detectMultiScale(gray, 1.1, 6, minSize=(max(6, w // 9),) * 2)]
    best = None
    for i, (ax, ay, aw, ah) in enumerate(eyes):
        for bx, by, bw, bh in eyes[i + 1:]:
            dx, dy = (bx + bw / 2) - (ax + aw / 2), (by + bh / 2) - (ay + ah / 2)
            if dx < 0:
                dx, dy = -dx, -dy
            # Two eyes: similar size, a believable distance apart, one each side of the middle.
            if not (.28 * w <= dx <= .62 * w) or min(aw, bw) / max(aw, bw) < .6:
                continue
            if (ax + aw / 2 - w / 2) * (bx + bw / 2 - w / 2) >= 0:
                continue
            angle = math.degrees(math.atan2(dy, dx))
            # An impossible angle is a wrong pair; it must not hide a real one.
            if abs(angle) > TILT_MAX:
                continue
            if best is None or aw * bw > best[0]:
                best = (aw * bw, angle)
    if best is None or abs(best[1]) < TILT_MIN:
        return 0.0
    return best[1]


def cut_head(source: Path, output: Path, *, face=None, detection: dict | None = None,
             room: float = 1.0, tilt: float | None = None) -> Path:
    """Cut the face, retain hair, and add a faceted white paper edge."""
    cv2, np = _image_tools()
    try:
        image = cv2.imdecode(np.frombuffer(Path(source).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, cv2.error) as exc:
        raise StoryError(f"Cannot read photo {Path(source).name}.") from exc
    if image is None:
        raise StoryError(f"Cannot read photo {Path(source).name}.")
    manual = face is not None
    if face is None:
        details = {}
        face = _find_face(image, cv2, detection=details)
        if details.get("face_count", 0) > 1:
            print(f"{Path(source).name}: found {details['face_count']} faces; using the largest. "
                  "Set photo.face to choose another.", file=sys.stderr)
            if detection is not None:
                detection.update(face_count=details["face_count"], face=list(face), selection="largest")
    if face is None:
        raise StoryError(f"No face found in {Path(source).name}. Add a face box [x, y, width, height] to its photo.")
    if (len(face) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float, np.number))
                             or not math.isfinite(v) for v in face)):
        raise StoryError("Photo face must be [x, y, width, height].")
    x, y, w, h = (int(value) for value in face)
    height, width = image.shape[:2]
    if x < 0 or y < 0 or w < 2 or h < 2 or x + w > width or y + h > height:
        raise StoryError(f"Face box for {Path(source).name} must fit inside its {width}x{height} image.")
    if tilt is None:
        # A face box the author supplied is taken as given, with no detector run.
        tilt = 0.0 if manual else _eye_tilt(image, (x, y, w, h), cv2)
    if tilt:
        # Level a tilted head first, so the allowed area and the jaw line sit square on it.
        turn = cv2.getRotationMatrix2D((x + w / 2, y + h / 2), tilt, 1.0)
        image = cv2.warpAffine(image, turn, (width, height), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)
        if detection is not None:
            detection["leveled"] = round(tilt, 1)

    hx0, hx1 = x - SIDE_ROOM * room * w, x + w + SIDE_ROOM * room * w
    hy0, hy1 = y - HAIR_ROOM * room * h, y + h + CHIN_ROOM * h
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
    edge = cv2.bitwise_and(limit, cv2.bitwise_not(cv2.erode(limit, np.ones((5, 5), np.uint8))))
    edge[center[1]:, :] = 0
    pressed = cv2.countNonZero(cv2.bitwise_and(edge, foreground)) / max(1, cv2.countNonZero(edge))
    if pressed > LEAK_EDGE_SHARE:
        if room * LEAK_ROOM_STEP >= LEAK_MIN_ROOM:
            return cut_head(source, output, face=face, detection=detection, room=room * LEAK_ROOM_STEP, tilt=tilt)
        print(f"{Path(source).name}: the background may have leaked into this cut. Check heads/sheet.png "
              "(zing story heads --sheet), then set a tighter photo.face or use another photo.", file=sys.stderr)
        if detection is not None:
            detection["warning"] = "background may have leaked into the cut"
    if detection is not None and room != 1.0:
        detection["room"] = round(room, 2)
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
    canvas = _paper_sticker(head, alpha, cv2, np)
    return _write_sticker(canvas, output, cv2)


def _paper_sticker(head, alpha, cv2, np):
    """Give heads and image cutouts the same faceted white paper edge."""
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
    return canvas


def _write_sticker(canvas, output: Path, cv2) -> Path:
    temporary = None
    try:
        encoded, content = cv2.imencode(".png", canvas)
        if not encoded:
            raise StoryError("OpenCV could not encode the head PNG.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".sticker-", suffix=".png", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content.tobytes())
        temporary.replace(output)
    except OSError as exc:
        raise StoryError(f"Cannot write head sticker {output.name}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output


def _write_sheet(directory: Path, records: list[dict], *, folder: str = "heads") -> Path:
    """Put each cutout on checks with its cast ID, including all photo variants."""
    try:
        image_api = importlib.import_module("PIL.Image")
        drawing = importlib.import_module("PIL.ImageDraw")
        fonts = importlib.import_module("PIL.ImageFont")
    except (ImportError, OSError) as exc:
        raise StoryError("Head contact sheets need Pillow. Install 'myzing[factory]' and retry.") from exc
    from . import data_path

    columns = min(4, max(1, math.ceil(math.sqrt(len(records)))))
    rows = max(1, math.ceil(len(records) / columns))
    cell_w, cell_h = 280, 340
    sheet = image_api.new("RGBA", (columns * cell_w, rows * cell_h), (235, 235, 235, 255))
    pen = drawing.Draw(sheet)
    for y in range(0, sheet.height, 20):
        for x in range(0, sheet.width, 20):
            if (x // 20 + y // 20) % 2:
                pen.rectangle((x, y, x + 19, y + 19), fill=(210, 210, 210, 255))
    try:
        font = fonts.truetype(str(data_path("..", "fonts", "ZingCaption-800.ttf")), 24)
        for index, record in enumerate(records):
            x, y = (index % columns) * cell_w, (index // columns) * cell_h
            with image_api.open(directory / record.get("head", record.get("portrait", record.get("image")))) as opened:
                head = opened.convert("RGBA")
            head.thumbnail((cell_w - 32, cell_h - 70))
            sheet.alpha_composite(head, (x + (cell_w - head.width) // 2, y + 12 + (cell_h - 70 - head.height) // 2))
            if "head" in record and "cast_id" in record:
                portrait_path = directory / "heads" / f"{record['cast_id']}-{record['index']}-portrait.jpg"
                if portrait_path.is_file():
                    with image_api.open(portrait_path) as opened:
                        portrait = opened.convert("RGBA")
                    portrait.thumbnail((104, 104))
                    px, py = x + cell_w - portrait.width - 12, y + cell_h - portrait.height - 58
                    pen.rectangle((px - 4, py - 4, px + portrait.width + 3, py + portrait.height + 3),
                                  fill=(251, 244, 228, 255))
                    sheet.alpha_composite(portrait, (px, py))
            label = f"{record['cast_id']} / {record['index']}" if "cast_id" in record else record["image_id"]
            label_width = pen.textbbox((0, 0), label, font=font)[2]
            if label_width > cell_w - 16:
                label_font = fonts.truetype(str(data_path("..", "fonts", "ZingCaption-800.ttf")),
                                            max(8, int(24 * (cell_w - 16) / label_width)))
            else:
                label_font = font
            pen.rectangle((x, y + cell_h - 46, x + cell_w - 1, y + cell_h - 1), fill=(251, 244, 228, 255))
            pen.text((x + cell_w // 2, y + cell_h - 24), label, font=label_font,
                     fill=(23, 22, 28, 255), anchor="mm")
        if not records:
            pen.text((cell_w // 2, cell_h // 2), "No photo heads" if folder == "heads" else "No images", font=font,
                     fill=(23, 22, 28, 255), anchor="mm")
        output = directory / folder / "sheet.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".sheet-", suffix=".png", delete=False) as stream:
                temporary = Path(stream.name)
                sheet.save(stream, format="PNG")
            temporary.replace(output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except OSError as exc:
        raise StoryError(f"Cannot write {folder}/sheet.png. Check the images and output folder.") from exc
    return output


def generate(directory: Path, story: dict, *, sheet: bool = False) -> list[dict]:
    """Write portraits and the selected look's stickers after checking rights."""
    from .contract import local_photo
    from .portraits import crop_portrait

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
        detection = {}
        uses_heads = story.get("look", "cutout") in ("cutout", "comic")
        if uses_heads:
            cut_head(source, directory / head, face=photo.get("face"), detection=detection)
            if detection.get("warning") == "background may have leaked into the cut":
                print("You can also render with --look scrapbook or --look headline, "
                      "which use the photo as it is.", file=sys.stderr)
        portrait = f"heads/{cast_id}-{index}-portrait.jpg"
        crop_portrait(source, directory / portrait, face=photo.get("face", detection.get("face")),
                      detection=detection)
        result.append({"cast_id": cast_id, "index": index, "path": photo["path"],
                       **({"head": head} if uses_heads else {"portrait": portrait}),
                       "credit": photo["credit"], "license": photo["license"],
                       "source_url": photo["source_url"], "rights": photo_rights(photo), **detection})
    if sheet:
        _write_sheet(directory, result)
    return result
