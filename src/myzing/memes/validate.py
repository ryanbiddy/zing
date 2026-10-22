"""MemeForge's on-image budgets, independent of any writer or renderer."""

from __future__ import annotations

import re
from typing import Any

from . import MemeError

LINE_HARD_CAP = 70
TOTAL_HARD_CAP = 110
BANNED_FILLER = (
    r"\bnobody\s*:",
    r"\bthat moment when\b",
    r"\balso me\s*:",
    r"\bin today's fast[- ]paced world\b",
    r"\blet that sink in\b",
)


def normalize_text(text: str) -> str:
    """Preserve deliberate line breaks; normalize whitespace within each line."""
    return "\n".join(" ".join(line.split()) for line in text.splitlines()).strip()


def check_texts(texts: list[str], *, box_count: int | None = None) -> dict[str, Any]:
    """One array entry is a beat/box, even if it wraps onto multiple lines.

    Empty entries preserve template positions. Counts use Unicode code points,
    with each explicit newline counting as one character (as a space would).
    """
    if not isinstance(texts, (list, tuple)) or any(not isinstance(t, str) for t in texts):
        raise MemeError("text must be a list of strings")
    if box_count is not None and (type(box_count) is not int or not 1 <= box_count <= 6):
        raise MemeError("box_count must be an integer from 1 to 6")
    normalized = [normalize_text(t) for t in texts]
    problems: list[dict[str, Any]] = []
    beats = sum(bool(t) for t in normalized)
    maximum = box_count if box_count is not None else 3
    if not beats or beats > maximum or len(normalized) > maximum:
        problems.append({
            "code": "beat_count", "message": f"Use 1-{maximum} text boxes with at least one non-empty beat.",
            "actual": beats, "slots": len(normalized), "limit": maximum,
        })
    for index, text in enumerate(normalized):
        if len(text) > LINE_HARD_CAP:
            problems.append({
                "code": "line_too_long", "index": index, "actual": len(text),
                "limit": LINE_HARD_CAP, "message": f"Text box {index + 1} exceeds 70 characters.",
            })
        for pattern in BANNED_FILLER:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                problems.append({
                    "code": "banned_filler", "index": index, "match": match.group(),
                    "message": f"Cut filler from text box {index + 1}: {match.group()!r}.",
                })
    total = sum(map(len, normalized))
    if total > TOTAL_HARD_CAP:
        problems.append({
            "code": "total_too_long", "actual": total, "limit": TOTAL_HARD_CAP,
            "message": "On-image text exceeds 110 characters total.",
        })
    return {"valid": not problems, "texts": normalized, "beats": beats,
            "characters": total, "problems": problems}
