"""SFNT advances and baseline metrics from the very face passed to libass.

ASS's default has kerning disabled. Presets use separate, fixed word slots;
the bundled faces disable optional ligatures so hmtx advances match those
slots. No system-font lookup, FFmpeg or optional Python package is needed for
text the face covers. For a character the face lacks, libass substitutes a
system font at render time; that word is measured by libass itself when FFmpeg
is available (and the substituted font is reported). Without libass, planning
unsupported glyphs fails with an installation remedy rather than guessing. Widths therefore follow what libass will draw.
"""

from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json
import re
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


def bundled_path(digest):
    """This install's copy of a pinned preset face (plans store absolute paths)."""
    manifest = json.loads((DATA / "caption-presets.json").read_text(encoding="utf-8"))
    for entry in manifest["faces"].values():
        path = DATA / entry["file"]
        if entry["sha256"] == digest and path.is_file() and sha256(path.read_bytes()).hexdigest() == digest:
            return path.resolve()
    return None


def ignorable(ch):
    """Characters libass draws without a glyph of their own (joiners, selectors)."""
    code = ord(ch)
    return (ch.isspace() or unicodedata.category(ch) == "Cf" or 0xFE00 <= code <= 0xFE0F
            or 0xE0100 <= code <= 0xE01EF)


class FontMetrics:
    def __init__(self, data, path=None):
        tables = {}
        for i in range(struct.unpack_from(">H", data, 4)[0]):
            tag, _, offset, length = struct.unpack_from(">4sIII", data, 12 + i * 16)
            tables[tag] = data[offset:offset + length]
        self.path = path
        self.substitutions = {}
        self.units = struct.unpack_from(">H", tables[b"head"], 18)[0]
        self.ascent, self.descent = struct.unpack_from(">hh", tables[b"hhea"], 4)
        self.ass_ascent, self.ass_descent = struct.unpack_from(">HH", tables[b"OS/2"], 74)
        self.cap = struct.unpack_from(">h", tables[b"OS/2"], 88)[0]
        count = struct.unpack_from(">H", tables[b"hhea"], 34)[0]
        self.advances = [struct.unpack_from(">H", tables[b"hmtx"], i * 4)[0] for i in range(count)]
        self.glyph_tops = None
        if b"loca" in tables and b"glyf" in tables:
            short = struct.unpack_from(">h", tables[b"head"], 50)[0] == 0
            stride, fmt = (2, ">H") if short else (4, ">I")
            offsets = [struct.unpack_from(fmt, tables[b"loca"], i)[0] * (2 if short else 1)
                       for i in range(0, len(tables[b"loca"]), stride)]
            self.glyph_tops = {gid: struct.unpack_from(">h", tables[b"glyf"], start + 8)[0]
                               for gid, (start, end) in enumerate(zip(offsets, offsets[1:])) if end > start}
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

    def missing(self, text):
        return [c for c in unicodedata.normalize("NFC", text) if not self.cmap.get(ord(c)) and not ignorable(c)]

    def _advance(self, c):
        gid = self.cmap.get(ord(c))
        return self.advances[min(gid, len(self.advances)-1)] if gid else 0

    def substituted(self, word):
        """Em width of a word that libass completes from a substitute font."""
        if word not in self.substitutions:
            measured = None
            if self.path is not None:
                try:
                    measured = libass_extent(str(self.path), word)
                except Exception:  # No FFmpeg/libass here: estimate instead.
                    measured = None
            if measured is not None:
                self.substitutions[word] = {"em": measured[0], "fonts": measured[1], "source": "libass"}
            else:
                raise ValueError(
                    "Caption text needs a fallback font. Install FFmpeg with libass "
                    "and reapply the preset so Zing can measure the actual fallback glyphs."
                )
        return self.substitutions[word]["em"]

    def width(self, text, size):
        total = 0
        for part in re.split(r"( )", unicodedata.normalize("NFC", text)):
            if not part:
                continue
            if part != " " and self.missing(part):
                total += self.substituted(part) * self.units
            else:
                total += sum(self._advance(c) for c in part)
        return total * size / self.units

    def substitution_notes(self, words):
        notes = []
        for word in dict.fromkeys(unicodedata.normalize("NFC", w) for w in words):
            chars = "".join(dict.fromkeys(self.missing(word)))
            if not chars:
                continue
            self.substituted(word)
            entry = self.substitutions[word]
            if entry["source"] == "libass":
                fonts = ", ".join(entry["fonts"]) or "no installed font (nothing drawn)"
                notes.append(f"Caption face has no glyph for {chars!r} in {word!r}; libass substitutes {fonts} "
                             "on this machine, and that width was measured with libass. Other machines may differ.")
        return notes

    def line_height(self, size):
        return (self.ascent - self.descent) * size / self.units

    def ink_top(self, text, size):
        """Height above the baseline, including currency and accented glyphs."""
        if self.glyph_tops is None:
            return self.cap * size / self.units
        return max([self.cap, *(self.glyph_tops.get(self.cmap.get(ord(c)), self.cap)
                               if self.cmap.get(ord(c)) else self.ascent
                               for c in unicodedata.normalize("NFC", text) if not ignorable(c))]) * size / self.units


@lru_cache(maxsize=256)
def libass_extent(path, text):
    """(em right extent, substituted fonts) of text drawn alone by libass.

    Uses the renderer's private face name, tags and fontsdir, so libass makes
    the substitution it will make at render time. The extent runs from the
    event anchor to the rightmost ink pixel, with the outline off.
    """
    import shutil
    import subprocess
    import tempfile
    from myzing.ffmpeg_capabilities import caption_filter
    from myzing.render.font_files import ass_em_scale, private_font
    from myzing.render.positioned_captions import escape_ass
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg is not on PATH")
    data = Path(path).read_bytes()
    alias, payload = private_font(data)
    size, x = 100, 50
    width = int(x + size * (2 * len(text) + 2))
    height = 3 * size
    header = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
              "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
              "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
              "MarginL, MarginR, MarginV, Encoding\nStyle: Default,%s,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
              "0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
              "MarginV, Effect, Text\n") % (width, height, alias)
    event = ("Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{\\an7\\q2\\fn%s\\b100\\fs%.4f\\bord0\\shad0\\pos(%d,%d)}%s\n"
             % (alias, size * ass_em_scale(data), x, size, escape_ass(text)))
    with tempfile.TemporaryDirectory(prefix="zing-caption-glyphs-") as temporary:
        directory = Path(temporary)
        (directory / "fonts").mkdir()
        (directory / "fonts" / f"{alias}.ttf").write_bytes(payload)
        (directory / "probe.ass").write_text(header + event, encoding="utf-8", newline="\n")
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "verbose", "-f", "lavfi", "-i", f"color=black:s={width}x{height}:r=1:d=1",
             "-vf", f"{caption_filter('ffmpeg')}=filename='probe.ass':fontsdir='fonts',format=gray",
             "-frames:v", "1", "-threads", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            cwd=directory, capture_output=True, check=False, timeout=60)
    if result.returncode or len(result.stdout) != width * height:
        raise RuntimeError("libass glyph probe failed")
    log = result.stderr.decode("utf-8", errors="replace").splitlines()
    fonts = []
    for i, line in enumerate(log):
        if "not found, selecting one more font" in line and i+1 < len(log) and "fontselect:" in log[i+1]:
            name = log[i+1].split("->")[-1].split(",")[0].strip()
            if name and name not in fonts:
                fonts.append(name)
    mask = result.stdout.translate(bytes(0 if value < 16 else 1 for value in range(256)))
    right = max((mask.rfind(b"\1", row * width, (row + 1) * width) - row * width + 1 for row in range(height)), default=0)
    return max(0., right - x) / size, fonts


@lru_cache(maxsize=8)
def metrics(path, digest):
    resolved = Path(path) if Path(path).is_file() else bundled_path(digest)
    if resolved is None:
        raise ValueError("Caption font is missing; reapply the preset to use Zing's bundled face.")
    data = resolved.read_bytes()
    if sha256(data).hexdigest() != digest:
        raise ValueError("Caption font changed; restore the pinned font.")
    return FontMetrics(data, str(resolved))
