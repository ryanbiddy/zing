"""On-screen plan for one clip: layouts, graphics drawn only from spoken facts, and visual requests."""
from __future__ import annotations

import difflib
import json
import math
import re
from pathlib import Path

from .tools import NO_HOOK, data_path

LAYOUTS = ("solo", "split", "graphic")
GRAPHICS = ("counter", "list", "funnel", "quote", "title", "endcard")
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


def prompt(moment: dict, words: dict, mode: str = "context", brand: dict | None = None,
           vocab: list[str] | None = None, news: dict | None = None) -> str:
    from .postcopy import brand_line, news_line
    text = data_path("prompts", "plan.md").read_text(encoding="utf-8")
    spellings = ("SPELLINGS: " + ", ".join(vocab) + "\n"
                 "Names and terms in SPELLINGS are spelled exactly so; a near-miss in WORDS is a fix.\n") if vocab else ""
    for k, v in {"{TOPIC}": moment.get("topic", ""), "{HOOK}": moment["hook"] or NO_HOOK,
                 "{DURATION}": f"{words['duration']:.1f}",
                 "{BRAND}": brand_line(brand), "{SPELLINGS}": spellings, "{NEWS}": news_line(news, links=True),
                 "{WORDS}": words_block(words["words"]),
                 "{STYLE}": data_path("prompts", f"style-{mode}.md").read_text(encoding="utf-8").strip()}.items():
        text = text.replace(k, v)
    return text


def _in_clip(at, last_word: float | None = None) -> bool:
    return isinstance(at, (int, float)) and 0 <= at <= (last_word + 3 if last_word is not None else float("inf")) \
        and math.isfinite(at)


def visual_id(value, used: set[str]) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-")[:60] or "item"
    while safe in used:
        safe += "_"
    used.add(safe)
    return safe


def check(plan: dict, last_word: float | None = None) -> dict:
    if not isinstance(plan.get("hook"), str) or not isinstance(plan.get("shots"), list) or not plan["shots"]:
        raise ValueError("plan needs a hook and a non-empty shots list")
    shots = []
    for s in plan["shots"]:
        if s.get("layout") not in LAYOUTS or not isinstance(s.get("from"), (int, float)):
            raise ValueError(f"bad shot {s}")
        if not _in_clip(s["from"], last_word):
            continue
        if s["layout"] == "graphic" and (s.get("graphic") or {}).get("kind") not in GRAPHICS:
            raise ValueError(f"bad graphic in shot at {s['from']}")
        shots.append(s)
    plan["shots"] = shots or [{"from": 0, "layout": "solo"}]
    ids, used = {}, set()
    for r in plan.get("visual_requests", []):
        old = r.get("id", "")
        r["id"] = visual_id(old, used)
        ids.setdefault(old, r["id"])
    for s in plan["shots"]:
        if "visual" in s:
            s["visual"] = ids.get(s["visual"], s["visual"])
        if s["layout"] == "split" and s.get("visual") not in used:
            s.update(layout="solo")
            s.pop("visual", None)
    return plan


def _norm(x: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", x.lower().replace(",", "").replace("-", " ").replace("–", " "))


def tokens(words: list[dict]) -> tuple[list[str], list[int]]:
    """Normalized tokens of the words, and the word each token came from."""
    toks, owner = [], []
    for i, w in enumerate(words):
        for tok in _norm(w["w"]).split():
            toks.append(tok)
            owner.append(i)
    return toks, owner


def apply_fixes(words: list[dict], fixes) -> tuple[list[dict], list[tuple[str, str]], list[str]]:
    """Correct clear mishearings the planner names: a sound-alike name or term, never a number or a new meaning.

    Returns the corrected words, the (heard, meant) pairs applied, and a log line per fix.
    """
    words, done, log = [dict(w) for w in words], [], []
    for f in fixes if isinstance(fixes, list) else []:
        heard, meant = str((f or {}).get("heard", "")).strip(), str((f or {}).get("meant", "")).strip()
        a, b = _norm(heard).split(), _norm(meant).split()
        if not a or not b or a == b or len(a) > 4 or len(b) > 4:
            continue
        if re.search(r"\d", heard + meant) or any(t in SMALL or t in TENS for t in b) \
                or difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio() < .6:
            log.append(f"kept caption {heard!r}: {meant!r} is not a clear mishearing")
            continue
        toks, owner = tokens(words)
        starts = [k for k in range(len(toks) - len(a) + 1) if toks[k:k + len(a)] == a]
        for k in reversed(starts):
            i, j = owner[k], owner[k + len(a) - 1]
            tail = re.search(r"[^\w']*$", words[j]["w"]).group()      # keep the sentence's punctuation
            new = meant.split()
            if len(new) == j - i + 1:
                for n, w in enumerate(new):
                    words[i + n]["w"] = w + (tail if i + n == j else re.search(r"[^\w']*$", words[i + n]["w"]).group())
            else:
                words[i:j + 1] = [{**words[i], "w": meant + tail, "oe": words[j]["oe"]}]
        if starts:
            done.append((heard, meant))
            log.append(f"caption fix: {heard!r} -> {meant!r}" + (f" (x{len(starts)})" if len(starts) > 1 else ""))
    return words, done, log


def _fix_text(value, pairs: list[tuple[str, str]]):
    """The same corrections in on-screen text and copy, case-insensitive."""
    if isinstance(value, str):
        for heard, meant in pairs:
            pattern = f"(?:{re.escape(meant)})|(?:{re.escape(heard)})" if heard.lower() in meant.lower() else re.escape(heard)
            value = re.sub(rf"(?<!\w)(?:{pattern})(?!\w)", lambda m: meant, value, flags=re.IGNORECASE)
        return value
    if isinstance(value, list):
        return [_fix_text(v, pairs) for v in value]
    if isinstance(value, dict):
        return {k: _fix_text(v, pairs) for k, v in value.items()}
    return value


def spoken_numbers(words: list[dict]) -> tuple[str, set[str]]:
    spoken = " " + " ".join(_norm(w["w"]) for w in words) + " "
    nums = set(re.findall(r"\d+(?:\.\d+)?", spoken))
    nums |= set(re.findall(r"\d+\.\d+", " ".join(str(w["w"]).replace(",", "") for w in words)))   # "$6.3" keeps its point
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


FILLER = set("a an the of and or to in on for at by with from is are was it its this that our your my we i".split())


def _stem(w: str) -> str:
    return re.sub(r"(ing|ed|es|s|ly)$", "", w) if len(w) > 4 else w


def site(url: str) -> str:
    """A url as people read it: no scheme, no www, no trailing slash."""
    return re.sub(r"^(https?://)?(www\.)?", "", str(url).strip().lower()).rstrip("/")


def ungrounded(text: str, spoken: str, brand: dict | None = None) -> list[str]:
    """Words of a name, role or line that neither the clip nor the brand says (small words and word endings don't count)."""
    known = {_stem(k) for k in set(spoken.split()) | set(_norm(" ".join(str(v) for v in (brand or {}).values())).split())}
    return [t for t in _norm(str(text)).split() if t not in FILLER and _stem(t) not in known]


def on_screen(label: dict, shot: dict, people: str, requests: dict) -> bool:
    """A name tag names someone the viewer sees: the speaker, by a name the source credit or brand gives, or on a
    split shot the person pictured. Never the speaker labelled with someone they only mention."""
    name = [_stem(w) for w in _norm(label.get("name", "")).split() if w not in FILLER]

    def has(text: str) -> bool:
        return bool(name) and set(name) <= {_stem(w) for w in _norm(text).split()}
    request = requests.get(shot.get("visual")) or {} if shot.get("layout") == "split" else {}
    return has(people) or has(f"{request.get('entity', '')} {request.get('query', '')}")


def fact_check(graphic: dict, words: list[dict], brand: dict | None = None) -> list:
    """What the graphic draws that the clip never says: every number must be spoken, a quote word for word, a name
    or line said in the clip or given by the brand."""
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
    elif kind == "title":
        shown = re.findall(r"\d+(?:\.\d+)?", str(graphic.get("text", "")))
    elif kind == "endcard":
        shown = re.findall(r"\d+(?:\.\d+)?", f"{graphic.get('name', '')} {graphic.get('line', '')}")
    bad = [v for v in shown if not said(v)]
    if kind == "quote" and f" {_norm(str(graphic.get('text', '')).replace('*', ''))} " not in spoken:
        bad.append("quote")
    if kind == "title":
        bad += ungrounded(re.sub(r"(?i)^\s*introducing\s+", "", str(graphic.get("text", "")).replace("*", "")), spoken, brand)
    if kind == "endcard":
        bad += ungrounded(f"{graphic.get('name', '')} {graphic.get('line', '')}", spoken, brand)
        if graphic.get("url") and site(graphic["url"]) != site((brand or {}).get("url", ""))                 and _norm(site(graphic["url"])) not in spoken:
            bad.append(graphic["url"])
    return bad


def finalize(clipdir: Path, plan: dict, found: dict[str, dict], brand: dict | None = None,
             news: dict | None = None) -> dict:
    """Drop what can't be shown honestly: unspoken graphics and splits without a usable visual become solo."""
    from .receipt import added
    from .pipeline import _write
    from . import campaign, postcopy
    d = Path(clipdir)
    heard = d / "words-heard.json"                     # the speech model's words, kept once a fix changes them
    data = json.loads((heard if heard.is_file() else d / "words.json").read_text(encoding="utf-8"))
    words, pairs, log = apply_fixes(data["words"], plan.get("fixes"))
    manual = d / "word-fixes.json"
    fixes = json.loads(manual.read_text(encoding="utf-8")) if manual.is_file() else []
    applied = []
    for f in fixes:
        i = f["index"]
        matches = [words[i]] if 0 <= i < len(words) and (words[i]["os"], words[i]["oe"]) == (f["os"], f["oe"]) else [
            w for w in words if w["os"] == f["os"] and w["oe"] == f["oe"]]
        if len(matches) == 1:
            matches[0]["w"] = f["meant"]
            applied.append(f)
            log.append(f"caption fix: {f['heard']!r} -> {f['meant']!r}")
        else:
            log.append(f"caption fix at {f['os']} no longer matches a word: review the captions")
    if pairs or applied or heard.is_file():
        if not heard.is_file():
            heard.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (d / "words.json").write_text(json.dumps({**data, "words": words}, ensure_ascii=False), encoding="utf-8")
    text_pairs = pairs + [(f["heard"], f["meant"]) for f in applied]
    plan = _fix_text({k: v for k, v in plan.items() if k != "fixes"}, text_pairs)
    post = d / "post.json"
    if text_pairs and post.is_file():                  # the copy was written from the same words
        copy = json.loads(post.read_text(encoding="utf-8"))
        for field in postcopy.FIELDS:
            if field in copy:
                copy[field] = _fix_text(copy[field], text_pairs)
        for option in copy.get("title_options", []):
            option["text"] = _fix_text(option["text"], text_pairs)
        chosen = next((t for t in copy.get("title_options", []) if t["pattern"] == copy.get("title_pattern")), None)
        if chosen:
            copy["youtube_title"] = postcopy.require_tags({"youtube_title": chosen["text"]}, campaign.read(d.parent))["youtube_title"]
        post.write_text(json.dumps(copy, indent=1, ensure_ascii=False), encoding="utf-8")
    shots, quoted = [], False
    spoken = spoken_numbers(words)[0]
    src = d.parent / "source.json"
    source = json.loads(src.read_text(encoding="utf-8")) if src.is_file() else {}
    intro = " ".join(_norm(name) for name in re.findall(
        r"(?i:\bI['’]m|\bI am|\bmy name is|\bmy name['’]s)\s+((?:[A-Z][\w'-]*\s?){1,3})", " ".join(w["w"] for w in words)))
    people = " ".join(str(v) for v in (source.get("name"), source.get("tag"), (brand or {}).get("name"), intro) if v)
    requests = {r.get("id"): r for r in plan.get("visual_requests", []) if isinstance(r, dict)}
    for s in plan["shots"]:
        if not _in_clip(s.get("from"), words[-1]["oe"]):
            log.append(f"dropped shot at {s.get('from')} outside the clip")
            continue
        label = s.get("label")
        if label is not None:
            stray = ungrounded(f"{(label or {}).get('name', '')} {(label or {}).get('role', '')}", spoken, brand) \
                if isinstance(label, dict) and label.get("name") else ["no name"]
            if stray:
                log.append(f"dropped name tag at {s['from']}: not said {stray}")
                s = {k: v for k, v in s.items() if k != "label"}
        if s.get("layout") == "graphic":
            bad = fact_check(s.get("graphic", {}), words, brand)
            if bad:
                log.append(f"dropped {s['graphic'].get('kind')} at {s['from']}: not spoken {bad}")
                s = {"from": s["from"], "layout": "solo", **({"label": s["label"]} if s.get("label") else {})}
            elif s["graphic"].get("kind") == "endcard" and s["graphic"].get("url"):
                s = {**s, "graphic": {**s["graphic"], "url": site(s["graphic"]["url"])}}   # shown as people type it
            elif s["graphic"].get("kind") == "quote":
                if quoted:                         # the takeover only lands once a clip
                    log.append(f"dropped quote at {s['from']}: one quote per clip")
                    s = {"from": s["from"], "layout": "solo"}
                quoted = True
        if s.get("layout") == "split" and s.get("visual") not in found:
            s = {"from": s["from"], "layout": "solo"}
        if s.get("label") and not on_screen(s["label"], s, people, requests):
            log.append(f"dropped name tag at {s['from']}: {s['label'].get('name')} is not the person on screen")
            s = {k: v for k, v in s.items() if k != "label"}
        shots.append(s)
    final = {"hook": plan["hook"], "hook_until": plan.get("hook_until", 3.0), "shots": shots or [{"from": 0, "layout": "solo"}],
             "sensitive": bool(plan.get("sensitive")), "sensitive_reason": plan.get("sensitive_reason", ""),
             "visuals": {k: v for k, v in found.items() if any(s.get("visual") == k for s in shots)},
             "fixes": [{"heard": h, "meant": m} for h, m in pairs] + applied}
    peg = [{"w": t, "s": 0.0, "e": 0.0} for t in str((news or {}).get("peg", "")).split()]   # the news is given, not spoken
    hook_bad = fact_check({"kind": "list", "items": [{"text": plan["hook"].replace("*", "")}]}, words + peg)
    if hook_bad:
        log.append(f"hook number not spoken {hook_bad}: review the hook")
    final["fact_check"] = log or ["every drawn number and quote is in the clip's words"]
    _write(d / "plan.json", final)
    (d / "receipt.json").write_text(json.dumps(added(d), indent=1, ensure_ascii=False), encoding="utf-8")
    return final
