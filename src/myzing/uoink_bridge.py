"""Optional Uoink bridge: kept media, reference search and breakdown notes.

Optional by design — Zing is fully standalone. When the uoink helper
answers on localhost (explicit ``UOINK_URL``, then its valid runtime lease,
then default ``http://127.0.0.1:5179``), the ``push_to_uoink`` MCP tool
sends ``breakdown.md`` to uoink's ``POST /notes`` intake, where it lands
as a first-class note in the corpus (searchable, queryable over uoink's
own MCP). When uoink is absent, nothing nags: doctor reports it as a calm
optional item and the tool answers honestly if called.

Auth: uoink's local API requires its per-install token in the
``X-Uoink-Token`` header. Zing reads it from the ``UOINK_TOKEN`` env var
and tells the user exactly where uoink keeps it — see ``TOKEN_LOCATION``,
the one place that guidance is written (final review P3-3: "next to
server.py" alone is meaningless to someone who installed the app).

Kept media uses the existing exact-key handoff. Search uses corpus.read/1,
documented in docs/UOINK-MEMORY.md, with its v1 response validated unchanged.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from myzing import storage, suite_peer
from myzing.urls import is_http_url

UOINK_DEFAULT_URL = suite_peer.UOINK_DEFAULT_URL
UOINK_URL_ENV = suite_peer.UOINK_URL_ENV

UOINK_TOKEN_ENV = "UOINK_TOKEN"
_TIMEOUT = 5.0

# INTEGRATION-CONTRACT v1 §6.1 (ratified it#52): the kept-media handoff
# envelope is exact-key — drift is a DISTINCT, named state, never
# flattened into "absent" or a generic failure (§8 doctrine).
_ITEM_REF_PREFIX = "uoink://item/"
_HANDOFF_TOP_KEYS = {"ok", "contract", "version", "operation", "data"}
_HANDOFF_DATA_KEYS = {"item_ref", "state", "source_url", "media", "provenance"}
_HANDOFF_MEDIA_KEYS = {"path", "media_type", "byte_length", "sha256"}
_HANDOFF_PROVENANCE_KEYS = {"kind", "sidecar_schema_version", "field"}
_HANDOFF_ERROR_KEYS = {"ok", "contract", "version", "operation", "error"}
_HANDOFF_MEDIA_TYPES = frozenset({
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/webm",
    "video/x-matroska",
})
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


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
    return suite_peer.resolve_uoink_base().base


def _token() -> str:
    return os.environ.get(UOINK_TOKEN_ENV, "").strip()


def redact(value: str) -> str:
    """Never persist or display credentials echoed by an optional peer."""
    token = _token()
    if token:
        for secret in {token, urllib.parse.quote(token, safe=""), urllib.parse.quote_plus(token),
                       json.dumps(token, ensure_ascii=False)[1:-1], repr(token)[1:-1]}:
            value = value.replace(secret, "[redacted]")
    return value


def credential_safe_url(url: str) -> str:
    if redact(url) != url:
        raise ValueError("Uoink request URL contains a credential; remove it from the URL/input.")
    return url


def _item_id_from_ref(item_ref: Any) -> str | None:
    """Return one canonical Uoink item id, or ``None``.

    Uoink emits an already-percent-encoded path segment. Decode it exactly
    once so the HTTP request can re-encode the underlying opaque id exactly
    once; accepting a raw slash or an encoded slash would identify more than
    one path segment.
    """
    if not isinstance(item_ref, str) or not item_ref.startswith(
        _ITEM_REF_PREFIX
    ):
        return None
    encoded = item_ref[len(_ITEM_REF_PREFIX):]
    try:
        item_id = urllib.parse.unquote(encoded, errors="strict")
    except (TypeError, UnicodeDecodeError):
        return None
    if (
        not item_id
        or len(item_id) > 200
        or "/" in item_id
        or "\\" in item_id
        or urllib.parse.quote(item_id, safe="") != encoded
    ):
        return None
    return item_id


def _err(message: str, **extra: Any) -> dict[str, Any]:
    """The house errors-as-data envelope (uoink house pattern, same shape
    the MCP server returns). Hand-built literals were duplicated 15
    times here before SG-3."""
    return {"ok": False, "error": redact(message),
            **{key: redact(value) if isinstance(value, str) else value for key, value in extra.items()}}


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
    item_ref = data.get("item_ref")
    if (
        not isinstance(item_ref, str)
        or not item_ref.startswith(_ITEM_REF_PREFIX)
        or not item_ref[len(_ITEM_REF_PREFIX):]
    ):
        return f"invalid item_ref {item_ref!r}"
    source_url = data.get("source_url")
    # FF-8 (final review, contract §5): a cross-product source_url is
    # null or HTTP(S) — a file:// or filesystem-shaped value here would
    # turn "refetch from the source" into a local file read.
    if source_url is not None and (
        not is_http_url(source_url)
    ):
        return f"source_url must be null or an HTTP(S) URL, got {source_url!r}"
    media = data.get("media")
    if state == "available":
        if not isinstance(media, dict) or set(media) != _HANDOFF_MEDIA_KEYS:
            return "media keys for state=available"
        media_path = media.get("path")
        if not isinstance(media_path, str) or not (
            PureWindowsPath(media_path).is_absolute()
            or PurePosixPath(media_path).is_absolute()
        ):
            return f"media.path must be absolute, got {media_path!r}"
        media_type = media.get("media_type")
        if media_type not in _HANDOFF_MEDIA_TYPES:
            return f"unsupported media_type {media_type!r}"
        byte_length = media.get("byte_length")
        if (
            isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length < 0
        ):
            return f"invalid byte_length {byte_length!r}"
        sha256 = media.get("sha256")
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            return f"invalid sha256 {sha256!r}"
    elif media is not None:
        return f"state={state} with non-null media"
    provenance = data.get("provenance")
    if (
        not isinstance(provenance, dict)
        or set(provenance) != _HANDOFF_PROVENANCE_KEYS
    ):
        return "provenance keys"
    if (
        provenance.get("kind") != "uoink_sidecar"
        or isinstance(provenance.get("sidecar_schema_version"), bool)
        or not isinstance(provenance.get("sidecar_schema_version"), int)
        or provenance.get("field") != "media_file"
    ):
        return "invalid provenance values"
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
    item_id = _item_id_from_ref(item_ref)
    if item_id is None:
        return _err(
            "item_ref must identify one corpus item like "
            "'uoink://item/short-123' using Uoink's canonical reference "
            "encoding — never a file path"
        )
    token = _token()
    if not token:
        return _err(
            f"no uoink credential configured: set {UOINK_TOKEN_ENV} to "
            f"uoink's per-install token ({TOKEN_LOCATION}). Zing never "
            "reads uoink's token file itself."
        )
    try:
        base = helper_url()
    except suite_peer.UoinkResolutionError as error:
        return _err(
            f"uoink discovery failed: {error.code} — {error}",
            code=error.code,
        )
    url = (
        base.rstrip("/")
        + "/api/corpus/v1/items/"
        + urllib.parse.quote(item_id, safe="")
        + "/kept-media"
    )
    try:
        request = urllib.request.Request(credential_safe_url(url), method="GET")
    except ValueError as error:
        return _err(str(error))
    request.add_unredirected_header("X-Uoink-Token", token)
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
            f"no uoink helper at {base} — is Uoink running? "
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
    if body["data"]["item_ref"] != item_ref:
        return _nonconformant(
            "item_ref does not match the requested item")
    return {"ok": True, "data": body["data"]}


SEARCH_CAPABILITY = "uoink.corpus.read/1"


def search_references(query: str) -> dict[str, Any]:
    """List reference candidates only when the peer advertises this contract."""
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        return _err("Supply a search query of 1 to 500 characters.", code="invalid_query")
    token = _token()
    if not token:
        return _err("Reference search unavailable: configure UOINK_TOKEN, or supply a local file.", code="unconfigured")
    if redact(query) != query:
        # GET search puts the query in the URL; never send a pasted credential.
        return _err("Remove the Uoink credential from the search query.", code="invalid_query")
    try:
        base = credential_safe_url(helper_url())
        status, manifest = suite_peer._get_json(base + "/.well-known/suite-service.json")
        if status != 200 or suite_peer._manifest_defect(manifest) is not None:
            return _err("Reference search unavailable: peer service manifest is nonconformant.", code="contract_mismatch")
        service = manifest["service"]
        if service["id"] != "uoink":
            return _err("Reference search unavailable: endpoint is not Uoink.", code="wrong_service")
        if SEARCH_CAPABILITY not in service["capabilities"]:
            return _err("Reference search unavailable: peer does not advertise uoink.corpus.read/1. Supply a known uoink:<id> or a local file.", code="unsupported_capability")
        # Omit mode, match and search_details: use the peer's default matching
        # and its unchanged v1 shape (forgiving keyword search on Uoink 3.11).
        request = urllib.request.Request(
            credential_safe_url(base + "/api/corpus/v1/search?" + urllib.parse.urlencode(
                {"q": query.strip(), "limit": 20})),
            method="GET",
        )
        request.add_unredirected_header("X-Uoink-Token", token)
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized search response")
        body = json.loads(raw.decode("utf-8"))
    except suite_peer.UoinkResolutionError as error:
        return _err("Reference search unavailable: " + str(error), code=error.code)
    except urllib.error.HTTPError as error:
        code = "unsupported_capability" if error.code in (404, 405, 501) else "peer_error"
        return _err(f"Reference search unavailable (HTTP {error.code}); use a known ID or local file.", code=code)
    except (OSError, ValueError):
        return _err("Reference search unavailable: peer offline or response invalid. Use a known ID or local file.", code="unavailable")
    return parse_search_response(body)


def parse_search_response(body: Any) -> dict[str, Any]:
    """Validate corpus.read/1 search; project items to Zing's stable candidates.

    All wire fields are checked before mapping id -> item_ref and retaining
    title/source_url. Page and descriptive metadata are not returned to callers.
    """
    invalid = _err("Reference search response is not uoink.corpus.read v1 search.",
                   code="contract_mismatch")
    if (not isinstance(body, dict) or set(body) != _HANDOFF_TOP_KEYS
            or body["ok"] is not True or body["contract"] != "uoink.corpus.read"
            or type(body["version"]) is not int or body["version"] != 1
            or body["operation"] != "search"
            or not isinstance(body["data"], dict) or set(body["data"]) != {"items", "page"}):
        return invalid
    items, page = body["data"]["items"], body["data"]["page"]
    if (not isinstance(items, list) or len(items) > 20
            or not isinstance(page, dict)
            or set(page) != {"state", "total", "corpus_total", "limit", "offset"}
            or page["state"] not in ("matches", "no_matches", "empty_corpus")
            or any(type(page[key]) is not int or page[key] < 0
                   for key in ("total", "corpus_total", "limit", "offset"))):
        return invalid
    results = []
    for item in items:
        if not _search_item_valid(item):
            return invalid
        result = {"item_ref": _ITEM_REF_PREFIX + urllib.parse.quote(item["id"], safe=""),
                  "title": item["title"], "source_url": item["source_url"]}
        if (_item_id_from_ref(result["item_ref"]) is None
                or any(isinstance(value, str) and redact(value) != value for value in result.values())):
            return invalid
        results.append(result)
    return {"ok": True, "results": results, "selected": None}


def _search_item_valid(item: Any) -> bool:
    """Mirror corpus_contract.validate_item_ref, including nested exact keys."""
    if (not isinstance(item, dict) or set(item) != {
            "id", "title", "author", "source_type", "platform", "source_url",
            "captured_at", "duration_seconds", "credit", "facets", "preview"}
            or not isinstance(item["id"], str) or not item["id"]
            or not isinstance(item["title"], str)
            or any(item[key] is not None and not isinstance(item[key], str)
                   for key in ("author", "source_type", "platform", "captured_at"))
            or (item["source_url"] is not None and not is_http_url(item["source_url"]))
            or (item["duration_seconds"] is not None
                and type(item["duration_seconds"]) not in (int, float))):
        return False
    credit, facets, preview = item["credit"], item["facets"], item["preview"]
    if (not isinstance(credit, dict) or set(credit) != {"creator", "handle", "source_url"}
            or any(credit[key] is not None and not isinstance(credit[key], str)
                   for key in ("creator", "handle"))
            or (credit["source_url"] is not None and not is_http_url(credit["source_url"]))
            or not isinstance(facets, dict)
            or set(facets) != {"topic", "hook_type", "format", "performance_tier", "length_bucket"}
            or any(value is not None and not isinstance(value, str) for value in facets.values())):
        return False
    return preview is None or (
        isinstance(preview, dict)
        and set(preview) == {"id", "kind", "role", "media_type", "label", "byte_length", "href"}
        and type(preview["byte_length"]) is int and preview["byte_length"] >= 0
        and all(isinstance(preview[key], str) and preview[key]
                for key in ("id", "kind", "role", "media_type", "label", "href"))
    )


_GET_DATA_KEYS = {"item", "content", "attachments"}
# Uoink caps get content at 2 MiB of Markdown but serializes it with
# json.dumps' ASCII escapes: CJK text grows about 2x and control or
# replacement characters up to 6x, so a conformant reply can exceed 4 MiB.
_GET_MAX_BYTES = 16 * 1024 * 1024
_GET_CONTENT_KEYS = {"available", "media_type", "text", "byte_length", "truncated"}
_ATTACHMENT_KEYS = {"id", "kind", "role", "media_type", "label", "byte_length", "href"}


def parse_get_response(body: Any, item_id: str) -> dict[str, Any]:
    """Validate a corpus.read/1 ``get`` envelope; keep only item metadata.

    The item has the same exact-key shape as a search item. Markdown content
    and attachments are validated and dropped: Zing needs the title only.
    """
    invalid = _err("Uoink item response is not uoink.corpus.read v1 get.", code="contract_mismatch")
    if (not isinstance(body, dict) or body.get("contract") != "uoink.corpus.read"
            or type(body.get("version")) is not int or body["version"] != 1 or body.get("operation") != "get"):
        return invalid
    if body.get("ok") is False:
        if set(body) != _HANDOFF_ERROR_KEYS or not isinstance(body["error"], dict):
            return invalid
        return _err(f"Uoink item lookup failed: {body['error'].get('code', '')}", code=str(body["error"].get("code", "")))
    if set(body) != _HANDOFF_TOP_KEYS or body["ok"] is not True:
        return invalid
    data = body["data"]
    if not isinstance(data, dict) or set(data) != _GET_DATA_KEYS:
        return invalid
    item, content, attachments = data["item"], data["content"], data["attachments"]
    if (not _search_item_valid(item) or item["id"] != item_id
            or not isinstance(content, dict) or set(content) != _GET_CONTENT_KEYS
            or not isinstance(attachments, list)
            or any(not isinstance(a, dict) or set(a) != _ATTACHMENT_KEYS for a in attachments)):
        return invalid
    result = {"item_ref": _ITEM_REF_PREFIX + urllib.parse.quote(item["id"], safe=""), "title": item["title"],
              "author": item["author"], "source_url": item["source_url"]}
    if any(isinstance(value, str) and redact(value) != value for value in result.values()):
        return invalid
    return {"ok": True, **result}


def item_metadata(item_ref: str) -> dict[str, Any]:
    """Title/author/source of one corpus item via corpus.read/1 ``get``.

    Same discovery, capability check and token header as reference search;
    GET /api/corpus/v1/items/<id> sends no query or body. Best effort: the
    caller falls back to local titles on any error.
    """
    item_id = _item_id_from_ref(item_ref)
    if item_id is None:
        return _err("item_ref must identify one corpus item.", code="invalid_ref")
    token = _token()
    if not token:
        return _err("Uoink item lookup unavailable: configure UOINK_TOKEN.", code="unconfigured")
    try:
        base = credential_safe_url(helper_url())
        status, manifest = suite_peer._get_json(base + "/.well-known/suite-service.json")
        if status != 200 or suite_peer._manifest_defect(manifest) is not None:
            return _err("Uoink item lookup unavailable: peer service manifest is nonconformant.", code="contract_mismatch")
        service = manifest["service"]
        if service["id"] != "uoink" or SEARCH_CAPABILITY not in service["capabilities"]:
            return _err("Uoink item lookup unavailable: peer does not advertise uoink.corpus.read/1.",
                        code="unsupported_capability")
        request = urllib.request.Request(
            credential_safe_url(base + "/api/corpus/v1/items/" + urllib.parse.quote(item_id, safe="")), method="GET")
        request.add_unredirected_header("X-Uoink-Token", token)
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            raw = response.read(_GET_MAX_BYTES + 1)
        if len(raw) > _GET_MAX_BYTES:
            raise ValueError("oversized item response")
        body = json.loads(raw.decode("utf-8"))
    except suite_peer.UoinkResolutionError as error:
        return _err("Uoink item lookup unavailable: " + str(error), code=error.code)
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except (OSError, ValueError, http.client.HTTPException, RecursionError):
            return _err(f"Uoink item lookup unavailable (HTTP {error.code}).", code="peer_error")
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        # Best effort: a garbled status line, a truncated body or absurdly
        # nested JSON must leave resolution and push to their fallbacks.
        return _err("Uoink item lookup unavailable: peer offline or response invalid.", code="unavailable")
    return parse_get_response(body, item_id)


def _container_title(path) -> str | None:
    """The media container's title tag, when FFmpeg can read one."""
    import shutil
    import subprocess

    if path is None or shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=title", "-of", "json",
                                 str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=15, check=False)
        title = (json.loads(result.stdout or "{}").get("format", {}).get("tags", {}) or {}).get("title")
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    title = " ".join(str(title or "").split())
    return title or None


def note_title(slug: str) -> tuple[str, str]:
    """(best real title, its source) for a pushed breakdown note.

    Order: the Uoink corpus item's title (recorded when the project resolved
    uoink:<id>, else looked up now); the platform title of a URL study; the
    container's title tag; the project name; the file name; the slug.
    """
    try:
        breakdown = storage.load_breakdown(slug)
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return slug, "slug"
    meta, provenance = breakdown.meta, breakdown.provenance or {}
    reference = provenance.get("project_reference") if isinstance(provenance.get("project_reference"), dict) else {}
    if reference.get("title"):
        return str(reference["title"]), "uoink_item"
    value = str(reference.get("reference") or "")
    if value.startswith("uoink:"):
        canonical = value if value.startswith(_ITEM_REF_PREFIX) else _ITEM_REF_PREFIX + urllib.parse.quote(value[6:], safe="")
        looked_up = item_metadata(canonical)
        if looked_up.get("ok") and looked_up.get("title", "").strip():
            return looked_up["title"].strip(), "uoink_item"
    if meta.title and is_http_url(meta.source_url or ""):
        return meta.title, "platform"
    try:
        media = storage.resolve_relpath(slug, meta.media_path) if meta.media_path else None
    except (ValueError, OSError):
        media = None
    tag = _container_title(media)
    if tag:
        return tag, "container"
    if reference.get("project_name"):
        return str(reference["project_name"]), "project"
    if meta.title:
        return meta.title, "filename"
    return slug, "slug"


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

    # A Uoink-kept file is named media.mp4, so its stem is not a title.
    best, title_source = note_title(slug)
    title = f"Zing breakdown: {redact(best)[:200]}"

    try:
        base = helper_url()
    except suite_peer.UoinkResolutionError as error:
        return _err(
            f"uoink discovery failed: {error.code} — {error}",
            code=error.code,
        )
    try:
        url = credential_safe_url(base.rstrip("/") + "/notes")
    except ValueError as error:
        return _err(str(error))
    payload = json.dumps(
        {"text": text, "title": title, "author": "Zing"}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )
    request.add_unredirected_header("X-Uoink-Token", _token())
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
            f"no uoink helper at {base} — is Uoink running? "
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
        "title_source": title_source,
        "hint": "the breakdown is now a note in your uoink corpus",
    }
