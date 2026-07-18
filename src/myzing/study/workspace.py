"""Workspace paths for study outputs.

Lane B owns the real storage layout (planned: ~/.zing/, env-overridable).
Until that lands, every path the study engine touches routes through this
module so adopting Lane B's storage is a one-file change. The directory
shape already mirrors Lane B's plan: <root>/breakdowns/<slug>/{media.*,
breakdown.json, breakdown.md}.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

_SLUG_BAD = re.compile(r"[^a-zA-Z0-9._-]+")


def workspace_root() -> Path:
    root = os.environ.get("ZING_WORKSPACE")
    if root:
        return Path(root)
    return Path.cwd() / "zing-workspace"


def slugify(text: str) -> str:
    slug = _SLUG_BAD.sub("-", text).strip("-.")
    return slug[:80] or "video"


def slug_for_source(source: str) -> str:
    """Deterministic slug: same source always lands in the same folder."""
    if is_url(source):
        parsed = urlparse(source)
        segments = [s for s in parsed.path.split("/") if s]
        # Last two path segments carry the identity on all three platforms
        # (e.g. @user/video/123..., shorts/<id>, reel/<id>).
        tail = "-".join(segments[-2:]) if segments else parsed.netloc
        return slugify(tail)
    # Backslashes normalized so the same source yields the same slug on
    # Windows (where the product runs) and Linux (where CI runs).
    return slugify(Path(source.replace("\\", "/")).stem)


def is_url(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def breakdown_dir(slug: str, root: Path | None = None) -> Path:
    d = (root or workspace_root()) / "breakdowns" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d
