"""Postable draft regressions: source color, skin, uniform captions, answers, slates."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from myzing.match.skin import compare_lab, summarize
from myzing.schemas import Breakdown, Shot, VideoMeta, Word


def test_source_default_skips_fitter_even_with_numpy_and_reference_opts_in(tmp_path, monkeypatch, zing_workspace):
    from tools.plan_examples import example_project
    from myzing.match import api
    from myzing.match.state import read, write
    from myzing.project.api import load_project, hash_file
    root, _, _ = example_project(tmp_path / "project")
    write(root / "match-state.json", {"version": 1, "steps": {}})
    reference = root / "clips/take-0.mp4"
    monkeypatch.setattr(api, "init", lambda *a: load_project(root))
    monkeypatch.setattr("myzing.match.preflight.check", lambda *a, **kw: {"problems": [], "warnings": []})
    monkeypatch.setattr(api, "capabilities", lambda: {"color": True, "audio": False, "fonts": False, "layout": False})
    monkeypatch.setattr(api, "resolve_reference", lambda *a: SimpleNamespace(
        state="resolved", path=str(reference), sha256=hash_file(reference), title="fixture"))
    monkeypatch.setattr(api, "_study", lambda *a, **kw: {
        "path": str(root / "breakdowns/take-0/breakdown.json"), "media": str(reference), "geometry": None, "outputs": []})
    monkeypatch.setattr(api, "_audio", lambda *a: {"outputs": []})
    def stop(*a, **kw):
        raise RuntimeError("stop after recipe")
    monkeypatch.setattr("myzing.director.api.plan_drafts", stop)
    calls = []
    def fitter(*a):
        calls.append(a)
        raise RuntimeError("reference fit reached")
    monkeypatch.setattr(api, "_color", fitter)
    result = api.match(str(reference), str(root / "clips"), root, answers={})
    assert not calls and result["color_mode"] == "source"
    assert result["failures"][0]["step"] == "director"
    assert read(root / "recipe.json")["color_mode"] == "source"
    assert "Color mode: source" in (root / "comparison.md").read_text()
    result = api.match(str(reference), str(root / "clips"), root, answers={}, resume=True, color="reference")
    assert len(calls) == 1 and result["color_mode"] == "reference"
    assert result["failures"][0]["step"].startswith("color-")


@pytest.mark.parametrize("mode", ["source", "reference"])
def test_cli_color_reaches_worker(mode, tmp_path, monkeypatch, capsys):
    from myzing.match import command
    captured = {}
    monkeypatch.setattr(command, "validate", lambda **kw: None)
    def execute(options, **kw):
        captured.update(options)
        return {"status": "ready"}
    monkeypatch.setattr(command, "execute", execute)
    assert command.run(["ref.mp4", "--clips", str(tmp_path), "--out", str(tmp_path / "out"),
                        "--answers", "{}", "--json", "--color", mode]) == 0
    assert captured["color"] == mode


def test_mcp_color_default_and_validation(tmp_path):
    import inspect
    from myzing.mcp_server import h_match_start
    assert inspect.signature(h_match_start).parameters["color"].default == "source"
    result = h_match_start("ref.mp4", str(tmp_path), str(tmp_path / "out"), answers={}, color="invalid")
    assert not result["ok"] and "color must be" in result["error"]


def test_source_plan_clears_an_old_grade(tmp_path):
    from myzing.composition import Composition, CompositionClip, AssetRef
    from myzing.composition.models import ColorTransform
    from myzing.style_recipe import StyleRecipe, ObservationProvenance
    from myzing.match.api import _prepare_plan
    from myzing.match.state import read, write
    plan = Composition(assets=[AssetRef("a", "clip.mp4", None)], clips=[CompositionClip(
        "clip.mp4", 0, 2, 0, id="a", asset_id="a", color=ColorTransform("old.cube", "a"*64, 1., "sRGB"))])
    write(tmp_path / "old.json", plan.to_dict())
    result = _prepare_plan(tmp_path / "old.json", tmp_path / "source.json", {},
                           StyleRecipe(ObservationProvenance("reference"), color_mode="source"), {"layout": False})
    assert Composition.from_dict(read(result["path"])).clips[0].color is None


def test_nasa_skin_chroma_loss_is_miss_and_report_warning():
    from myzing.match.evidence import report, markdown
    from myzing.style_recipe import build_style_recipe
    from myzing.composition import Composition
    face = compare_lab([70.1, 15.2, 22.2], [59.4, 4.7, 6.1])
    assert face["status"] == "miss" and face["decided_by"] == ["chroma_ratio"]
    assert face["chroma_ratio"] == pytest.approx(.286, abs=.002)
    assert face["components"]["lightness_drop"]["status"] == "approximate"
    skin = summarize([dict(source="nasa.mp4", timestamp=459.04, **face)], [])
    b = Breakdown(VideoMeta("fixture", "file", duration=1), shots=[Shot(0, 0, 1)])
    recipe = build_style_recipe(b)
    result = report(recipe, b, {}, None, {}, Composition(), skin=skin)
    assert any("Skin preservation miss" in w for w in result["warnings"])
    text = markdown({"summary": "fixture", "project": ".", "drafts": {}, "warnings": result["warnings"], "color_mode": "reference"})
    assert "Skin preservation miss" in text and "chroma_ratio" in text


@pytest.mark.parametrize("ratio,drop,status", [(.8, 6, "pass"), (.65, 12, "approximate"),
    (.649, 0, "miss"), (1, 12.01, "miss"), (.799, 0, "approximate"), (1, 6.01, "approximate")])
def test_skin_chroma_and_lightness_boundaries(ratio, drop, status):
    face = compare_lab([70., 12., 16.], [70.-drop, 12.*ratio, 16.*ratio])
    assert face["status"] == status


def test_gray_source_skips_unstable_ratio_but_still_checks_light():
    face = compare_lab([55., 1., 2.], [40., .1, .2])
    assert face["gray_source"] and face["chroma_ratio"] is None
    assert face["status"] == "miss" and face["decided_by"] == ["lightness_drop"]


@pytest.mark.ffmpeg
def test_podcast_reference_keeps_one_render_size_and_reports_zero_spread(tmp_path):
    from test_capref import caption_plan, reference
    from myzing.match.caption_fit import fit_captions
    from myzing.match.evidence import report
    plan = caption_plan("applications, sometimes as much encourage applicants that folks")
    assert len({c.style.size for c in plan.captions}) == 1
    fit_captions(plan, tmp_path)
    assert len({c.style.size * c.layout.scale for c in plan.captions}) == 1
    assert [w.text for c in plan.captions for w in c.words] == "applications, sometimes as much encourage applicants that folks".split()
    assert min(c.style.size for c in plan.captions) >= 24
    b = Breakdown(VideoMeta("render", "file", duration=2), shots=[Shot(0, 0, 2)])
    result = report(reference(), b, {}, None, {}, plan)
    assert result["dimensions"]["caption_size"]["size_spread_px"] == 0


@pytest.mark.parametrize("preset", ["punch", "box", "clean"])
def test_presets_have_one_size_across_shots_and_rails(preset):
    from test_caption2 import plan
    from myzing.captions.presets import apply_preset, phone_floor
    from myzing.captions.rail import place_presets
    p = plan("applications, sometimes as much encourage applicants that folks", 1080, 1920)
    p.clips = [replace(p.clips[0], src_out=1.8),
               replace(p.clips[0], id="shot2", src_in=1.8, timeline_start=1.8)]
    apply_preset(p, preset, vad=False)
    place_presets(p, {}, {})
    assert len({c.style.size * c.layout.scale for c in p.captions}) == 1
    assert all(c.style.size >= phone_floor(p, c.start, c.end, preset) for c in p.captions)


def test_answer_after_question_and_sentence_end_not_pause():
    from myzing.director.moments import suggest_moments
    from myzing.director.models import ClipStudy
    words = [Word("Why?", 0, .4), Word("So", .45, .7), Word("we", .7, 1.), Word("tried.", 1., 1.4),
             Word("It", 1.5, 1.7), Word("worked.", 1.7, 2.5), Word("unfinished,", 2.7, 3.5)]
    clip = ClipStudy("a", "a.mp4", "a"*64, 4, "ready", words=words, shots=[Shot(0, 0, 4)])
    rows = suggest_moments(clip, target=3, top=5)
    assert len(rows) == 1 and rows[0]["start"] == .45 and rows[0]["end"] == 2.5
    assert rows[0]["first_sentence"] == "So we tried."


def test_missing_question_mark_does_not_make_host_a_hook():
    from myzing.director.moments import opens_question
    assert opens_question("Where do we sit right now in terms of applications because I heard 600.")
    assert not opens_question("We received 600 applications.")
    assert not opens_question("What we've found is that experience matters.")


def test_misplaced_punctuation_does_not_promote_a_continuation():
    from myzing.director.moments import sentences
    words = [Word(text, i, i+.8) for i, text in enumerate(
        ["We", "need", "to.", "be", "qualified.", "Experience", "matters."])]
    assert [s.complete for s in sentences(words)] == [False, False, True]
    words[2].text = "can."
    assert [s.complete for s in sentences(words)] == [True, False, True]


def test_visual_rejection_one_second_graphics_and_unknown_gaps():
    from myzing.director.visual_quality import excluded_spans, filter_candidates
    clip = SimpleNamespace(duration=10, text_geometry={"frames": [{"t": 5., "detections": [
        {"text": "NASA", "confidence": .9, "box": [.1, .1, .9, .4]}]}]})
    samples = [{"time": t, "present": face} for t, face in
               [(0, True), (.5, False), (1., False), (1.5, True), (3, False), (5., False), (8., False)]]
    excluded = excluded_spans(clip, {"samples": samples})
    assert (.5, 1.5) in excluded and (4.75, 5.5) in excluded
    assert not any(a <= 3 <= b or a <= 8 <= b for a, b in excluded)
    pool = [SimpleNamespace(asset_id="a", start=a, end=b) for a, b in [(0, .5), (.4, 2), (4, 6), (6, 7)]]
    assert filter_candidates(pool, {"a": excluded}) == [pool[0], pool[-1]]
    assert excluded_spans(clip, {}) == []
    assert excluded_spans(SimpleNamespace(duration=10, text_geometry={}), {"samples": samples[1:3]}) == []
    for geometry in (
        {"tracks": [{"text": "NASA", "samples": [{"t": 5., "box": [.1, .1, .9, .4]}]}]},
        {"protected_samples": [{"t": 5., "boxes": [[.1, .1, .9, .4]], "words": 1}]},
    ):
        clip.text_geometry = geometry
        assert (4.75, 5.5) in excluded_spans(clip, {"samples": [{"time": 5., "present": False}]})


def test_director_filters_slates_before_choosing_and_keeps_music_exclusions(tmp_path, monkeypatch):
    from tools.plan_examples import example_project
    from myzing.director.api import plan_drafts
    from myzing.match.state import read, write
    root, _, _ = example_project(tmp_path / "project")
    brief = read(root / "brief.json")
    brief["picture_crop"] = "off"
    write(root / "brief.json", brief)
    def subjects(*a, presence=None, **kw):
        presence["samples"] = [{"time": i*.5, "present": i >= 2} for i in range(16)]
        return [], []
    monkeypatch.setattr("myzing.layout.framing.analyze_subjects", subjects)
    result = plan_drafts(root, root / "recipe.json", tmp_path / "plans")
    assert result["plans"], result
    report = read(result["comparison_path"])
    assert report["visual_selection"]["rejected_candidates"] > 0
    for path in result["plans"].values():
        plan = read(path)
        assert all(c["src_in"] >= 1 for c in plan["clips"])
    assert all((0, 1) in [tuple(s) for s in spans]
               for p in report["plans"].values() for spans in p["constraints"]["forbidden_word_safe"].values())
