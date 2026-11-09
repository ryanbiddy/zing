"""Vertical editorial gates from existing face tracks, never a new detector."""

from dataclasses import replace
from functools import lru_cache

from myzing.composition import CompositionClip
from myzing.composition.aspects import dimensions
from myzing.layout.caption_safety import is_face
from myzing.layout.crop_planner import select_framing
from myzing.layout.face_size import face_share, match_face_framing, measurements

from .selection import EPS, merge, overlaps, subtract
from .visual_quality import filter_candidates


class VerticalQuality:
    def __init__(self, studies, subjects, sizes, brief, pool, required, reference_share=None):
        self.rows, self.actions, self.warnings = {}, [], []
        self.required = required
        self.protected_required = list(required)
        self.enabled = brief.aspect in ("9:16", "4:5")
        if not self.enabled:
            return
        width, height = dimensions(brief.aspect, 1080 if brief.short_side == "auto" else brief.short_side)
        for study in studies:
            tracks = subjects.get(study.asset_id, ([], []))[0]
            if study.asset_id not in sizes or not any(is_face(t) for t in tracks):
                self.warnings.append(f"Vertical quality unmeasured for {study.asset_id}: no face/head geometry or source size.")
                continue
            spans = merge([(c.start, c.end) for c in pool if c.asset_id == study.asset_id])
            rows = []
            for shot in study.shots:
                for a, b in spans:
                    start, end = max(a, shot.start), min(b, shot.end)
                    if end <= start:
                        continue
                    clip = CompositionClip(study.path, start, end, 0, id='quality', asset_id=study.asset_id)
                    framing = select_framing(brief.framing, *sizes[study.asset_id], width, height,
                                             clip, tracks, max_upscale=brief.framing_max_upscale)
                    if brief.framing == "auto" and reference_share is not None:
                        framing = match_face_framing(framing, clip, tracks, width, height, reference_share)
                    rows.extend(measurements(clip, framing, tracks, width, height))
            self.rows[study.asset_id] = rows

    def required_at(self, key, start, end):
        return any(k == key and overlaps((start, end), (a, b))
                   for k, a, b in [*self.required, *self.protected_required])

    @lru_cache(maxsize=10000)
    def parts(self, candidate):
        return [dict(r, start=max(r['start'], candidate.start), end=min(r['end'], candidate.end))
                for r in self.rows.get(candidate.asset_id, [])
                if overlaps((r['start'], r['end']), (candidate.start, candidate.end))]

    def filter(self, pool, studies, required):
        from .continuity import clauses
        # The exclusion and the gate must protect the same whole speech unit.
        # Protecting only the raw interval lets inward clause snapping erase it.
        for study in studies:
            for clause in clauses(study.words):
                if any(k == study.asset_id and overlaps((a, b), (clause.start, clause.end))
                       for k, a, b in required):
                    span = (study.asset_id, clause.start, clause.end)
                    if span not in self.protected_required:
                        self.protected_required.append(span)
        self.gates.cache_clear()
        excluded = {}
        for key, rows in self.rows.items():
            bad = merge([(r['start'], r['end']) for r in rows if r['bad']])
            required_spans = [(a, b) for k, a, b in self.protected_required if k == key]
            excluded[key] = subtract([(a, b) for a, b in bad if b-a > 1 + EPS], required_spans)
        result = filter_candidates(pool, excluded, studies, required)
        for key, rows in self.rows.items():
            bad = merge([(r['start'], r['end']) for r in rows if r['bad']])
            for a, b in bad:
                retained = any(c.asset_id == key and c.start <= x + EPS and c.end >= y - EPS
                               and overlaps((a, b), (x, y))
                               for k, x, y in required if k == key for c in result)
                if b-a > 1 + EPS and retained:
                    warning = f"Vertical must_keep retained: {key} {a:.3f}-{b:.3f}s has a face below 10% or needs excessive enlargement."
                    if warning not in self.warnings:
                        self.warnings.append(warning)
        identities = {c.identity for c in result}
        for c in pool:
            if c.identity not in identities:
                self.actions.append({"asset_id": c.asset_id, "start": c.start, "end": c.end,
                                     "retained_spans": [[p.start,p.end] for p in result if p.asset_id == c.asset_id
                                                        and c.start <= p.start and p.end <= c.end],
                                     "action": "trimmed or dropped", "reason": "wide run exceeds 1s; retained pieces use clause boundaries"})
        scored = []
        for c in result:
            rows = self.parts(c)
            close = sum(r['end']-r['start'] for r in rows if r['close']) / c.duration if rows else 0.
            if rows and close < 1-EPS:
                self.actions.append({"asset_id":c.asset_id,"start":c.start,"end":c.end,
                                     "action":"demoted","close_share":close,
                                     "reason":"Candidate score prefers time dominated by close shots."})
            scored.append(replace(c, close_share=close))
        return scored, excluded

    @lru_cache(maxsize=10000)
    def gates(self, candidate):
        return [(r['start']-candidate.start, r['end']-candidate.start,
                 r['bad'] and not self.required_at(candidate.asset_id, r['start'], r['end']),
                 r['close'] or self.required_at(candidate.asset_id, r['start'], r['end']))
                for r in self.parts(candidate)]

    def valid(self, sequence):
        cursor, bad_run = 0., 0.
        for c in sequence:
            for a, b, bad, close in self.gates(c):
                if cursor + a < 2 - EPS and not close:
                    return False
                bad_run = bad_run + b-a if bad else 0.
                if bad_run > 1 + EPS:
                    return False
            cursor += c.duration
        return True

    def report(self, plan, subjects, sizes):
        shots, opening, violations = [], True, []
        from myzing.composition.aspects import aspect_for
        enabled = self.enabled and aspect_for(plan.width,plan.height) in ('9:16','4:5')
        for clip in plan.clips:
            tracks = subjects.get(clip.asset_id, ([], []))[0]
            if not enabled or clip.asset_id not in self.rows:
                continue
            from myzing.layout.framing import centered_framing
            f = clip.framing or centered_framing('fit', *sizes[clip.asset_id], plan.width, plan.height)
            rows = measurements(clip, f, tracks, plan.width, plan.height)
            first = [r for r in rows if clip.timeline_start + r['start']-clip.src_in < 2-EPS]
            opening = opening and all(r['close'] for r in first)
            if any(not r['close'] and self.required_at(clip.asset_id,r['start'],r['end']) for r in first):
                warning = f"Vertical must_keep retained: opening in {clip.asset_id} {clip.src_in:.3f}-{clip.src_out:.3f}s cannot meet the 15% close-shot gate within the enlargement limit."
                if warning not in self.warnings:
                    self.warnings.append(warning)
            bad = merge([(r['start'], r['end']) for r in rows if r['bad']])
            for a,b in bad:
                unrequired = subtract([(a,b)],[(x,y) for k,x,y in [*self.required, *self.protected_required]
                                              if k == clip.asset_id])
                if any(y-x > 1+EPS for x,y in unrequired):
                    violations.append({"source_span":[a,b],"reason":"Final crop has a wide run over 1s."})
            if any(not r['close'] and not self.required_at(clip.asset_id,r['start'],r['end']) for r in first):
                violations.append({"source_span":[clip.src_in,clip.src_out],"reason":"Final crop opening is below 15% or exceeds required enlargement."})
            shots.append({"asset_id": clip.asset_id, "source_span": [clip.src_in, clip.src_out],
                          "output_span": [clip.timeline_start, clip.timeline_end],
                          "face_height_share": min((r['face_height_share'] for r in rows), default=None),
                          "max_required_enlargement": max((r['required_enlargement'] or 0 for r in rows), default=None),
                          "longest_wide_run": max((b-a for a,b in bad), default=0.),
                          "first_two_seconds_close": all(r['close'] for r in first) if first else None})
        return {"enabled": enabled, "shots": shots, "first_two_seconds_close": opening if shots else None,
                "protected_required": self.protected_required,
                "violations":violations,
                "candidate_changes": list({(a['asset_id'],a['start'],a['end'],a['action']):a for a in self.actions}.values()), "warnings": self.warnings,
                "basis": "Existing face/head geometry at 30 Hz; speaker-held identity or dominant-face heuristic (identity unverified). 10% face minimum, <=1s wide runs, 15% for first 2s; required enlargement uses source face pixels. Missing geometry is unmeasured."}
