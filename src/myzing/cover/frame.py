"""Read still dimensions without an imaging extra. Never decode a remote URL."""
from __future__ import annotations

import struct
from pathlib import Path

from . import CoverError


def _orientation(exif: bytes) -> int:
    """Read the TIFF orientation tag from the first image directory."""
    exif = exif.removeprefix(b"Exif\0\0")
    order = {b"II": "<", b"MM": ">"}.get(exif[:2])
    if not order or len(exif) < 8:
        return 1
    magic, offset = struct.unpack_from(order + "HI", exif, 2)
    if magic != 42 or offset + 2 > len(exif):
        return 1
    count = struct.unpack_from(order + "H", exif, offset)[0]
    for index in range(count):
        start = offset + 2 + index * 12
        if start + 12 > len(exif):
            break
        tag, kind, items, value = struct.unpack_from(order + "HHIH", exif, start)
        if (tag, kind, items) == (274, 3, 1):
            return value
    return 1


def _webp(stream) -> tuple[int, int, int]:
    stream.seek(12)
    w = h = 0
    orientation = 1
    while len(chunk := stream.read(8)) == 8:
        kind, length = struct.unpack("<4sI", chunk)
        end = stream.tell() + length + length % 2
        data = stream.read(min(length, 10))
        if kind == b"VP8X" and len(data) == 10:
            if data[0] & 2:
                raise CoverError("Extract one still frame from the animated WebP.")
            w = 1 + int.from_bytes(data[4:7], "little")
            h = 1 + int.from_bytes(data[7:10], "little")
        elif kind == b"VP8 " and len(data) == 10 and not w and data[3:6] == b"\x9d\x01\x2a":
            w, h = (v & 0x3fff for v in struct.unpack("<HH", data[6:]))
        elif kind == b"VP8L" and len(data) >= 5 and not w and data[0] == 0x2f:
            bits = int.from_bytes(data[1:5], "little")
            w, h = 1 + (bits & 0x3fff), 1 + ((bits >> 14) & 0x3fff)
        elif kind == b"EXIF" and length <= 65536:
            orientation = _orientation(data + stream.read(length - len(data)))
        stream.seek(end)
    return w, h, orientation


def dimensions(path: Path) -> tuple[int, int]:
    """Read still dimensions in the display orientation used by the browser."""
    orientation = 1
    w = h = 0
    with path.open("rb") as stream:
        header = stream.read(24)
        if header.startswith(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") and len(header) == 24:
            w, h = struct.unpack(">II", header[16:])
            stream.seek(33)  # End of IHDR and its CRC.
            while len(chunk := stream.read(8)) == 8:
                length, kind = struct.unpack(">I4s", chunk)
                if kind == b"acTL":
                    raise CoverError("Extract one still frame from the animated PNG.")
                if kind == b"IDAT":
                    break
                if kind == b"eXIf" and length <= 65536:
                    orientation = _orientation(stream.read(length))
                    stream.seek(4, 1)
                else:
                    stream.seek(length + 4, 1)
            else:
                raise CoverError("Supply a PNG containing image pixels.")
        elif header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            w, h, orientation = _webp(stream)
        elif header.startswith(b"\xff\xd8"):
            stream.seek(2)
            while stream.read(1) == b"\xff":
                marker = stream.read(1)
                while marker == b"\xff":
                    marker = stream.read(1)
                if not marker or marker in (b"\xd9", b"\xda"):
                    break
                length = int.from_bytes(stream.read(2), "big")
                if length < 2:
                    break
                segment = stream.read(length - 2)
                if len(segment) != length - 2:
                    break
                if marker == b"\xe1" and segment.startswith(b"Exif\0\0"):
                    orientation = _orientation(segment)
                elif marker[0] in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
                                    0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf) and len(segment) >= 5:
                    h, w = struct.unpack_from(">HH", segment, 1)
    if w and h:
        return (h, w) if orientation in (5, 6, 7, 8) else (w, h)
    raise CoverError("Use a still PNG, JPEG or WebP with readable pixel dimensions.")


def inside(directory: Path, src: str) -> Path:
    relative = Path(src)
    if relative.anchor or ":" in src or src.startswith(("/", "\\")):
        raise CoverError("Set frame.src to a relative file inside the cover directory.")
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise CoverError("Place the frame inside the cover directory and correct frame.src.")
    return path
