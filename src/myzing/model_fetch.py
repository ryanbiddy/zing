"""Explicit pinned model downloads, shared by OCR and speech provisioning.

Transport policy: HTTPS only, on the first request and on every redirect hop
(http, ftp and other schemes are refused before any body is read). Redirects
to another HTTPS host are followed, because Hugging Face serves weights from
its CDN hosts and those names change; integrity rests on the pinned byte limit
and SHA-256, checked before anything is published.
"""

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit

LOCK_NAME = ".zing-download.lock"


class _HTTPSOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urlsplit(newurl).scheme.lower()
        if scheme != "https":
            fp.close()
            # Never echo the target: signed CDN URLs carry tokens.
            raise RuntimeError(f"Model download refused a redirect to a non-HTTPS URL ({scheme or 'no scheme'}); "
                               "Zing downloads models over HTTPS only.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener():
    return urllib.request.build_opener(_HTTPSOnlyRedirects())


def https_open(url, timeout=60):
    """Open a model URL over HTTPS, following only HTTPS redirects."""
    if urlsplit(url).scheme.lower() != "https":
        raise ValueError("Zing downloads models over HTTPS only; refusing a non-HTTPS model URL.")
    response = opener().open(url, timeout=timeout)
    if urlsplit(response.geturl()).scheme.lower() != "https":
        response.close()
        raise RuntimeError("Model download left HTTPS; Zing downloads models over HTTPS only.")
    return response


# The one network seam for model bytes; tests replace it with fakes.
open_url = https_open


def verified(path, digest):
    path = Path(path)
    if not path.is_file():
        return False
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest() == digest


def _try_lock(stream):
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(stream):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_UN)


@contextmanager
def download_lock(folder, progress=None):
    """One downloader per cache folder across processes; the OS releases it on exit or kill."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / LOCK_NAME).open("a+b") as stream:
        waiting = False
        while not _try_lock(stream):
            if not waiting and progress:
                progress(f"Waiting for another Zing download in {folder} to finish")
            waiting = True
            time.sleep(.25)
        try:
            yield
        finally:
            _unlock(stream)


def _discard_parts(folder, name="*"):
    for stale in Path(folder).glob(f".{name}.*.part"):
        try:
            stale.unlink()
        except OSError:
            pass


def discard_abandoned(folder):
    """After a supervisor kills a download, remove its partial files, unless a
    live download still holds the folder (that one cleans up after itself)."""
    folder = Path(folder)
    if not (folder / LOCK_NAME).is_file():
        return
    with (folder / LOCK_NAME).open("a+b") as stream:
        if _try_lock(stream):
            try:
                _discard_parts(folder)
            finally:
                _unlock(stream)


def _saved(target, write):
    try:
        write()
    except OSError as exc:
        error = OSError(f"Could not save {target.name} in {target.parent} ({exc.strerror or exc}). "
                        "Free space there, or move ZING_HOME to a roomier drive, then retry.")
        error.errno = exc.errno
        raise error from exc


def _replace(source, target):
    for attempt in range(50):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            # A Windows reader (an inventory hash) can briefly hold a corrupt
            # target open without delete sharing; retry instead of failing.
            if os.name != "nt" or attempt == 49:
                raise
            time.sleep(.02)


def fetch_verified(url, target, digest, limit, *, progress=None):
    """Stream to a sibling temporary file; publish only after SHA-256 matches."""
    target = Path(target)
    if verified(target, digest):
        return False
    with download_lock(target.parent, progress):
        if verified(target, digest):
            return False  # another process published it while this one waited
        # Only the lock holder writes these, so any left over were abandoned by
        # a killed or crashed download (a kill skips the finally below).
        _discard_parts(target.parent, target.name)
        temporary = None
        try:
            sha, count, last = hashlib.sha256(), 0, -1
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", suffix=".part",
                                             delete=False) as out:
                temporary = Path(out.name)
                with open_url(url) as response:
                    while chunk := response.read(1024 * 1024):
                        count += len(chunk)
                        if count > limit:
                            raise RuntimeError(f"Model exceeds pinned size: {target.name}")
                        sha.update(chunk)
                        _saved(target, lambda: out.write(chunk))
                        percent = int(count * 100 / limit)
                        if progress and (percent // 5 != last or count == limit):
                            progress(f"Downloading {target.name}: {count / 1e6:.1f}/{limit / 1e6:.1f} MB ({percent}%)")
                            last = percent // 5
                if sha.hexdigest() != digest:
                    raise RuntimeError(f"Model SHA-256 verification failed: {target.name}")
                _saved(target, lambda: (out.flush(), os.fsync(out.fileno())))
            _replace(temporary, target)
            if progress:
                progress(f"Verified SHA-256: {target.name}")
            return True
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
