"""Timing constraints preserve clauses and explain the nearest feasible fallback."""

import json

import pytest

from myzing.composition import AssetRef, Composition, CompositionClip
from myzing.director.continuity import score
from myzing.director.models import ClipStudy
from myzing.director.plans import REPORT_PREFIX
from myzing.director.selection import Candidate, candidates, choose, envelope
from myzing.match.evidence import markdown, report
from myzing.music.planning import retime
from myzing.schemas import Breakdown, Shot, VideoMeta, Word
from myzing.style_ranges import timing_band
from myzing.style_recipe import build_style_recipe


def reference():
    return build_style_recipe(Breakdown(VideoMeta("fixture", "file", duration=4, fps=30),
                                        shots=[Shot(i, i * .8, (i + 1) * .8) for i in range(5)]))


def test_feasible_primary_edit_survives_expanded_candidate_search():
    studies = [ClipStudy(str(i), f"{i}.mp4", str(i) * 64, 2, "ready", shots=[Shot(0, 0, 2)])
               for i in range(3)]
    style = envelope(reference())
    pool, required = candidates(studies, {}, {}, style, 2.4)
    incumbent = [next(c for c in pool if c.asset_id == str(i) and c.start == 0 and abs(c.end - .8) < 1e-8)
                 for i in (2, 1, 0)]
    evidence = {}
    selected = choose(pool, required, studies, style, 2.4, 30, 0, preferred_a=incumbent, timing_evidence=evidence)
    assert selected["A"] == incumbent
    assert all(v["distance_outside_seconds"] == 0 for row in evidence.values() for v in row.values())


def test_nearest_whole_clause_fallback_is_disclosed_in_match_and_markdown():
    studies = [ClipStudy(str(i), f"{i}.mp4", str(i) * 64, length, "ready",
                         shots=[Shot(0, 0, length)], words=[Word("Complete.", 0, length)])
               for i, length in enumerate([2., 2., 2., 3., 3., 3.])]
    recipe = reference()
    style = envelope(recipe)
    pool, required = candidates(studies, {}, {}, style, 6)
    evidence = {}
    selected = choose(pool, required, studies, style, 6, 30, 0, timing_evidence=evidence)
    rows = {}
    for label, sequence in selected.items():
        # Two-second complete clauses are the nearest feasible choice; using
        # the available three-second clauses would be farther from both bands.
        assert all(c.duration == 2 for c in sequence)
        for value in evidence[label].values():
            assert value["planned"] == 2
            assert value["distance_outside_seconds"] == pytest.approx(.95)
            assert value["jointly_in_band_edits"] == 0
            assert "Outside band because" in value["reason"]
        continuity = score(sequence, studies)
        assert continuity["partial_clauses"] == 0
        planning = {"match": {key: {"selection": value} for key, value in evidence[label].items()},
                    "continuity": continuity, "pacing_evidence": {"shot_durations_seconds": [2.] * 3}}
        plan = Composition(assets=[AssetRef(s.asset_id, s.path, s.sha256) for s in studies],
                           clips=[CompositionClip(id=f"c{i}", asset_id=c.asset_id, src=f"{c.asset_id}.mp4",
                                                  src_in=0, src_out=2, timeline_start=i * 2)
                                  for i, c in enumerate(sequence)],
                           warnings=[REPORT_PREFIX + json.dumps(planning)])
        pixels = Breakdown(VideoMeta("render", "file", duration=6, fps=30),
                           shots=[Shot(i, i * 2, (i + 1) * 2) for i in range(3)])
        checked = report(recipe, pixels, {}, None, {}, plan)
        for name in ("first_cut", "shot_pace"):
            assert checked["dimensions"][name]["status"] == "not_applicable"
            assert "Outside band because" in checked["dimensions"][name]["reason"]
            assert "protected" in checked["dimensions"][name]["reason"]
        rows[label] = {"status": "ready", "dimensions": checked["dimensions"], "video": "a.mp4",
                       "plan": "a.json", "timeline": "a.png", "report": "a.match.json"}
    text = markdown({"project": ".", "summary": "3 ready", "drafts": rows})
    assert "Outside band because" in text and "not applicable for this footage" in text


@pytest.mark.parametrize("lengths,beat,dimension", [([.8, .8, .8], .5, "first_cut"),
                                                  ([.8, .6, 1.5], 1.1, "shot_pace")])
def test_music_trim_cannot_undo_timing_constraints(lengths, beat, dimension):
    studies = [ClipStudy(str(i), f"{i}.mp4", str(i) * 64, 4, "ready", shots=[Shot(0, 0, 4)])
               for i in range(3)]
    sequence = [Candidate(s.asset_id, s.sha256, 1, 1 + length, 0, 0, None, "", False, False)
                for s, length in zip(studies, lengths)]
    bands = {name: timing_band(.8, [.8] * 5) for name in ("first_cut", "shot_pace")}
    if dimension == "shot_pace":
        bands["first_cut"] = timing_band(1, [1] * 5)
    selected, decisions = retime(sequence, studies, [beat], [], 0, speech=False, required={}, forbidden={},
                                 timing_bands=bands, locked=1)
    assert selected == sequence
    assert any(d["kind"] == "cut_kept" and dimension in d["reason"] for d in decisions)
