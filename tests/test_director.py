"""P17 contract tests: real choices, preserved constraints and honest shortages."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median

import pytest
from jsonschema import Draft202012Validator

from myzing.composition import Composition, lower_to_v1
from myzing.director import plan_drafts
from myzing.director.inventory import inventory
from myzing.director.models import ClipStudy, Shortage
from myzing.director.plans import REPORT_PREFIX, render_projection
from myzing.layout.types import Box, EventLayout, LayoutPlan, OverlapCheck
from myzing.schema_export import schemas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.plan_examples import example_project, write_json


@pytest.fixture
def project(tmp_path, zing_workspace):
    root, _, _ = example_project(tmp_path / "project")
    return root


def run(project, out="plans", seed=17, **options):
    return plan_drafts(project, project / "recipe.json", project / out, seed=seed, **options)


def report(result):
    return json.loads(Path(result["comparison_path"]).read_text(encoding="utf-8"))


def plans(result):
    return [Composition.from_json(Path(path).read_text(encoding="utf-8")) for path in result["plans"].values()]


def change_brief(project, **changes):
    path = project / "brief.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    write_json(path, {**data, **changes})


def test_three_plans_are_deterministic_valid_distinct_and_word_safe(project):
    result = run(project)
    assert result["status"] == "ready", report(result)
    original = {p.name: p.read_bytes() for p in (project / "plans").glob("*.json")}
    run(project)
    other = run(project, "again")
    assert original == {p.name: p.read_bytes() for p in (project / "again").glob("*.json")}
    assert original == {p.name: p.read_bytes() for p in (project / "plans").glob("*.json")}
    loaded = plans(other)
    assert len(loaded) == 3
    assert len({(p.clips[0].asset_id, p.clips[0].src_in) for p in loaded}) == 3
    schema = Draft202012Validator(schemas()["composition-v2.schema.json"])
    studies, _ = inventory(project)
    for p in loaded:
        schema.validate(p.to_dict())
        assert p.brief.target_length_seconds == 6
        kept = sorted((c.src_in, c.src_out) for c in p.clips if c.asset_id == "take-0")
        assert any(a <= 4.25 and b >= 5 for a, b in kept)
        assert not any(c.asset_id == "take-1" and c.src_out > 6 and c.src_in < 8 for c in p.clips)
        for c in p.clips:
            study = next(s for s in studies if s.asset_id == c.asset_id)
            for point in (c.src_in, c.src_out):
                assert not any(w.start < point < w.end for w in study.words)
                if any(w.start <= point <= w.end for w in study.words):
                    assert point in {v for w in study.words for v in (w.start, w.end)}
        evidence = json.loads(next(w[len(REPORT_PREFIX):] for w in p.warnings if w.startswith(REPORT_PREFIX)))
        assert evidence["differs_from"] and evidence["recipe_facts"]
        assert evidence["match"]["median_shot_seconds"]["status"] == "honored"
        assert abs(evidence["match"]["median_shot_seconds"]["planned"] - 2) <= .2
        assert evidence["match"]["first_cut_seconds"]["status"] == "honored"
        assert evidence["match"]["first_caption_seconds"]["status"] == "honored"
        assert median(len(c.words) for c in p.captions) == 4  # retain each complete clause
        assert evidence["continuity"]["score"] == 1
        assert abs(sum(c.all_caps for c in p.captions) / len(p.captions) - .5) <= .5 / len(p.captions)
        with pytest.raises(ValueError, match="brief"):
            lower_to_v1(p)  # Strict v2 lowering never silently discards evidence.
        legacy, blockers = render_projection(p)
        assert not blockers
        assert [(c.src, c.src_in, c.src_out) for c in legacy.clips] == [(c.src, c.src_in, c.src_out) for c in p.clips]
        assert legacy.to_dict()["schema_version"] == 1
    assert len(result["v1_edls"]) == 3


@pytest.mark.parametrize("kind,expected", [("length", "target_length"), ("missing", "must_keep_missing"),
                                          ("unstudied", "must_keep_unstudied"), ("conflict", "constraint_conflict")])
def test_named_shortages(project, kind, expected):
    if kind == "length":
        change_brief(project, target_length_seconds=50)
    elif kind == "missing":
        change_brief(project, must_keep=[{"phrase": "This line was never filmed"}])
    elif kind == "unstudied":
        (project / "breakdowns/take-0/breakdown.json").unlink()
    else:
        # Raw requests do not overlap; whole-word expansion makes them conflict.
        change_brief(project, must_keep=[{"clip": "take-0", "start": .27, "end": .3}],
                     forbidden=[{"clip": "take-0", "start": .4, "end": .45}])
    result = run(project)
    assert result["status"] == "shortage"
    assert result["plans"] == result["v1_edls"] == {}
    failure = report(result)["shortages"][0]
    assert failure["code"] == expected
    assert failure["missing"] and failure["remedy"]
    assert Shortage.from_dict(failure).to_dict() == failure
    assert not list((project / "plans").glob("plan-*.json"))


def test_shortage_does_not_pad_or_leave_previous_success(project):
    assert run(project)["status"] == "ready"
    # Exactly one available source shot, all of which is required. Permuting
    # clip labels and splitting adjacent source ranges cannot make three edits.
    change_brief(project, target_length_seconds=2,
                 must_keep=[{"clip": "take-0", "start": 0, "end": 2}],
                 forbidden=[{"clip": "take-0", "start": 2, "end": 8},
                            {"clip": "take-1", "start": 0, "end": 8},
                            {"clip": "take-2", "start": 0, "end": 8}])
    result = run(project)
    assert result["status"] == "shortage"
    assert report(result)["shortages"][0]["code"] == "distinct_edits"
    assert not list((project / "plans").glob("plan-*.json"))


def test_unstudied_clip_is_reported_and_not_guessed(project):
    (project / "breakdowns/take-2/breakdown.json").unlink()
    result = run(project)
    assert "take-2" in result["summary"]["clips_needing_study"]
    for plan in plans(result):
        assert all(c.asset_id != "take-2" for c in plan.clips)
    assert "zing study" in " ".join(report(result)["inventory"][2]["warnings"])


@pytest.mark.parametrize("issue", ["zero", "overlap", "nonfinite", "stale", "running"])
def test_bad_studies_are_excluded_without_repair(project, issue):
    path = project / "breakdowns/take-0/breakdown.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if issue == "zero":
        data["words"][0]["end"] = data["words"][0]["start"]
    elif issue == "overlap":
        data["words"][1]["start"] = .3
    elif issue == "nonfinite":
        data["words"][0]["end"] = float("nan")
    elif issue == "stale":
        data["provenance"]["source_sha256"] = "f" * 64
    else:
        write_json(path.parent / "status.json", {"state": "running"})
    write_json(path, data)
    before = path.read_bytes()
    result = run(project, repair_asr=False)
    assert result["status"] == "shortage"
    assert path.read_bytes() == before
    assert "take-0" in result["summary"]["clips_needing_study"]


def test_phrase_constraints_and_word_expansion(project):
    change_brief(project, must_keep=[{"clip": "take-0", "phrase": "Keep this"}],
                 forbidden=[{"phrase": "Another view"}])
    result = run(project)
    assert result["status"] == "ready"
    for p in plans(result):
        assert any(c.asset_id == "take-0" and c.src_in <= 4.25 and c.src_out >= 5 for c in p.clips)
        assert all(c.src_out <= 6.25 or c.src_in >= 7 for c in p.clips)


def test_layout_is_retained_and_blocks_v1_with_honest_safety_scope(project):
    path = project / "recipe.json"
    recipe = json.loads(path.read_text(encoding="utf-8"))
    layout = LayoutPlan([EventLayout("reference-caption", .25, 1, "known fixture", OverlapCheck(True),
                                    box=Box(.2, .1, .6, .12))], [], [])
    recipe["approximations"]["layout"] = layout.to_dict()
    write_json(path, recipe)
    result = run(project)
    assert result["status"] == "ready" and not result["v1_edls"]
    for p in plans(result):
        for caption in p.captions:
            assert caption.layout.box == layout.events[0].box
            assert (caption.id, caption.start, caption.end) == (caption.layout.id, caption.layout.start, caption.layout.end)
            assert "faces unmeasured" in caption.layout.overlap.scope
        assert render_projection(p)[0] is None


def test_record_roundtrip_and_input_mutation_boundaries(project):
    clips, _ = inventory(project)
    for clip in clips:
        assert ClipStudy.from_dict(clip.to_dict()).to_dict() == clip.to_dict()
    before = {p: p.read_bytes() for p in project.rglob("*.json")}
    run(project)
    assert all(p.read_bytes() == content for p, content in before.items())


def test_cli_and_mcp_paths_and_shortage_envelope(project, capsys):
    from myzing.cli import main
    from myzing.mcp_server import h_plan_drafts
    change_brief(project, target_length_seconds=50)
    assert main(["plan", "drafts", str(project), "--recipe", str(project / "recipe.json"),
                 "--out", str(project / "cli"), "--seed", "17"]) == 1
    cli = json.loads(capsys.readouterr().out)
    result = h_plan_drafts(str(project), str(project / "recipe.json"), str(project / "mcp"), 17)
    assert result["ok"] and result["status"] == cli["status"] == "shortage"
    assert Path(result["comparison_path"]).is_file()
    assert not h_plan_drafts(str(project), "absent-recipe.json", str(project / "mcp"))["ok"]
    assert not h_plan_drafts(str(project), str(project / "recipe.json"), str(project / "mcp"), True)["ok"]


def test_output_refuses_unowned_file(project):
    output = project / "plans"
    output.mkdir()
    protected = output / "plan-A.json"
    protected.write_text("do not replace", encoding="utf-8")
    change_brief(project, target_length_seconds=50)
    with pytest.raises(ValueError, match="already exists"):
        run(project)
    assert protected.read_text(encoding="utf-8") == "do not replace"


def test_must_keep_survives_across_shots_and_dead_air_override(project):
    path = project / "breakdowns/take-0/breakdown.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["provenance"]["raw_mode"]["dead_air"] = [{"start": 2, "end": 6}]
    write_json(path, data)
    change_brief(project, must_keep=[{"clip": "take-0", "start": 3.8, "end": 4.3}])
    result = run(project)
    assert result["status"] == "ready", report(result)
    for plan in plans(result):
        # Request expands to complete words [3.75, 4.5], including the gap.
        assert any(c.asset_id == "take-0" and c.src_in <= 3.75 and c.src_out >= 4.5 for c in plan.clips)


def test_duplicate_files_cannot_evade_forbidden_spans(project):
    from myzing.project.api import hash_file
    path = project / "project.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    original, duplicate = manifest["assets"][0], manifest["assets"][2]
    media = project / duplicate["path"]
    media.write_bytes((project / original["path"]).read_bytes())
    duplicate.update(sha256=hash_file(media), size=media.stat().st_size, mtime_ns=media.stat().st_mtime_ns)
    write_json(path, manifest)
    study_path = project / "breakdowns/take-2/breakdown.json"
    data = json.loads(study_path.read_text(encoding="utf-8"))
    data["provenance"]["source_sha256"] = duplicate["sha256"]
    write_json(study_path, data)
    # Exact source paths disambiguate two copies with the same checksum.
    change_brief(project, must_keep=[], forbidden=[{"clip": "take-0", "start": 0, "end": 8}])
    result = run(project)
    assert result["status"] == "ready", report(result)
    for plan in plans(result):
        assert all(c.asset_id == "take-1" for c in plan.clips)


def test_recipe_timing_deviations_are_measured_and_named(project):
    path = project / "recipe.json"
    recipe = json.loads(path.read_text(encoding="utf-8"))
    for fact in recipe["measured"]:
        if fact["name"].startswith("captions["):
            fact["value"]["start"] += 20
    write_json(path, recipe)
    result = run(project)
    assert result["status"] == "ready"
    for draft in report(result)["plans"].values():
        check = draft["match"]["first_caption_seconds"]
        assert check["status"] == "deviation" and check["planned"] < check["target"]
        assert any(d["metric"] == "first_caption_seconds" and d["reason"] for d in draft["deviations"])


def test_pinned_font_substitution_survives_and_blocks_legacy(project):
    from myzing.project.api import hash_file
    path = project / "recipe.json"
    recipe = json.loads(path.read_text(encoding="utf-8"))
    font = Path(__file__).resolve().parents[1] / "src/myzing/_data/fonts/IBMPlexSans.ttf"
    recipe["approximations"]["font_candidates"] = [{"version": 1, "family": "IBM Plex Sans",
        "substitution_evidence": ["fixture caption geometry suggests a sans substitution"],
        "asset": {"version": 1, "path": str(font), "sha256": hash_file(font), "license": "OFL-1.1"}}]
    write_json(path, recipe)
    result = run(project)
    assert result["status"] == "ready" and not result["v1_edls"]
    for plan in plans(result):
        assert all(c.font and c.font.sha256 == hash_file(font) for c in plan.captions)
    recipe["approximations"]["font_candidates"][0]["asset"] = None
    write_json(path, recipe)
    result = run(project)
    assert result["status"] == "shortage"
    assert report(result)["shortages"][0]["code"] == "font_asset"


def test_unmeasured_recipe_keeps_defaults_disclosed(project):
    path = project / "recipe.json"
    recipe = json.loads(path.read_text(encoding="utf-8"))
    recipe["measured"] = []
    write_json(path, recipe)
    result = run(project)
    assert result["status"] == "ready"
    for draft in report(result)["plans"].values():
        assert draft["match"]["median_shot_seconds"]["status"] == "unmeasured"
        assert draft["font"]["status"] == "disclosed default"
        assert draft["match"]["words_visible"]["status"] == "unmeasured"


def test_must_keep_longer_than_brief_names_length_shortage(project):
    change_brief(project, target_length_seconds=2, must_keep=[{"clip": "take-0", "start": 0, "end": 4}])
    result = run(project)
    assert report(result)["shortages"][0]["code"] == "must_keep_length"


def test_audio_map_silence_is_used_without_inventing_roles(project):
    from myzing.audio.models import AudioMap, Loudness, Segment, Tempo
    path = project / "breakdowns/take-2"
    audio = AudioMap(str(project / "clips/take-2.mp4"), 8, 48000, 60, False, Tempo(), [], [],
                     [Segment(0, 8, "silence", 1, "synthetic zero-energy measurement")], Loudness(None, None, None))
    write_json(path / "audio-map.json", audio.to_dict())
    result = run(project)
    assert result["status"] == "ready"
    assert report(result)["inventory"][2]["dead_air"][0]["label"] == "silence"
    assert all(c.asset_id != "take-2" for plan in plans(result) for c in plan.clips)
