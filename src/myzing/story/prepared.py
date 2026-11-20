"""Track which local source and crop produced each prepared picture."""
from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from myzing.color.media import sha256
from myzing.storage import _write_atomic

from . import StoryError
from .contract import local_photo


def source_record(source: Path, settings: dict) -> dict:
    return {"sha256": sha256(source), **{key: settings[key] for key in ("path", "face", "box") if key in settings}}


def targets(directory: Path, name: str) -> tuple[Path, Path]:
    return local_photo(directory, name), local_photo(directory, name + ".json")


@contextmanager
def writing(directory: Path, name: str, record: dict):
    output, manifest = targets(directory, name)
    # Hash the file this invocation actually made, even if a second preparer
    # publishes the same name. A mismatched pair fails verification on render.
    with tempfile.TemporaryDirectory(prefix=".story-asset-", dir=directory) as scratch:
        staged = Path(scratch) / output.name
        yield staged
        data = json.dumps({"source": record, "output_sha256": sha256(staged)})
        output.parent.mkdir(parents=True, exist_ok=True)
        staged.replace(output)
        _write_atomic(manifest, data)


def verify(directory: Path, name: str, settings: dict, label: str, step: str) -> None:
    output, manifest = targets(directory, name)
    if not output.is_file():
        raise StoryError(f"Prepared {label} is missing. Run 'zing story {step}' first.")
    if not manifest.is_file():   # art placed by hand, or prepared before records existed
        return
    try:
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        source = local_photo(directory, settings["path"])
        if saved == {"source": source_record(source, settings), "output_sha256": sha256(output)}:
            return
    except (OSError, ValueError):
        pass
    raise StoryError(f"Prepared {label} is stale. Run 'zing story {step}' again.")
