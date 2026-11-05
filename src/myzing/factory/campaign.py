"""Source labels and campaign rules checked before capture."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .tools import FactoryError

RIGHTS = {"own": "you own this source", "licensed": "licensed", "permission": "you have permission",
          "unknown": "unknown. Check before posting."}
POSTED = ("x", "instagram", "tiktok", "youtube_title")   # the first comment isn't the post; required tags go in these


def load(path: Path) -> dict:
    try:
        brief = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise FactoryError(f"cannot read brief {path}. {exc}") from exc
    if not isinstance(brief, dict):
        raise FactoryError("brief must be a JSON object")
    fields = {"name", "disclosure", "disclosure_seconds", "tags", "banned", "min_seconds", "max_seconds", "notes"}
    if set(brief) - fields:
        raise FactoryError(f"unknown brief fields {', '.join(sorted(set(brief) - fields))}")
    for key in ("name", "disclosure", "notes"):
        if key in brief and not isinstance(brief[key], str):
            raise FactoryError(f"brief {key} must be text")
    if "disclosure" in brief and not brief["disclosure"].strip():
        raise FactoryError("brief disclosure must not be empty")
    for key in ("tags", "banned"):
        if key in brief:
            if not isinstance(brief[key], list) or any(not isinstance(s, str) or not s.strip() for s in brief[key]):
                raise FactoryError(f"brief {key} must be a list of non-empty text")
            brief[key] = list(dict.fromkeys(s.strip() for s in brief[key]))
    for key in ("min_seconds", "max_seconds", "disclosure_seconds"):
        if key in brief:
            value = brief[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise FactoryError(f"brief {key} must be a positive number of seconds")
    if not 1 <= brief.get("disclosure_seconds", 2.0) <= 5:
        raise FactoryError("brief disclosure_seconds must be between 1 and 5")
    if brief.get("min_seconds", 0) > brief.get("max_seconds", math.inf):
        raise FactoryError("brief min_seconds must be no greater than max_seconds")
    return brief


def read(project: Path) -> dict:
    path = project / "brief.json"
    return load(path) if path.is_file() else {}


def length_errors(brief: dict, seconds: float) -> list[str]:
    out = []
    for key, fails, limit in (("min_seconds", seconds < brief.get("min_seconds", 0), "at least"),
                              ("max_seconds", seconds > brief.get("max_seconds", math.inf), "at most")):
        if fails:
            out.append(f"clip runs {seconds:g} seconds; brief allows {limit} {brief[key]:g} seconds")
    return out


def missing_tags(text: str, tags: list[str]) -> list[str]:
    return [tag for tag in tags if not re.search(r"(?<!\w)" + re.escape(tag) + r"(?!\w)", text, re.IGNORECASE)]


def disclosure(brief: dict) -> dict | None:
    return {"text": brief["disclosure"], "from": 0, "to": brief.get("disclosure_seconds", 2.0)} if brief.get("disclosure") else None


def check(d: Path, brief: dict, seconds: float, hook: str, words: list[dict], overlay: dict | None) -> dict:
    from .pipeline import _read, _write
    post = _read(d / "post.json", {})
    errors, flags = length_errors(brief, seconds), []
    expected = disclosure(brief)
    if expected and (overlay != expected or seconds < expected["to"]):
        errors.append(f"missing disclosure for the first {expected['to']:g} seconds")
    for field in POSTED:
        missing = missing_tags(post.get(field, ""), brief.get("tags", []))
        if missing:
            flags.append({"kind": "tags", "where": field, "tags": missing,
                          "why": f"{field} is missing {' '.join(missing)}"})
    texts = {"hook": hook.replace("*", ""), **{k: post.get(k, "") for k in (*POSTED, "first_comment")},
             "spoken": " ".join(w["w"] for w in words)}
    for term in brief.get("banned", []):
        pattern = r"(?<!\w)" + r"""[\s,.;:?!'"()‘’“”\u2010-\u2015-]+""".join(re.escape(s) for s in term.split()) + r"(?!\w)"
        for where, text in texts.items():
            if re.search(pattern, text, re.IGNORECASE):
                flags.append({"kind": "banned", "where": where, "term": term,
                              "why": f'Banned term "{term}" in {where}'})
    result = {"seconds": seconds, "errors": errors, "flags": flags}
    _write(d / "brief_check.json", result)
    return result
