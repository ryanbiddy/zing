"""Joining punctuation-led transcript pieces."""
import unicodedata


def joins_previous(text: str, *, raw: bool = False) -> bool:
    piece = text.strip()
    if not piece:
        return False
    if raw:
        return not text[0].isspace() and unicodedata.category(piece[0])[0] in "PS"
    return piece[0] in ".,%'’-:;!?)]" and piece not in {"-", "--", "—", "–", "...", "…"}
