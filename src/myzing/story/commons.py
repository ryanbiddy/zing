"""Find and fetch Commons pictures through the factory's HTTP and rights checks."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import StoryError
from .contract import ID, local_photo

# Commons serves originals from upload.wikimedia.org and scaled copies from
# thumb.wikimedia.org.
COMMONS_HOSTS = frozenset({"commons.wikimedia.org", "upload.wikimedia.org", "thumb.wikimedia.org"})


def _factory():
    try:
        from myzing.factory import visuals
    except ImportError as exc:
        raise StoryError("Finding pictures needs Pillow. Install 'myzing[factory]' and retry.") from exc
    return visuals


def _commons_url(value: str, *, page: bool = False) -> str:
    try:
        url = urlsplit(value)
        allowed = {"commons.wikimedia.org"} if page else COMMONS_HOSTS
        if (url.scheme not in ("https", "http") or url.hostname not in allowed
                or url.username or url.password or url.port not in (None, 80, 443)):
            raise ValueError
    except (TypeError, ValueError):
        raise StoryError("Only Wikimedia Commons page and upload URLs are allowed.") from None
    return value


def _title(value: str) -> str:
    value = value.strip()
    if "://" in value or value.startswith("//"):
        _commons_url(value, page=True)
        url = urlsplit(value)
        if url.path.startswith("/wiki/"):
            value = unquote(url.path[len("/wiki/"):])
        elif url.path == "/w/index.php":
            value = parse_qs(url.query).get("title", [""])[0]
        else:
            raise StoryError("Use a Commons File: title or its /wiki/File: page URL.")
        if not value.lower().startswith("file:"):
            raise StoryError("Use a Commons File: title or its /wiki/File: page URL.")
    if not value.lower().startswith("file:"):
        value = "File:" + value
    value = "File:" + value[5:].strip().replace("_", " ")
    if len(value) <= 5 or len(value) > 500 or any(ord(c) < 32 or c == "|" for c in value):
        raise StoryError("Use one Commons File: title.")
    return value


def _candidate(page: dict, visuals) -> tuple[dict, dict] | None:
    candidate = visuals.commons_cand(page, "commons", visuals.MIN_LONG_SIDE)
    if candidate is None or candidate["media_type"] != "image":
        return None
    info = (page.get("imageinfo") or [{}])[0]
    metadata = {key: (value or {}).get("value", "") for key, value in (info.get("extmetadata") or {}).items()}
    credit = visuals.strip_html(metadata.get("Artist"))
    license = visuals.strip_html(metadata.get("LicenseShortName"))
    # commons_cand has display fallbacks. A story needs the actual metadata.
    candidate.update(creator=credit, license=license)
    rights, _ = visuals.rights_for(candidate)
    reason = ""
    if not credit or credit.lower() in {"unknown", "unknown author", "unknown (see source page)", "n/a"}:
        reason = "Commons metadata has no author; a credit cannot be guessed"
    elif not license:
        reason = "Commons metadata has no license"
    elif rights not in ("cleared", "attribution"):
        reason = "license must permit reuse and changes; NC, ND and unknown licenses are refused"
    elif len(credit) > 120 or len(license) > 100:
        reason = "author credit or license is too long for the story; it cannot be shortened without review"
    source_url = candidate.get("source_url") or ""
    try:
        _commons_url(source_url, page=True)
        _commons_url(candidate.get("file_url") or "")
    except StoryError:
        reason = reason or "Commons metadata points outside Commons or has no file/page URL"
    result = {"title": page.get("title", ""), "license": license, "credit": credit,
              "width": candidate.get("width", 0), "height": candidate.get("height", 0),
              "bytes": info.get("size"), "source_url": source_url, "rights": rights,
              "accepted": not reason, "reason": reason}
    return result, candidate


def find(query: str, *, limit: int = 10) -> list[dict]:
    """List Commons pictures and explain each rights refusal without downloading."""
    if not isinstance(query, str) or not query.strip():
        raise StoryError("A picture search needs some words.")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise StoryError("Picture search limit must be from 1 to 50.")
    visuals = _factory()
    http = visuals.Http(allowed_hosts=COMMONS_HOSTS)
    pages = visuals.commons_query(http, {"generator": "search", "gsrsearch": query.strip(),
                                        "gsrnamespace": 6, "gsrlimit": limit})
    result = []
    for page in pages:
        item = _candidate(page, visuals)
        if item is not None:
            result.append(item[0])
    return result[:limit]


def _save(path: Path, content: bytes) -> None:
    """Replace a local output only after its complete contents are written."""
    handle, name = tempfile.mkstemp(prefix=".story-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch(directory: Path, title_or_url: str, target: str) -> dict:
    """Download one accepted picture and add its actual metadata to story.json."""
    title = _title(title_or_url)
    kind, separator, ident = target.partition(":")
    if not separator or kind not in ("photo", "image") or not ID.fullmatch(ident):
        raise StoryError("--as must be photo:<cast-id> or image:<image-id>, using a lowercase ID.")
    directory = Path(directory).resolve()
    story_path = local_photo(directory, "story.json")
    try:
        original = story_path.read_bytes()
        story = json.loads(original)
    except (OSError, ValueError) as exc:
        raise StoryError(f"Cannot read story.json: {exc}") from exc
    if not isinstance(story, dict):
        raise StoryError("story.json must contain an object.")
    if kind == "photo":
        cast = story.get("cast", {})
        if not isinstance(cast, dict) or not isinstance(cast.get(ident), dict):
            raise StoryError(f"Unknown cast member {ident!r}; add it to story.json before fetching a photo.")
        if not isinstance(cast[ident].get("photos", []), list):
            raise StoryError(f"cast.{ident}.photos must be a list.")
    else:
        images = story.get("images", {})
        if not isinstance(images, dict):
            raise StoryError("images must be an object keyed by image ID.")
        if ident in images:
            raise StoryError(f"Image {ident!r} already exists; choose a new image ID.")
    visuals = _factory()
    http = visuals.Http(project=directory, allowed_hosts=COMMONS_HOSTS)
    pages = visuals.commons_query(http, {"titles": title, "redirects": 1})
    candidates = [item for page in pages if (item := _candidate(page, visuals)) is not None]
    if len(candidates) != 1:
        raise StoryError("Commons did not return one supported picture at least 900 pixels on its long side.")
    result, candidate = candidates[0]
    if not result["accepted"]:
        raise StoryError(f"Refused {result['title']}: {result['reason']}.")
    data = http.get_bytes(_commons_url(candidate["file_url"]), visuals.IMG_CAP)
    if len(data) > visuals.IMG_CAP:
        raise StoryError("Picture exceeds the factory's 40 MB download limit.")
    try:
        extension, width, height, _ = visuals.validate_image(data)
    except (OSError, ValueError) as exc:
        raise StoryError(f"Commons returned an unreadable or unsupported picture: {exc}") from exc
    if max(width, height) < visuals.MIN_LONG_SIDE:
        raise StoryError(f"Picture is too small ({width}x{height}); its long side must be at least 900 pixels.")
    folder = "photos" if kind == "photo" else "images"
    relative = f"{folder}/{ident}-source-{hashlib.sha256(data).hexdigest()[:16]}.{extension}"
    output = local_photo(directory, relative)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_bytes() != data:
        raise StoryError(f"Picture output {relative} already exists with different contents.")
    entry = {"path": relative, "credit": result["credit"], "license": result["license"],
             "source_url": result["source_url"]}
    if kind == "photo":
        story["cast"][ident].setdefault("photos", []).append(entry)
    else:
        story.setdefault("images", {})[ident] = entry
    if story_path.read_bytes() != original:
        raise StoryError("story.json changed during the download; retry after those edits are saved.")
    if not output.exists():
        _save(output, data)
    _save(story_path, (json.dumps(story, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return {"target": target, "title": result["title"], "entry": entry,
            "width": width, "height": height, "bytes": len(data)}
