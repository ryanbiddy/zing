"""The uoink bridge: push a breakdown back into the user's corpus.

Optional by design — Zing is fully standalone. When the uoink helper
answers on localhost (default ``http://127.0.0.1:5179``, override via
``UOINK_URL``), the ``push_to_uoink`` MCP tool sends ``breakdown.md`` to
uoink's ``POST /notes`` intake, where it lands as a first-class note in
the corpus (searchable, queryable over uoink's own MCP). When uoink is
absent, nothing nags: doctor reports it as a calm optional item and the
tool answers honestly if called.

Auth: uoink's local API requires its per-install token in the
``X-Uoink-Token`` header. Zing reads it from the ``UOINK_TOKEN`` env var
and tells the user exactly where uoink keeps it (``token.txt`` next to
uoink's server.py) when it's missing or rejected.

The full two-way integration (reading saved shorts from the corpus,
profiles/shot-lists back) is the S6 sprint with its own contract doc —
this is deliberately just the one high-value push.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from myzing import storage
from myzing.doctor import UOINK_DEFAULT_URL, UOINK_URL_ENV

UOINK_TOKEN_ENV = "UOINK_TOKEN"
_TIMEOUT = 5.0


def helper_url() -> str:
    return os.environ.get(UOINK_URL_ENV, "").strip() or UOINK_DEFAULT_URL


def _token() -> str:
    return os.environ.get(UOINK_TOKEN_ENV, "").strip()


def push_breakdown(slug: str) -> dict[str, Any]:
    """Send a slug's breakdown.md to uoink as a note.

    Returns the uoink house envelope: {"ok": True, ...} or
    {"ok": False, "error": actionable}.
    """
    try:
        storage.validate_slug(slug)  # F-02: slugs are caller input, never paths
    except storage.SlugError as e:
        return {
            "ok": False,
            "error": f"invalid slug: {e} — use a slug from list_breakdowns()",
        }
    md_path = storage.breakdown_dir(slug) / "breakdown.md"
    if not md_path.is_file():
        return {
            "ok": False,
            "error": (
                f"no breakdown.md for slug '{slug}' — study the video first "
                "(the markdown render is written when a study completes)"
            ),
        }
    text = md_path.read_text(encoding="utf-8")

    title = f"Zing breakdown: {slug}"
    try:
        meta = storage.load_breakdown(slug).meta
        if meta.title:
            title = f"Zing breakdown: {meta.title}"
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        pass  # markdown alone is still worth pushing; slug title suffices

    url = helper_url().rstrip("/") + "/notes"
    payload = json.dumps(
        {"text": text, "title": title, "author": "Zing"}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Uoink-Token": _token(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {
                "ok": False,
                "error": (
                    "uoink rejected the push (auth). Set the "
                    f"{UOINK_TOKEN_ENV} env var to uoink's per-install "
                    "token — it lives in token.txt next to uoink's "
                    "server.py — and restart zing serve-mcp."
                ),
            }
        return {
            "ok": False,
            "error": f"uoink answered HTTP {e.code} — is your uoink up to date?",
        }
    except (urllib.error.URLError, OSError, ValueError):
        return {
            "ok": False,
            "error": (
                f"no uoink helper at {helper_url()} — is Uoink running? "
                "Zing works fine without it; this push is optional."
            ),
        }

    if not isinstance(body, dict) or not body.get("ok"):
        error = "unknown error"
        if isinstance(body, dict):
            error = str(body.get("error") or error)
        return {"ok": False, "error": f"uoink declined the note: {error}"}
    return {
        "ok": True,
        "pushed": slug,
        "uoink_slug": body.get("slug", ""),
        "uoink_id": body.get("video_id", ""),
        "title": body.get("title", title),
        "hint": "the breakdown is now a note in your uoink corpus",
    }
