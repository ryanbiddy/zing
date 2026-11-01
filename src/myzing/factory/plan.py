"""On-screen plan for one clip: layouts, graphics drawn only from spoken facts, and visual requests."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .tools import data_path

LAYOUTS = ("solo", "split", "graphic")
GRAPHICS = ("counter", "list", "funnel", "quote")
SMALL = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
         "seventeen eighteen nineteen").split()
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def words_block(words: list[dict]) -> str:
    out, line = [], []
    for w in words:
        line.append(f"{w['os']:.2f}:{w['w']}")
        if len(line) == 10 or re.search(r"[.?!]$", w["w"]):
            out.append(" ".join(line))
            line = []
    if line:
        out.append(" ".join(line))
    return "\n".join(out)


def prompt(moment: dict, words: dict, mode: str = "context") -> str:
    text = data_path("prompts", "plan.md").read_text(encoding="utf-8")
    for k, v in {"{TOPIC}": moment.get("topic", ""), "{HOOK}": moment["hook"], "{DURATION}": f"{words['duration']:.1f}",
                 "{WORDS}": words_block(words["words"]),
                 "{STYLE}": data_path("prompts", f"style-{mode}.md").read_text(encoding="utf-8").strip()}.items():
        text = text.replace(k, v)
    return text


def check(plan: dict) -> dict:
    if not isinstance(plan.get("hook"), str) or not isinstance(plan.get("shots"), list) or not plan["shots"]:
        raise ValueError("plan needs a hook and a non-empty shots list")
    for s in plan["shots"]:
        if s.get("layout") not in LAYOUTS or not isinstance(s.get("from"), (int, float)):
            raise ValueError(f"bad shot {s}")
        if s["layout"] == "graphic" and (s.get("graphic") or {}).get("kind") not in GRAPHICS:
            raise ValueError(f"bad graphic in shot at {s['from']}")
    ids = {r.get("id") for r in plan.get("visual_requests", [])}
    for s in plan["shots"]:
        if s["layout"] == "split" and s.get("visual") not in ids:
            s.update(layout="solo")
            s.pop("visual", None)
    return plan


def _norm(x: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", x.lower().replace(",", "").replace("-", " ").replace("–", " "))


def spoken_numbers(words: list[dict]) -> tuple[str, set[str]]:
    spoken = " " + " ".join(_norm(w["w"]) for w in words) + " "
    nums = set(re.findall(r"\d+(?:\.\d+)?", spoken))
    toks = spoken.split()
    for j, tok in enumerate(toks):
        nxt = toks[j + 1] if j + 1 < len(toks) else ""
        if tok in SMALL:
            nums.add(str(SMALL.index(tok)))
        if tok in TENS:
            nums.add(str(TENS[tok] + (SMALL.index(nxt) if nxt in SMALL[1:10] else 0)))
        if tok == "hundred" and j and toks[j - 1] in SMALL:
            nums.add(str(SMALL.index(toks[j - 1]) * 100))
        if tok in ("half", "a") and nxt == "dozen":
            nums.add("12" if tok == "a" else "6")
    return spoken, nums


def fact_check(graphic: dict, words: list[dict]) -> list:
    """What the graphic draws that the clip never says: every number must be spoken, a quote word for word."""
    spoken, nums = spoken_numbers(words)

    def said(v) -> bool:
        try:
            return any(abs(float(n) - float(v)) < 1e-6 for n in nums)
        except (TypeError, ValueError):
            return False
    kind, shown = graphic.get("kind"), []
    if kind == "counter":
        shown = [graphic.get("value")]
    elif kind == "funnel":
        for r in graphic.get("rows", []):
            shown += re.findall(r"\d+(?:\.\d+)?", str(r.get("text", "")).replace(",", "")) or [r.get("value")]
    elif kind == "list":
        for item in graphic.get("items", []):
            shown += re.findall(r"\d+(?:\.\d+)?", str(item.get("text", "")).replace(",", ""))
    bad = [v for v in shown if not said(v)]
    if kind == "quote" and f" {_norm(str(graphic.get('text', '')).replace('*', ''))} " not in spoken:
        bad.append("quote")
    return bad


def finalize(clipdir: Path, plan: dict, found: dict[str, dict]) -> dict:
    """Drop what can't be shown honestly: unspoken graphics and splits without a usable visual become solo."""
    d = Path(clipdir)
    words = json.loads((d / "words.json").read_text(encoding="utf-8"))["words"]
    shots, log, quoted = [], [], False
    for s in plan["shots"]:
        if s.get("layout") == "graphic":
            bad = fact_check(s.get("graphic", {}), words)
            if bad:
                log.append(f"dropped {s['graphic'].get('kind')} at {s['from']}: not spoken {bad}")
                s = {"from": s["from"], "layout": "solo"}
            elif s["graphic"].get("kind") == "quote":
                if quoted:                         # the takeover only lands once a clip
                    log.append(f"dropped quote at {s['from']}: one quote per clip")
                    s = {"from": s["from"], "layout": "solo"}
                quoted = True
        if s.get("layout") == "split" and s.get("visual") not in found:
            s = {"from": s["from"], "layout": "solo"}
        shots.append(s)
    final = {"hook": plan["hook"], "hook_until": plan.get("hook_until", 3.0), "shots": shots,
             "sensitive": bool(plan.get("sensitive")), "sensitive_reason": plan.get("sensitive_reason", ""),
             "visuals": {k: v for k, v in found.items() if any(s.get("visual") == k for s in shots)}}
    hook_bad = fact_check({"kind": "list", "items": [{"text": plan["hook"].replace("*", "")}]}, words)
    if hook_bad:
        log.append(f"hook number not spoken {hook_bad}: review the hook")
    final["fact_check"] = log or ["every drawn number and quote is in the clip's words"]
    (d / "plan.json").write_text(json.dumps(final, indent=1, ensure_ascii=False), encoding="utf-8")
    return final
