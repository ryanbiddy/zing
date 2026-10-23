"""Explicit pinned model downloads, shared by OCR and speech provisioning."""

import hashlib
import os
from pathlib import Path
import tempfile
import urllib.request


def verified(path, digest):
    path = Path(path)
    if not path.is_file():
        return False
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest() == digest


def fetch_verified(url, target, digest, limit, *, progress=None):
    """Stream to a sibling temporary file; publish only after SHA-256 matches."""
    target = Path(target)
    if verified(target, digest):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        sha, count, last = hashlib.sha256(), 0, -1
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as out:
            temporary = Path(out.name)
            with urllib.request.urlopen(url, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > limit:
                        raise RuntimeError(f"Model exceeds pinned size: {target.name}")
                    sha.update(chunk)
                    out.write(chunk)
                    percent = int(count * 100 / limit)
                    if progress and (percent // 5 != last or count == limit):
                        progress(f"Downloading {target.name}: {count / 1e6:.1f}/{limit / 1e6:.1f} MB ({percent}%)")
                        last = percent // 5
            if sha.hexdigest() != digest:
                raise RuntimeError(f"Model SHA-256 verification failed: {target.name}")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, target)
        if progress:
            progress(f"Verified SHA-256: {target.name}")
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
