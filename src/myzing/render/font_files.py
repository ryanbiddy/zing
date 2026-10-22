"""Private libass font names without changing glyphs or installing fonts.

Only SFNT name/head metadata is rebuilt. Copyright and license name records,
outlines, shaping tables and variation data retain their original bytes.
"""

from __future__ import annotations

import struct
from hashlib import sha256

from .validation import EDLValidationError


def _checksum(data: bytes) -> int:
    padded = data + b"\0" * (-len(data) % 4)
    return sum(v[0] for v in struct.iter_unpack(">I", padded)) & 0xFFFFFFFF


def ass_em_scale(data: bytes) -> float:
    """Convert output em pixels to libass REAL_DIM pixels for an SFNT face.

    libass uses OS/2 Win ascender+descender for REAL_DIM, rather than unitsPerEm.
    See libass/ass_font.c: set_font_metrics and ass_face_set_size.
    """
    try:
        tables = {}
        for i in range(struct.unpack_from(">H", data, 4)[0]):
            tag, _, offset, length = struct.unpack_from(">4sIII", data, 12 + 16 * i)
            tables[tag] = data[offset:offset + length]
        units = struct.unpack_from(">H", tables[b"head"], 18)[0]
        win_ascent, win_descent = struct.unpack_from(">hh", tables[b"OS/2"], 74)
        extent = win_ascent + win_descent
        if units <= 0 or extent <= 0:
            raise ValueError("font needs positive unitsPerEm and OS/2 Win metrics")
        return extent / units
    except (KeyError, ValueError, struct.error) as exc:
        raise EDLValidationError(f"unsupported caption font metrics: {exc}") from exc


def private_font(data: bytes) -> tuple[str, bytes]:
    """Give a verified TTF/OTF a content-specific family, avoiding name clashes.

    These are temporary render assets, never changes to the supplied file.
    Collections/WOFF are not SFNT faces: reject them instead of substituting.
    """
    alias = "Zing" + sha256(data).hexdigest()[:32]
    try:
        if data[:4] not in (b"\0\1\0\0", b"OTTO", b"true"):
            raise ValueError("use a single-face TTF or OTF file (not WOFF or a collection)")
        count = struct.unpack_from(">H", data, 4)[0]
        tables = {}
        for i in range(count):
            tag, _, offset, length = struct.unpack_from(">4sIII", data, 12 + 16 * i)
            if offset + length > len(data) or tag in tables:
                raise ValueError("invalid SFNT table directory")
            tables[tag] = data[offset:offset + length]
        names = tables[b"name"]
        version, records, storage = struct.unpack_from(">HHH", names)
        if version not in (0, 1) or storage > len(names):
            raise ValueError("invalid SFNT name table")
        kept = []
        language_tags = []
        if version == 1:
            offset = 6 + records * 12
            language_count = struct.unpack_from(">H", names, offset)[0]
            for i in range(language_count):
                length, offset_in_storage = struct.unpack_from(">HH", names, offset + 2 + i * 4)
                if storage + offset_in_storage + length > len(names):
                    raise ValueError("invalid SFNT language tag")
                language_tags.append(names[storage + offset_in_storage:storage + offset_in_storage + length])
        # Replace every family/full/unique/PostScript name, including localized
        # and typographic names. Keep attribution, licenses and designer URLs.
        replaced = {1, 2, 3, 4, 6, 16, 17, 18, 21, 22, 25}
        for i in range(records):
            platform, encoding, language, name, length, offset = struct.unpack_from(
                ">6H", names, 6 + i * 12,
            )
            if storage + offset + length > len(names):
                raise ValueError("invalid SFNT name string")
            if name not in replaced:
                kept.append((platform, encoding, language, name,
                             names[storage + offset:storage + offset + length]))
        for name in sorted(replaced):
            value = "Regular" if name in {2, 17, 22} else alias
            kept.append((3, 1, 0x409, name, value.encode("utf-16-be")))
        kept.sort(key=lambda item: item[:4])
        strings = bytearray()
        entries = bytearray()
        for platform, encoding, language, name, value in kept:
            entries.extend(struct.pack(">6H", platform, encoding, language, name,
                                       len(value), len(strings)))
            strings.extend(value)
        languages = bytearray()
        if version == 1:
            languages.extend(struct.pack(">H", len(language_tags)))
            for value in language_tags:
                languages.extend(struct.pack(">HH", len(value), len(strings)))
                strings.extend(value)
        tables[b"name"] = (struct.pack(">HHH", version, len(kept), 6 + len(entries) + len(languages))
                           + entries + languages + strings)
        head = bytearray(tables[b"head"])
        struct.pack_into(">I", head, 8, 0)
        tables[b"head"] = bytes(head)
        tables.pop(b"DSIG", None)  # A signature cannot describe renamed metadata.
        count = len(tables)
        power = count.bit_length() - 1
        result = bytearray(struct.pack(">4s4H", data[:4], count, 16 << power,
                                       power, count * 16 - (16 << power)))
        result.extend(b"\0" * (count * 16))
        head_offset = 0
        for i, (tag, body) in enumerate(sorted(tables.items())):
            offset = len(result)
            struct.pack_into(">4sIII", result, 12 + i * 16, tag, _checksum(body), offset, len(body))
            if tag == b"head":
                head_offset = offset
            result.extend(body)
            result.extend(b"\0" * (-len(result) % 4))
        struct.pack_into(">I", result, head_offset + 8, (0xB1B0AFBA - _checksum(result)) & 0xFFFFFFFF)
        return alias, bytes(result)
    except (KeyError, ValueError, struct.error, OverflowError) as exc:
        raise EDLValidationError(f"invalid caption font: {exc}") from exc
