"""Post copy for one clip, anchored to the source's date and credited to the source."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import campaign
from .tools import NO_HOOK, data_path

FIELDS = ("x", "instagram", "tiktok", "youtube_title", "first_comment")
PATTERNS = ("name_claim", "how_why", "superlative", "quote", "question")


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
           news: dict | None = None, voice: str | None = None) -> str:
    text = data_path("prompts", "copy-launch.md" if mode == "launch" else "copy.md").read_text(encoding="utf-8")
    for k, v in {"{SOURCE}": source.get("name", ""), "{HOOK}": moment["hook"] or NO_HOOK,
                 "{DATE}": source.get("date") or "unknown",
                 "{BRAND}": brand_line(brand), "{NEWS}": news_line(news),
                 "{TEXT}": " ".join(w["w"] for w in words["words"])}.items():
        text = text.replace(k, v)
    return text + ("\n\nCHANNEL VOICE\n" + voice if voice else "")


def stamp(seconds: float) -> str:
    mm, ss = divmod(int(seconds), 60)
    hh, mm = divmod(mm, 60)
    return f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"


def context_url(url: str, seconds: float) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = parse_qsl(parts.query, keep_blank_values=True)
    watch = parts.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"} and parts.path == "/watch"
    short = parts.hostname in {"youtu.be", "www.youtu.be"} and bool(parts.path.strip("/"))
    if parts.scheme not in {"http", "https"} or not (short or watch and any(k == "v" and v for k, v in query)):
        return url
    query = [(k, v) for k, v in query if k != "t"] + [("t", f"{int(seconds)}s")]
    return urlunsplit(parts._replace(query=urlencode(query)))


def require_tags(post: dict, brief: dict) -> dict:
    out = dict(post)
    for field in campaign.POSTED:
        missing = campaign.missing_tags(out.get(field, ""), brief.get("tags", []))
        if missing:                                 # a title stays on one line
            out[field] = (out.get(field, "").rstrip() + (" " if field == "youtube_title" else "\n\n")
                          + " ".join(missing)).lstrip()
    return out


def finalize(answer: dict, words: dict, source: dict, brief: dict | None = None, news: dict | None = None) -> dict:
    missing = [k for k in FIELDS if not isinstance(answer.get(k), str)]
    if missing:
        raise ValueError(f"copy answer is missing {', '.join(missing)}")
    start = words["spans"][0][0] if words.get("spans") else words["start"]
    url = source.get("url") or ""
    if not url.startswith(("http://", "https://")):
        url = ""
    link = context_url(url, start)
    post = {k: answer[k].replace("{SOURCE_URL}", link if k == "first_comment" else url) for k in FIELDS}
    post["first_comment"] = post["first_comment"].replace("{TIMESTAMP}", stamp(start))
    links = [u for u in (news or {}).get("links", []) if str(u).startswith("https://")]
    if not url and links and "{SOURCE_URL}" in answer["first_comment"]:   # a recorded take credits what it discusses
        post["first_comment"] = f"About this: {links[0]}"
    titles = answer.get("titles")
    options = [{"text": t["text"].strip(), "pattern": t["pattern"]} for t in titles
               if isinstance(t, dict) and isinstance(t.get("text"), str) and t["text"].strip()
               and len(t["text"].strip()) <= 60 and not any(c in t["text"] for c in "\r\n")
               and t.get("pattern") in PATTERNS] if isinstance(titles, list) else []
    if options:
        post["title_options"] = options
    return {**require_tags(post, brief or {}), "rights": source.get("rights", "unknown")}


def choose(post: dict, channel: str, rng=None, *, clipdir: Path | None = None) -> dict:
    import random
    from myzing.channels import bandit, registry
    from .pipeline import _read
    options = post.get("title_options", [])
    if not options:
        return post
    rows = bandit.history(channel)
    if clipdir is not None:
        seen = {r["id"] for r in rows}
        at = datetime.fromtimestamp(max((bandit.when(r) for r in rows), default=0), timezone.utc).isoformat()
        for i in range(1, int(clipdir.name[4:])):
            d = clipdir.parent / f"clip{i:02d}"
            arms = _read(d / "arms.json", {})
            if not arms.get("title_pattern"):
                arms = {**arms, **{k: v for k, v in _read(d / "post.json", {}).items() if k.startswith("title_")}}
            ident = f"{d.parent.name}/{d.name}"
            if ident not in seen and arms.get("title_pattern"):
                rows.append({"id": ident, "arms": arms, "queued_at": at})
    candidates = bandit.allowed("title_pattern", [t["pattern"] for t in options], rows)
    if not candidates:
        return post
    value, propensity, policy = bandit.choose("title_pattern", candidates, rows, rng or random.Random(),
                                            baseline="name_claim", prior=bandit.prior(registry.load(channel)))
    title = next(t["text"] for t in options if t["pattern"] == value)
    return {**post, "youtube_title": title, "title_pattern": value, "title_propensity": propensity,
            "title_policy": policy, "title_candidates": candidates}
