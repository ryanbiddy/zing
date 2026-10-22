"""Content-free anchors for evaluation data without redistribution rights."""

from __future__ import annotations

import hashlib


def text_measurements(text: str) -> dict[str, str | int]:
    """Keep equality and token-count evidence without publishing OCR text.

    Normalization matches the historical calibration persistence rule. Hashes
    are provenance anchors, not encryption or a promise of anonymity.
    """
    normalized = " ".join(text.upper().split())
    return {
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "normalized_text_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "token_count": len(text.split()),
    }
