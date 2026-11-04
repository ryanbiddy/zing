"""What the shot plan adds to a clip, measured from its local files."""
from __future__ import annotations

import json
from pathlib import Path

from .render import timeline

KINDS = ("picture", "graphic", "quote", "name tag", "title")


def _read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _text(parts) -> str:
    return " ".join(" · ".join(str(p) for p in parts if p is not None and p != "").replace("*", "").split())[:160]


def _graphic(g: dict) -> str:
    kind = g.get("kind")
    if kind in ("quote", "title"):
        return _text([g.get("text")])
    if kind == "endcard":
        return _text([g.get("name"), g.get("line"), g.get("url")])
    if kind == "counter":
        return _text([g.get("title"), f"{g.get('prefix', '')}{g.get('value', '')}{g.get('suffix', '')}", g.get("label")])
    if kind == "list":
        return _text([g.get("title"), *(r.get("text") for r in g.get("items", []))])
    if kind == "funnel":
        return _text([g.get("title"), *(_text([r.get("text", r.get("value")), r.get("label")]) for r in g.get("rows", []))])
    return ""


def _seconds(items: list[dict]) -> float:
    total, end = 0, 0
    for s in sorted(items, key=lambda s: s["from"]):
        total += max(0, s["to"] - max(end, s["from"]))
        end = max(end, s["to"])
    return round(total, 3)


def added(clipdir: Path) -> dict:
    d = Path(clipdir)
    plan = _read(d / "plan.json", {"shots": []})
    words = _read(d / "words.json", {"words": [], "duration": 0})
    duration, shots, quotes = timeline(plan, words)
    visdir = d / "visuals"
    requests = _read(visdir / "requests.json", []) or _read(d / "plan-raw.json", {}).get("visual_requests", [])
    requests = {r["id"]: r for r in requests}
    manifest = _read(visdir / "manifest.json", {})
    items = []

    def put(a, b, kind, what, source="said in the clip", license=""):
        a, b = round(max(0, a), 3), round(min(duration, b), 3)
        spans = [(a, b)]
        for q in quotes if kind != "quote" else []:    # a quote takes over the screen
            spans = [(x, y) for lo, hi in spans for x, y in ((lo, min(hi, q["from"])), (max(lo, q["to"]), hi)) if y > x]
        for a, b in spans:
            if b > a and what:
                items.append({"from": a, "to": b, "kind": kind, "what": what, "source": source, "license": license})

    for q in quotes:
        put(q["from"], q["to"], "quote", _text([" ".join(w["w"] for w in words["words"][q["a"]:q["b"] + 1])]))
    for s in shots:
        a, b = s["from"], s["to"]
        if s.get("layout") == "split" and s.get("visual") in plan.get("visuals", {}):
            rid = s["visual"]
            v, r = plan["visuals"][rid], requests.get(rid, {})
            c = next((c for c in manifest.get(rid, []) if c.get("path") and v.get("path")
                      and (visdir / c["path"]).resolve() == Path(v["path"]).resolve()), {})
            what = _text([r.get("query") or r.get("entity") or c.get("entity") or c.get("title") or rid])
            source = c.get("source_url") or c.get("credit_text") or v.get("credit") or c.get("file_url") \
                or c.get("creator") or c.get("source") or "unknown"
            put(a, b, "picture", what, source, c.get("license") or v.get("license") or "")
        if s.get("layout") == "graphic":
            g = s.get("graphic") or {}
            kind = "title" if g.get("kind") in ("title", "endcard") else "graphic"
            put(a, b, kind, _graphic(g))
        label = s.get("label") or {}
        if label.get("name"):
            put(a, min(b, a + 3.4), "name tag", _text([label["name"]]))
    items.sort(key=lambda s: (s["from"], s["to"], s["kind"]))
    total = _seconds(items)
    return {"duration": duration, "added": total, "share": round(total / duration, 2) if duration else 0,
            "by_kind": {k: _seconds([s for s in items if s["kind"] == k]) for k in KINDS}, "items": items}
