"""Conservative, English-oriented clause boundaries; no language model or IO.

These rules detect editing hazards, not semantic truth. See docs/CONTINUITY.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from myzing.contracts import Record

PAUSE_SECONDS = .6
TAILS = set("a an the to of for with from in on at by and or but because if when where whose which that already is are was were produced".split())
PRONOUNS = set("we you i he she they it".split())
DEPENDENT = set("because although unless whereas while if when since".split())


def lex(text):
    return re.findall(r"[\w]+(?:['’][\w]+)*", text.casefold())


def dangling(text):
    parts = lex(text)
    terminal = bool(re.search(r"[.!?;][\"'’)]*$", text)) and not text.endswith("...")
    return (not parts or parts[-1] in TAILS or (parts[-1] in PRONOUNS and not terminal)
            or (parts[0] in DEPENDENT and ("," not in text or not lex(text.rsplit(",", 1)[1])))
            or parts[0] in {"and", "but", "which", "with"} or text.endswith("...")
            or (len(parts) == 1 and text.rstrip().endswith(",") and parts[0] not in {"hello", "yes", "no", "thanks"}))


@dataclass
class Clause(Record):
    start: float
    end: float
    text: str
    boundary: str
    complete: bool
    version: int = 1


def clauses(words):
    """Split at terminal punctuation or >=600 ms silence, never inside a word.

    Commas only split when followed by a pause >=300 ms and the prefix is
    independent. A dependent prefix stays attached to the next clause. A
    truncated final clause remains visible as incomplete, never certified.
    """
    result, group = [], []
    for i, word in enumerate(words):
        group.append(word)
        text = " ".join(w.text.strip() for w in group)
        gap = words[i + 1].start - word.end if i + 1 < len(words) else 0
        terminal = bool(re.search(r"[.!?;][\"'’)]*$", word.text))
        comma = bool(re.search(r",[\"'’)]*$", word.text)) and gap >= .3
        continuation = i + 1 < len(words) and lex(words[i + 1].text)[:1] in (["which"], ["just"], ["because"])
        reason = "punctuation" if terminal or comma else "pause" if gap >= PAUSE_SECONDS else "source_end"
        if i + 1 == len(words) or ((terminal or comma or gap >= PAUSE_SECONDS) and not dangling(text) and not continuation):
            complete = not dangling(text) and (terminal or comma or gap >= PAUSE_SECONDS)
            result.append(Clause(group[0].start, group[-1].end, text, reason, complete))
            group = []
    return result


def expand_clauses(span, words):
    start, end = span
    for clause in clauses(words):
        if min(end, clause.end) > max(start, clause.start):
            start, end = min(start, clause.start), max(end, clause.end)
    return start, end


def score(sequence, studies, *, allow_reordering=False):
    lookup = {c.asset_id: c for c in studies}
    complete = partial = endings = order = 0
    previous, evidence = {}, []
    for c in sequence:
        last = previous.get(c.content)
        if last is not None and c.start < last - 1e-8:
            order += 1
        previous[c.content] = c.end
        for clause in clauses(lookup[c.asset_id].words):
            if min(c.end, clause.end) <= max(c.start, clause.start) + 1e-8:
                continue
            whole = c.start <= clause.start + 1e-8 and c.end >= clause.end - 1e-8
            ok = whole and clause.complete
            complete += int(ok)
            partial += int(not whole)
            endings += int(not ok)
            evidence.append({"asset_id": c.asset_id, **clause.to_dict(), "selected_whole": whole})
    total = complete + endings
    # A selection with no speech has nothing to grade: report it as not
    # applicable instead of a perfect score that would outrank real speech.
    value = (None if not total else
             round(max(0., complete / total - (0 if allow_reordering else order * .25)), 4))
    return {"version": 1, "score": value, "complete_clauses": complete,
            "partial_clauses": partial, "dangling_endings": endings,
            "source_order_violations": order, "reordering_allowed": allow_reordering,
            "status": ("flagged" if endings or (order and not allow_reordering)
                       else "pass" if total else "not_applicable"),
            "clauses": evidence, "basis": "Punctuation and pause rules; semantic coherence and ASR accuracy unverified."}
