"""Offline classic catalog and explicit, bounded Memegen blank downloads."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from myzing import storage
from . import MemeError

CATALOG = Path(__file__).resolve().parents[1] / "_data" / "memes" / "templates.json"
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def list_templates(search: str = "") -> list[dict]:
    if not isinstance(search, str):
        raise MemeError("search must be a string")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    term = search.strip().casefold()
    return [t for t in catalog if term in f"{t['id']} {t['name']}".casefold()]


def get_template(template_id: str) -> dict:
    if not isinstance(template_id, str):
        raise MemeError("template must be a catalog id")
    key = template_id.removeprefix("memegen-").casefold()
    for template in list_templates():
        if template["id"] == key:
            return template
    raise MemeError(f"Unknown template {template_id!r}; use 'zing meme templates --search <name>'.")


class _MemegenRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.netloc != "api.memegen.link":
            raise MemeError("Memegen redirected outside api.memegen.link; use a local image instead.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _require_decodable(data: bytes) -> None:
    """Fully decode a downloaded blank so a truncated body is never cached."""
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:  # rendering needs Pillow anyway; the signature check still ran
        return
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
    except Exception as exc:  # Pillow raises several types for corrupt data
        raise MemeError(f"Memegen returned an unreadable image ({exc}); retry or use --image.") from exc


def fetch_blank(template_id: str, *, allow_download: bool = False) -> Path:
    """Return a cached blank. A cache miss needs explicit download consent.

    Only catalog IDs become URLs. No user text or local photos leave the machine.
    Unique temporary files plus atomic replace prevent partial cache entries.
    """
    template = get_template(template_id)
    root = storage.workspace_root().resolve()
    directory = root / "memes" / "templates"
    target = directory / f"{template['memegen_id']}.jpg"
    if not target.resolve().is_relative_to(root):
        raise MemeError("Template cache resolves outside the Zing workspace.")
    if target.is_file():
        if 0 < target.stat().st_size <= MAX_IMAGE_BYTES:
            return target
        raise MemeError(f"Invalid cached blank: {target}; remove it and retry.")
    if not allow_download:
        raise MemeError(f"Template {template['id']!r} is not cached; omit --offline to fetch it, or use --image.")
    url = f"https://api.memegen.link/images/{template['memegen_id']}.jpg"
    request = Request(url, headers={"User-Agent": "Zing/0.1 (meme blank)", "Accept": "image/jpeg"})
    try:
        with build_opener(_MemegenRedirect()).open(request, timeout=15) as response:
            if response.headers.get_content_type() not in ("image/jpeg", "image/png", "image/webp"):
                raise MemeError("Memegen returned non-image content; use --image or retry later.")
            data = response.read(MAX_IMAGE_BYTES + 1)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise MemeError("Memegen blank is empty or exceeds the 20 MiB download limit.")
        if not (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")
                or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")):
            raise MemeError("Memegen returned an invalid image signature.")
        _require_decodable(data)
        directory.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
                temp = Path(stream.name)
                stream.write(data)
            os.replace(temp, target)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
    except (OSError, URLError) as exc:
        raise MemeError(f"Could not fetch blank {template['id']!r}: {exc}. Retry or use --image <local photo>.") from exc
    return target
