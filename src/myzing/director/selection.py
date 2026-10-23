"""Bounded editorial search using observed shots, clean takes and whole words."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from statistics import median

from myzing.brief.models import Brief
from myzing.contracts import Record
from myzing.project.models import ProjectManifest
from myzing.style_recipe import StyleRecipe
from myzing.style_ranges import timing_band
from myzing.timing import finite

from .models import ClipStudy, shortage
from .continuity import clauses, expand_clauses

EPS = 1e-8
BEAM = 96
MAX_CANDIDATES = 2400
MAX_STEPS = 120


def tokens(text):
    return re.findall(r"\w+(?:['’]\w+)*", text.casefold())


@dataclass
class Envelope(Record):
    median_shot: float | None
    first_cut: float | None
    first_caption: float | None
    words_visible: int
    all_caps_rate: float
    position: str
    basis: dict
    version: int = 1


def envelope(recipe: StyleRecipe) -> Envelope:
    facts = {f.name: f.value for f in recipe.measured}
    if len(facts) != len(recipe.measured):
        raise ValueError("Recipe has duplicate fact names; keep one authoritative value per fact.")
    durations = facts.get("shot_durations", [])
    if not isinstance(durations, list) or any(not finite(n) or n <= 0 for n in durations):
        raise ValueError("recipe shot_durations must contain positive finite seconds")
    captions = [f.value for f in recipe.measured if re.fullmatch(r"captions\[\d+\]", f.name)]
    for c in captions:
        if (not isinstance(c, dict) or not finite(c.get("start")) or c["start"] < 0
                or type(c.get("words_visible")) is not int or c["words_visible"] < 1
                or type(c.get("all_caps")) is not bool
                or c.get("position") not in {"top", "center", "lower", "bottom"}):
            raise ValueError("recipe caption facts need valid start, words_visible, all_caps and position")
    widths = [c["words_visible"] for c in captions]
    positions = [c["position"] for c in captions]
    return Envelope(
        median(durations) if durations else None,
        durations[0] if len(durations) > 1 else None,
        min(c["start"] for c in captions) if captions else None,
        max(1, round(median(widths))) if widths else 1,
        sum(c["all_caps"] for c in captions) / len(captions) if captions else 0,
        min(set(positions), key=lambda p: (-positions.count(p), p)) if positions else "lower",
        {"pacing": "shot_durations" if durations else "unmeasured; 2s search default",
         "captions": "captions[]" if captions else "unmeasured; one word, original case, lower anchor",
         "caption_events": len(captions), "shot_durations": durations},
    )


def merge(spans):
    result = []
    for start, end in sorted(spans):
        if result and start <= result[-1][1] + EPS:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def subtract(spans, removed):
    for low, high in merge(removed):
        remaining = []
        for start, end in spans:
            if low > start:
                remaining.append((start, min(end, low)))
            if high < end:
                remaining.append((max(start, high), end))
        spans = [(a, b) for a, b in remaining if b - a > EPS]
    return spans


def overlaps(a, b):
    return min(a[1], b[1]) - max(a[0], b[0]) > EPS


def expand_words(span, words):
    start, end = span
    for word in words:
        if word.start < start < word.end:
            start = word.start
        if word.start < end < word.end:
            end = word.end
    return start, end


def constraints(brief: Brief, manifest: ProjectManifest, studies: list[ClipStudy]):
    by_id = {c.asset_id: c for c in studies}
    keep, forbidden = {}, {}
    for field, out in (("must_keep", keep), ("forbidden", forbidden)):
        for moment in getattr(brief, field):
            pool = studies
            if "clip" in moment:
                selector = moment["clip"]
                assets = [a for a in manifest.assets if selector in
                          [a.id, a.path, a.original_path, *a.previous_paths]]
                if len(assets) != 1 or assets[0].id not in by_id:
                    shortage("unknown_constraint_clip", f"{field}: cannot resolve {selector!r} to one video.",
                             "Use an exact inventory ID from zing project status --json.")
                pool = [by_id[assets[0].id]]
            if "phrase" in moment:
                needle = tokens(moment["phrase"])
                if not needle:
                    shortage("invalid_phrase", f"{field}: phrase contains no words.", "Supply exact transcript words.")
                found = []
                for clip in pool:
                    if clip.status != "ready":
                        continue
                    flattened = [(token, w) for w in clip.words for token in tokens(w.text)]
                    for i in range(len(flattened) - len(needle) + 1):
                        part = flattened[i:i + len(needle)]
                        if [t for t, _ in part] == needle:
                            found.append((clip, (part[0][1].start, part[-1][1].end)))
                if field == "must_keep" and len(found) != 1:
                    shortage("must_keep_missing" if not found else "must_keep_ambiguous",
                             f"{moment['phrase']!r} has {len(found)} validated occurrences.",
                             "Study or film the requested line; for repeats, specify clip/start/end.")
            else:
                clip = pool[0]
                found = [(clip, (moment["start"], moment["end"]))]
            for clip, span in found:
                if clip.status != "ready":
                    if field == "forbidden":
                        continue  # This entire unavailable clip is excluded already.
                    shortage("must_keep_unstudied", f"Required moment in {clip.asset_id} has no usable study.",
                             f'Run zing study "{clip.path}" --raw, then correct any timing errors.', clip.asset_id)
                if span[1] > clip.duration + EPS:
                    shortage("must_keep_missing" if field == "must_keep" else "constraint_out_of_range",
                             f"{field} extends beyond {clip.asset_id}'s duration.",
                             "Film the missing moment or shorten the requested span.", clip.asset_id)
                # Exclude whole overlapping words from forbidden ranges too.
                out.setdefault(clip.asset_id, []).append(
                    expand_clauses(span, clip.words) if field == "must_keep" else expand_words(span, clip.words))
    for out in (keep, forbidden):
        for key in out:
            out[key] = merge(out[key])
    # A renamed/duplicated file must not bypass a forbidden source moment.
    for source in studies:
        for duplicate in studies:
            if source.sha256 == duplicate.sha256 and source.asset_id in forbidden:
                forbidden[duplicate.asset_id] = merge(forbidden.get(duplicate.asset_id, []) + forbidden[source.asset_id])
    for key, spans in keep.items():
        if any(overlaps(a, b) for a in spans for b in forbidden.get(key, [])):
            shortage("constraint_conflict", f"Word-safe must-keep and forbidden spans overlap in {key}.",
                     "Move a constraint to a complete word boundary or relax one of the moments.", key)
    return keep, forbidden


@dataclass(frozen=True)
class Candidate(Record):
    asset_id: str
    content: str
    start: float
    end: float
    shot: int
    word_count: int
    first_word: float | None
    text: str
    keeper: bool
    keyframe: bool
    covers: int = 0
    version: int = 1
    dangling_clauses: int = 0

    @property
    def duration(self):
        return self.end - self.start

    @property
    def identity(self):
        return self.content, self.start, self.end


def candidates(studies, keep, forbidden, style, target, *, expand_timing=True):
    """Candidate trims stay within shot regions snapped out of spoken words.

    Must-keeps remain indivisible, even across original visual cuts. Full
    regions and minimal required spans accompany pace-sized excerpts.
    """
    pool = []
    required = [(key, a, b) for key, spans in sorted(keep.items()) for a, b in spans]
    available = 0.0
    pace = style.median_shot or 2.0
    reference = style.basis.get("shot_durations", [])
    bands = [timing_band(value, reference) for value in (style.first_cut, style.median_shot)]
    lengths = {pace, style.first_cut or pace}
    # Keep new trims one delivery frame inside the band: source times are
    # fractional, but the director emits 30 fps plans.
    if expand_timing:
        lengths.update(value for b in bands if b["lower"] is not None
                       for value in (b["lower"] + 1 / 30, b["upper"] - 1 / 30) if value > 0)
    for clip in studies:
        if clip.status != "ready":
            continue
        kept = keep.get(clip.asset_id, [])
        speech = clauses(clip.words)
        quarantine = [(q["start"], q["end"]) for q in clip.asr_repair.get("quarantined", [])]
        dead = subtract([(d["start"], d["end"]) for d in clip.dead_air], kept)
        removed = merge(forbidden.get(clip.asset_id, []) + [expand_words(s, clip.words) for s in dead])
        # A must-keep wins over a dead-air heuristic, including a word-expanded edge.
        removed = merge(forbidden.get(clip.asset_id, []) + subtract(removed, kept) + quarantine)
        allowed = subtract([(0, clip.duration)], removed)
        available += sum(b - a for a, b in allowed)
        bits = [(1 << i, (a, b)) for i, (key, a, b) in enumerate(required) if key == clip.asset_id]

        def add(start, stop):
            if not .2 <= stop - start <= target + .1:
                return
            if any(overlaps((start, stop), part) and not
                   (start <= part[0] + EPS and stop >= part[1] - EPS) for _, part in bits):
                return
            if subtract([(start, stop)], [(s.start, s.end) for s in clip.shots]):
                return  # Do not guess the content of an unobserved shot gap.
            if any(overlaps((start, stop), interval) for interval in removed):
                return
            selected_clauses = [s for s in speech if overlaps((start, stop), (s.start, s.end))]
            if any(start > s.start + EPS or stop < s.end - EPS for s in selected_clauses):
                return
            if any(start < a - EPS and stop > a + EPS for a, b in quarantine if a == b):
                return
            inside = [w for w in clip.words if w.start >= start - EPS and w.end <= stop + EPS]
            shot = next((s for s in clip.shots if s.start <= start < s.end), clip.shots[-1])
            covers = sum(bit for bit, (a, b) in bits if start <= a + EPS and stop >= b - EPS)
            pool.append(Candidate(clip.asset_id, clip.sha256, start, stop, shot.index,
                                  len(inside), inside[0].start - start if inside else None,
                                  " ".join(w.text for w in inside),
                                  any(start >= k["start"] - .35 and stop <= k["end"] + .35
                                      for k in clip.keepers), bool(shot.keyframe), covers,
                                  dangling_clauses=sum(not s.complete for s in selected_clauses)))
        # Speech may cross internal visual cuts. Enumerate complete consecutive
        # clauses with optional surrounding silence; never split for pacing.
        for i, clause in enumerate(speech):
            low = speech[i - 1].end if i else 0.
            starts = {clause.start, max(low, clause.start - .12), low}
            # A clause may contain natural picture cuts. Move its opening only
            # within the preceding silence, placing that first cut in band.
            if expand_timing:
                starts.update(s.start - length for s in clip.shots for length in lengths
                              if low <= s.start - length <= clause.start)
            for j in range(i, len(speech)):
                last = speech[j]
                if last.end - clause.start > target + .1:
                    break
                high = speech[j + 1].start if j + 1 < len(speech) else clip.duration
                for start in starts:
                    stops = {last.end, min(high, last.end + .12), high}
                    for length in (*lengths, target):
                        if last.end <= start + length <= high:
                            stops.add(start + length)
                    for stop in sorted(stops):
                        add(start, stop)
        # These are selection boundaries; the match report still counts the
        # original, measured visual cuts inside each chosen trim.
        boundaries = {0.0, clip.duration}
        for shot in clip.shots:
            for point in (shot.start, shot.end):
                boundaries.add(next((w.end for w in clip.words if w.start < point < w.end), point))
        edges = sorted(boundaries)
        for start, stop in kept:
            # Preserve a requested phrase/span in source order and with its
            # original pauses. A shot boundary cannot reorder its two halves.
            add(start, stop)
            left = max(p for p in edges if p <= start)
            right = min(p for p in edges if p >= stop)
            for begin, end in allowed:
                if begin <= start and end >= stop:
                    add(max(left, begin), min(right, end))
                    add(start, min(right, end))
                    add(max(left, begin), stop)
        for low, high in zip(edges, edges[1:]):
            # Do not select unobserved gaps between shot records.
            if not any(s.start <= (low + high) / 2 < s.end for s in clip.shots):
                continue
            for begin, end in subtract([(low, high)], removed):
                if end - begin < .2:
                    continue
                pieces = [(max(a, begin), min(b, end)) for a, b in kept if overlaps((a, b), (begin, end))]
                words = [w for w in clip.words if w.start >= begin - EPS and w.end <= end + EPS]
                starts = sorted({begin, *(w.start for w in words), *(a for a, _ in pieces),
                                 *(end - length for length in lengths if expand_timing and begin <= end - length < end)})
                ends = sorted({end, *(w.end for w in words), *(b for _, b in pieces)})
                desired = {*lengths, target % pace or pace, target}
                for start in starts:
                    stops = {end, *(b for _, b in pieces if b > start)}
                    for length in desired:
                        before = [p for p in ends if p <= start + length + EPS and p > start]
                        after = [p for p in ends if p >= start + length - EPS]
                        if before:
                            stops.add(before[-1])
                        if after:
                            stops.add(after[0])
                        if not words and start + length <= end:
                            stops.add(start + length)
                    for stop in sorted(stops):
                        add(start, stop)
    if available + EPS < target - 2 / 30:
        shortage("target_length", f"Only {available:.3f}s survives the studied footage constraints for a {target:g}s target.",
                 f"Film at least {max(0, target - available):.3f}s of additional usable footage, or shorten the brief.")
    covered = 0
    for c in pool:
        covered |= c.covers
    if covered != (1 << len(required)) - 1 or any(
        sum(b - a for key, a, b in required if key == asset_id) < sum(b - a for a, b in spans) - EPS
        for asset_id, spans in keep.items()
    ):
        shortage("must_keep_unavailable", "A required moment has no complete word-safe candidate in measured shots.",
                 "Study the missing shot or relax the conflicting trim/target length.")
    # Exact duplicate content is not an extra editorial choice. Keep asset IDs
    # when required, so constraints referring to a particular inventory ID survive.
    unique = {}
    for c in pool:
        unique.setdefault((c.identity, c.covers), c)
    pool = sorted(unique.values(), key=lambda c: (c.asset_id, c.start, c.end))
    if len(pool) > MAX_CANDIDATES:
        shortage("planner_capacity", f"{len(pool)} candidates exceed the bounded search limit {MAX_CANDIDATES}.",
                 "Use a smaller project or narrower forbidden ranges to focus the edit.")
    return pool, required


def shot_lengths(sequence, studies):
    cuts, cursor = [], 0.0
    lookup = {c.asset_id: c for c in studies}
    for i, c in enumerate(sequence):
        if i:
            prev = sequence[i - 1]
            if prev.content != c.content or abs(prev.end - c.start) > EPS or any(
                abs(s.start - c.start) < EPS for s in lookup[c.asset_id].shots[1:]
            ):
                cuts.append(cursor)
        cuts.extend(cursor + s.start - c.start for s in lookup[c.asset_id].shots
                    if c.start + EPS < s.start < c.end - EPS)
        cursor += c.duration
    edges = [0.0, *sorted(set(cuts)), cursor]
    return [b - a for a, b in zip(edges, edges[1:]) if b - a > EPS]


def first_caption(sequence):
    cursor = 0.0
    for c in sequence:
        if c.first_word is not None:
            return cursor + c.first_word
        cursor += c.duration
    return None


def different_opening(a, b):
    x, y = a[0], b[0]
    opening_overlap = (max(0, min(x.end, y.end) - max(x.start, y.start))
                       if x.content == y.content else 0)
    if opening_overlap < .5 * min(x.duration, y.duration) - EPS:
        if (x.content != y.content or x.shot != y.shot or
                (len(tokens(x.text)) >= 2 and len(tokens(y.text)) >= 2 and tokens(x.text) != tokens(y.text))):
            return True
    return False


def different(a, b, target, pace):
    """An opening must change content, or choices must change substantial footage."""
    if different_opening(a, b):
        return True
    common = sum(max(0, min(x.end, y.end) - max(x.start, y.start))
                 for x in a for y in b if x.content == y.content)
    changed = max(sum(c.duration for c in a), sum(c.duration for c in b)) - common
    return changed >= max(1.0, pace, target * .2) - EPS


def band_distance(value, band):
    """Seconds outside a measured band; missing cuts cannot satisfy a target."""
    if band["lower"] is None:
        return 0.0
    if value is None:
        return float("inf")
    return max(0.0, band["lower"] - value, value - band["upper"])


def choose(pool, required, studies, style, target, fps, seed, *, allow_reordering=False,
           timing_evidence=None, prefer_bands=True, preferred_a=None):
    """Beam search, with no repeats/overlapping source use and stable tie breaks.

    Failure is explicitly bounded-search failure, not a proof that no possible
    human edit exists. A/B/C are ranked only after hard constraints are satisfied.
    """
    tolerance = 2 / fps
    needed = (1 << len(required)) - 1
    pace = style.median_shot or 2.0
    by_id = {c.asset_id: c for c in studies}
    reference = style.basis.get("shot_durations", [])
    pace_band = timing_band(style.median_shot, reference)
    opening_band = timing_band(style.first_cut, reference)

    def timing(seq, *, partial=False):
        durations = shot_lengths(seq, studies)
        first = durations[0] if partial or len(durations) > 1 else None
        return (band_distance(first, opening_band), band_distance(median(durations), pace_band))

    def timing_rank(seq, *, partial=False):
        distances = timing(seq, partial=partial)
        return (sum(d > EPS for d in distances), sum(distances))

    def tie(c):
        return hashlib.sha256(f"{seed}:{c.identity}".encode()).hexdigest()

    def editorial(c, mode):
        if mode == "A":
            return (-c.keeper, -c.word_count / c.duration, tie(c))
        if mode == "B":
            return (-c.keyframe, c.word_count / c.duration, -c.keeper, tie(c))
        return (-bool(c.covers), c.word_count, c.duration, tie(c))

    def metrics(seq):
        durations = shot_lengths(seq, studies)
        med = median(durations)
        fc = durations[0] if len(durations) > 1 else None
        caption = first_caption(seq)
        errors = [abs(med - pace) / pace if style.median_shot else 0,
                  abs(fc - style.first_cut) / max(tolerance, style.first_cut)
                  if style.first_cut is not None and fc is not None else int(style.first_cut is not None),
                  abs(caption - style.first_caption) / max(tolerance, 1)
                  if style.first_caption is not None and caption is not None else int(style.first_caption is not None)]
        return errors

    complete = {}
    if preferred_a is not None:
        indices = tuple(pool.index(c) for c in preferred_a)
        complete[(indices[0], tuple(sorted(indices)))] = preferred_a
    bucket_count = len({(c.content, c.shot) for c in pool})
    # All openings compete; distinct opening buckets stop one appealing line
    # consuming the entire beam before B or C has an alternative.
    for mode in "ABC":
        ordered = sorted(range(len(pool)), key=lambda i: editorial(pool[i], mode))
        frontier = [((i,), pool[i].covers, pool[i].duration) for i in ordered]
        for step in range(min(MAX_STEPS, len(pool))):
            live = []
            for indices, mask, duration in frontier:
                if target - tolerance - EPS <= duration <= target + tolerance + EPS and mask == needed:
                    key = tuple(sorted(indices))
                    seq = [pool[i] for i in indices]
                    # Retain each opening, not every permutation of the tail.
                    complete[(indices[0], key)] = seq
                if duration < target - tolerance - EPS:
                    live.append((indices, mask, duration))
            if not live:
                break

            def rank(state):
                indices, mask, duration = state
                remaining_keep = sum(b - a for n, (_, a, b) in enumerate(required) if not mask & (1 << n))
                seq = [pool[i] for i in indices]
                error = metrics(seq)
                opening_distance, pace_distance = timing(seq, partial=True)
                band_rank = (opening_distance > EPS, opening_distance, pace_distance > EPS, pace_distance)
                return (max(0, duration + remaining_keep - target - tolerance),
                        (needed ^ (mask & needed)).bit_count(),
                        sum(c.dangling_clauses for c in seq), *(band_rank if prefer_bands else ()),
                        sum(error), abs(target - duration), editorial(seq[0], mode), indices)

            live.sort(key=rank)
            counts, selected = {}, []
            for state in live:
                first = pool[state[0][0]]
                bucket = (first.content, first.shot)
                if counts.get(bucket, 0) < max(2, BEAM // max(1, bucket_count)):
                    selected.append(state)
                    counts[bucket] = counts.get(bucket, 0) + 1
                if len(selected) == BEAM:
                    break
            next_states = {}
            for indices, mask, duration in selected:
                for i in ordered:
                    c = pool[i]
                    if duration + c.duration > target + tolerance + EPS:
                        continue
                    if any(c.content == pool[j].content and overlaps((c.start, c.end), (pool[j].start, pool[j].end))
                           for j in indices):
                        continue
                    if not allow_reordering and any(c.content == pool[j].content and c.start < pool[j].end - EPS for j in indices):
                        continue
                    # Adjacent same-shot trims would manufacture a "cut" without
                    # removing footage. Keep the complete candidate instead.
                    prev = pool[indices[-1]]
                    if (prev.content == c.content and abs(prev.end - c.start) < EPS
                            and not any(abs(s.start - c.start) < EPS for s in by_id[c.asset_id].shots[1:])):
                        continue
                    new = (*indices, i)
                    key = (indices[0], tuple(sorted(new)))
                    next_states.setdefault(key, (new, mask | c.covers, duration + c.duration))
            frontier = list(next_states.values())
            if len(complete) >= 512:
                break
    if not complete:
        shortage("edit_constraints", "No complete target-length edit was found by the bounded word-safe search.",
                 "Film a clean take near the recipe's shot length, shorten must-keeps, or relax the target length.")

    def final_rank(seq, mode):
        errors = metrics(seq)
        duration = sum(c.duration for c in seq)
        if not prefer_bands:
            gates = (errors[0] * pace > pace_band["tolerance"] + EPS,
                     errors[1] * max(tolerance, style.first_cut or 0) > opening_band["tolerance"] + EPS,
                     errors[2] > 1 / fps + EPS)
            prefix = (sum(gates),)
        else:
            prefix = (*timing_rank(seq), errors[2] > 1 / fps + EPS)
        # Timing feasibility precedes caption onset and opening variety. When
        # no in-band choice survives, minimize distance from the bands first.
        return (sum(c.dangling_clauses for c in seq), *prefix, sum(errors),
                duration if mode == "C" else abs(target - duration),
                editorial(seq[0], mode), sum(c.word_count for c in seq) if mode == "C" else 0,
                tuple(c.identity for c in seq))

    # A greedy first choice can strand two valid alternatives. Try the leading
    # A choices and require pairwise meaningful differences for the whole trio.
    def trio(options):
        ranked = {m: sorted(options, key=lambda s: final_rank(s, m)) for m in "ABC"}
        if preferred_a is not None and preferred_a in ranked["A"]:
            ranked["A"].remove(preferred_a)
            ranked["A"].insert(0, preferred_a)
        prefix = 4 if prefer_bands else 2
        def opening_changed(a, b):
            return different_opening(a, b) if prefer_bands else different([a[0]], [b[0]], target, pace)
        for a in ranked["A"][:BEAM]:
            alternatives = sorted(ranked["B"], key=lambda s: (*final_rank(s, "B")[:prefix],
                                  not opening_changed(a, s), final_rank(s, "B")))
            for b in (s for s in alternatives if different(a, s, target, pace)):
                concise = sorted(ranked["C"], key=lambda s: (*final_rank(s, "C")[:prefix],
                                 not (opening_changed(a, s) and opening_changed(b, s)), final_rank(s, "C")))
                c = next((s for s in concise if different(a, s, target, pace) and different(b, s, target, pace)), None)
                if c is not None:
                    return dict(zip("ABC", (a, b, c)))
    clean = [seq for seq in complete.values() if not any(c.dangling_clauses for c in seq)]
    in_band = [seq for seq in clean if timing_rank(seq)[0] == 0]
    result = (trio(in_band) if prefer_bands else None) or trio(clean) or trio(complete.values())
    if result is not None:
        if timing_evidence is not None:
            for label, seq in result.items():
                timing_evidence[label] = selection_timing_evidence(
                    seq, studies, opening_band, pace_band, clean or list(complete.values()), len(in_band))
        return result
    shortage("distinct_edits", "Studied footage supports fewer than three meaningfully distinct feasible choices in this search.",
             "Film an alternate opening line and a separate visual shot near the reference pace, or relax must-keeps/forbidden spans.")


def selection_timing_evidence(sequence, studies, opening_band, pace_band, feasible, in_band_count):
    """Disclose bounded-search evidence without claiming footage impossibility."""
    lengths = shot_lengths(sequence, studies)
    first = sequence[0]
    study = next(c for c in studies if c.asset_id == first.asset_id)
    internal = [s.start for s in study.shots if first.start + EPS < s.start < first.end - EPS]
    protected = [s for s in clauses(study.words) if overlaps((first.start, first.end), (s.start, s.end))]
    result = {}
    for name, value, band in (("first_cut_seconds", lengths[0] if len(lengths) > 1 else None, opening_band),
                              ("median_shot_seconds", median(lengths), pace_band)):
        distance = band_distance(value, band)
        reason = ("Selected a feasible edit inside the reference band." if band["lower"] is not None
                  else "Reference timing is unmeasured; no band constraint applied.")
        if distance > EPS:
            if name == "first_cut_seconds":
                event = (f"the opening reaches its natural source cut at {internal[0]:.3f} s "
                         f"after {internal[0] - first.start:.3f} s" if internal else
                         f"the opening's whole selected span runs {first.duration:.3f} s before an edit" if value is not None
                         else "the selected footage has no natural or edit cut in this completed draft")
                speech = ("; protected clauses at " + ", ".join(f"{s.start:.3f}-{s.end:.3f} s" for s in protected)
                          + " must remain whole" if protected else "")
                reason = f"Outside band because {event}{speech}."
            else:
                reason = (f"Outside band because the selected footage supplies {len(lengths)} natural/edit shots "
                          f"with a {median(lengths):.3f} s median under the whole-clause, source-order and duration constraints.")
            reason += (" This is the closest timing choice found for this distinct draft in the bounded search; "
                       "it does not prove that every possible edit of the footage is outside band.")
            if in_band_count:
                reason += (f" {in_band_count} completed in-band edits were found, but no complete, "
                           "meaningfully distinct in-band trio was selected.")
        result[name] = {"band": band, "planned": value,
                        "distance_outside_seconds": distance if distance != float("inf") else None,
                        "feasible_edits_examined": len(feasible), "jointly_in_band_edits": in_band_count,
                        "reason": reason, "scope": "completed edits in the bounded search"}
    return result
