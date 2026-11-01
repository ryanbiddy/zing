"""Post copy for one clip, anchored to the source's date and credited to the source."""
from __future__ import annotations

from .tools import data_path

FIELDS = ("x", "instagram", "tiktok", "youtube_title", "first_comment")


def prompt(moment: dict, words: dict, source: dict) -> str:
    text = data_path("prompts", "copy.md").read_text(encoding="utf-8")
    for k, v in {"{SOURCE}": source.get("name", ""), "{HOOK}": moment["hook"], "{DATE}": source.get("date") or "unknown",
                 "{TEXT}": " ".join(w["w"] for w in words["words"])}.items():
        text = text.replace(k, v)
    return text


def stamp(seconds: float) -> str:
    mm, ss = divmod(int(seconds), 60)
    hh, mm = divmod(mm, 60)
    return f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"


def finalize(answer: dict, words: dict, source: dict) -> dict:
    missing = [k for k in FIELDS if not isinstance(answer.get(k), str)]
    if missing:
        raise ValueError(f"copy answer is missing {', '.join(missing)}")
    post = {k: answer[k].replace("{SOURCE_URL}", source.get("url", "")) for k in FIELDS}
    post["first_comment"] = post["first_comment"].replace("{TIMESTAMP}", stamp(words["start"]))
    return post
