"""Offline regressions for peer replies and workspace writes."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import FakeHTTPResponse
from myzing import doctor, storage, suite_peer, urls
from myzing.schemas import Breakdown, StyleProfile, VideoMeta
from test_suite_peer import FakeUoink, make_health

LIMIT = 1024 * 1024
ROUTES = ["/.well-known/suite-service.json", "/api/suite/v1/health", "/kept-media"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked peer request")
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    doctor._peer_cache.clear()
    yield
    doctor._peer_cache.clear()


@pytest.mark.parametrize("host,loopback", [
    ("127.0.0.1", True), ("127.23.45.67", True), ("127.255.255.255", True),
    ("localhost", True), ("LOCALHOST", True), ("[::1]", True),
    ("[0:0:0:0:0:0:0:1]", True), ("public.example", False),
    ("localhost.example", False), ("127.0.0.1.example", False), ("128.0.0.1", False),
])
@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("as_request", [False, True])
@pytest.mark.parametrize("system_proxy", [False, True])
def test_loopback_opener_never_uses_a_proxy(monkeypatch, host, loopback, scheme, as_request, system_proxy):
    proxy = "http://127.0.0.1:9"
    for key in list(os.environ):
        if key.lower().endswith("_proxy") or key == "REQUEST_METHOD":
            monkeypatch.delenv(key)
    if system_proxy:
        monkeypatch.setattr(urllib.request, "getproxies", lambda: {"http": proxy, "https": proxy})
    else:
        monkeypatch.setenv("HTTP_PROXY", proxy)
        monkeypatch.setenv("HTTPS_PROXY", proxy)
    request = f"{scheme}://{host}:61234/notes"
    if as_request:
        request = urllib.request.Request(request, data=b"breakdown")
        request.add_unredirected_header("X-Uoink-Token", "test-token")
    opened = []

    def open_request(opener, incoming, *, timeout):
        assert incoming is request and timeout == 3
        proxies = [handler.proxies for handler in opener.handlers
                   if isinstance(handler, urllib.request.ProxyHandler)]
        assert all(not p.get(scheme) for p in proxies) if loopback else any(p.get(scheme) == proxy for p in proxies)
        assert any(isinstance(handler, urls._NoRedirect) for handler in opener.handlers)
        opened.append(incoming)
        return FakeHTTPResponse(b"{}")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", open_request)
    with urls.open_no_redirect(request, timeout=3) as response:
        assert response.read() == b"{}"
    assert opened == [request]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("raw", [b"<html>not a peer</html>", b"\xff", b"", b"[" * 2000 + b"]" * 2000],
                         ids=["html", "utf8", "empty", "nested"])
def test_bad_peer_body_is_contract_mismatch(monkeypatch, route, raw):
    fake = FakeUoink()

    def open_request(request, timeout=0):
        if request.full_url.endswith(route):
            return FakeHTTPResponse(raw)
        return fake(request, timeout)

    monkeypatch.setenv("UOINK_TOKEN", "test-token")
    monkeypatch.setattr(urls, "open_no_redirect", open_request)
    check = doctor.check_uoink()
    assert check.ok is False and check.mark == "unhealthy"
    assert check.data["peer"]["error"]["code"] == "contract_mismatch"


@pytest.mark.parametrize("field", ["state", "status", "id"])
@pytest.mark.parametrize("value", [[], {}, 1, True, None])
def test_health_fields_require_strings(monkeypatch, field, value):
    health = make_health()
    target = health if field == "state" else health["checks"][0]
    target[field] = value
    assert isinstance(suite_peer._health_defect(health), str)
    monkeypatch.setattr(urls, "open_no_redirect", FakeUoink(health=health))
    peer, evidence = suite_peer.probe_uoink()
    assert peer["error"]["code"] == "contract_mismatch"
    assert "health non-conformant" in evidence


@pytest.mark.parametrize("reader", ["get", "conformance"])
@pytest.mark.parametrize("status", [200, 404, 500])
@pytest.mark.parametrize("extra", [0, 1, LIMIT])
def test_peer_body_limit_includes_http_errors(monkeypatch, reader, status, extra):
    body = {"contract": "uoink.media.handoff", "version": 1}
    raw = json.dumps(body).encode()
    reads = []

    class Response(FakeHTTPResponse):
        def read(self, size=-1):
            assert 0 < size <= LIMIT + 1
            reads.append(size)
            return super().read(size)

    response = Response(raw + b" " * (LIMIT + extra - len(raw)))

    def open_request(request, timeout=0):
        if status != 200:
            raise urllib.error.HTTPError(request.full_url, status, "test error", {}, response)
        return response

    monkeypatch.setattr(urls, "open_no_redirect", open_request)
    if reader == "get":
        assert suite_peer._get_json("http://localhost:61234/manifest") == (status, None if extra else body)
    else:
        peer, evidence = suite_peer._conformance_read("http://localhost:61234", "test-token", [], "test peer")
        if extra:
            assert peer["error"]["code"] == "contract_mismatch"
            if status != 200:
                assert f"HTTP {status}" in evidence
        else:
            assert peer["state"] == "available"
    assert reads == [LIMIT + 1]


@pytest.fixture(params=["breakdown.md", "breakdown.json.bak", "profile.json.bak"])
def saved_file(request, zing_workspace):
    name = request.param
    if name == "profile.json.bak":
        profile = StyleProfile(name="test-profile")
        folder = storage.save_profile(profile)
        expected = (folder / "profile.json").read_bytes()
        profile.genre = "changed"
        save = lambda: storage.save_profile(profile)
    else:
        breakdown = Breakdown(VideoMeta("clip.mp4", "file"))
        folder = storage.save_breakdown(breakdown, "clip")
        expected = "# New breakdown\n" if name.endswith(".md") else (folder / "breakdown.json").read_bytes()
        breakdown.meta.title = "changed"
        save = lambda: storage.save_breakdown(breakdown, "clip", "# New breakdown\n")
    return folder / name, expected, save


@pytest.mark.parametrize("dangling", [False, True])
def test_saved_files_replace_symlinks(saved_file, tmp_path, dangling):
    path, expected, save = saved_file
    outside = tmp_path / "outside.txt"
    if not dangling:
        outside.write_bytes(b"outside content")
    try:
        path.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this system")
    save()
    assert not outside.exists() if dangling else outside.read_bytes() == b"outside content"
    assert path.is_file() and not path.is_symlink()
    assert (path.read_text(encoding="utf-8") if isinstance(expected, str) else path.read_bytes()) == expected
    assert not list(path.parent.glob("*.part"))


@pytest.mark.parametrize("saved_file", ["breakdown.md"], indirect=True)  # backups are unlinked then copied
@pytest.mark.parametrize("failure", ["retry", "permanent"])
def test_saved_files_replace_atomically_and_clean_up(saved_file, monkeypatch, failure):
    path, expected, save = saved_file
    path.write_bytes(b"old content")
    replace = storage.os.replace
    attempts = []

    def busy(source, target):
        if Path(target) == path:
            assert path.read_bytes() == b"old content"
            assert Path(source).parent == path.parent
            assert (Path(source).read_text(encoding="utf-8") if isinstance(expected, str)
                    else Path(source).read_bytes()) == expected
            attempts.append(source)
            if failure == "permanent":
                raise OSError("disk full")
            if len(attempts) < 3:
                raise PermissionError("reader holds the old file")
        replace(source, target)

    monkeypatch.setattr(storage.os, "replace", busy)
    if failure == "permanent":
        with pytest.raises(OSError, match="disk full"):
            save()
        assert path.read_bytes() == b"old content" and len(attempts) == 1
    else:
        save()
        assert len(attempts) == 3
        assert (path.read_text(encoding="utf-8") if isinstance(expected, str) else path.read_bytes()) == expected
    assert not list(path.parent.glob("*.part"))
