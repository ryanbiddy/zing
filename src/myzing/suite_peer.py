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
from dataclasses import dataclass
from pathlib import Path
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


def _bad(
    code: str, message: str, evidence: str, *, retryable: bool
) -> tuple[dict[str, Any], str]:
    """A not-ok verdict paired with the receipt for it.

    Every failed return in the probe is this shape. Naming it once keeps
    each check's RULE on screen instead of its packaging — the sequence
    of §4 states is the thing a reader needs to follow.
    """
    return _unhealthy(code, message, retryable=retryable), evidence


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


_LEASE_KEYS = {
    "contract", "version", "service_id", "service_version", "api_version",
    "base_url", "health_url", "manifest_url", "capabilities", "ui",
    "pid", "started_at",
}

# The lease is the most attacker-controllable input zing has: a file any
# local process can write, read on every doctor run. A conformant lease
# is well under a kilobyte, so cap the read — `shot_list` already caps
# its (user-CHOSEN, therefore less hostile) import at 2 MiB, and leaving
# this one unbounded was an inconsistency, not a decision.
_LEASE_SIZE_LIMIT = 64 * 1024


def lease_paths(service_id: str) -> list[Path]:
    """The per-user runtime-lease locations from §3.4, in platform order.

    The lease is WRITABLE state: it only says where a resident process
    claims to be. It never grants launch authority and never carries a
    command, token, or path to user content — which is why an unknown
    key invalidates it outright rather than being ignored.
    """
    name = f"{service_id}.json"
    candidates: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "RyanSuite" / "services.d" / name)
    home = Path.home()
    candidates.append(
        home / "Library" / "Application Support" / "RyanSuite" / "services.d" / name
    )
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state) if xdg_state else home / ".local" / "state"
    candidates.append(base / "ryan-suite" / "services.d" / name)
    return candidates


def _pid_is_live(pid: int) -> bool:
    """Delegates to the F-03 liveness primitive rather than growing a
    second copy of the Windows kernel32 dance (its access-denied branch
    is directly pinned on windows CI). Imported lazily: doctor stays
    light until a lease actually exists."""
    from myzing.mcp_server import _pid_alive

    return _pid_alive(pid)


def _is_service_ui_path(value: Any) -> bool:
    """True for one-origin service paths, never URL references."""
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
    ):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return not parsed.scheme and not parsed.netloc


def _ui_defect(value: Any) -> str | None:
    if not isinstance(value, dict) or set(value) != {"home", "routes"}:
        return "ui keys"
    routes = value.get("routes")
    if not isinstance(routes, dict):
        return "ui.routes must be an object"
    if any(not isinstance(name, str) for name in routes):
        return "ui.routes keys must be strings"
    for path in [value.get("home"), *routes.values()]:
        if not _is_service_ui_path(path):
            return (
                f"ui path {path!r} must begin with exactly one / and stay "
                "on the service origin"
            )
    return None


def lease_defect(payload: Any, service_id: str) -> str | None:
    """Exact-shape §3.4 validation. Returns the first defect or None.
    Liveness is checked by the caller so this stays pure and testable
    against Lane C's fixtures."""
    if not isinstance(payload, dict):
        return "lease is not a JSON object"
    if set(payload) != _LEASE_KEYS:
        return f"lease keys {sorted(payload)}"
    if payload.get("contract") != "ryan.suite.runtime-lease":
        return f"contract={payload.get('contract')!r}"
    if payload.get("version") != 1:
        return f"version={payload.get('version')!r}"
    if payload.get("service_id") != service_id:
        return (
            f"lease claims service_id={payload.get('service_id')!r}, "
            f"expected {service_id!r}"
        )
    for field_name in ("base_url", "health_url", "manifest_url"):
        value = payload.get(field_name)
        if not isinstance(value, str):
            return f"{field_name} must be a string"
        defect = _validate_url(value)
        if defect is not None:
            return f"{field_name}: {defect}"
    caps = payload.get("capabilities")
    if not isinstance(caps, list) or any(not isinstance(c, str) for c in caps):
        return "capabilities must be a list of strings"
    if list(caps) != sorted(set(caps)):
        return "capabilities must be sorted and unique"
    ui_defect = _ui_defect(payload.get("ui"))
    if ui_defect is not None:
        return ui_defect
    if not isinstance(payload.get("pid"), int) or payload["pid"] <= 0:
        return "pid must be a positive integer"
    if not isinstance(payload.get("started_at"), str):
        return "started_at must be a string"
    return None


def read_lease(service_id: str) -> tuple[str | None, str | None, str]:
    """Resolve the runtime lease for ``service_id``.

    Returns (base_url, error_code, detail). ``error_code`` is None when
    there is simply no lease (a calm, expected state), ``invalid_lease``
    for a malformed or hostile one (§4: the caller must not follow it),
    or ``stale_lease`` when the shape is valid but its process is gone
    (§4: never silently downgraded to absent).
    """
    for path in lease_paths(service_id):
        try:
            if path.stat().st_size > _LEASE_SIZE_LIMIT:
                return (
                    None,
                    "invalid_lease",
                    f"lease at {path} is larger than "
                    f"{_LEASE_SIZE_LIMIT // 1024} KiB — a conformant lease is "
                    "well under a kilobyte; refusing to read it",
                )
            raw = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue  # absent or unreadable: try the next platform location
        try:
            payload = json.loads(raw)
        except ValueError:
            return None, "invalid_lease", f"lease at {path} is not valid JSON"
        defect = lease_defect(payload, service_id)
        if defect is not None:
            return None, "invalid_lease", f"lease at {path} is invalid: {defect}"
        if not _pid_is_live(payload["pid"]):
            return (
                None,
                "stale_lease",
                f"lease at {path} names pid {payload['pid']}, which is not "
                "running — the service exited without removing it",
            )
        return payload["base_url"], None, f"runtime lease at {path}"
    return None, None, ""


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
    ui_defect = _ui_defect(service.get("ui"))
    if ui_defect is not None:
        return f"service.{ui_defect}"
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


@dataclass
class _Discovery:
    """Where the probe decided to look, and why — or the verdict that
    ended it before any request (§3.3/§4)."""

    base: str = ""
    source: str = ""          # human-readable receipt of WHICH path won
    configured: bool = False  # explicit URL or valid lease: never calm-absent
    failure: tuple[dict[str, Any], str] | None = None


@dataclass(frozen=True)
class UoinkBaseResolution:
    """Validated, network-free result of the suite discovery order."""

    base: str
    source: str
    configured: bool


class UoinkResolutionError(RuntimeError):
    """Named contract failure that must stop discovery without fallback."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        evidence: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.evidence = evidence


def _discover_base() -> _Discovery:
    """§3.3 discovery order: explicit URL, then a valid runtime lease,
    then the default address.

    Credential resolution stays independent and explicit — a lease never
    carries one and we never read the peer's token file (§3.2). A lease
    that is invalid, hostile, or stale ENDS the probe with its own named
    code rather than falling through to the default: §4 forbids
    following it and forbids silently downgrading it to absent.
    """
    explicit = os.environ.get(UOINK_URL_ENV, "").strip()
    if explicit:
        defect = _validate_url(explicit)
        if defect is not None:
            return _Discovery(failure=(
                _unhealthy(
                    "invalid_configuration",
                    f"{UOINK_URL_ENV} is invalid: {defect}",
                    retryable=False,
                ),
                "no probe attempted (invalid explicit URL)",
            ))
        return _Discovery(
            base=explicit.rstrip("/"),
            source=f"{UOINK_URL_ENV}={explicit}",
            configured=True,
        )

    leased, lease_error, lease_detail = read_lease("uoink")
    if lease_error is not None:
        return _Discovery(failure=(
            _unhealthy(
                lease_error,
                lease_detail,
                retryable=lease_error == "stale_lease",
            ),
            lease_detail,
        ))
    if leased:
        return _Discovery(
            base=leased.rstrip("/"), source=lease_detail, configured=True
        )

    return _Discovery(
        base=UOINK_DEFAULT_URL.rstrip("/"),
        source=f"default address {UOINK_DEFAULT_URL}",
        configured=False,
    )


def resolve_uoink_base() -> UoinkBaseResolution:
    """Resolve explicit URL → valid lease → default without network I/O."""
    discovered = _discover_base()
    if discovered.failure is not None:
        peer, evidence = discovered.failure
        error = peer["error"]
        raise UoinkResolutionError(
            str(error["code"]),
            str(error["message"]),
            retryable=bool(error["retryable"]),
            evidence=evidence,
        )
    return UoinkBaseResolution(
        base=discovered.base,
        source=discovered.source,
        configured=discovered.configured,
    )


def probe_uoink() -> tuple[dict[str, Any], str]:
    """Run the §8 probe. Returns (ryan.suite.peer v1 envelope, evidence).

    ``evidence`` is a one-line receipt of what the probe actually read
    (final review P2-5: doctor once printed "manifest verified" for a
    manifest the reviewer could not fetch — every verdict now names
    its evidence so two contradictory runs are distinguishable).
    """
    try:
        discovered = resolve_uoink_base()
    except UoinkResolutionError as error:
        return (
            _unhealthy(
                error.code,
                str(error),
                retryable=error.retryable,
            ),
            error.evidence,
        )
    base, source, configured = discovered.base, discovered.source, discovered.configured

    try:
        status, manifest = _get_json(base + "/.well-known/suite-service.json")
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        # §4: refusal or timeout at the DEFAULT address with no other
        # evidence is calm absence. A configured URL — or a valid current
        # lease — that fails transport is never calm.
        if not configured:
            return _peer("absent"), f"nothing answered at the default {base}"
        if isinstance(e, TimeoutError) or "timed out" in str(e):
            return _bad(
                "timeout",
                f"uoink at {base} timed out",
                "manifest fetch timed out",
                retryable=True,
            )
        return _bad(
            "unavailable",
            f"uoink at {base} refused the connection",
            "manifest fetch refused",
            retryable=True,
        )

    if status != 200 or manifest is None:
        return _bad(
            "contract_mismatch",
            f"no suite manifest at {base} (HTTP {status}) — a service "
            "answered but does not speak INTEGRATION-CONTRACT v1; if this "
            "is uoink, update it",
            f"manifest fetch: HTTP {status}",
            retryable=False,
        )
    defect = _manifest_defect(manifest)
    if defect is not None:
        return _bad(
            "contract_mismatch",
            f"manifest drift: {defect}",
            "manifest fetched but non-conformant",
            retryable=False,
        )

    service = manifest["service"]
    evidence = (
        f"via {source}; manifest read: "
        f"{service['id']} {service['service_version']}"
    )
    if service["id"] != "uoink":
        return _bad(
            "wrong_service",
            f"the endpoint at {base} identifies as "
            f"{service['id']!r}, not uoink",
            evidence,
            retryable=False,
        )
    capabilities = service["capabilities"]
    if _REQUIRED_CAPABILITY not in capabilities:
        return _bad(
            "contract_mismatch",
            f"uoink does not offer {_REQUIRED_CAPABILITY} — update uoink",
            evidence,
            retryable=False,
        )

    try:
        status, health = _get_json(base + service["health"]["href"])
    except (TimeoutError, urllib.error.URLError, OSError):
        return _bad(
            "unavailable",
            "uoink served its manifest but its health endpoint did not answer",
            evidence + "; health: no answer",
            retryable=True,
        )
    if status != 200 or health is None:
        return _bad(
            "contract_mismatch",
            f"health endpoint answered HTTP {status} without a valid body",
            evidence + f"; health: HTTP {status}",
            retryable=False,
        )
    defect = _health_defect(health)
    if defect is not None:
        return _bad(
            "contract_mismatch",
            f"health drift: {defect}",
            evidence + "; health non-conformant",
            retryable=False,
        )
    if health["service_id"] != "uoink":
        return _bad(
            "wrong_service",
            f"health identifies as {health['service_id']!r}, not uoink",
            evidence,
            retryable=False,
        )
    if health["ok"] is not True:
        failed = [
            c["id"] for c in health["checks"]
            if c["required"] and c["status"] == "failed"
        ]
        return _bad(
            "peer_unhealthy",
            "uoink reports required checks failed: "
            + ", ".join(failed) + " — open uoink's own doctor for the fix",
            evidence + "; health read, ok=false",
            retryable=True,
        )

    token = os.environ.get(UOINK_TOKEN_ENV, "").strip()
    if not token:
        # §3.3: a verified manifest without a credential is unconfigured
        # — never an auth attempt with an empty token.
        return _peer("unconfigured"), evidence + "; health ok"
    return _conformance_read(base, token, capabilities, evidence)


def _conformance_read(
    base: str, token: str, capabilities: list[str], evidence: str
) -> tuple[dict[str, Any], str]:
    """§8 step 5: the cheapest read-only credentialed call.

    A nonexistent item id exercises auth AND the media.handoff contract
    at once — any well-formed handoff answer, INCLUDING a not_found
    error envelope, proves both (the contract says internal failures
    carry the same contract metadata, so a 500 with a valid envelope is
    still a conformant peer).
    """
    request = urllib.request.Request(
        base + "/api/corpus/v1/items/zing-doctor-probe/kept-media",
        headers={"X-Uoink-Token": token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        seen = evidence + f"; conformance read: HTTP {e.code}"
        if e.code in (401, 403):
            return _bad(
                "authentication_failed",
                f"uoink rejected the configured {UOINK_TOKEN_ENV} "
                f"(HTTP {e.code})",
                seen,
                retryable=False,
            )
        try:
            body = json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            return _bad(
                "contract_mismatch",
                f"conformance read answered HTTP {e.code} without a "
                "handoff envelope",
                seen,
                retryable=False,
            )
    except (TimeoutError, urllib.error.URLError, OSError):
        return _bad(
            "unavailable",
            "uoink stopped answering during the conformance read",
            evidence + "; conformance read: no answer",
            retryable=True,
        )

    if (
        not isinstance(body, dict)
        or body.get("contract") != "uoink.media.handoff"
        or body.get("version") != 1
    ):
        return _bad(
            "contract_mismatch",
            "the kept-media conformance read did not return a "
            "uoink.media.handoff v1 envelope",
            evidence + "; conformance read non-conformant",
            retryable=False,
        )
    return (
        _peer("available", capabilities),
        evidence + "; health ok; credentialed read ok",
    )
