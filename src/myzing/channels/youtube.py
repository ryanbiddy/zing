"""Owner consent and protected YouTube credentials."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import secrets
import time
import webbrowser
from contextlib import contextmanager
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from myzing.model_fetch import _try_lock, _unlock

from . import queue, registry

TOKEN = "https://oauth2.googleapis.com/token"
SCOPES = tuple("https://www.googleapis.com/auth/" + scope for scope in
               ("youtube.upload", "youtube.readonly", "yt-analytics.readonly"))
RECONNECT = "YouTube authorization failed. reconnect with zing channels connect"
AUDIT = "YouTube locks uploads private until the Google Cloud project passes Google's API audit."


@contextmanager
def lock():
    with (registry.home() / ".youtube.guard").open("a+b") as stream:
        if not _try_lock(stream):
            raise registry.ChannelError("Another YouTube command is running.")
        try:
            yield
        finally:
            _unlock(stream)


def _dpapi(data: bytes, *, decrypt=False) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    call = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    call.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                     ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    call.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source, dest = Blob(len(data), ctypes.cast(buffer, ctypes.c_void_p)), Blob()
    if not call(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):  # current user, no UI
        raise registry.ChannelError("Windows could not protect or open the YouTube token. " + RECONNECT)
    try:
        return ctypes.string_at(dest.data, dest.size)
    finally:
        kernel.LocalFree(dest.data)


def save_token(slug: str, token: dict) -> None:
    data = json.dumps(token, allow_nan=False).encode("utf-8")
    if os.name == "nt":
        data = _dpapi(data)
    path = registry.directory(slug) / "youtube.token"
    tmp = path.with_name(".youtube-" + secrets.token_hex(8) + ".tmp")
    try:
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def load_token(slug: str) -> dict:
    try:
        data = (registry.directory(slug) / "youtube.token").read_bytes()
        token = json.loads(_dpapi(data, decrypt=True) if os.name == "nt" else data)
        if not isinstance(token, dict) or any(not isinstance(token.get(k), str) or not token[k] for k in
                ("client_id", "client_secret", "refresh_token", "access_token", "project_id")):
            raise ValueError
        return token
    except (OSError, ValueError):
        raise registry.ChannelError(RECONNECT) from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(request, *, timeout):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


class Error(registry.ChannelError):
    def __init__(self, status, reason=""):
        self.status, self.reason = status, reason
        super().__init__(f"YouTube request failed with HTTP {status}." + (" " + reason if reason else ""))


def checked(response) -> dict:
    status, _, body = response
    try:
        data = json.loads(body) if body else {}
    except (ValueError, UnicodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if status not in (200, 201):
        error = data.get("error")
        errors = error.get("errors", []) if isinstance(error, dict) else []
        reason = next((e.get("reason") for e in errors if isinstance(e, dict)
                       and e.get("reason") in ("quotaExceeded", "uploadLimitExceeded")), "")
        raise Error(status, reason)
    return data


class Client:
    def __init__(self, slug, *, opener=None, now=None, sleep=None, stop=None, token=None):
        self.slug, self.opener = slug, opener or _open
        self.now, self.sleep, self.stop = now, sleep or time.sleep, stop
        self.token = load_token(slug) if token is None else token

    def checkpoint(self):
        registry.require_running(self.slug)
        if self.stop and self.stop():
            raise registry.ChannelError("YouTube work stopped.")

    def _send(self, method, url, data, headers):
        for attempt in range(4):
            self.checkpoint()
            request = Request(url, data=data, headers=headers, method=method)
            try:
                response = self.opener(request, timeout=60)
            except HTTPError as exc:
                response = exc
            except (OSError, URLError, HTTPException):
                raise registry.ChannelError("YouTube could not be reached. Try again later.") from None
            try:
                status = response.status if hasattr(response, "status") else response.code
                result = status, {k.lower(): v for k, v in response.headers.items()}, response.read()
            except (OSError, URLError, HTTPException):
                raise registry.ChannelError("YouTube response was interrupted. Try again later.") from None
            finally:
                response.close()
            if status < 500 or status > 599 or attempt == 3:
                return result
            self.checkpoint()
            self.sleep((1, 4, 16)[attempt])

    def refresh(self):
        self.checkpoint()
        try:
            values = {k: self.token[k] for k in ("client_id", "client_secret", "refresh_token")}
            data = checked(self._send("POST", TOKEN, urlencode({**values, "grant_type": "refresh_token"}).encode(),
                                      {"Content-Type": "application/x-www-form-urlencoded"}))
            self.accept(data)
            save_token(self.slug, self.token)
        except (OSError, ValueError, KeyError, TypeError):
            self.checkpoint()
            raise registry.ChannelError(RECONNECT) from None

    def accept(self, data):
        access, expires = data.get("access_token"), data.get("expires_in")
        if not isinstance(access, str) or not access or type(expires) not in (int, float) or not 0 < expires < 10**9:
            raise registry.ChannelError(RECONNECT)
        self.token.update(access_token=access, expires_at=queue._now(self.now).timestamp() + expires)
        if data.get("refresh_token"):
            if not isinstance(data["refresh_token"], str):
                raise registry.ChannelError(RECONNECT)
            self.token["refresh_token"] = data["refresh_token"]

    def request(self, method, url, data=None, headers=None):
        self.checkpoint()
        try:
            expired = float(self.token.get("expires_at", 0)) <= queue._now(self.now).timestamp() + 30
        except (ValueError, TypeError):
            expired = True
        if expired:
            self.refresh()
        for attempt in range(2):
            response = self._send(method, url, data, {**(headers or {}), "Authorization": "Bearer " + self.token["access_token"]})
            if response[0] != 401:
                return response
            if attempt == 0:
                self.refresh()
        raise registry.ChannelError(RECONNECT)


def _callback(path: str, state: str) -> str:
    params = parse_qs(urlsplit(path).query)
    supplied = params.get("state", [])
    if len(supplied) != 1 or not secrets.compare_digest(supplied[0].encode(), state.encode()):
        raise registry.ChannelError("YouTube sign-in state did not match. Run connect again.")
    codes = params.get("code", [])
    if params.get("error") or len(codes) != 1 or not codes[0]:
        raise registry.ChannelError("YouTube sign-in was not completed. Run connect again.")
    return codes[0]


def connect(slug, client_secret, *, opener=None, now=None, say=print, open_browser=None, server_factory=None) -> dict:
    channel = registry.load(slug)
    registry.require_running(slug)
    try:
        installed = json.loads(Path(client_secret).read_text(encoding="utf-8-sig"))["installed"]
        token = {k: installed[k] for k in ("client_id", "client_secret")}
        token["project_id"] = installed.get("project_id") or token["client_id"].split("-", 1)[0]
        if any(not isinstance(v, str) or not v for v in token.values()):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise registry.ChannelError("Read an OAuth client JSON for a Desktop app with --client-secret.") from None
    verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    received = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if urlsplit(self.path).path != "/":
                self.send_error(404)
                return
            try:
                received["code"] = _callback(self.path, state)
                status, text = 200, "You can close this tab and return to zing."
            except registry.ChannelError as exc:
                received["error"] = exc
                status, text = 400, "Sign-in failed. Return to zing and run connect again."
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(text.encode())

    with lock(), (server_factory or HTTPServer)(("127.0.0.1", 0), Callback) as server:
        redirect = f"http://127.0.0.1:{server.server_address[1]}/"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": token["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": " ".join(SCOPES),
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            "access_type": "offline", "prompt": "consent"})
        say(url)
        (open_browser or webbrowser.open)(url)
        server.timeout, deadline = 1, time.monotonic() + 300
        while not received and time.monotonic() < deadline:
            registry.require_running(slug)
            server.handle_request()
        if "error" in received:
            raise received["error"]
        if "code" not in received:
            raise registry.ChannelError("YouTube sign-in timed out. Run connect again.")
        client = Client(slug, opener=opener, now=now, token=token)
        values = {"client_id": token["client_id"], "client_secret": token["client_secret"],
                  "code": received["code"], "code_verifier": verifier, "redirect_uri": redirect, "grant_type": "authorization_code"}
        client.accept(checked(client._send("POST", TOKEN, urlencode(values).encode(),
                                          {"Content-Type": "application/x-www-form-urlencoded"})))
        if not token.get("refresh_token"):
            raise registry.ChannelError(RECONNECT)
        data = checked(client.request("GET", "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"))
        items = data.get("items", [])
        if len(items) != 1 or not items[0].get("id") or not items[0].get("snippet", {}).get("title"):
            raise registry.ChannelError("Choose a YouTube channel and run connect again.")
        channel["youtube"] = {"channel_id": items[0]["id"], "title": items[0]["snippet"]["title"],
                              "connected_at": queue._now(now).isoformat(timespec="seconds")}
        registry.validate(channel)
        token["channel_id"] = channel["youtube"]["channel_id"]
        save_token(slug, token)
        registry.save(channel)
        return channel["youtube"]


def disconnect(slug) -> dict:
    channel = registry.load(slug)
    with lock():
        (registry.directory(slug) / "youtube.token").unlink(missing_ok=True)
        channel.pop("youtube", None)
        registry.save(channel)
    return {"channel": slug, "connected": False}
