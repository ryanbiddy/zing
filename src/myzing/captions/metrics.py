"""SFNT advances and baseline metrics from the very face passed to libass.

ASS's default has kerning disabled. Presets use separate, fixed word slots;
the bundled faces disable optional ligatures so hmtx advances match those
slots. No system-font lookup, FFmpeg or optional Python package is needed.
"""

from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json
import struct
import unicodedata


DATA = Path(__file__).resolve().parents[1] / "_data" / "fonts"


def font_asset(preset):
    from myzing.composition import FontAsset
    manifest = json.loads((DATA / "caption-presets.json").read_text(encoding="utf-8"))
    entry = manifest["faces"]["700" if preset == "clean" else "800"]
    path = DATA / entry["file"]
    if sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise ValueError("Caption preset font checksum mismatch; reinstall Zing.")
    if sha256((DATA / "ZingCaption-OFL.txt").read_bytes()).hexdigest() != manifest["license_sha256"]:
        raise ValueError("Caption preset font license checksum mismatch; reinstall Zing.")
    return FontAsset(str(path.resolve()), entry["sha256"], "OFL-1.1")


class FontMetrics:
    def __init__(self, data):
        tables = {}
        for i in range(struct.unpack_from(">H", data, 4)[0]):
            tag, _, offset, length = struct.unpack_from(">4sIII", data, 12 + i * 16)
            tables[tag] = data[offset:offset + length]
        self.units = struct.unpack_from(">H", tables[b"head"], 18)[0]
        self.ascent, self.descent = struct.unpack_from(">hh", tables[b"hhea"], 4)
        self.ass_ascent, self.ass_descent = struct.unpack_from(">HH", tables[b"OS/2"], 74)
        self.cap = struct.unpack_from(">h", tables[b"OS/2"], 88)[0]
        count = struct.unpack_from(">H", tables[b"hhea"], 34)[0]
        self.advances = [struct.unpack_from(">H", tables[b"hmtx"], i * 4)[0] for i in range(count)]
        self.cmap = {}
        cmap = tables[b"cmap"]
        for i in range(struct.unpack_from(">H", cmap, 2)[0]):
            platform, encoding, offset = struct.unpack_from(">HHI", cmap, 4 + i * 8)
            if platform not in (0, 3):
                continue
            fmt = struct.unpack_from(">H", cmap, offset)[0]
            if fmt == 12:
                for j in range(struct.unpack_from(">I", cmap, offset + 12)[0]):
                    start, end, gid = struct.unpack_from(">III", cmap, offset + 16 + j * 12)
                    self.cmap.update((c, gid + c - start) for c in range(start, end + 1))
            elif fmt == 4:
                n = struct.unpack_from(">H", cmap, offset + 6)[0] // 2
                for j in range(n):
                    end = struct.unpack_from(">H", cmap, offset + 14 + 2*j)[0]
                    start = struct.unpack_from(">H", cmap, offset + 16 + 2*n + 2*j)[0]
                    delta = struct.unpack_from(">h", cmap, offset + 16 + 4*n + 2*j)[0]
                    loc = offset + 16 + 6*n + 2*j
                    ro = struct.unpack_from(">H", cmap, loc)[0]
                    for c in range(start, min(end, 65534) + 1):
                        gid = struct.unpack_from(">H", cmap, loc + ro + 2*(c-start))[0] if ro else c
                        self.cmap[c] = (gid + delta) & 65535 if gid else 0

    def width(self, text, size):
        total = 0
        for c in unicodedata.normalize("NFC", text):
            gid = self.cmap.get(ord(c))
            if not gid:
                raise ValueError(f"Caption preset font has no glyph for {c!r}; use a reference style with a suitable font.")
            total += self.advances[min(gid, len(self.advances)-1)]
        return total * size / self.units

    def line_height(self, size):
        return (self.ascent - self.descent) * size / self.units


@lru_cache(maxsize=8)
def metrics(path, digest):
    data = Path(path).read_bytes()
    if sha256(data).hexdigest() != digest:
        raise ValueError("Caption font changed; restore the pinned font.")
    return FontMetrics(data)
