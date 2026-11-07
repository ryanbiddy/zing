"""Suite source-URL validation shared by every ingestion boundary."""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit


def is_http_url(value: Any) -> bool:
    """True only for absolute HTTP(S) URLs allowed by the suite contract."""
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(character.isspace() for character in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        # Accessing port rejects malformed netlocs such as ``:abc``.
        parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
    )


def require_public_host(url: str) -> None:
    p = urlsplit(url)
    try:
        addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError(f"could not resolve host {p.hostname}") from None
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError(f"refusing private address {p.hostname}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def open_no_redirect(request, *, timeout):
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def has_http_scheme(value: Any) -> bool:
    """True when input claims HTTP(S), even if the rest is malformed."""
    if not isinstance(value, str):
        return False
    try:
        return urlsplit(value).scheme.lower() in {"http", "https"}
    except ValueError:
        return value.lower().startswith(("http:", "https:"))
