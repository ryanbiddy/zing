"""Contract-aware uoink peer probe (B-S6, INTEGRATION-CONTRACT v1 §8).

Same integration-truth pattern as the shot-list import: my exact-key
manifest/health validation is proven against Lane C's checked-in
service/health fixtures, and every peer envelope the probe emits runs
through Lane C's own contract validator.
"""

from __future__ import annotations

import json
import os
import urllib.error
from pathlib import Path

import pytest

from conftest import FakeHTTPResponse
from myzing import doctor, suite_peer
from tools.eval.suite_contracts import validate_contract_payload

FIXDIR = Path(__file__).resolve().parents[1] / "tools" / "eval" / "fixtures" / "suite_v1"


def fixture_cases(name):
    data = json.loads((FIXDIR / name).read_text(encoding="utf-8"))
    out = []
    for case in data["cases"]:
        if "payload" not in case:
            continue
        out.append(case)
    return out


def make_manifest(**service_overrides):
    service = {
        "id": "uoink",
        "name": "Uoink",
        "service_version": "3.6.0",
        "api_version": 1,
        "resident": True,
        "default_port": 5179,
        "health": {
            "contract": "ryan.suite.health",
            "version": 1,
            "href": "/api/suite/v1/health",
        },
        "capabilities": [
            "uoink.corpus.read/1",
            "uoink.engagement.ingest/1",
            "uoink.media.handoff/1",
        ],
        "ui": {"home": "/dashboard", "routes": {}},
        "mcp": {"name": "uoink", "transport": "stdio"},
    }
    service.update(service_overrides)
    return {
        "ok": True,
        "contract": "ryan.suite.service",
        "version": 1,
        "service": service,
    }


def make_health(**overrides):
    body = {
        "ok": True,
        "contract": "ryan.suite.health",
        "version": 1,
        "service_id": "uoink",
        "service_version": "3.6.0",
        "state": "ready",
        "checks": [
            {"id": "core", "required": True, "status": "ready"},
            {"id": "index", "required": True, "status": "ready"},
            {"id": "corpus_paths", "required": True, "status": "ready"},
        ],
    }
    body.update(overrides)
    return body


class FakeUoink:
    """Serves manifest/health/kept-media per configured behavior."""

    def __init__(self, manifest=None, health=None, handoff_status=None):
        self.manifest = manifest if manifest is not None else make_manifest()
        self.health = health if health is not None else make_health()
        self.handoff_status = handoff_status  # None => contract not_found body
        self.tokens_seen = []

    def __call__(self, request, timeout=0):
        import io

        url = request if isinstance(request, str) else request.full_url
        if "/.well-known/suite-service.json" in url:
            body = self.manifest
        elif "/api/suite/v1/health" in url:
            body = self.health
        elif "/kept-media" in url:
            self.tokens_seen.append(request.get_header("X-uoink-token"))
            if self.handoff_status in (401, 403):
                raise urllib.error.HTTPError(url, self.handoff_status, "no", {}, io.BytesIO())
            body = {
                "ok": False,
                "contract": "uoink.media.handoff",
                "version": 1,
                "operation": "resolve",
                "error": {"code": "not_found", "message": "nope", "retryable": False},
            }
        else:
            raise AssertionError(f"unexpected probe URL: {url}")

        return FakeHTTPResponse(json.dumps(body).encode("utf-8"))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(suite_peer.UOINK_URL_ENV, raising=False)
    monkeypatch.delenv(suite_peer.UOINK_TOKEN_ENV, raising=False)
    doctor._peer_cache.clear()
    yield
    doctor._peer_cache.clear()


def peer_is_valid(envelope):
    return validate_contract_payload(
        "ryan.suite.peer/1", envelope, expected_peer="uoink"
    )["issues"] == []


# -- classification matrix ----------------------------------------------------

def test_refusal_at_default_is_calm_absent(monkeypatch):
    def refuse(request, timeout=0):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", refuse)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "absent" and peer["ok"] is True
    assert peer_is_valid(peer)


def test_refusal_at_explicit_url_is_unhealthy_not_absent(monkeypatch):
    monkeypatch.setenv(suite_peer.UOINK_URL_ENV, "http://127.0.0.1:6001")

    def refuse(request, timeout=0):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", refuse)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "unhealthy"
    assert peer["error"]["code"] == "unavailable"
    assert peer["error"]["retryable"] is True
    assert peer_is_valid(peer)


@pytest.mark.parametrize("url,why", [
    ("http://example.com:5179", "loopback"),
    ("http://127.0.0.1", "port"),
    ("http://user:pw@127.0.0.1:5179", "userinfo"),
    ("http://127.0.0.1:5179/x?q=1", "query"),
    ("ftp://127.0.0.1:5179", "scheme"),
])
def test_invalid_explicit_url_never_falls_through(monkeypatch, url, why):
    monkeypatch.setenv(suite_peer.UOINK_URL_ENV, url)
    calls = {"n": 0}
    monkeypatch.setattr(
        suite_peer.urllib.request, "urlopen",
        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1),
    )
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "invalid_configuration"
    assert calls["n"] == 0  # §3.3: no silent fall-through to a default
    assert peer_is_valid(peer)


def test_answering_service_without_manifest_is_drift_not_absence(monkeypatch):
    def not_found(request, timeout=0):
        import io

        raise urllib.error.HTTPError(
            request.full_url, 404, "nf", {}, io.BytesIO(b"not json")
        )

    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", not_found)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "unhealthy"
    assert peer["error"]["code"] == "contract_mismatch"
    assert "update" in peer["error"]["message"]
    assert peer_is_valid(peer)


def test_wrong_identity_is_named(monkeypatch):
    fake = FakeUoink(manifest=make_manifest(id="writer", name="Writer"))
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", fake)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "wrong_service"
    assert peer_is_valid(peer)


def test_missing_required_capability_is_drift(monkeypatch):
    fake = FakeUoink(
        manifest=make_manifest(capabilities=["uoink.corpus.read/1"])
    )
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", fake)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "contract_mismatch"
    assert "uoink.media.handoff/1" in peer["error"]["message"]


def test_failed_required_health_check_is_peer_unhealthy(monkeypatch):
    health = make_health(
        ok=False,
        state="needs_attention",
        checks=[
            {"id": "core", "required": True, "status": "ready"},
            {"id": "index", "required": True, "status": "failed"},
            {"id": "corpus_paths", "required": True, "status": "ready"},
        ],
    )
    fake = FakeUoink(health=health)
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", fake)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "peer_unhealthy"
    assert "index" in peer["error"]["message"]
    assert peer["error"]["retryable"] is True


def test_verified_manifest_without_token_is_unconfigured(monkeypatch):
    fake = FakeUoink()
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", fake)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "unconfigured" and peer["ok"] is True
    assert fake.tokens_seen == []  # never an auth attempt with no token
    assert peer_is_valid(peer)


def test_available_after_credentialed_conformance_read(monkeypatch):
    monkeypatch.setenv(suite_peer.UOINK_TOKEN_ENV, "tok")
    fake = FakeUoink()
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", fake)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "available"
    assert "uoink.media.handoff/1" in peer["capabilities"]
    assert fake.tokens_seen == ["tok"]
    assert peer_is_valid(peer)


def test_rejected_credential_is_authentication_failed(monkeypatch):
    monkeypatch.setenv(suite_peer.UOINK_TOKEN_ENV, "bad")
    fake = FakeUoink(handoff_status=401)
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", fake)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "authentication_failed"
    assert peer["error"]["retryable"] is False
    assert peer_is_valid(peer)


# -- fixture parity with Lane C's validators ----------------------------------

@pytest.mark.parametrize(
    "case", fixture_cases("service.json"), ids=lambda c: c["id"]
)
def test_manifest_validation_agrees_with_lane_c(case):
    defect = suite_peer._manifest_defect(case["payload"])
    if case["expected_valid"] and case["payload"]["service"]["id"] == "uoink":
        assert defect is None, defect
    elif not case["expected_valid"]:
        assert defect is not None
    # valid_writer: a conformant manifest for another service — my
    # exact-key pass accepts it; identity is checked separately.


@pytest.mark.parametrize(
    "case", fixture_cases("health.json"), ids=lambda c: c["id"]
)
def test_health_validation_agrees_with_lane_c(case):
    defect = suite_peer._health_defect(case["payload"])
    if case["expected_valid"] and case["payload"].get("service_id") == "uoink":
        assert defect is None, defect
    elif not case["expected_valid"]:
        assert defect is not None


# -- doctor integration -------------------------------------------------------

def test_doctor_maps_states_and_never_flattens(monkeypatch):
    for state, ok, mark in (
        ("absent", False, ""),
        ("unconfigured", False, "unconfig"),
        ("available", True, ""),
    ):
        doctor._peer_cache.clear()
        peer = {
            "ok": True, "contract": "ryan.suite.peer", "version": 1,
            "peer": "uoink", "state": state,
            "capabilities": ["uoink.media.handoff/1"] if state == "available" else [],
        }
        monkeypatch.setattr(suite_peer, "probe_uoink", lambda p=peer: (p, "faked"))
        check = doctor.check_uoink()
        assert (check.ok, check.mark) == (ok, mark), state
        assert check.data["peer"]["state"] == state

    doctor._peer_cache.clear()
    unhealthy = {
        "ok": False, "contract": "ryan.suite.peer", "version": 1,
        "peer": "uoink", "state": "unhealthy",
        "error": {"code": "contract_mismatch", "message": "drift", "retryable": False},
    }
    monkeypatch.setattr(suite_peer, "probe_uoink", lambda: (unhealthy, "faked"))
    check = doctor.check_uoink()
    assert check.ok is False and check.mark == "unhealthy"
    assert "contract_mismatch" in check.detail
    assert "standalone" not in check.detail  # drift never reads as absence


def test_doctor_probe_is_cached_60s(monkeypatch):
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return ({
            "ok": True, "contract": "ryan.suite.peer", "version": 1,
            "peer": "uoink", "state": "absent", "capabilities": [],
        }, "faked")

    monkeypatch.setattr(suite_peer, "probe_uoink", counting)
    doctor.check_uoink()
    doctor.check_uoink()
    doctor.check_uoink()
    assert calls["n"] == 1  # §4 cadence: at most one probe per 60s


# -- FF-9 / P2-5: verdicts carry their evidence -------------------------------

def test_unconfigured_verdict_names_what_the_manifest_said(monkeypatch):
    """Final review P2-5: doctor printed "manifest verified" for a
    manifest the reviewer could not fetch. Every peer verdict now names
    its evidence — a false "verified" claim requires a false receipt."""
    fake = FakeUoink()
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", fake)
    check = doctor.check_uoink()
    assert check.mark == "unconfig"
    assert "manifest read: uoink 3.6.0" in check.detail
    # B-CONF1: evidence now also names WHICH discovery path was used, so
    # "manifest verified" can never be read without knowing where from.
    assert "manifest read: uoink 3.6.0" in check.data["evidence"]
    assert check.data["evidence"].startswith("via default address")
    # P3-3: the fix names the installed-app token location, not server.py
    # internals only.
    from myzing.uoink_bridge import TOKEN_LOCATION

    assert TOKEN_LOCATION in check.fix


def test_unhealthy_verdict_names_probe_evidence(monkeypatch):
    def forbidden(request, timeout=0):
        import io

        raise urllib.error.HTTPError(
            request.full_url, 403, "no", {}, io.BytesIO(b"{}")
        )

    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", forbidden)
    check = doctor.check_uoink()
    assert check.mark == "unhealthy"
    assert "probe evidence: manifest fetch: HTTP 403" in check.detail


# -- SG-2: validator drift matrix + conformance-read tails --------------------

def _mut_manifest(**kw):
    m = make_manifest()
    m.update(kw)
    return m


@pytest.mark.parametrize("body,why", [
    ("not a dict", "not a JSON object"),
    ({**make_manifest(), "extra": 1}, "keys"),
    (_mut_manifest(contract="wrong.name"), "contract"),
    (_mut_manifest(version=2), "version"),
    (_mut_manifest(ok=False), "ok"),
], ids=["nondict", "extrakey", "contract", "version", "ok"])
def test_manifest_defects_top_level(body, why):
    assert suite_peer._manifest_defect(body) is not None


@pytest.mark.parametrize("service_patch", [
    {"health": {"contract": "wrong", "version": 1, "href": "/h"}},
    {"health": {"contract": "ryan.suite.health", "version": 1, "href": "relative"}},
    {"health": {"contract": "ryan.suite.health", "version": 1}},
    {"mcp": {"name": "uoink", "transport": "stdio", "command": "evil.exe"}},
    {"ui": {"home": "/"}},
    {"capabilities": "not-a-list"},
    {"capabilities": [1, 2]},
], ids=["href-contract", "href-relative", "href-missing", "mcp-launcher",
        "ui-keys", "caps-str", "caps-ints"])
def test_manifest_defects_service_level(service_patch):
    assert suite_peer._manifest_defect(make_manifest(**service_patch)) is not None


@pytest.mark.parametrize("patch", [
    {"contract": "wrong"},
    {"state": "sideways"},
    {"checks": []},
    {"checks": [{"id": "core", "required": True}]},
    {"checks": [{"id": "core", "required": True, "status": "meh"}]},
    {"checks": [{"id": "core", "required": "yes", "status": "ready"}]},
    {"checks": [{"id": "core", "required": True, "status": "ready"},
                {"id": "index", "required": True, "status": "ready"}]},
    {"ok": False},
], ids=["contract", "state", "empty", "item-keys", "status", "required-type",
        "missing-required-id", "ok-inconsistent"])
def test_health_defects(patch):
    assert suite_peer._health_defect(make_health(**patch)) is not None


def test_health_not_a_dict():
    assert suite_peer._health_defect([1, 2]) is not None


def test_invalid_port_in_explicit_url(monkeypatch):
    monkeypatch.setenv(suite_peer.UOINK_URL_ENV, "http://127.0.0.1:notaport")
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "invalid_configuration"
    assert "port" in peer["error"]["message"]


class ConformanceFails(FakeUoink):
    """Manifest + health fine; the credentialed read fails per mode."""

    def __init__(self, mode):
        super().__init__()
        self.mode = mode

    def __call__(self, request, timeout=0):
        import io

        url = request if isinstance(request, str) else request.full_url
        if "/kept-media" not in url:
            return super().__call__(request, timeout)
        if self.mode == "http500-nonjson":
            raise urllib.error.HTTPError(url, 500, "boom", {}, io.BytesIO(b"<html>"))
        if self.mode == "http500-envelope":
            body = json.dumps({
                "ok": False, "contract": "uoink.media.handoff", "version": 1,
                "operation": "resolve",
                "error": {"code": "unavailable", "message": "internal",
                          "retryable": True},
            }).encode()
            raise urllib.error.HTTPError(url, 500, "boom", {}, io.BytesIO(body))
        if self.mode == "dies":
            raise urllib.error.URLError("reset")
        if self.mode == "not-handoff":
            return FakeHTTPResponse(json.dumps({"hello": "world"}).encode())
        raise AssertionError(self.mode)


def test_conformance_read_nonjson_500_is_drift(monkeypatch):
    monkeypatch.setenv(suite_peer.UOINK_TOKEN_ENV, "tok")
    monkeypatch.setattr(
        suite_peer.urllib.request, "urlopen", ConformanceFails("http500-nonjson")
    )
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "contract_mismatch"
    assert "conformance read: HTTP 500" in evidence


def test_conformance_read_500_with_valid_envelope_is_available(monkeypatch):
    """A well-formed handoff ERROR envelope on HTTP 500 proves both auth
    and contract — the contract's own rule ('internal failures use the
    same contract metadata'). The peer is available, not unhealthy."""
    monkeypatch.setenv(suite_peer.UOINK_TOKEN_ENV, "tok")
    monkeypatch.setattr(
        suite_peer.urllib.request, "urlopen", ConformanceFails("http500-envelope")
    )
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "available"


def test_conformance_read_network_death_is_unavailable(monkeypatch):
    monkeypatch.setenv(suite_peer.UOINK_TOKEN_ENV, "tok")
    monkeypatch.setattr(
        suite_peer.urllib.request, "urlopen", ConformanceFails("dies")
    )
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "unavailable"
    assert "stopped answering" in peer["error"]["message"]


def test_conformance_read_wrong_shape_is_drift(monkeypatch):
    monkeypatch.setenv(suite_peer.UOINK_TOKEN_ENV, "tok")
    monkeypatch.setattr(
        suite_peer.urllib.request, "urlopen", ConformanceFails("not-handoff")
    )
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "contract_mismatch"
    assert "handoff" in peer["error"]["message"]


# -- cross-product claim, made falsifiable (2026-07-20) -----------------------

class TokenGatingUoink(FakeUoink):
    """A peer that requires a credential for the manifest — i.e. one that
    does NOT serve it 'public' as §3.5 requires. Would accept the token
    if we sent one; we do not, because §3.3 forbids requiring a
    credential to DISCOVER a service."""

    def __call__(self, request, timeout=0):
        import io

        url = request if isinstance(request, str) else request.full_url
        if "/.well-known/suite-service.json" in url:
            if not request.get_header("X-uoink-token"):
                raise urllib.error.HTTPError(
                    url, 403, "forbidden", {},
                    io.BytesIO(b'{"ok": false, "error": "missing or invalid token"}'),
                )
        return super().__call__(request, timeout)


def test_token_gated_manifest_is_reported_as_drift_even_with_a_token(monkeypatch):
    """Demonstrates the cross-product observation routed to uoink instead
    of merely asserting it: a peer that token-gates its manifest is
    reported contract_mismatch by zing EVEN WHEN UOINK_TOKEN is set,
    because the discovery fetch deliberately carries no credential. If
    the rebuilt uoink token-gates the manifest, this is the false
    negative its users would see — the peer is healthy, zing says drift.
    Failing this test would disprove the claim; it does not."""
    monkeypatch.setenv(suite_peer.UOINK_TOKEN_ENV, "a-perfectly-good-token")
    monkeypatch.setattr(
        suite_peer.urllib.request, "urlopen", TokenGatingUoink()
    )
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "unhealthy"
    assert peer["error"]["code"] == "contract_mismatch"
    assert "manifest fetch: HTTP 403" in evidence
    assert peer_is_valid(peer)


def test_public_manifest_peer_is_available_with_the_same_token(monkeypatch):
    """The control: identical peer, manifest served publicly per §3.5 —
    zing reaches 'available'. The ONLY difference is the gating, which
    isolates the cause to uoink's side, not zing's."""
    monkeypatch.setenv(suite_peer.UOINK_TOKEN_ENV, "a-perfectly-good-token")
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", FakeUoink())
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "available"


# -- B-CONF1: runtime-lease consumption (§3.3 discovery order, §3.4) ---------

def valid_lease(**overrides):
    lease = {
        "contract": "ryan.suite.runtime-lease",
        "version": 1,
        "service_id": "uoink",
        "service_version": "3.6.0",
        "api_version": 1,
        "base_url": "http://127.0.0.1:5999",
        "health_url": "http://127.0.0.1:5999/api/suite/v1/health",
        "manifest_url": "http://127.0.0.1:5999/.well-known/suite-service.json",
        "capabilities": [
            "uoink.corpus.read/1",
            "uoink.engagement.ingest/1",
            "uoink.media.handoff/1",
        ],
        "ui": {"home": "/dashboard", "routes": {"library": "/dashboard#library"}},
        # Must be alive on EVERY platform: the test process itself. The
        # first draft used pid 4 (Windows' System process) — alive there,
        # absent on macOS/Linux, so the lease read as stale and two tests
        # failed on two platforms. Cross-platform tests need a
        # cross-platform liveness fact.
        "pid": os.getpid(),
        "started_at": "2026-07-19T12:00:00Z",
    }
    lease.update(overrides)
    return lease


@pytest.fixture
def lease_dir(tmp_path, monkeypatch):
    """Point every platform lease location at a temp dir so the suite can
    never read (or be fooled by) a real one on the host."""
    d = tmp_path / "services.d"
    d.mkdir(parents=True)
    monkeypatch.setattr(
        suite_peer, "lease_paths", lambda sid: [d / f"{sid}.json"]
    )
    return d


def write_lease(lease_dir, payload, service_id="uoink"):
    (lease_dir / f"{service_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


@pytest.mark.parametrize(
    "case", fixture_cases("runtime-lease.json"), ids=lambda c: c["id"]
)
def test_lease_validation_agrees_with_lane_c(case):
    """Integration truth: my validator against Lane C's checked-in
    conformance fixtures. dead_pid is expected-invalid for LIVENESS,
    which lease_defect deliberately does not judge — the caller does."""
    payload = case["payload"]
    service_id = payload.get("service_id") if isinstance(payload, dict) else "uoink"
    expected = service_id if case["id"] != "wrong_identity" else "uoink"
    defect = suite_peer.lease_defect(payload, expected)
    if case["expected_valid"]:
        assert defect is None, defect
    elif case["id"] == "dead_pid":
        assert defect is None  # shape is fine; liveness is the caller's job
    else:
        assert defect is not None


def test_lease_supplies_the_base_url_when_no_env_var(lease_dir, monkeypatch):
    write_lease(lease_dir, valid_lease())
    seen = {}

    class LeaseServer(FakeUoink):
        def __call__(self, request, timeout=0):
            seen["url"] = request.full_url if hasattr(request, "full_url") else request
            return super().__call__(request, timeout)

    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", LeaseServer())
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "unconfigured"  # no token, but discovered fine
    assert "127.0.0.1:5999" in seen["url"]  # the LEASED port, not the default
    assert "runtime lease at" in evidence


def test_explicit_url_beats_the_lease(lease_dir, monkeypatch):
    """§3.3 order: explicit configuration wins outright."""
    write_lease(lease_dir, valid_lease())
    monkeypatch.setenv(suite_peer.UOINK_URL_ENV, "http://127.0.0.1:5179")
    seen = {}

    class Server(FakeUoink):
        def __call__(self, request, timeout=0):
            seen["url"] = request.full_url
            return super().__call__(request, timeout)

    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", Server())
    peer, evidence = suite_peer.probe_uoink()
    assert "127.0.0.1:5179" in seen["url"]
    assert suite_peer.UOINK_URL_ENV in evidence


def test_hostile_lease_is_never_followed(lease_dir, monkeypatch):
    """A writable file must not be able to point zing off-loopback."""
    write_lease(lease_dir, valid_lease(base_url="http://evil.example.com:80"))
    monkeypatch.setattr(
        suite_peer.urllib.request, "urlopen",
        lambda *a, **k: pytest.fail("a hostile lease must not be followed"),
    )
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "invalid_lease"
    assert peer["error"]["retryable"] is False
    assert peer_is_valid(peer)


@pytest.mark.parametrize("payload", [
    valid_lease(token="secret"),                      # forbidden content
    valid_lease(ui={"home": "https://evil.test/x", "routes": {}}),
    valid_lease(capabilities=["b/1", "a/1"]),         # unsorted
    valid_lease(pid=0),
    "not an object",
])
def test_malformed_leases_are_invalid_lease(lease_dir, monkeypatch, payload):
    write_lease(lease_dir, payload)
    monkeypatch.setattr(
        suite_peer.urllib.request, "urlopen",
        lambda *a, **k: pytest.fail("an invalid lease must not be followed"),
    )
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "invalid_lease"


def test_stale_lease_is_named_not_downgraded_to_absent(lease_dir, monkeypatch):
    """§4: 'A stale lease is never silently downgraded to absent.'"""
    from myzing.mcp_server import _pid_alive  # noqa: F401  (delegation target)

    write_lease(lease_dir, valid_lease())
    monkeypatch.setattr(suite_peer, "_pid_is_live", lambda pid: False)
    monkeypatch.setattr(
        suite_peer.urllib.request, "urlopen",
        lambda *a, **k: pytest.fail("a stale lease must not be followed"),
    )
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "stale_lease"
    assert peer["error"]["retryable"] is True  # the service may come back
    assert peer["state"] != "absent"
    assert peer_is_valid(peer)


def test_leased_peer_that_refuses_is_unhealthy_not_absent(lease_dir, monkeypatch):
    """§4: a valid current lease is 'configured' for classification —
    only the bare default address earns calm absence."""
    write_lease(lease_dir, valid_lease())

    def refuse(request, timeout=0):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", refuse)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "unhealthy"
    assert peer["error"]["code"] == "unavailable"


def test_no_lease_falls_through_to_the_default(lease_dir, monkeypatch):
    def refuse(request, timeout=0):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", refuse)
    peer, evidence = suite_peer.probe_uoink()
    assert peer["state"] == "absent"  # calm: nothing configured, nothing there


def test_lease_paths_cover_all_three_platforms(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/x/AppData/Local")
    monkeypatch.setenv("XDG_STATE_HOME", "/home/x/.state")
    paths = [str(p).replace("\\", "/") for p in suite_peer.lease_paths("uoink")]
    assert any("RyanSuite/services.d/uoink.json" in p for p in paths)
    assert any("Library/Application Support/RyanSuite" in p for p in paths)
    assert any("ryan-suite/services.d/uoink.json" in p for p in paths)
