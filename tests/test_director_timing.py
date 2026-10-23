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


def test_music_snapping_reasons_and_planned_values_describe_the_final_edit(tmp_path, zing_workspace, monkeypatch):
    """Selection evidence predates music snapping; plans must describe what renders."""
    import sys
    from dataclasses import replace
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.plan_examples import example_project, write_json
    from test_director import stub_default_ink
    from myzing.director.api import plan_drafts
    from myzing.layout import framing as layout_framing
    from myzing.music import planning
    from myzing.music.models import MusicPlan
    from myzing.schemas import CaptionEvent

    monkeypatch.setattr(layout_framing, "measure_default_ink", stub_default_ink)
    project, _, _ = example_project(tmp_path / "project")
    # 1.4 s reference shots: band 1.12-1.68 s. The footage's natural openings
    # are 1.75-1.87 s, so some selections start outside the band.
    shots = [Shot(i, i * 1.4, (i + 1) * 1.4) for i in range(4)]
    words = [Word("two words", .25 + i, .75 + i) for i in range(5)]
    write_json(project / "recipe.json", build_style_recipe(Breakdown(
        VideoMeta("fixture:style", "file", duration=5.6, width=320, height=180, fps=30), shots=shots, words=words,
        captions=[CaptionEvent("two words", .25 + i, .75 + i, "lower", i % 2 == 0, 2) for i in range(5)])).to_dict())

    def snap(sequence, studies, brief, manifest, root, pace, required, forbidden, cache=None, **kwargs):
        # A stand-in for MUSIC1 retiming: pull the opening out-point 0.35 s
        # earlier (the montage limit), toward or into the band.
        a = sequence[0]
        moved = [replace(a, end=a.end - .35), *sequence[1:]] if a.duration > .6 else sequence
        return moved, [], [], MusicPlan(mode="speech-led", timeline=planning.timeline_of(moved))

    monkeypatch.setattr(planning, "plan_music", snap)
    result = plan_drafts(project, project / "recipe.json", tmp_path / "plans", seed=17)
    assert result["status"] == "ready", result
    moved = 0
    for path in result["plans"].values():
        plan = Composition.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        planning_report = next(json.loads(w[len(REPORT_PREFIX):]) for w in plan.warnings if w.startswith(REPORT_PREFIX))
        durations = planning_report["pacing_evidence"]["shot_durations_seconds"]
        for key, value in (("first_cut_seconds", durations[0]), ("median_shot_seconds", None)):
            item = planning_report["match"][key]
            assert item["selection"]["planned"] == item["planned"]
            if value is not None:
                assert item["planned"] == pytest.approx(value)
            inside = item["band"]["lower"] - 1e-9 <= item["planned"] <= item["band"]["upper"] + 1e-9
            # One cut, one duration, one verdict.
            assert ("Outside band because" in item["reason"]) == (not inside), item["reason"]
            assert item["reason"].startswith("Inside" if inside else f"{item['selection']['distance_outside_seconds']:.3f} s")
            if "selected_before_music_seconds" in item["selection"]:
                moved += 1
                assert f"moved it from {item['selection']['selected_before_music_seconds']:.3f} s to {item['planned']:.3f} s" in item["reason"]
    assert moved >= 2  # Both the opening and the median moved in at least one draft.


def test_fallback_wording_names_closer_edits_left_out_of_the_trio():
    from myzing.director.selection import selection_timing_evidence
    studies = [ClipStudy(k, f"{k}.mp4", k * 64, n, "ready", shots=[Shot(0, 0, n)]) for k, n in (("a", 3), ("b", 1))]
    sequence = [Candidate(s.asset_id, s.sha256, 0, s.duration, 0, 0, None, "", False, False) for s in studies]
    band = timing_band(.8, [.8] * 5)  # 0.55-1.05 s: the 3 s opening is 1.95 s out, the 2 s median 0.95 s.
    closest = {"feasible_edits_examined": 9, "jointly_in_band_edits": 0, "closest_violations": 2,
               "closest_seconds_outside": 2.9, "scope": "completed edits in the bounded search"}
    own = selection_timing_evidence(sequence, studies, band, band, closest)["median_shot_seconds"]
    assert own["closest_in_search"] and "No completed edit in the bounded search is closer" in own["reason"]
    nearer = {**closest, "closest_violations": 1, "closest_seconds_outside": .5}
    later = selection_timing_evidence(sequence, studies, band, band, nearer)["median_shot_seconds"]
    assert not later["closest_in_search"]
    assert "Completed edits closer to the bands exist (1 timing dimension(s), 0.500 s outside" in later["reason"]
    assert "No completed edit" not in later["reason"] and "this edit completes the trio" in later["reason"]
    in_band = {**closest, "jointly_in_band_edits": 4, "closest_violations": 0, "closest_seconds_outside": 0.0}
    text = selection_timing_evidence(sequence, studies, band, band, in_band)["median_shot_seconds"]["reason"]
    assert "4 completed edits inside both bands were found" in text and "closest" not in text
