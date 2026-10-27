"""Generated video, authored speech timing and complete-clause render checks."""

import json
from pathlib import Path

import pytest

from myzing.composition import Composition
from myzing.director import plan_drafts
from myzing.match.caption_fit import fit_captions
from myzing.match.evidence import decode
from myzing.render.composition import render_composition
from tools.plan_examples import example_project, write_json


@pytest.mark.ffmpeg
def test_repaired_clauses_render_and_raw_study_is_immutable(tmp_path, zing_workspace):
    root, _, _ = example_project(tmp_path / "project", media=True)
    path = root / "breakdowns/take-0/breakdown.json"
    raw = json.loads(path.read_text())
    raw["words"][9]["end"] = raw["words"][9]["start"]
    write_json(path, raw)
    before = path.read_bytes()
    result = plan_drafts(root, root / "recipe.json", root / "plans", seed=17)
    assert result["status"] == "ready"
    comparison = json.loads(Path(result["comparison_path"]).read_text())
    assert all(p["continuity"]["score"] == 1 for p in comparison["plans"].values())
    plan = Composition.from_json(Path(result["plans"]["A"]).read_text())
    # Render at the planned size: caption bands are measured for it, and a
    # raw resize skips the delivery rebuild that re-places them.
    fit_captions(plan, tmp_path / "fit")
    assert all(len(c.words) <= 2 and c.word_timed for c in plan.captions)
    assert plan.captions[-1].text.endswith(".")  # the edit retains clauses; display groups follow the reference
    video = tmp_path / "draft.mp4"
    render_composition(plan, video)
    assert decode(video, plan)["full_decode"]
    assert path.read_bytes() == before
    strict = plan_drafts(root, root / "recipe.json", root / "strict", seed=17, repair_asr=False)
    assert strict["status"] == "shortage"  # required speech is in the rejected clip
