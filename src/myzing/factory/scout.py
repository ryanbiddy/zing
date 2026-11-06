"""Scout: pick the strongest self-contained moments from an episode transcript, then snap them to sentences."""
from __future__ import annotations

import re

from . import campaign
from .tools import data_path

FILLER = {"and", "so", "yeah", "well", "um", "uh", "like", "okay", "ok"}
ARCHETYPES = ("confession", "conflict", "counterintuitive", "how_it_works", "funny", "origin", "prediction", "other")


def prompt(segments: list[dict], n: int, mode: str = "context", *, focus: str | None = None,
           taste: list[dict] | None = None, news: dict | None = None, brief: dict | None = None,
           channel: str | None = None) -> str:
    lines = "\n".join(f"[{s['s']:.1f}-{s['e']:.1f}] {s['text']}" for s in segments)
    if news:   # the clips are the backstory to today's news
        lines = (f"NEWS PEG: {news['peg']}\nThese clips are posted as \"here's how it happened\" shorts about this news. "
                 "Favor moments where the speaker explains how it came about: the origin, the turning points, the bets "
                 "and the numbers.\n\n" + lines)
    return (data_path("prompts", "scout-launch.md" if mode == "launch" else "scout.md").read_text(encoding="utf-8")
            .replace("{LENGTH}", length_rule(brief or {}, mode)).replace("{BRIEF}", brief_rules(brief or {}))
            .replace("{N}", str(n)).replace("{STEER}", steer(focus, taste, channel)).replace("{TRANSCRIPT}", lines))


def length_bounds(brief: dict, mode: str) -> dict:
    return {key: brief[key] + margin for key, margin in (("min_seconds", 1.0),
            ("max_seconds", -4.0 if mode == "launch" else -1.0)) if key in brief}


def length_rule(brief: dict, mode: str) -> str:
    brief = length_bounds(brief, mode)
    low, high = brief.get("min_seconds"), brief.get("max_seconds")
    if low is not None or high is not None:
        bounds = f"{low:g} to {high:g}" if low is not None and high is not None else (
            f"at least {low:g}" if low is not None else f"at most {high:g}")
        return f"Each clip must use {bounds} seconds of source material in total."
    return ("40 to 120 seconds of speech in total. A second film can be a 20 to 35 second teaser."
            if mode == "launch" else "25–70 seconds of speech.")


def brief_rules(brief: dict) -> str:
    out = []
    if brief.get("banned"):
        out.append("Avoid these topics. " + "; ".join(brief["banned"]))
    if brief.get("notes"):
        out.append(brief["notes"])
    return "Campaign rules\n" + "\n".join(out) + "\n\n" if out else ""


CALLS = {"post": "POSTED", "fix": "POSTED AFTER EDITS", "no": "PASSED"}


def steer(focus: str | None, taste: list[dict] | None, channel: str | None = None) -> str:
    """What the user asked for, and the Post/No calls they made on earlier clips of this show."""
    out = []
    if focus:
        out.append(f"WHAT THE USER WANTS: {focus}\nFavor moments about this. If fewer fit than asked for, fill the rest "
                   "with the strongest other moments, and say in each 'why' whether it is on the user's ask.")
    calls = [r for r in taste or [] if r.get("v") in CALLS and r.get("hook")]
    if calls:
        out.append("THE USER'S PAST CALLS on clips from this show, newest first. Learn what they post and what they "
                   "pass on, and don't pick moments like the passed ones:\n" + "\n".join(
                       f"- {CALLS[r['v']]}: \"{r['hook'].replace('*', '')}\"" + (f" ({r['topic']})" if r.get("topic") else "")
                       + (f". Their reason: {r['why']}" if r.get("why") else "") for r in calls))
    if channel:
        from myzing.channels.learn import steer as learned
        out.append(learned(channel))
    return "\n\n".join(out) + "\n\n" if out else ""


def parts(moment: dict) -> list[list[float]]:
    """The spans a moment plays, in order: one for a clip, several for a launch film."""
    return [[s["start"], s["end"]] for s in moment["spans"]] if moment.get("spans") else [[moment["start"], moment["end"]]]


def check(answer: dict, duration: float | None = None, brief: dict | None = None, mode: str = "context") -> list[dict]:
    moments = answer.get("moments")
    if not isinstance(moments, list) or not moments:
        raise ValueError("scout answer needs a non-empty 'moments' list")
    out, off = [], []
    for m in moments:
        spans = [{"start": float(s["start"]), "end": float(s["end"]), "role": str(s.get("role", ""))}
                 for s in m.get("spans") or []]
        for s in spans or [{"start": float(m["start"]), "end": float(m["end"])}]:
            if not 0 <= s["start"] < s["end"] or (duration and s["start"] >= duration):
                raise ValueError(f"moment {s['start']}-{s['end']} is outside the episode")
        if any(a["start"] < b["end"] and b["start"] < a["end"] for i, a in enumerate(spans) for b in spans[i + 1:]):
            raise ValueError("a film uses the same part of the recording twice")
        rec = {"hook": str(m["hook"]), "why": str(m.get("why", "")), "topic": str(m.get("topic", "")), "score": m.get("score", "")}
        rec["archetype"] = m.get("archetype") if m.get("archetype") in ARCHETYPES else "other"
        if spans:
            rec.update(start=spans[0]["start"], end=spans[-1]["end"], spans=spans)
        else:
            rec.update(start=float(m["start"]), end=float(m["end"]))
        errors = campaign.length_errors(length_bounds(brief or {}, mode), sum(b - a for a, b in parts(rec)))
        if errors:                                  # one long pick drops out; the rest of the answer stands
            off += errors
            continue
        out.append(rec)
    if not out:
        raise ValueError("; ".join(off))
    return out


def snap(moment: dict, words: list[dict], brief: dict | None = None, mode: str = "context") -> dict:
    """End on a sentence end and start after a leading filler word (And/So/Yeah/Well/Um); each span of a film alike."""
    if moment.get("spans"):
        spans = [{**s, **{k: v for k, v in _snap(s, words).items() if k in ("start", "end")}} for s in moment["spans"]]
        snapped = {**moment, "spans": spans, "start": spans[0]["start"], "end": spans[-1]["end"]}
    else:
        snapped = _snap(moment, words)
    return moment if campaign.length_errors(length_bounds(brief or {}, mode), sum(b - a for a, b in parts(snapped))) else snapped


def _snap(moment: dict, words: list[dict]) -> dict:
    ws = [w for w in words if moment["start"] - 0.05 <= w["s"] <= moment["end"] + 6.5]
    if not ws:
        return moment
    k = 0
    while k < len(ws) - 1 and re.sub(r"[^a-z]", "", ws[k]["w"].lower()) in FILLER:
        k += 1
    start = max(0.0, ws[k]["s"] - 0.05)
    inside = [w for w in ws[k:] if w["e"] <= moment["end"] + 0.05] or ws[k:k + 1]
    end_word = inside[-1]
    if not moment.get("whole") and not re.search(r"[.?!]$", end_word["w"]):   # a whole recorded take keeps its end
        after = [w for w in ws if w["s"] > end_word["s"] and re.search(r"[.?!]$", w["w"])]
        before = [w for w in inside if re.search(r"[.?!]$", w["w"]) and w["e"] > start + 20]
        end_word = after[0] if after else (before[-1] if before else end_word)
    return {**moment, "scout_start": moment["start"], "scout_end": moment["end"],
            "start": round(start, 2), "end": round(end_word["e"] + 0.05, 2)}
