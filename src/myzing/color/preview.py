"""Before/reference/after PNG contact sheet, without an imaging dependency."""

import struct
import tempfile
import zlib
from pathlib import Path

from .cube import read_cube, write_cube
from .media import frame
from .science import np

# Original 3x5 bitmap glyphs for compact, portable image labels.
_GLYPHS = dict(zip("ABCEFORSTN0123456789.- ", [
    "010101111101101", "110101110101110", "011100100100011",
    "111100110100111", "111100110100100", "010101101101010",
    "110101110101101", "011100010001110", "111010010010010",
    "101111111111101", "111101101101111", "010110010010111",
    "110001111100111", "110001010001110", "101101111001001",
    "111100110001110", "011100111101111", "111001010010010",
    "111101111101111", "111101111001110", "000000000000010",
    "000000111000000", "000000000000000",
]))


def _label(canvas, text, x, y):
    for character in text:
        bitmap = _GLYPHS.get(character, _GLYPHS[" "])
        for row in range(5):
            for col in range(3):
                if bitmap[row * 3 + col] == "1":
                    canvas[y + 2 * row:y + 2 * row + 2, x + 2 * col:x + 2 * col + 2] = 235
        x += 8


def write_png(path, rgb):
    """Minimal RGB8 PNG encoder using only the stdlib."""
    rgb = np.asarray(rgb, dtype=np.uint8)
    height, width, _ = rgb.shape
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    scanlines = b"".join(b"\x00" + row.tobytes() for row in rgb)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n"
                          + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                          + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def contact_sheet(reference, clip, lut, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    indices = np.linspace(0, len(clip.samples) - 1, min(3, len(clip.samples)), dtype=int)
    # Letterbox every source independently; no aspect distortion in the sheet.
    from .media import probe
    _, cw, ch, _ = probe(clip.path)
    _, rw, rh, _ = probe(reference.path)
    tile_w, tile_h, gap, heading = 240, 180, 8, 22
    canvas = np.full((len(indices) * (tile_h + heading + gap) + heading,
                      3 * tile_w + 4 * gap, 3), 24, dtype=np.uint8)
    for col, label in enumerate(("BEFORE", "REFERENCE", "AFTER")):
        _label(canvas, label, gap + col * (tile_w + gap), 6)
    with tempfile.TemporaryDirectory(prefix="lut-", dir=directory) as work:
        write_cube(read_cube(lut), Path(work) / "look.cube")
        for row, index in enumerate(indices):
            timestamp = clip.samples[index].timestamp
            ri = round(index * (len(reference.samples) - 1) / max(1, len(clip.samples) - 1))
            rt = reference.samples[ri].timestamp
            y = heading + row * (tile_h + heading + gap)
            for col, (path, seek, w, h, graded) in enumerate((
                (clip.path, timestamp, cw, ch, False),
                (reference.path, rt, rw, rh, False),
                (clip.path, timestamp, cw, ch, True),
            )):
                scale = min(tile_w / w, tile_h / h)
                width, height = max(1, round(w * scale)), max(1, round(h * scale))
                rgb = frame(path, seek, width, height, lut_dir=work if graded else None)
                x = gap + col * (tile_w + gap)
                _label(canvas, f"{seek:.2f} S", x, y + 5)
                x += (tile_w - width) // 2
                top = y + heading + (tile_h - height) // 2
                canvas[top:top + height, x:x + width] = np.rint(rgb * 255).astype(np.uint8)
    output = directory / "before-reference-after.png"
    write_png(output, canvas)
    return output
