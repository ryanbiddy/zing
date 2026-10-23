"""Write small HEIC test photos: FFmpeg encodes HEVC, Python adds HEIF boxes.

FFmpeg has no HEIF muxer, so tests wrap one HEVC still (or a grid of tiles,
like phone cameras write) in a minimal ISO/IEC 23008-12 container. Only test
code uses this; product code decodes HEIC through the installed FFmpeg.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path


class HeifUnavailable(RuntimeError):
    """The local FFmpeg cannot encode the HEVC still a fixture needs."""


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _full(kind: bytes, version: int, flags: int, payload: bytes) -> bytes:
    return _box(kind, struct.pack(">I", (version << 24) | flags) + payload)


def _nals(stream: bytes) -> list[bytes]:
    """Split an Annex B elementary stream on 3/4-byte start codes."""
    units, i, start = [], 0, None
    while i + 3 <= len(stream):
        if stream[i:i + 3] == b"\0\0\1":
            if start is not None:
                units.append(stream[start:i].rstrip(b"\0"))
            start = i = i + 3
            continue
        i += 1
    if start is not None:
        units.append(stream[start:])
    return [u for u in units if u]


def _hvcc(vps: bytes, sps: bytes, pps: bytes) -> bytes:
    # Copy general_profile_tier_level from the SPS (bytes after the 2-byte
    # NAL header and one byte of ids); FFmpeg reads only the NAL arrays.
    ptl = sps[3:15].ljust(12, b"\0")
    record = bytes([1]) + ptl[:1] + ptl[1:5] + ptl[5:11] + ptl[11:12]
    record += struct.pack(">HBBBBHB", 0xF000, 0xFC, 0xFD, 0xF8, 0xF8, 0, 0x0F)
    arrays = b""
    for kind, unit in ((32, vps), (33, sps), (34, pps)):
        arrays += bytes([0x80 | kind]) + struct.pack(">HH", 1, len(unit)) + unit
    return _box(b"hvcC", record + bytes([3]) + arrays)


def encode_hevc(source: Path, ffmpeg: str = "ffmpeg") -> list[bytes]:
    """HEVC NAL units for one 4:2:0 frame of ``source`` (any image FFmpeg reads)."""
    if shutil.which(ffmpeg) is None:
        raise HeifUnavailable("FFmpeg is not on PATH")
    result = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(source), "-frames:v", "1",
                             "-pix_fmt", "yuv420p", "-c:v", "libx265", "-x265-params", "log-level=error",
                             "-f", "hevc", "-"], capture_output=True, timeout=120, check=False)
    if result.returncode or not result.stdout:
        raise HeifUnavailable("FFmpeg cannot encode HEVC (libx265): "
                              + result.stderr.decode("utf-8", "replace")[-300:])
    return _nals(result.stdout)


def _split(units: list[bytes]) -> tuple[bytes, bytes, bytes, bytes]:
    by_type = {}
    vcl = b""
    for unit in units:
        kind = (unit[0] >> 1) & 0x3F
        if kind < 32:
            vcl += struct.pack(">I", len(unit)) + unit
        elif kind in (32, 33, 34):
            by_type.setdefault(kind, unit)
    return by_type[32], by_type[33], by_type[34], vcl


def write_heic(target: Path, tiles: list[list[bytes]], size: tuple[int, int], *,
               grid: tuple[int, int] | None = None, tile_size: tuple[int, int] | None = None,
               rotation: int = 0) -> Path:
    """Write ``tiles`` (HEVC NAL lists) as one image item or a rows x columns grid.

    ``rotation`` is an ``irot`` property in 90-degree anticlockwise steps
    (HEIF's orientation mechanism; phone HEICs also carry it this way).
    """
    pieces = [_split(units) for units in tiles]
    vps, sps, pps, _ = pieces[0]
    count = len(pieces)
    primary = count + 1 if grid else 1
    item_ids = list(range(1, count + 1))
    grid_data = b""
    if grid:
        rows, columns = grid
        grid_data = struct.pack(">BBBBHH", 0, 0, rows - 1, columns - 1, size[0], size[1])
    infe = b"".join(_full(b"infe", 2, 1 if grid else 0, struct.pack(">HH", i, 0) + b"hvc1" + b"\0")
                    for i in item_ids)
    if grid:
        infe += _full(b"infe", 2, 0, struct.pack(">HH", primary, 0) + b"grid" + b"\0")
    iinf = _full(b"iinf", 0, 0, struct.pack(">H", count + (1 if grid else 0)) + infe)
    width, height = tile_size or size
    properties = [_hvcc(vps, sps, pps), _full(b"ispe", 0, 0, struct.pack(">II", width, height))]
    if grid:
        properties.append(_full(b"ispe", 0, 0, struct.pack(">II", *size)))
    if rotation:
        properties.append(_box(b"irot", bytes([rotation % 4])))
    ipco = _box(b"ipco", b"".join(properties))
    # Property indexes are 1-based; 0x80 marks a property as essential.
    # Single image: hvcC=1, ispe=2, irot=3. Grid: hvcC=1, tile ispe=2,
    # grid ispe=3, irot=4 (on the grid item only).
    associations = []
    tile_props = [0x81, 2] + ([0x83] if rotation and not grid else [])
    for i in item_ids:
        associations.append(struct.pack(">HB", i, len(tile_props)) + bytes(tile_props))
    if grid:
        grid_props = [3] + ([0x84] if rotation else [])
        associations.append(struct.pack(">HB", primary, len(grid_props)) + bytes(grid_props))
    ipma = _full(b"ipma", 0, 0, struct.pack(">I", len(associations)) + b"".join(associations))
    iref = b""
    if grid:
        iref = _full(b"iref", 0, 0, _box(b"dimg", struct.pack(">HH", primary, count)
                                          + b"".join(struct.pack(">H", i) for i in item_ids)))
    ftyp = _box(b"ftyp", b"heic" + struct.pack(">I", 0) + b"mif1heic")

    def meta(offsets: list[int]) -> bytes:
        hdlr = _full(b"hdlr", 0, 0, struct.pack(">I", 0) + b"pict" + b"\0" * 12 + b"\0")
        pitm = _full(b"pitm", 0, 0, struct.pack(">H", primary))
        entries = []
        lengths = [len(p[3]) for p in pieces] + ([len(grid_data)] if grid else [])
        for index, (offset, length) in enumerate(zip(offsets, lengths), 1):
            entries.append(struct.pack(">HHHII", index, 0, 1, offset, length))
        iloc = _full(b"iloc", 0, 0, bytes([0x44, 0x00]) + struct.pack(">H", len(entries)) + b"".join(entries))
        return _full(b"meta", 0, 0, hdlr + pitm + iloc + iinf + _box(b"iprp", ipco + ipma) + iref)

    payload = b"".join(p[3] for p in pieces) + grid_data
    probe = meta([0] * (count + (1 if grid else 0)))
    base = len(ftyp) + len(probe) + 8
    offsets, cursor = [], base
    for length in [len(p[3]) for p in pieces] + ([len(grid_data)] if grid else []):
        offsets.append(cursor)
        cursor += length
    target.write_bytes(ftyp + meta(offsets) + _box(b"mdat", payload))
    return target


def make_heic(target: Path, source: Path, *, grid: tuple[int, int] | None = None,
              rotation: int = 0, ffmpeg: str = "ffmpeg") -> Path:
    """HEIC from an image file; ``grid`` splits it into equal tiles first."""
    probe = subprocess.run([ffmpeg.replace("ffmpeg", "ffprobe"), "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(source)],
                           capture_output=True, text=True, timeout=60, check=False)
    width, height = (int(v) for v in probe.stdout.strip().split(","))
    if not grid:
        return write_heic(target, [encode_hevc(source, ffmpeg)], (width, height), rotation=rotation)
    rows, columns = grid
    tw, th = width // columns, height // rows
    tiles = []
    for row in range(rows):
        for column in range(columns):
            piece = target.with_name(f"{target.stem}-tile-{row}-{column}.png")
            subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(source), "-vf",
                            f"crop={tw}:{th}:{column * tw}:{row * th}", "-frames:v", "1", str(piece)],
                           check=True, timeout=60)
            tiles.append(encode_hevc(piece, ffmpeg))
            piece.unlink()
    return write_heic(target, tiles, (tw * columns, th * rows), grid=grid, tile_size=(tw, th), rotation=rotation)
