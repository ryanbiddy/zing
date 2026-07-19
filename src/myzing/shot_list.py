"""Writer shot-list import (INTEGRATION-CONTRACT v1 §6.2, ratified it#53).

Writer exports a user-chosen UTF-8 Markdown file; zing imports it against
a studied breakdown as editorial context and draft provenance. Binding
rules this module enforces:

- The file is the wire format: exact front matter (four keys, fixed
  order), exact heading sequence, ≤ 2 MiB, UTF-8, regular file only.
- ``unsupported_version`` is a DISTINCT outcome from ``invalid_file`` —
  a well-formed document from a future writer must say "update zing",
  not "your file is broken".
- The persisted copy is content-addressed by SHA-256, which makes
  re-importing the same document for the same target idempotent by
  construction (same receipt, one copy on disk).
- The receipt is path-free: the selected input path is neither returned
  nor persisted (stable-references rule). Direction stays the authority
  for measured keeper spans — an import never touches judgment.

Error codes are the contract's stable set: ``invalid_file``,
``unsupported_version``, ``target_not_found``, ``conflict``,
``storage_unavailable``.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from myzing import storage

CONTRACT = "zing.shot-list.import"
CONTRACT_VERSION = 1
DOCUMENT_TYPE = "writer.shot-list"
DOCUMENT_VERSION = 1
SIZE_LIMIT = 2 * 1024 * 1024

_FRONT_KEYS = (
    "document_type",
    "schema_version",
    "generated_at",
    "source_script_id",
)
_HEADINGS = ("## Hook", "## Beats", "## Script", "## CTA", "## Shots", "## Credits")
IMPORTS_DIRNAME = "imports"


def _ok(document: dict[str, Any], target_ref: str) -> dict[str, Any]:
    return {
        "ok": True,
        "contract": CONTRACT,
        "version": CONTRACT_VERSION,
        "data": {
            "state": "imported",
            "document": document,
            "target_ref": target_ref,
            "warnings": [],
        },
    }


def _fail(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "contract": CONTRACT,
        "version": CONTRACT_VERSION,
        "error": {"code": code, "message": message, "retryable": retryable},
    }


def _is_rfc3339(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def parse_document(raw: bytes) -> tuple[dict[str, str], str | None]:
    """Validate the writer.shot-list wire format.

    Returns (front_matter, defect). ``defect`` is None for a valid
    document, the string "unsupported_version" for a well-formed document
    with a schema_version other than 1, or a human message describing the
    first defect (an invalid_file outcome).
    """
    if len(raw) > SIZE_LIMIT:
        return {}, f"file exceeds the {SIZE_LIMIT // (1024 * 1024)} MiB limit"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {}, "file is not valid UTF-8"
    lines = text.splitlines()
    if len(lines) < 6 or lines[0] != "---" or lines[5] != "---":
        return {}, (
            "front matter must be exactly four 'key: value' lines between "
            "'---' fences at the top of the file"
        )
    parsed: dict[str, str] = {}
    seen: list[str] = []
    for line in lines[1:5]:
        if ":" not in line:
            return {}, f"front matter line without 'key: value' form: {line!r}"
        key, value = line.split(":", 1)
        key = key.strip()
        if key in parsed:
            return {}, f"duplicate front matter key: {key}"
        seen.append(key)
        parsed[key] = value.strip()
    if tuple(seen) != _FRONT_KEYS:
        return {}, (
            f"front matter keys must be exactly {list(_FRONT_KEYS)} in that "
            f"order; found {seen}"
        )
    if parsed["document_type"] != DOCUMENT_TYPE:
        return {}, (
            f"document_type is {parsed['document_type']!r}, expected "
            f"'{DOCUMENT_TYPE}'"
        )
    if parsed["schema_version"] != str(DOCUMENT_VERSION):
        # Distinct outcome: the document may be perfectly fine for a
        # newer zing — that is not the user's file being broken.
        return parsed, "unsupported_version"
    if not _is_rfc3339(parsed["generated_at"]):
        return {}, (
            f"generated_at is not an RFC 3339 timestamp: "
            f"{parsed['generated_at']!r}"
        )
    if not re.fullmatch(r"[1-9][0-9]*", parsed["source_script_id"]):
        return {}, (
            "source_script_id must be a positive decimal Writer script id; "
            f"found {parsed['source_script_id']!r}"
        )
    headings = [
        line for line in lines[6:] if line.startswith(("# ", "## "))
    ]
    if not headings or not headings[0].startswith("# "):
        return {}, "missing '# <title>' heading after the front matter"
    if not headings[0].removeprefix("# ").strip():
        return {}, "the '# <title>' heading is empty"
    if tuple(headings[1:]) != _HEADINGS:
        return {}, (
            f"section headings must be exactly {list(_HEADINGS)} in that "
            f"order, each once; found {headings[1:]}"
        )
    return parsed, None


def import_shot_list(path: str | Path, slug: str) -> dict[str, Any]:
    """Import a writer shot-list file against a studied breakdown.

    Returns the ``zing.shot-list.import`` v1 envelope (the contract
    receipt IS the tool response). The selected input path never appears
    in it and is never persisted.
    """
    try:
        storage.validate_slug(slug)
    except storage.SlugError as e:
        return _fail("target_not_found", f"invalid target slug: {e}")
    source = Path(path).expanduser()
    if not source.is_file():
        return _fail(
            "invalid_file",
            "selected file does not exist or is not a regular file",
        )
    try:
        raw = source.read_bytes()
    except OSError as e:
        return _fail("invalid_file", f"selected file could not be read: {e}")

    front, defect = parse_document(raw)
    if defect == "unsupported_version":
        return _fail(
            "unsupported_version",
            f"writer.shot-list version {front.get('schema_version')} is not "
            f"supported (this zing speaks version {DOCUMENT_VERSION}) — "
            "update zing",
        )
    if defect is not None:
        return _fail("invalid_file", f"not a valid writer.shot-list file: {defect}")

    breakdown_json = storage.breakdown_dir(slug) / "breakdown.json"
    if not breakdown_json.is_file():
        return _fail(
            "target_not_found",
            f"no studied breakdown for slug '{slug}' — study the video "
            "first (study_video), then import",
        )

    sha256 = hashlib.sha256(raw).hexdigest()
    imports_dir = storage.breakdown_dir(slug) / IMPORTS_DIRNAME
    copy_path = imports_dir / f"writer-shot-list-{sha256[:16]}.md"
    try:
        imports_dir.mkdir(parents=True, exist_ok=True)
        if copy_path.is_file():
            if copy_path.read_bytes() != raw:
                # Content-addressing makes this a 16-hex-prefix collision
                # between different documents — never overwrite evidence.
                return _fail(
                    "conflict",
                    "a different imported document already occupies this "
                    "content address — rename nothing, report this as a bug",
                )
            # Same bytes, same target: idempotent by construction — the
            # receipt below is deterministic and the copy count stays 1.
        else:
            copy_path.write_bytes(raw)
    except OSError as e:
        return _fail(
            "storage_unavailable",
            f"could not persist the imported copy: {e}",
            retryable=True,
        )

    document = {
        "type": DOCUMENT_TYPE,
        "version": DOCUMENT_VERSION,
        "sha256": sha256,
        "source_ref": f"writer://script/{front['source_script_id']}",
    }
    return _ok(document, f"zing://breakdown/{slug}")
