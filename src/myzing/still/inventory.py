"""Bounded photo inventory. Decode and measure locally; never fetch a model."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PureWindowsPath

from myzing.layout.detector import LayoutError, YuNetDetector
from myzing.memes import MemeError
from myzing.memes.framing import saliency_box
from myzing.memes.photo import HEIF_EXTENSIONS, load_photo
from myzing.memes.render import require_pillow
from myzing.memes.subject import describe_estimate, estimate_subject
from myzing.project.api import hash_file
from .models import Photo

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", *HEIF_EXTENSIONS}
FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}
MAX_PHOTOS = 64
MAX_ENTRIES = 4096
# Phone photos of 48-108 MP are often 15-40 MB; decoding is bounded by pixels.
MAX_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
FALLBACK = ("Face detection unavailable; reserving the central 60% of the photo as a "
            "subject heuristic. Faces elsewhere may be missed. For local YuNet detection, "
            "install myzing[layout] and explicitly run 'zing layout fetch-model'.")


def local_path(value: str | Path) -> Path:
    text = str(value)
    if not text or "\0" in text or "://" in text or text.startswith(("//", "\\\\")):
        raise MemeError("Use a local path, not a URL or network share.")
    path = Path(text).expanduser().resolve()
    if PureWindowsPath(str(path)).drive.startswith("\\\\"):
        raise MemeError("Use a local path, not a network share.")
    return path


def open_photo(path: Path):
    """The oriented RGB working copy (see myzing.memes.photo)."""
    return read_photo(path)[0]


def read_photo(path: Path):
    """(working copy, PhotoSource): EXIF/HEIF orientation, large photos reduced."""
    require_pillow()
    if path.suffix.lower() not in EXTENSIONS:
        raise MemeError("Use a JPEG, PNG, WebP, BMP, TIFF, or HEIC/HEIF photo.")
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise MemeError(f"Photo is missing, empty, or over {MAX_BYTES // 2 ** 20} MiB: {path}")
    try:
        return load_photo(path, formats=FORMATS, single_frame=True)
    except MemeError as exc:
        message = str(exc)
        raise MemeError(message if message.startswith(("Cannot read photo", "Use a single-frame"))
                        else f"Cannot read photo {path.name}: {message}") from exc


def detect_faces(image, detector) -> list[dict]:
    # numpy is supplied by the optional layout extra, never required for fallback.
    import numpy as np

    sample = image.copy()
    sample.thumbnail((1280, 1280))
    return [d.box.to_dict() for d in detector.detect(np.asarray(sample)[:, :, ::-1].copy())]


def describe_photo(path: Path, detector=None) -> Photo:
    from PIL import ImageFilter, ImageStat

    before = (path.stat().st_size, path.stat().st_mtime_ns)
    digest = hash_file(path)
    decoded, origin = read_photo(path)
    with decoded as source:
        width, height = source.size
        small = source.copy()
        small.thumbnail((256, 256))
        palette = small.quantize(colors=3).convert("RGB").getcolors(256 * 256)
        colors = ["#%02x%02x%02x" % color for _, color in
                  sorted(palette, key=lambda item: (-item[0], item[1]))[:3]]
        edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
        # Exclude FIND_EDGES' artificial outer border.
        if min(edges.size) > 4:
            edges = edges.crop((1, 1, edges.width - 1, edges.height - 1))
        density = ImageStat.Stat(edges).mean[0] / 255
        band = max(1, round(edges.height * .26))
        bands = [edges.crop((0, y, edges.width, y + band)) for y in (0, edges.height - band)]
        band_density = max(ImageStat.Stat(b).mean[0] / 255 for b in bands)
        notes, faces, method = [], [], "center_heuristic"
        if detector is not None:
            try:
                faces, method = detect_faces(source, detector), "yunet"
            except LayoutError as exc:
                notes.append(str(exc))
        if method == "center_heuristic":
            notes.append(FALLBACK)
        if origin.note():
            notes.append(origin.note())
        subject = saliency_box(source)
        estimate = estimate_subject(source)
        notes.append(describe_estimate(estimate))
    if before != (path.stat().st_size, path.stat().st_mtime_ns):
        raise MemeError(f"Photo changed during inventory: {path}; run again.")
    orientation = "square" if width == height else "landscape" if width > height else "portrait"
    face_text = (f"{len(faces)} face candidates detected" if method == "yunet"
                 else "face count unknown (detector unavailable)")
    size_text = (f"{width} by {height} pixels" if not origin.downscaled else
                 f"{origin.original[0]} by {origin.original[1]} pixels ({width} by {height} working copy)")
    description = (f"{orientation.capitalize()} photo, {size_text}; "
                   f"dominant sampled colors {', '.join(colors)}; {face_text}. "
                   "Subject details have not been identified.")
    return Photo("photo-" + digest[:16], str(path), digest, width, height, before[0],
                 description, colors, orientation, round(density, 6), round(band_density, 6),
                 faces, method, notes, subject, origin.to_dict(), estimate)


def inventory(folder: str | Path) -> tuple[list[Photo], list[str]]:
    require_pillow()
    root = local_path(folder)
    if not root.is_dir():
        raise MemeError(f"Photo folder does not exist: {root}")
    # One directory only, with bounded enumeration even for unsupported entries.
    paths, notes, entries, total = [], [], 0, 0
    with os.scandir(root) as scan:
        for entry in scan:
            entries += 1
            if entries > MAX_ENTRIES:
                raise MemeError("Photo folder exceeds 4096 entries; use a smaller folder.")
            info = entry.stat(follow_symlinks=False)
            if (entry.is_symlink() or getattr(info, "st_file_attributes", 0)
                    & stat.FILE_ATTRIBUTE_REPARSE_POINT or not stat.S_ISREG(info.st_mode)):
                continue
            if Path(entry.name).suffix.lower() not in EXTENSIONS:
                continue
            if not 0 < info.st_size <= MAX_BYTES:
                raise MemeError(f"Photo is empty or over {MAX_BYTES // 2 ** 20} MiB: {entry.name}; resize or remove it.")
            total += info.st_size
            paths.append(Path(entry.path))
            if len(paths) > MAX_PHOTOS or total > MAX_TOTAL_BYTES:
                raise MemeError("Photo inventory exceeds 64 files / 256 MiB; use a smaller folder.")
    if not paths:
        raise MemeError("No supported photos found; add JPEG, PNG, WebP, BMP, TIFF, or HEIC files directly to the folder.")
    try:
        detector = YuNetDetector(download=False)
    except LayoutError:
        detector = None
    photos, seen = [], set()
    for path in sorted(paths, key=lambda p: (p.name.casefold(), p.name)):
        photo = describe_photo(path, detector)
        if photo.sha256 in seen:
            notes.append(f"Skipped byte-identical photo: {path.name}")
            continue
        seen.add(photo.sha256)
        photos.append(photo)
    return photos, notes
