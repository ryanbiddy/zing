"""Post copy for one clip, anchored to the source's date and credited to the source."""
from __future__ import annotations

from .tools import NO_HOOK, data_path

FIELDS = ("x", "instagram", "tiktok", "youtube_title", "first_comment")


def brand_line(brand: dict | None) -> str:
    if not brand:
        return "none given"
    return "; ".join(f"{k}: {brand[k]}" for k in ("name", "url", "cta") if brand.get(k))


def news_line(news: dict | None, links: bool = False) -> str:
    if not news:
        return "none given"
    urls = [str(u) for u in news.get("links", [])]
    return news["peg"] + (("\n" + "\n".join(f"- {u}" for u in urls)) if links and urls else "")


def prompt(moment: dict, words: dict, source: dict, mode: str = "context", brand: dict | None = None,
           news: dict | None = None) -> str:
    text = data_path("prompts", "copy-launch.md" if mode == "launch" else "copy.md").read_text(encoding="utf-8")
    for k, v in {"{SOURCE}": source.get("name", ""), "{HOOK}": moment["hook"] or NO_HOOK,
                 "{DATE}": source.get("date") or "unknown",
                 "{BRAND}": brand_line(brand), "{NEWS}": news_line(news),
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
