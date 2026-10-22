"""Atomic single-file publication with exclusive output/receipt reservations."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def reserve_output(output: Path, *, overwrite: bool = False):
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = Path(str(output) + ".publish-lock")
    # The exclusive lock serializes cooperating writers, including overwriters.
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        if not overwrite:
            for path in (output, Path(str(output) + ".receipt.json")):
                if os.path.lexists(path):
                    raise FileExistsError(f"Output or receipt already exists: {path}; use overwrite=True explicitly")
        yield
    finally:
        lock.unlink()


def atomic_publish(source: Path, destination: Path, *, overwrite: bool = False) -> None:
    """Stage on the destination volume, then link exclusively or replace.

    link() is the no-clobber commit, including if an unrelated writer races us.
    No check-then-rename fallback on filesystems without hard links.
    """
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)
    stage = Path(name)
    try:
        with os.fdopen(fd, "wb") as target, source.open("rb") as original:
            shutil.copyfileobj(original, target)
            target.flush()
            os.fsync(target.fileno())
        if overwrite:
            os.replace(stage, destination)
        else:
            os.link(stage, destination)
    finally:
        stage.unlink(missing_ok=True)


def publish_pair(source: Path, output: Path, receipt: dict, *, overwrite: bool = False) -> None:
    receipt_source = source.with_name(source.name + ".publish.json")
    receipt_source.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    # Receipt first: a receipt collision cannot publish an unreceipted video.
    receipt_path = Path(str(output) + ".receipt.json")
    atomic_publish(receipt_source, receipt_path, overwrite=overwrite)
    try:
        atomic_publish(source, output, overwrite=overwrite)
    except BaseException:
        if not overwrite:
            receipt_path.unlink(missing_ok=True)
        raise
