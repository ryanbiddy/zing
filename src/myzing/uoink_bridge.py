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
and tells the user exactly where uoink keeps it — see ``TOKEN_LOCATION``,
the one place that guidance is written (final review P3-3: "next to
server.py" alone is meaningless to someone who installed the app).

The full two-way integration (reading saved shorts from the corpus,
profiles/shot-lists back) is the S6 sprint with its own contract doc —
this is deliberately just the one high-value push.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from myzing import storage
from myzing.doctor import UOINK_DEFAULT_URL, UOINK_URL_ENV

UOINK_TOKEN_ENV = "UOINK_TOKEN"
_TIMEOUT = 5.0

# INTEGRATION-CONTRACT v1 §6.1 (ratified it#52): the kept-media handoff
# envelope is exact-key — drift is a DISTINCT, named state, never
# flattened into "absent" or a generic failure (§8 doctrine).
_ITEM_REF_PREFIX = "uoink://item/"
_HANDOFF_TOP_KEYS = {"ok", "contract", "version", "operation", "data"}
_HANDOFF_DATA_KEYS = {"item_ref", "state", "source_url", "media", "provenance"}
_HANDOFF_MEDIA_KEYS = {"path", "media_type", "byte_length", "sha256"}
_HANDOFF_ERROR_KEYS = {"ok", "contract", "version", "operation", "error"}


# Where uoink keeps its per-install token, said ONCE (final review
# P3-3). Doctor learned to name the installed-app path in #220; this
# module kept three copies of the older source-checkout-only wording,
# which is exactly how a fixed finding survives on a second surface.
#
# All THREE locations come from INTEGRATION-CONTRACT §3.2. The first
# version of this constant listed only Windows + source checkout —
# consolidating duplicated wording made it consistent without making
# it complete, and a macOS user would have been handed a Windows path.
TOKEN_LOCATION = (
    "installed app: %LOCALAPPDATA%\\Uoink\\token.txt on Windows, "
    "~/Library/Application Support/Uoink/token.txt on macOS; "
    "source checkout: token.txt next to uoink's server.py"
)


def helper_url() -> str:
    return os.environ.get(UOINK_URL_ENV, "").strip() or UOINK_DEFAULT_URL


def _token() -> str:
    return os.environ.get(UOINK_TOKEN_ENV, "").strip()


def _err(message: str, **extra: Any) -> dict[str, Any]:
    """The house errors-as-data envelope (uoink house pattern, same shape
    the MCP server returns). Hand-built literals were duplicated 15
    times here before SG-3."""
    return {"ok": False, "error": message, **extra}


def _nonconformant(what: str) -> dict[str, Any]:
    return _err(
        f"uoink's kept-media response is not contract-conformant: {what} "
        "(expected uoink.media.handoff v1, exact keys). This is version "
        "drift, not absence — update uoink or zing so both speak "
        "INTEGRATION-CONTRACT v1."
    )


def handoff_error_defect(body: Any) -> str | None:
    """Exact-shape check for a `uoink.media.handoff` v1 ERROR envelope."""
    if set(body) != _HANDOFF_ERROR_KEYS or not isinstance(body.get("error"), dict):
        return f"error envelope keys {sorted(body)}"
    return None


def handoff_defect(body: Any) -> str | None:
    """Exact-shape §6.1 validation of a SUCCESS handoff envelope.

    Pure: returns the first defect or None, mirroring the validator
    pattern `suite_peer` already uses (`lease_defect`,
    `_manifest_defect`, `_health_defect`). Keeping validation separate
    from transport means the contract rules can be exercised directly,
    without a fake HTTP layer standing between the test and the rule.
    """
    if not isinstance(body, dict):
        return "response is not a JSON object"
    if body.get("contract") != "uoink.media.handoff" or body.get("version") != 1:
        return (
            f"contract={body.get('contract')!r} version={body.get('version')!r}"
        )
    if set(body) != _HANDOFF_TOP_KEYS or body.get("operation") != "resolve":
        return f"envelope keys {sorted(body)}"
    data = body["data"]
    if not isinstance(data, dict) or set(data) != _HANDOFF_DATA_KEYS:
        return "data keys " + str(
            sorted(data) if isinstance(data, dict) else type(data).__name__
        )
    state = data.get("state")
    if state not in ("available", "not_kept", "missing"):
        return f"unknown state {state!r}"
    source_url = data.get("source_url")
    # FF-8 (final review, contract §5): a cross-product source_url is
    # null or HTTP(S) — a file:// or filesystem-shaped value here would
    # turn "refetch from the source" into a local file read.
    if source_url is not None and (
        not isinstance(source_url, str)
        or not source_url.lower().startswith(("http://", "https://"))
    ):
        return f"source_url must be null or an HTTP(S) URL, got {source_url!r}"
    media = data.get("media")
    if state == "available":
        if not isinstance(media, dict) or set(media) != _HANDOFF_MEDIA_KEYS:
            return "media keys for state=available"
    elif media is not None:
        return f"state={state} with non-null media"
    return None


def resolve_kept_media(item_ref: str) -> dict[str, Any]:
    """Resolve a uoink item reference to its kept-media handoff.

    INTEGRATION-CONTRACT v1 §6.1: token-gated
    GET /api/corpus/v1/items/<id>/kept-media, exact-key
    ``uoink.media.handoff`` v1 envelope. Returns the house envelope:
    ok:True with the validated contract ``data``, or ok:False with an
    actionable error. Never touches the network without a credential
    (§3.3: no credential means unconfigured, not an auth attempt).
    """
    if not isinstance(item_ref, str) or not item_ref.startswith(_ITEM_REF_PREFIX):
        return _err(
            "item_ref must be a uoink item reference like "
            "'uoink://item/short-123' — never a file path (stable "
            "references only; paths travel inside the handoff)"
        )
    item_id = item_ref[len(_ITEM_REF_PREFIX):]
    if not item_id:
        return _err("item_ref has an empty item id")
    token = _token()
    if not token:
        return _err(
            f"no uoink credential configured: set {UOINK_TOKEN_ENV} to "
            f"uoink's per-install token ({TOKEN_LOCATION}). Zing never "
            "reads uoink's token file itself."
        )
    url = (
        helper_url().rstrip("/")
        + "/api/corpus/v1/items/"
        + urllib.parse.quote(item_id, safe="")
        + "/kept-media"
    )
    request = urllib.request.Request(
        url, headers={"X-Uoink-Token": token}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return _err(
                f"uoink rejected the credential (HTTP {e.code}) — check "
                f"{UOINK_TOKEN_ENV} against uoink's token ({TOKEN_LOCATION})"
            )
        try:
            body = json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            return _err(
                f"uoink answered HTTP {e.code} — is your uoink up to date?"
            )
    except (urllib.error.URLError, OSError, ValueError):
        return _err(
            f"no uoink helper at {helper_url()} — is Uoink running? "
            "Zing works fine without it; kept-media study needs it once."
        )

    if isinstance(body, dict) and body.get("ok") is False:
        # A conformant ERROR envelope is a legitimate answer, not drift —
        # it carries uoink's own stable code, which the caller deserves.
        defect = handoff_error_defect(body)
        if defect is not None:
            return _nonconformant(defect)
        err = body["error"]
        code = str(err.get("code", ""))
        message = str(err.get("message", ""))
        return _err(
            f"uoink could not resolve {item_ref}: {code} — {message}",
            code=code,
        )
    defect = handoff_defect(body)
    if defect is not None:
        return _nonconformant(defect)
    return {"ok": True, "data": body["data"]}


def push_breakdown(slug: str) -> dict[str, Any]:
    """Send a slug's breakdown.md to uoink as a note.

    Returns the uoink house envelope: {"ok": True, ...} or
    {"ok": False, "error": actionable}.
    """
    try:
        storage.validate_slug(slug)  # F-02: slugs are caller input, never paths
    except storage.SlugError as e:
        return _err(f"invalid slug: {e} — use a slug from list_breakdowns()")
    md_path = storage.breakdown_dir(slug) / "breakdown.md"
    if not md_path.is_file():
        return _err(
            f"no breakdown.md for slug '{slug}' — study the video first "
            "(the markdown render is written when a study completes)"
        )
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
            return _err(
                f"uoink rejected the push (auth). Set the {UOINK_TOKEN_ENV} "
                f"env var to uoink's per-install token ({TOKEN_LOCATION}) "
                "and restart zing serve-mcp."
            )
        return _err(
            f"uoink answered HTTP {e.code} — is your uoink up to date?"
        )
    except (urllib.error.URLError, OSError, ValueError):
        return _err(
            f"no uoink helper at {helper_url()} — is Uoink running? "
            "Zing works fine without it; this push is optional."
        )

    if not isinstance(body, dict) or not body.get("ok"):
        error = "unknown error"
        if isinstance(body, dict):
            error = str(body.get("error") or error)
        return _err(f"uoink declined the note: {error}")
    return {
        "ok": True,
        "pushed": slug,
        "uoink_slug": body.get("slug", ""),
        "uoink_id": body.get("video_id", ""),
        "title": body.get("title", title),
        "hint": "the breakdown is now a note in your uoink corpus",
    }
