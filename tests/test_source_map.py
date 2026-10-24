"""Planning-map contracts also run with no study extra or FFmpeg."""

import copy
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.schemas import Shot
from myzing.study.source_map import SourceMap, build_source_map, planning_shots


def breakdown():
    return SimpleNamespace(shots=[Shot(0, 0., 1.), Shot(1, 1., 2.)],
                           meta=SimpleNamespace(fps=30., duration=2.), provenance={})


def map_for(b):
    return SourceMap(b.meta.fps, b.meta.duration, [s.start for s in b.shots[1:]],
                     [{"frame": 36, "accepted": True, "confidence": "high", "evidence": {"test": True}}])


def test_planning_map_splits_only_confirmed_cuts_and_preserves_public_shots():
    b = breakdown()
    original = copy.deepcopy(b.shots)
    m = map_for(b)
    m.candidates.append({"frame": 42, "accepted": False, "confidence": "rejected", "evidence": {}})
    m.rejected_counts = [{"proposal": "p", "reason": "r", "count": 3, "recorded": 1}]
    b.provenance["source_map"] = m.to_dict()
    assert SourceMap.from_dict(m.to_dict()) == m
    assert [s.start for s in planning_shots(b)] == [0, 1, 1.2]
    assert b.shots == original


@pytest.mark.parametrize("field,value", [("fps", 24), ("duration", 3), ("base_cuts", [.5]),
                                        ("version", 2), ("method", "unknown"),
                                        ("method", "adaptive-and-content-confirmed-v1"),
                                        ("rejected_counts", [{"proposal": "p", "reason": "r", "count": 1, "recorded": 1}])])
def test_stale_or_unknown_map_is_not_used(field, value):
    b = breakdown()
    b.provenance["source_map"] = {**map_for(b).to_dict(), field: value}
    with pytest.raises(ValueError):
        planning_shots(b)


def test_missing_map_and_failed_fine_pass_retain_original_evidence(monkeypatch):
    import sys

    b = breakdown()
    assert planning_shots(b) is b.shots
    monkeypatch.setitem(sys.modules, "scenedetect", None)  # import raises ImportError
    m = build_source_map(Path("absent.mp4"), 2., 30., b.shots)
    assert m.status == "unmeasured" and m.warnings and not m.candidates
    b.provenance["source_map"] = m.to_dict()
    assert planning_shots(b) is b.shots


def test_fine_map_does_not_fill_unmeasured_gaps():
    b = breakdown()
    b.shots[0].end = .5
    m = map_for(b)
    m.candidates[0]["frame"] = 24
    b.provenance["source_map"] = m.to_dict()
    assert [(s.start, s.end) for s in planning_shots(b)] == [(0, .5), (1, 2)]


def test_match_uses_independently_confirmed_rendered_cuts():
    from myzing.match.timing import timing_dimensions

    b = breakdown()
    pacing = {"shot_durations_seconds": [1., .2, .8], "cut_positions_seconds": [1., 1.2]}
    args = ([1., 1., 1.], b, pacing, {}, SimpleNamespace(clips=[]), False)
    assert timing_dimensions(*args)["shot_pace"]["status"] == "detector_disagreement"
    b.provenance["source_map"] = map_for(b).to_dict()
    measured = timing_dimensions(*args)["shot_pace"]
    assert measured["status"] == "pass"
    assert measured["observed"] == pytest.approx(.8)
    assert not measured["cut_agreement"]["detected_not_mapped_seconds"]
    assert not measured["cut_agreement"]["mapped_not_detected_seconds"]


def test_inventory_and_pace_use_fine_source_map(tmp_path, zing_workspace):
    from myzing.director.inventory import inventory
    from myzing.director.selection import Candidate, shot_lengths
    from tools.plan_examples import example_project

    root, _, _ = example_project(tmp_path / "project")
    path = root / "breakdowns/take-0/breakdown.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    m = SourceMap(data["meta"]["fps"], data["meta"]["duration"], [s["start"] for s in data["shots"][1:]],
                  [{"frame": 36, "accepted": True, "confidence": "high", "evidence": {"test": True}}])
    data["provenance"]["source_map"] = m.to_dict()
    path.write_text(json.dumps(data), encoding="utf-8")
    studies, _ = inventory(root)
    clip = next(s for s in studies if s.asset_id == "take-0")
    assert clip.status == "ready"
    assert 36 / m.fps in [s.start for s in clip.shots]
    # The same ClipStudy shots feed selection and the plan's source pacing.
    assert data["shots"] != [asdict(s) for s in clip.shots]
    sequence = [Candidate(clip.asset_id, clip.sha256, 0., 2., 0, 0, None, "", False, False)]
    assert shot_lengths(sequence, [clip]) == pytest.approx([36 / m.fps, 2 - 36 / m.fps])


def test_rejections_are_bounded_and_counted():
    from myzing.study.source_map import MAX_REJECTED_RECORDED, _decision, _Recorder

    recorder = _Recorder()
    for frame in range(1, 5001):
        recorder.add(_decision(frame, frame % 1000 == 0, {"reason": "weak" if frame % 2 else "motion",
                                                          "proposal": "content",
                                                          "mean_absolute_difference": frame % 97 / 100}))
    candidates, counts = recorder.finish()
    rejected = [r for r in candidates if not r["accepted"]]
    assert len(rejected) == MAX_REJECTED_RECORDED
    assert [r["frame"] for r in candidates if r["accepted"]] == [1000, 2000, 3000, 4000, 5000]
    assert sum(c["count"] for c in counts) == 4995
    assert sum(c["recorded"] for c in counts) == MAX_REJECTED_RECORDED
    # The strongest rejected changes are the ones kept.
    strengths = sorted((f % 97 / 100 for f in range(1, 5001) if f % 1000), reverse=True)
    assert sorted((r["evidence"]["mean_absolute_difference"] for r in rejected), reverse=True) ==         strengths[:MAX_REJECTED_RECORDED]
    m = SourceMap(30., 200., [], candidates, counts)
    assert SourceMap.from_dict(m.to_dict()) == m
    assert [r["frame"] for r in m.candidates] == sorted(r["frame"] for r in m.candidates)
