"""MemeForge's viral lens: a readability heuristic, never a reach forecast."""

from __future__ import annotations


def viral_score(texts: list[str], *, aspect: str = "1:1",
                contrast: list[bool] | None = None) -> dict:
    visible = [i for i, text in enumerate(texts) if text.strip()]
    chars = sum(len(texts[i].strip()) for i in visible)
    score = 48
    notes = []
    if 1 <= len(visible) <= 3:
        score += 12
        notes.append("Focused 1-3 beat structure")
    else:
        notes.append("Trim the number of text beats")
    if chars <= 100:
        score += 15
        notes.append("Fast read")
    elif chars <= 150:
        score += 7
        notes.append("Readable, but could be tighter")
    else:
        score -= 8
        notes.append("Heavy text may slow the scroll")
    if visible and contrast is not None and all(i < len(contrast) and contrast[i] for i in visible):
        score += 10
        notes.append("Strong text contrast")
    if aspect in ("16:9", "1:1", "4:5", "x-landscape", "square", "portrait"):
        score += 7
        notes.append("Timeline-safe crop")
    return {"score": max(1, min(98, score)), "notes": notes[:3],
            "kind": "readability_heuristic", "predicts_reach": False}


def idea_score(texts: list[str], tone: str = "dry") -> int:
    total = sum(map(len, texts))
    score = 66 + (12 if total <= 60 else 0) + (8 if total <= 40 else 0)
    score -= 12 if total > 80 else 0
    score -= 8 if any(len(t) > 45 for t in texts) else 0
    score += 3 if any(t in tone.lower() for t in ("dry", "savage", "chaotic")) else 0
    return max(48, min(96, score))
