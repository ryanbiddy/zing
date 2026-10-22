"""Bounded photo decoding for memes and stills.

Every photo is decoded into a working copy no larger than WORKING_MAX_SIDE on
its long side, in display orientation (EXIF for JPEG/PNG/WebP/TIFF, HEIF
``irot``/``imir`` for HEIC through FFmpeg). Very large photos are reduced
before analysis and rendering; JPEGs decode at a reduced DCT scale so a
50-megapixel photo never needs a full-size bitmap. Pillow's decompression
bomb warning is replaced by an explicit, documented pixel bound.

HEIC/HEIF photos are decoded by the installed FFmpeg when it can read HEIF
image items (FFmpeg 8.1 can, including phone-style tile grids; 6.1 cannot).
Zing bundles no HEIC decoder: pillow-heif wheels include GPL x265.
Stdlib-only at import; Pillow loads lazily.
"""

from __future__ import annotations

import functools
import io
import json
import math
import shutil
import struct
import subprocess
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

from . import MemeError, PILLOW_HINT

# Explicit decode bounds. A 108 MP phone photo (12000x9000) fits; 200 MP
# modes must be resized first. Pillow's own bomb check would warn at 89.5 MP.
MAX_SOURCE_PIXELS = 120_000_000
MAX_SOURCE_SIDE = 16384
# Analysis and rendering use this working copy; outputs are at most 1920 px.
WORKING_MAX_SIDE = 4096
HEIF_EXTENSIONS = (".heic", ".heif", ".hif")
HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}
DECODE_TIMEOUT = 120
HEIF_REMEDY = ("Convert the photo to JPEG or PNG (on iPhone: Settings > Camera > Formats > Most Compatible), "
               "or put FFmpeg 7.1 or newer first on PATH; 'zing doctor' reports HEIC support. "
               "Zing does not bundle a HEIC decoder.")


@dataclass(frozen=True)
class PhotoSource:
    """How a photo was decoded: original and working sizes in display orientation."""

    original: tuple[int, int]
    working: tuple[int, int]
    decoder: str  # pillow | ffmpeg-heif
    orientation: str  # exif | heif | none
    version: int = 1

    @property
    def downscaled(self) -> bool:
        return self.working != self.original

    def to_dict(self) -> dict:
        return {"version": self.version, "original": list(self.original), "working": list(self.working),
                "megapixels": round(self.original[0] * self.original[1] / 1e6, 1),
                "downscaled": self.downscaled, "decoder": self.decoder, "orientation": self.orientation}

    def note(self) -> str | None:
        """A one-line report for large photos; None when nothing was reduced."""
        if not self.downscaled:
            return None
        (ow, oh), (ww, wh) = self.original, self.working
        return (f"Large photo: {ow}x{oh} ({ow * oh / 1e6:.1f} MP) was decoded to a {ww}x{wh} working copy "
                "before analysis and rendering; outputs are at most 1920 px wide.")


def is_heif(path: Path) -> bool:
    """HEIF by extension or ISO-BMFF ``ftyp`` brand (renamed files still decode)."""
    if path.suffix.lower() in HEIF_EXTENSIONS:
        return True
    try:
        with path.open("rb") as stream:
            head = stream.read(64)
    except OSError:
        return False
    if len(head) < 16 or head[4:8] != b"ftyp":
        return False
    size = min(len(head), max(16, struct.unpack(">I", head[:4])[0]))
    brands = [head[8:12]] + [head[i:i + 4] for i in range(16, size - 3, 4)]
    return any(brand in HEIF_BRANDS for brand in brands)


def _check_bounds(width: int, height: int, name: str) -> None:
    if width <= 0 or height <= 0:
        raise MemeError(f"Photo has no pixels: {name}")
    if width * height > MAX_SOURCE_PIXELS or max(width, height) > MAX_SOURCE_SIDE:
        raise MemeError(f"Photo is {width}x{height} ({width * height / 1e6:.0f} MP), above Zing's "
                        f"{MAX_SOURCE_PIXELS // 1_000_000} MP / {MAX_SOURCE_SIDE} px decode limit: {name}; "
                        "resize it first.")


def _working_size(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, WORKING_MAX_SIDE / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def _reduce(image):
    from PIL import Image

    target = _working_size(*image.size)
    if target == image.size:
        return image
    # reducing_gap box-filters first, then LANCZOS: fast and alias-free.
    return image.resize(target, Image.Resampling.LANCZOS, reducing_gap=3.0)


def _require_pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise MemeError(PILLOW_HINT) from exc
    return Image, ImageOps


def _pillow(path: Path, mode: str, formats, single_frame: bool):
    Image, ImageOps = _require_pillow()
    name = path.name
    try:
        with warnings.catch_warnings():
            # The explicit bound below replaces Pillow's 89.5 MP warning.
            # Its hard error (above 179 MP) still applies and is reported.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(path) as opened:
                if formats is not None and opened.format not in formats:
                    raise MemeError(f"Use a single-frame supported photo: {name}")
                if single_frame and getattr(opened, "n_frames", 1) != 1:
                    raise MemeError(f"Use a single-frame supported photo: {name}")
                width, height = opened.size
                _check_bounds(width, height, name)
                orientation = opened.getexif().get(0x0112, 1)
                if orientation in (5, 6, 7, 8):
                    width, height = height, width
                if opened.format == "JPEG" and max(opened.size) > WORKING_MAX_SIDE:
                    # Decode at the smallest DCT scale that still covers the
                    # working copy (1/2, 1/4 or 1/8), never a full bitmap.
                    goal = _working_size(*opened.size)
                    opened.draft("RGB", goal)
                image = ImageOps.exif_transpose(opened)
                image = image.convert(mode)
    except MemeError:
        raise
    except Image.DecompressionBombError as exc:
        raise MemeError(f"Photo exceeds Zing's {MAX_SOURCE_PIXELS // 1_000_000} MP decode limit: {name}; "
                        "resize it first.") from exc
    except (OSError, ValueError, SyntaxError) as exc:
        raise MemeError(f"Cannot read photo {name}: {exc}") from exc
    image = _reduce(image)
    return image, PhotoSource((width, height), image.size, "pillow",
                              "exif" if orientation not in (None, 1) else "none")


def _ffmpeg_version(ffmpeg: str) -> str:
    try:
        result = subprocess.run([ffmpeg, "-hide_banner", "-version"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return "FFmpeg"
    line = (result.stdout.splitlines() or ["FFmpeg"])[0]
    return " ".join(line.split()[:3]) if line.startswith("ffmpeg version") else "FFmpeg"


def _heif_probe(path: Path, ffmpeg: str, ffprobe: str) -> tuple[int, int]:
    """Coded canvas size of the primary image (a tile grid's full size)."""
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_stream_groups",
                                 "-of", "json", str(path)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MemeError(f"HEIC/HEIF photos need FFmpeg on PATH ({exc}). {HEIF_REMEDY}") from exc
    if result.returncode:
        raise MemeError(f"{_ffmpeg_version(ffmpeg)} cannot read HEIC/HEIF photo "
                        f"{path.name} ({(result.stderr.strip().splitlines() or ['no detail'])[-1][:160]}). "
                        + HEIF_REMEDY)
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError as exc:
        raise MemeError(f"Cannot read HEIC/HEIF photo {path.name}: invalid probe output.") from exc
    for group in data.get("stream_groups") or []:
        for component in group.get("components") or []:
            if component.get("width") and component.get("height"):
                return int(component["width"]), int(component["height"])
    video = [s for s in data.get("streams") or [] if s.get("codec_type") == "video"]
    if not video:
        raise MemeError(f"HEIC/HEIF photo {path.name} has no image the installed FFmpeg can decode. " + HEIF_REMEDY)
    return int(video[0]["width"]), int(video[0]["height"])


def _heif(path: Path, mode: str, ffmpeg: str, ffprobe: str):
    Image, _ = _require_pillow()
    if shutil.which(ffmpeg) is None or shutil.which(ffprobe) is None:
        raise MemeError("HEIC/HEIF photos are decoded by FFmpeg, which is not on PATH. " + HEIF_REMEDY)
    width, height = _heif_probe(path, ffmpeg, ffprobe)
    _check_bounds(width, height, path.name)
    # The CLI applies HEIF irot/imir (display matrix) and assembles tile
    # grids. PPM keeps the pipe uncompressed; rgb24 also flattens 10-bit HEVC.
    try:
        result = subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-i", str(path),
                                 "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "image2pipe", "-c:v", "ppm", "-"],
                                capture_output=True, timeout=DECODE_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MemeError(f"FFmpeg could not decode HEIC/HEIF photo {path.name}: {exc}. {HEIF_REMEDY}") from exc
    if result.returncode or not result.stdout:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines() or ["no image decoded"]
        raise MemeError(f"{_ffmpeg_version(ffmpeg)} could not decode HEIC/HEIF photo {path.name} "
                        f"({detail[-1][:160]}). " + HEIF_REMEDY)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(result.stdout)) as decoded:
            image = decoded.convert(mode)
    original = image.size
    if original[0] * original[1] != width * height:
        raise MemeError(f"HEIC/HEIF photo {path.name} decoded to {original[0]}x{original[1]}, "
                        f"not its {width}x{height} canvas; convert it to JPEG first.")
    image = _reduce(image)
    return image, PhotoSource(original, image.size, "ffmpeg-heif", "heif")


def load_photo(path: str | Path, *, mode: str = "RGB", formats=None, single_frame: bool = False,
               ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
    """Decode ``path`` to a working copy. Returns (PIL image, PhotoSource).

    ``formats`` limits Pillow formats (None accepts any Pillow still, using the
    first frame of animated files). HEIC/HEIF always goes through FFmpeg.
    """
    path = Path(path)
    if is_heif(path):
        return _heif(path, mode, ffmpeg, ffprobe)
    return _pillow(path, mode, formats, single_frame)


def _probe_container() -> bytes:
    """A 248-byte HEIF header (one 64x48 HEVC item, no picture data).

    FFmpeg builds that read HEIF image items report the item as an HEVC
    stream; older mov demuxers fail with "moov atom not found". This tests
    demuxing without needing an HEVC encoder or a bundled sample photo.
    """
    def box(kind, payload):
        return struct.pack(">I", 8 + len(payload)) + kind + payload

    def full(kind, version, flags, payload):
        return box(kind, struct.pack(">I", (version << 24) | flags) + payload)

    hvcc = box(b"hvcC", bytes([1, 1]) + b"\x60\x00\x00\x00" + bytes(6) + bytes([90])
               + struct.pack(">HBBBBHB", 0xF000, 0xFC, 0xFD, 0xF8, 0xF8, 0, 0x0F) + bytes([0]))
    ispe = full(b"ispe", 0, 0, struct.pack(">II", 64, 48))
    ftyp = box(b"ftyp", b"heic" + bytes(4) + b"mif1heic")

    def meta(offset):
        return full(b"meta", 0, 0, full(b"hdlr", 0, 0, bytes(4) + b"pict" + bytes(13))
                    + full(b"pitm", 0, 0, struct.pack(">H", 1))
                    + full(b"iloc", 0, 0, bytes([0x44, 0]) + struct.pack(">HHHHII", 1, 1, 0, 1, offset, 4))
                    + full(b"iinf", 0, 0, struct.pack(">H", 1)
                           + full(b"infe", 2, 0, struct.pack(">HH", 1, 0) + b"hvc1\x00"))
                    + box(b"iprp", box(b"ipco", hvcc + ispe)
                          + full(b"ipma", 0, 0, struct.pack(">IHB", 1, 1, 2) + bytes([0x81, 2]))))

    offset = len(ftyp) + len(meta(0)) + 8
    return ftyp + meta(offset) + box(b"mdat", bytes(4))


@functools.lru_cache(maxsize=8)
def _heif_support(ffmpeg: str, ffprobe: str) -> tuple[bool, str]:
    version = _ffmpeg_version(ffmpeg)
    try:
        decoders = subprocess.run([ffmpeg, "-hide_banner", "-decoders"], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=30, check=False).stdout
        with tempfile.TemporaryDirectory(prefix="zing-heif-") as folder:
            sample = Path(folder) / "probe.heic"
            sample.write_bytes(_probe_container())
            probe = subprocess.run([ffprobe, "-v", "quiet", "-show_entries", "stream=codec_name,width,height",
                                    "-of", "json", str(sample)], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run FFmpeg for the HEIF check: {exc}"
    try:
        streams = json.loads(probe.stdout or "{}").get("streams") or []
    except ValueError:
        streams = []
    demux = probe.returncode == 0 and any(
        s.get("codec_name") == "hevc" and s.get("width") == 64 and s.get("height") == 48 for s in streams)
    hevc = any(line.split()[1:2] == ["hevc"] for line in decoders.splitlines() if line.strip())
    if demux and hevc:
        return True, f"{version} reads HEIF image items and decodes HEVC"
    if not demux:
        return False, f"{version} cannot read HEIF image items (FFmpeg 7.1 or newer reads phone HEIC photos)"
    return False, f"{version} reads HEIF items but has no HEVC decoder"


def heif_support(ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> tuple[bool, str]:
    """(supported, detail) for HEIC photos with the FFmpeg on PATH; cached per binary."""
    resolved = shutil.which(ffmpeg), shutil.which(ffprobe)
    if None in resolved:
        return False, "FFmpeg/ffprobe not found on PATH"
    return _heif_support(*(str(Path(p).resolve()) for p in resolved))
