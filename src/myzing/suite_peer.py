"""Contract-aware uoink peer probe (INTEGRATION-CONTRACT v1 §8, B-S6).

Replaces the ambiguity the contract names in this very repo: the old
check probed uoink's bare root and called any HTTP status below 500
"reachable". This probe walks the §8 order — explicit config validation,
exact-key ``ryan.suite.service`` v1 manifest, identity + capability
check, exact-key ``ryan.suite.health`` v1, one cheapest credentialed
conformance read — and normalizes every outcome to the ``ryan.suite.peer``
v1 envelope with the contract's stable error codes.

Doctrine (§4/§8, binding):

- ``absent`` and ``unconfigured`` are CALM states — never failures.
- ``unhealthy`` names its code; drift is never flattened into "not
  running" and a wrong identity is never reported as absence.
- An explicit invalid URL is ``invalid_configuration`` — no silent
  fall-through to the default address.
- The probe never starts, repairs, or reconfigures the peer.

Stdlib-only: doctor imports this before anything else is installed.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

UOINK_URL_ENV = "UOINK_URL"
UOINK_TOKEN_ENV = "UOINK_TOKEN"
UOINK_DEFAULT_URL = "http://127.0.0.1:5179"
_TIMEOUT = 3.0

PEER_CONTRACT = "ryan.suite.peer"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SERVICE_KEYS = {"ok", "contract", "version", "service"}
_SERVICE_INNER_KEYS = {
    "id", "name", "service_version", "api_version", "resident",
    "default_port", "health", "capabilities", "ui", "mcp",
}
_HEALTH_REF_KEYS = {"contract", "version", "href"}
_MCP_KEYS = {"name", "transport"}
_UI_KEYS = {"home", "routes"}
_HEALTH_KEYS = {
    "ok", "contract", "version", "service_id", "service_version",
    "state", "checks",
}
_CHECK_KEYS = {"id", "required", "status"}
_HEALTH_STATES = {"ready", "ready_with_limits", "needs_attention"}
_CHECK_STATUSES = {"ready", "busy", "degraded", "failed"}
_REQUIRED_UOINK_CHECKS = {"core", "index", "corpus_paths"}
_REQUIRED_CAPABILITY = "uoink.media.handoff/1"


def _peer(state: str, capabilities: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "contract": PEER_CONTRACT,
        "version": 1,
        "peer": "uoink",
        "state": state,
        "capabilities": capabilities or [],
    }


def _unhealthy(code: str, message: str, retryable: bool) -> dict[str, Any]:
    return {
        "ok": False,
        "contract": PEER_CONTRACT,
        "version": 1,
        "peer": "uoink",
        "state": "unhealthy",
        "error": {"code": code, "message": message, "retryable": retryable},
    }


def _validate_url(url: str) -> str | None:
    """§3.3: loopback only, explicit port, no userinfo/query/fragment.
    Returns a defect description or None."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"scheme must be http(s), got {parts.scheme!r}"
    if parts.username or parts.password:
        return "userinfo is not allowed in a peer URL"
    if parts.query or parts.fragment:
        return "query and fragment are not allowed in a peer URL"
    if parts.hostname not in _LOOPBACK_HOSTS:
        return f"host must be loopback ({', '.join(sorted(_LOOPBACK_HOSTS))})"
    try:
        if parts.port is None:
            return "an explicit port is required"
    except ValueError:
        return "port is not a valid number"
    return None


def _get_json(url: str) -> tuple[int, Any]:
    """(status, parsed body). Raises urllib/OS errors for transport
    failures; a non-2xx HTTP status is returned, not raised."""
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            return e.code, None


def _manifest_defect(body: Any) -> str | None:
    """Exact-key ryan.suite.service v1 validation (§3.5). Returns the
    first drift description, or None for a conformant uoink manifest.
    Wrong identity is reported separately by the caller."""
    if not isinstance(body, dict):
        return "manifest is not a JSON object"
    if set(body) != _SERVICE_KEYS:
        return f"manifest keys {sorted(body)}"
    if body.get("contract") != "ryan.suite.service" or body.get("version") != 1:
        return (
            f"manifest contract={body.get('contract')!r} "
            f"version={body.get('version')!r}"
        )
    if body.get("ok") is not True:
        return "manifest ok is not true"
    service = body.get("service")
    if not isinstance(service, dict) or set(service) != _SERVICE_INNER_KEYS:
        return "service keys " + str(
            sorted(service) if isinstance(service, dict) else type(service).__name__
        )
    health = service.get("health")
    if not isinstance(health, dict) or set(health) != _HEALTH_REF_KEYS:
        return "service.health keys"
    if health.get("contract") != "ryan.suite.health" or health.get("version") != 1:
        return "service.health contract/version"
    if not isinstance(health.get("href"), str) or not health["href"].startswith("/"):
        return "service.health.href must be an absolute path"
    if not isinstance(service.get("mcp"), dict) or set(service["mcp"]) != _MCP_KEYS:
        return "service.mcp keys (a manifest must publish no launcher)"
    if not isinstance(service.get("ui"), dict) or set(service["ui"]) != _UI_KEYS:
        return "service.ui keys"
    caps = service.get("capabilities")
    if not isinstance(caps, list) or any(not isinstance(c, str) for c in caps):
        return "service.capabilities must be a list of strings"
    return None


def _health_defect(body: Any) -> str | None:
    """Exact-key ryan.suite.health v1 validation (§3.6)."""
    if not isinstance(body, dict):
        return "health is not a JSON object"
    if set(body) != _HEALTH_KEYS:
        return f"health keys {sorted(body)}"
    if body.get("contract") != "ryan.suite.health" or body.get("version") != 1:
        return "health contract/version"
    if body.get("state") not in _HEALTH_STATES:
        return f"unknown health state {body.get('state')!r}"
    checks = body.get("checks")
    if not isinstance(checks, list) or not checks:
        return "health.checks must be a non-empty list"
    seen = set()
    for item in checks:
        if not isinstance(item, dict) or set(item) != _CHECK_KEYS:
            return "health check item keys"
        if item.get("status") not in _CHECK_STATUSES:
            return f"unknown check status {item.get('status')!r}"
        if not isinstance(item.get("required"), bool):
            return "check.required must be a boolean"
        seen.add(item.get("id"))
    missing = _REQUIRED_UOINK_CHECKS - seen
    if missing:
        return f"required uoink checks missing: {sorted(missing)}"
    required_failed = any(
        item["required"] and item["status"] == "failed" for item in checks
    )
    if body.get("ok") is not (not required_failed):
        return "health.ok is inconsistent with its required checks"
    return None


def probe_uoink() -> dict[str, Any]:
    """Run the §8 probe and return the ryan.suite.peer v1 envelope."""
    explicit = os.environ.get(UOINK_URL_ENV, "").strip()
    base = explicit or UOINK_DEFAULT_URL
    defect = _validate_url(base)
    if defect is not None:
        return _unhealthy(
            "invalid_configuration",
            f"{UOINK_URL_ENV} is invalid: {defect}",
            retryable=False,
        )
    base = base.rstrip("/")

    try:
        status, manifest = _get_json(base + "/.well-known/suite-service.json")
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        is_timeout = isinstance(e, TimeoutError) or "timed out" in str(e)
        if explicit:
            # A configured peer that fails transport is never calm.
            if is_timeout:
                return _unhealthy(
                    "timeout", f"uoink at {base} timed out", retryable=True
                )
            return _unhealthy(
                "unavailable",
                f"uoink at {base} refused the connection",
                retryable=True,
            )
        # §4: refusal or timeout at the DEFAULT address with no other
        # evidence is calm absence.
        return _peer("absent")
    if status != 200 or manifest is None:
        return _unhealthy(
            "contract_mismatch",
            f"no suite manifest at {base} (HTTP {status}) — a service "
            "answered but does not speak INTEGRATION-CONTRACT v1; if this "
            "is uoink, update it",
            retryable=False,
        )
    defect = _manifest_defect(manifest)
    if defect is not None:
        return _unhealthy(
            "contract_mismatch", f"manifest drift: {defect}", retryable=False
        )
    service = manifest["service"]
    if service["id"] != "uoink":
        return _unhealthy(
            "wrong_service",
            f"the endpoint at {base} identifies as "
            f"{service['id']!r}, not uoink",
            retryable=False,
        )
    capabilities = service["capabilities"]
    if _REQUIRED_CAPABILITY not in capabilities:
        return _unhealthy(
            "contract_mismatch",
            f"uoink does not offer {_REQUIRED_CAPABILITY} — update uoink",
            retryable=False,
        )

    try:
        status, health = _get_json(base + service["health"]["href"])
    except (TimeoutError, urllib.error.URLError, OSError):
        return _unhealthy(
            "unavailable",
            "uoink served its manifest but its health endpoint did not answer",
            retryable=True,
        )
    if status != 200 or health is None:
        return _unhealthy(
            "contract_mismatch",
            f"health endpoint answered HTTP {status} without a valid body",
            retryable=False,
        )
    defect = _health_defect(health)
    if defect is not None:
        return _unhealthy(
            "contract_mismatch", f"health drift: {defect}", retryable=False
        )
    if health["service_id"] != "uoink":
        return _unhealthy(
            "wrong_service",
            f"health identifies as {health['service_id']!r}, not uoink",
            retryable=False,
        )
    if health["ok"] is not True:
        failed = [
            c["id"] for c in health["checks"]
            if c["required"] and c["status"] == "failed"
        ]
        return _unhealthy(
            "peer_unhealthy",
            "uoink reports required checks failed: "
            + ", ".join(failed) + " — open uoink's own doctor for the fix",
            retryable=True,
        )

    token = os.environ.get(UOINK_TOKEN_ENV, "").strip()
    if not token:
        # §3.3: a verified manifest without a credential is unconfigured
        # — never an auth attempt with an empty token.
        return _peer("unconfigured")

    # §8 step 5: cheapest read-only conformance call with the credential.
    # A nonexistent item id exercises auth + the media.handoff contract:
    # any well-formed handoff answer (including not_found) proves both.
    request = urllib.request.Request(
        base + "/api/corpus/v1/items/zing-doctor-probe/kept-media",
        headers={"X-Uoink-Token": token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return _unhealthy(
                "authentication_failed",
                f"uoink rejected the configured {UOINK_TOKEN_ENV} "
                f"(HTTP {e.code})",
                retryable=False,
            )
        try:
            body = json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            return _unhealthy(
                "contract_mismatch",
                f"conformance read answered HTTP {e.code} without a "
                "handoff envelope",
                retryable=False,
            )
    except (TimeoutError, urllib.error.URLError, OSError):
        return _unhealthy(
            "unavailable",
            "uoink stopped answering during the conformance read",
            retryable=True,
        )
    if (
        not isinstance(body, dict)
        or body.get("contract") != "uoink.media.handoff"
        or body.get("version") != 1
    ):
        return _unhealthy(
            "contract_mismatch",
            "the kept-media conformance read did not return a "
            "uoink.media.handoff v1 envelope",
            retryable=False,
        )
    return _peer("available", capabilities)
