"""Suite source-URL validation shared by every ingestion boundary."""

from __future__ import annotations

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
    )


def has_http_scheme(value: Any) -> bool:
    """True when input claims HTTP(S), even if the rest is malformed."""
    if not isinstance(value, str):
        return False
    try:
        return urlsplit(value).scheme.lower() in {"http", "https"}
    except ValueError:
        return value.lower().startswith(("http:", "https:"))
