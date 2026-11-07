"""Offline regressions for DNS checks, API credentials and peer redirects."""
import io
import json
import socket
import ssl
import subprocess
import urllib.request
import urllib.response
from collections import deque
from email.message import Message
from http.client import BadStatusLine, IncompleteRead
from types import SimpleNamespace

import pytest

from myzing import engagement, storage, suite_peer, tts_providers, uoink_bridge, urls
from myzing.factory import network, visuals
from myzing.playbook import notes
from myzing.render.tts import SynthesisRequest, TTSGenerationError
from myzing.study import downloader, ingest
from myzing.study.proc import MediaError


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked network operation")
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: False)


def addresses(ips, port):
    return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "",
             (ip, port, 0, 0) if ":" in ip else (ip, port)) for ip in ips]


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(sockets=[], connected=[], tls=[], replies=deque(), fail=set())

    class Socket:
        def __init__(self, *args):
            self.sent, self.closed, self.timeout = b"", False, None
            state.sockets.append(self)

        def settimeout(self, timeout):
            self.timeout = timeout

        def setsockopt(self, *args):
            pass

        def connect(self, address):
            state.connected.append(address)
            if address[0] in state.fail:
                raise OSError("unreachable")

        def sendall(self, data):
            self.sent += data

        def makefile(self, *args):
            return io.BytesIO(state.replies.popleft() if state.replies else
                              b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

        def close(self):
            self.closed = True

    def wrap(context, sock, *, server_hostname):
        state.tls.append((server_hostname, context.check_hostname, context.verify_mode))
        return sock

    monkeypatch.setattr(socket, "socket", Socket)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    return state


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "192.168.1.2", "::1",
                               "fd00::1", "fe80::1", "::ffff:127.0.0.1"])
def test_network_rechecks_dns_at_connect(monkeypatch, wire, scheme, ip):
    answers = iter([["8.8.8.8"], [ip]])
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: addresses(next(answers), port))
    with pytest.raises(ValueError, match="refusing private address rebind.test") as error:
        network.Network().open(f"{scheme}://rebind.test/media?token=secret", "test", validate=visuals._public_url)
    assert "secret" not in str(error.value)
    assert not wire.sockets


@pytest.mark.parametrize("ips", [[], ["8.8.8.8", "127.0.0.1"], ["2606:4700:4700::1111", "::1"]])
def test_network_checks_all_addresses_before_connecting(monkeypatch, wire, ips):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: addresses(ips, port))
    with pytest.raises(ValueError, match="private address public.test"):
        network.Network().open("http://public.test/file", "test", validate=lambda url: url)
    assert not wire.sockets


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_network_connects_to_checked_address_and_keeps_hostname(monkeypatch, wire, scheme):
    calls = []

    def resolve(host, port, *args, **kwargs):
        calls.append(host)
        return addresses(["8.8.8.8"] if len(calls) == 1 else ["127.0.0.1"], port)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with network.Network().open(f"{scheme}://public.test:8443/file", "test", timeout=7,
                               validate=lambda url: url) as response:
        assert response.read() == b"ok"
    assert calls == ["public.test"]
    assert wire.connected == [("8.8.8.8", 8443)]
    assert wire.sockets[0].timeout == 7
    assert b"Host: public.test:8443\r\n" in wire.sockets[0].sent
    assert wire.tls == ([("public.test", True, ssl.CERT_REQUIRED)] if scheme == "https" else [])


def test_network_tries_other_checked_addresses(monkeypatch, wire):
    ips = ["2606:4700:4700::1111", "8.8.8.8"]
    wire.fail.add(ips[0])
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: addresses(ips, port))
    with network.Network().open("http://public.test/file", "test", validate=lambda url: url) as response:
        assert response.read() == b"ok"
    assert wire.connected == [(ips[0], 80, 0, 0), (ips[1], 80)]
    assert wire.sockets[0].closed


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_network_rechecks_redirect_connections(monkeypatch, tmp_path, wire, scheme):
    answers = iter([["8.8.8.8"], ["8.8.8.8"], ["8.8.4.4"], ["127.0.0.1"]])
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: addresses(next(answers), port))
    wire.replies.append((f"HTTP/1.1 302 Found\r\nLocation: {scheme}://rebind.test/file?token=secret\r\n"
                         "Content-Length: 0\r\n\r\n").encode())
    with pytest.raises(ValueError, match="private address rebind.test"):
        network.Network(tmp_path).open(f"{scheme}://public.test/file", "test", validate=visuals._public_url)
    assert len(wire.connected) == 1
    ledger = (tmp_path / "network.jsonl").read_text()
    assert "secret" not in ledger
    assert [(row["host"], row["bytes"]) for row in map(json.loads, ledger.splitlines())] == [
        ("public.test", 0), ("rebind.test", 0)]


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("bypass", [False, True])
def test_network_keeps_proxy_resolution_unless_bypassed(monkeypatch, wire, scheme, bypass):
    calls = []

    def resolve(host, port, *args, **kwargs):
        calls.append(host)
        return addresses(["127.0.0.1"], port)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {scheme: "http://proxy.test:8888"})
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: bypass)
    if bypass:
        with pytest.raises(ValueError, match="private address public.test"):
            network.Network().open(f"{scheme}://public.test/file", "test", validate=lambda url: url)
        assert calls == ["public.test"] and not wire.sockets
    else:
        if scheme == "https":
            wire.replies.append(b"HTTP/1.0 200 Connection established\r\n\r\n")
        with network.Network().open(f"{scheme}://public.test/file", "test", validate=lambda url: url) as response:
            assert response.read() == b"ok"
        assert calls == ["proxy.test"]
        assert wire.connected == [("127.0.0.1", 8888)]


def test_network_without_validator_keeps_local_requests(monkeypatch, wire):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: addresses(["127.0.0.1"], port))
    with network.Network().open("http://local.test/file", "test") as response:
        assert response.read() == b"ok"


@pytest.fixture
def fetch(zing_workspace, monkeypatch):
    calls = []
    dest = storage.breakdown_dir("review")
    dest.mkdir(parents=True)
    monkeypatch.setattr(ingest.doctor, "resolve_ytdlp_argv", lambda: ["yt-dlp"])
    monkeypatch.setattr(downloader, "runtime_options", lambda: {})

    def run(cmd, **kwargs):
        calls.append(cmd)
        (dest / "media.mp4").write_bytes(b"media")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ingest.proc, "run", run)
    return dest, calls


@pytest.mark.parametrize("ips", [["127.0.0.1"], ["169.254.169.254"], ["10.0.0.1"], ["::1"],
                                ["fd00::1"], ["::ffff:127.0.0.1"], [], ["8.8.8.8", "192.168.1.2"]])
def test_study_refuses_private_hosts_before_ytdlp(monkeypatch, fetch, ips):
    dest, calls = fetch
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: addresses(ips, port))
    with pytest.raises(MediaError, match="private address private.test") as error:
        ingest._fetch("https://private.test/video?key=secret", "review", dest, [])
    assert "secret" not in str(error.value) and not calls


def test_study_dns_failure_names_only_host(monkeypatch, fetch):
    dest, calls = fetch

    def fail(*args, **kwargs):
        raise socket.gaierror("resolver failure")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(MediaError, match="resolve.*missing.test") as error:
        ingest._fetch("https://missing.test/video?key=secret", "review", dest, [])
    assert "secret" not in str(error.value) and not calls


@pytest.mark.parametrize("ip", ["8.8.8.8", "2606:4700:4700::1111"])
def test_study_public_hosts_still_reach_ytdlp(monkeypatch, fetch, ip):
    dest, calls = fetch
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: addresses([ip], port))
    url = "https://public.test/video?key=secret"
    assert ingest._fetch(url, "review", dest, []) == dest / "media.mp4"
    assert len(calls) == 1 and calls[0][-1] == url


def test_study_cached_media_needs_no_dns(fetch):
    dest, calls = fetch
    media = dest / "media.mp4"
    media.write_bytes(b"cached")
    assert ingest._fetch("http://127.0.0.1/video", "review", dest, []) == media
    assert not calls and urls.is_http_url("http://127.0.0.1/video")


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(requests=[], replies=deque(), reads=[])

    class Body(io.BytesIO):
        def read(self, size=-1):
            state.reads.append(size)
            if isinstance(state.body, Exception):
                raise state.body
            return super().read(size)

    def opened(handler, request):
        state.requests.append(request)
        code, headers, state.body = state.replies.popleft()
        message = Message()
        for key, value in headers.items():
            message[key] = value
        response = urllib.response.addinfourl(Body(state.body if isinstance(state.body, bytes) else b""),
                                             message, request.full_url, code)
        response.msg = "test response"
        return response

    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", opened)
    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", opened)
    monkeypatch.setattr(urllib.request, "_opener", None)
    return state


@pytest.mark.parametrize("client", ["gemini", "elevenlabs"])
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_api_keys_and_requests_never_follow_redirects(http, tmp_path, client, status):
    http.replies.extend([(status, {"Location": "https://other.test/leak"}, b""), (200, {}, b"{}")])
    if client == "gemini":
        with pytest.raises(notes.NotesError, match=f"Gemini HTTP {status}"):
            notes.Client("secret-key", retries=0).request("/models")
        header = "X-goog-api-key"
    else:
        with pytest.raises(TTSGenerationError, match=f"HTTP {status}"):
            tts_providers.ElevenLabsProvider("secret-key").synthesize(
                SynthesisRequest(text="hello", voice="voice_1"), tmp_path / "voice.wav")
        header = "Xi-api-key"
    assert len(http.requests) == 1
    assert header not in http.requests[0].headers
    assert http.requests[0].unredirected_hdrs[header] == "secret-key"


@pytest.mark.parametrize("voice", ["../voices", "voice/extra", "voice?key=x", "voice#x", "a" * 129, "voïce", "a\\b"])
@pytest.mark.parametrize("configured", [False, True])
def test_elevenlabs_rejects_unsafe_voice_ids(monkeypatch, tmp_path, http, voice, configured):
    http.replies.append((200, {}, b"\0\0"))
    if configured:
        monkeypatch.setenv(tts_providers.ELEVENLABS_VOICE_ENV, voice)
    with pytest.raises(TTSGenerationError, match="invalid ElevenLabs voice"):
        tts_providers.ElevenLabsProvider("secret-key").synthesize(
            SynthesisRequest(text="hello", voice="af_sarah" if configured else voice), tmp_path / "voice.wav")
    assert not http.requests


@pytest.mark.parametrize("voice", ["a", "Ab_09-", "a" * 128])
def test_elevenlabs_accepts_valid_voice_ids(tmp_path, http, voice):
    http.replies.append((200, {}, b"\0\0"))
    result = tts_providers.ElevenLabsProvider("secret-key").synthesize(
        SynthesisRequest(text="hello", voice=voice), tmp_path / "voice.wav")
    assert result.voice == voice and result.path.is_file()


def test_gemini_bounds_response_reads(http):
    http.replies.append((200, {}, b'{"text":"' + b"x" * (8 * 1024 * 1024) + b'"}'))
    with pytest.raises(notes.NotesError, match="response.*(large|limit|MB)"):
        notes.Client("secret-key", retries=0).request("/models")
    assert http.reads == [8 * 1024 * 1024 + 1]


@pytest.mark.parametrize("client", ["gemini", "elevenlabs"])
@pytest.mark.parametrize("error", [IncompleteRead(b"partial"), BadStatusLine("broken")])
@pytest.mark.parametrize("during_read", [False, True])
def test_api_http_exceptions_are_transport_failures(monkeypatch, tmp_path, http, client, error, during_read):
    if during_read:
        http.replies.append((200, {}, error))
    else:
        def fail(*args, **kwargs):
            raise error
        monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", fail)
    if client == "gemini":
        with pytest.raises(notes.NotesError, match="Gemini transport failed"):
            notes.Client("secret-key", retries=0).request("/models")
    else:
        with pytest.raises(TTSGenerationError, match="could not reach ElevenLabs"):
            tts_providers.ElevenLabsProvider("secret-key").synthesize(
                SynthesisRequest(text="hello", voice="voice_1"), tmp_path / "voice.wav")


@pytest.mark.parametrize("operation", ["push", "kept", "search", "metadata", "manifest", "engagement"])
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_loopback_requests_never_follow_redirects(monkeypatch, zing_workspace, http, operation, status):
    base = "http://127.0.0.1:61983"
    monkeypatch.setenv("UOINK_URL", base)
    monkeypatch.setenv("UOINK_TOKEN", "local-token")
    http.replies.extend([(status, {"Location": "http://other.test/leak"}, b""), (200, {}, b"{}")])
    if operation in ("search", "metadata"):
        monkeypatch.setattr(suite_peer, "_get_json", lambda url: (200, {
            "service": {"id": "uoink", "capabilities": [uoink_bridge.SEARCH_CAPABILITY]}}))
        monkeypatch.setattr(suite_peer, "_manifest_defect", lambda body: None)
    if operation == "push":
        dest = storage.breakdown_dir("review")
        dest.mkdir(parents=True)
        (dest / "breakdown.md").write_text("private note", encoding="utf-8")
        result = uoink_bridge.push_breakdown("review")
        assert result == {"ok": False, "error": f"uoink answered HTTP {status} - is your uoink up to date?"}
    elif operation == "kept":
        result = uoink_bridge.resolve_kept_media("uoink://item/review")
        assert result == {"ok": False, "error": f"uoink answered HTTP {status} - is your uoink up to date?"}
    elif operation == "search":
        result = uoink_bridge.search_references("private search")
        assert result == {"ok": False, "code": "peer_error",
                          "error": f"Reference search unavailable (HTTP {status}); use a known ID or local file."}
    elif operation == "metadata":
        result = uoink_bridge.item_metadata("uoink://item/review")
        assert result == {"ok": False, "code": "peer_error",
                          "error": f"Uoink item lookup unavailable (HTTP {status})."}
    elif operation == "manifest":
        assert suite_peer._get_json(base + "/.well-known/suite-service.json") == (status, None)
    else:
        with pytest.raises(engagement._DeliveryError, match="Uoink engagement response is not valid JSON"):
            engagement._post({"event_id": "private event"})
    assert len(http.requests) == 1
    assert http.requests[0].full_url.startswith(base + "/")
