"""Conservative, English-oriented clause boundaries; no language model or IO.

These rules detect editing hazards, not semantic truth. See docs/CONTINUITY.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from myzing.contracts import Record

PAUSE_SECONDS = .6
MAX_CLAUSE_SECONDS = 20.
MAX_CLAUSE_SENTENCES = 3
TAILS = set("a an the to of for with from in on at by and or but because if when where whose which that already is are was were produced".split())
PRONOUNS = set("we you i he she they it".split())
DEPENDENT = set("because although unless whereas while if when since".split())
DEPENDENT_OPENERS = DEPENDENT | {"and", "but", "so", "which", "with", "just"}


def lex(text):
    return re.findall(r"[\w]+(?:['’][\w]+)*", text.casefold())


def dangling(text, *, check_opening=True):
    """Check editorial hazards; closure can check the ending independently."""
    parts = lex(text)
    terminal = bool(re.search(r"[.!?;][\"'’)]*$", text)) and not text.endswith("...")
    return (not parts or parts[-1] in TAILS or (parts[-1] in PRONOUNS and not terminal)
            or (check_opening and parts[0] in DEPENDENT and ("," not in text or not lex(text.rsplit(",", 1)[1])))
            or (check_opening and parts[0] in {"and", "but", "which", "with"}) or text.endswith("...")
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
    """Close thoughts independently of their opening, then attach context.

    Dependent openings join the previous complete clause across short gaps,
    up to three boundary units (at most three sentences) and 20 seconds.
    Terminal punctuation always closes a unit; >=600 ms pauses close units
    with clean endings. Commas need >=300 ms and an independent prefix.
    Unbroken speech is capped at whole-word boundaries before 20 seconds;
    both pieces of a forced split remain incomplete through the next natural
    boundary. A single word is indivisible even if its timing exceeds the cap.
    """
    units, group = [], []
    fragment = False
    for i, word in enumerate(words):
        if group and word.end - group[0].start > MAX_CLAUSE_SECONDS:
            units.append(Clause(group[0].start, group[-1].end,
                                " ".join(w.text.strip() for w in group), "limit", False))
            group = []
            fragment = True
        group.append(word)
        text = " ".join(w.text.strip() for w in group)
        gap = words[i + 1].start - word.end if i + 1 < len(words) else 0
        terminal = bool(re.search(r"[.!?;][\"'’)]*$", word.text.strip())) and not text.endswith("...")
        comma = bool(re.search(r",[\"'’)]*$", word.text)) and gap >= .3
        clean_end = not dangling(text, check_opening=False)
        comma_boundary = comma and not dangling(text)
        pause_boundary = gap >= PAUSE_SECONDS and clean_end and (not comma or comma_boundary)
        boundary = terminal or comma_boundary or pause_boundary
        if i + 1 == len(words) or boundary:
            reason = "punctuation" if terminal or comma else "pause" if gap >= PAUSE_SECONDS else "source_end"
            complete = clean_end and boundary and not fragment
            units.append(Clause(group[0].start, group[-1].end, text, reason, complete))
            group = []
            fragment = False

    result, count = [], 0
    for unit in units:
        opening = lex(unit.text)[:1]
        if (result and opening and opening[0] in DEPENDENT_OPENERS
                and result[-1].complete and unit.complete
                and unit.start - result[-1].end < PAUSE_SECONDS
                and count < MAX_CLAUSE_SENTENCES
                and unit.end - result[-1].start <= MAX_CLAUSE_SECONDS):
            previous = result[-1]
            result[-1] = Clause(previous.start, unit.end, previous.text + " " + unit.text,
                                unit.boundary, True)
            count += 1
        else:
            result.append(unit)
            count = 1
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
