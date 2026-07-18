"""Zing workspace storage: where breakdowns live on disk.

Layout (workspace root is ``~/.zing``, overridable via the ``ZING_HOME``
environment variable — read at call time, never cached at import):

    <root>/
      breakdowns/
        <slug>/
          breakdown.json      # the Breakdown, canonical
          breakdown.md        # human-readable render (optional)
          media.<ext>         # the analyzed media file (optional)

Rules this module enforces (the rest of the codebase relies on them):

- Storage owns slugs. ``slug_for()`` is deterministic: the same URL or the
  same file always maps to the same slug, so re-studying is an update, not
  a duplicate. No other lane invents slugs or paths.
- Re-study preserves judgment. ``save_breakdown()`` carries an existing
  ``judgment`` forward when the incoming Breakdown has none — judgment is
  the user's AI's work, Zing cannot regenerate it. The prior json is kept
  as ``breakdown.json.bak``.
- ``save_judgment()`` merges at the top level only: each top-level key is a
  section (e.g. "study") and is replaced wholesale. No deep merge.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from myzing.schemas import Breakdown

ENV_VAR = "ZING_HOME"

_SLUG_MAX = 80
_MEDIA_EXTS = (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v", ".ts")


def workspace_root() -> Path:
    """The Zing workspace directory (not created by this call)."""
    override = os.environ.get(ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".zing"


def breakdowns_root() -> Path:
    return workspace_root() / "breakdowns"


def breakdown_dir(slug: str) -> Path:
    return breakdowns_root() / slug


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------

def _sanitize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:_SLUG_MAX].strip("-") or "video"


def _hash8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def _file_slug(path: Path) -> str:
    stem = _sanitize(path.stem)
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(1024 * 1024)
        digest = _hash8(head + str(size).encode())
    except OSError:
        # Unreadable/missing file: still deterministic, keyed on the name.
        digest = _hash8(str(path.name).encode())
    return f"{stem}-{digest}"


def slug_for(url_or_path: str) -> str:
    """Deterministic slug for a video source (URL or local file path).

    URLs map to ``<platform>-<video id>`` when the id is recognizable
    (tiktok, youtube incl. shorts/youtu.be, instagram reel/post), else
    ``<domain>-<url hash>``. Local files map to ``<stem>-<content hash>``
    so the same file re-studied lands in the same place.
    """
    s = url_or_path.strip()
    parsed = urlparse(s)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        host = parsed.netloc.lower().removeprefix("www.")
        parts = [p for p in parsed.path.split("/") if p]

        if host.endswith("tiktok.com"):
            if "video" in parts:
                i = parts.index("video")
                if i + 1 < len(parts):
                    return f"tiktok-{_sanitize(parts[i + 1])}"
            if parts:  # vm.tiktok.com/<code> short links
                return f"tiktok-{_sanitize(parts[-1])}"
        elif host in ("youtu.be",) and parts:
            return f"youtube-{_sanitize(parts[0])}"
        elif host.endswith("youtube.com"):
            if parts and parts[0] in ("shorts", "embed", "live") and len(parts) > 1:
                return f"youtube-{_sanitize(parts[1])}"
            vid = parse_qs(parsed.query).get("v", [""])[0]
            if vid:
                return f"youtube-{_sanitize(vid)}"
        elif host.endswith("instagram.com"):
            if parts and parts[0] in ("reel", "reels", "p", "tv") and len(parts) > 1:
                return f"instagram-{_sanitize(parts[1])}"

        domain = _sanitize(host.split(":")[0])
        return f"{domain}-{_hash8(s.encode())}"

    return _file_slug(Path(s))


# ---------------------------------------------------------------------------
# Media placement
# ---------------------------------------------------------------------------

def media_target(slug: str, ext: str) -> Path:
    """Where the media file for ``slug`` belongs (dir is created).

    Lane A downloads/copies to exactly this path: ``media.<ext>``.
    """
    ext = ext.lstrip(".").lower() or "mp4"
    d = breakdown_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"media.{ext}"


def find_media(slug: str) -> Path | None:
    """The stored media file for ``slug``, or None if absent."""
    d = breakdown_dir(slug)
    if not d.is_dir():
        return None
    for p in sorted(d.iterdir()):
        if p.is_file() and p.stem == "media" and p.suffix.lower() in _MEDIA_EXTS:
            return p
    return None


# ---------------------------------------------------------------------------
# Breakdown persistence
# ---------------------------------------------------------------------------

def save_breakdown(
    b: Breakdown, slug: str | None = None, markdown: str | None = None
) -> Path:
    """Write a Breakdown to the workspace; returns its directory.

    - ``slug`` defaults to ``slug_for(meta.source_url)``.
    - If a previous breakdown.json exists it is kept as breakdown.json.bak,
      and its ``judgment`` is carried forward when ``b.judgment`` is empty.
    - ``markdown``, when given, is written as breakdown.md.
    """
    slug = slug or slug_for(b.meta.source_url)
    d = breakdown_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    json_path = d / "breakdown.json"

    if json_path.exists():
        if not b.judgment:
            try:
                prior = json.loads(json_path.read_text(encoding="utf-8"))
                if prior.get("judgment"):
                    b.judgment = prior["judgment"]
            except (OSError, ValueError):
                pass  # corrupt prior file: nothing to preserve
        json_path.replace(d / "breakdown.json.bak")

    json_path.write_text(b.to_json(indent=2) + "\n", encoding="utf-8")
    if markdown is not None:
        (d / "breakdown.md").write_text(markdown, encoding="utf-8")
    return d


def load_breakdown(slug: str) -> Breakdown:
    """Load a stored Breakdown. Raises FileNotFoundError with the looked-up
    path when the slug has no breakdown (the caller turns this into an
    actionable message)."""
    json_path = breakdown_dir(slug) / "breakdown.json"
    if not json_path.is_file():
        raise FileNotFoundError(
            f"no breakdown for slug '{slug}' (looked in {json_path})"
        )
    return Breakdown.from_json(json_path.read_text(encoding="utf-8"))


def save_judgment(slug: str, judgment: dict[str, Any]) -> Breakdown:
    """Merge judgment into a stored Breakdown and persist it.

    Top-level keys are sections; each provided section replaces the stored
    one wholesale (no deep merge — deep merges rot silently). Returns the
    updated Breakdown.
    """
    if not isinstance(judgment, dict):
        raise TypeError(f"judgment must be a dict of sections, got {type(judgment).__name__}")
    b = load_breakdown(slug)
    b.judgment.update(judgment)
    d = breakdown_dir(slug)
    (d / "breakdown.json").write_text(b.to_json(indent=2) + "\n", encoding="utf-8")
    return b


def list_breakdowns() -> list[dict[str, Any]]:
    """Index of stored breakdowns, one summary dict per slug, sorted by slug.

    Never raises on a bad entry: a directory whose breakdown.json is
    missing or corrupt yields ``{"slug": ..., "error": ...}`` so callers
    (MCP, CLI) can report it honestly instead of hiding the whole index.
    """
    root = breakdowns_root()
    if not root.is_dir():
        return []
    index: list[dict[str, Any]] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        json_path = d / "breakdown.json"
        if not json_path.is_file():
            index.append({"slug": d.name, "error": "no breakdown.json"})
            continue
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            meta = raw.get("meta", {})
            index.append({
                "slug": d.name,
                "platform": meta.get("platform", ""),
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "duration": meta.get("duration", 0.0),
                "source_url": meta.get("source_url", ""),
                "shots": len(raw.get("shots", [])),
                "words": len(raw.get("words", [])),
                "has_media": find_media(d.name) is not None,
                "judgment_sections": sorted(raw.get("judgment", {})),
            })
        except (OSError, ValueError) as e:
            index.append({"slug": d.name, "error": f"unreadable breakdown.json: {e}"})
    return index
