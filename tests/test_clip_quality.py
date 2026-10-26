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


def test_recipe_defaults_to_source_for_new_and_legacy_payloads():
    from myzing.style_recipe import StyleRecipe, ObservationProvenance, build_style_recipe
    recipe = StyleRecipe(ObservationProvenance("reference"))
    assert recipe.color_mode == "source"
    payload = recipe.to_dict()
    del payload["color_mode"]
    assert StyleRecipe.from_dict(payload).color_mode == "source"
    payload["color_mode"] = "reference"
    assert StyleRecipe.from_dict(payload).color_mode == "reference"
    assert build_style_recipe(Breakdown(VideoMeta("fixture", "file", duration=1))).color_mode == "source"


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
    recipe.color_mode = "reference"
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


@pytest.mark.parametrize("mixed_preset", [False, True])
def test_fallback_captions_share_one_size_including_earlier_and_preset_cues(tmp_path, monkeypatch, mixed_preset):
    from myzing.composition import Composition, CompositionCaption, CaptionStyle, CompositionClip, AssetRef
    from myzing.layout import Box
    from myzing.layout.types import EventLayout, OverlapCheck
    from myzing.match import caption_fit
    captions = [CompositionCaption(text, i, i+1, id=f"c{i}", word_timed=False, style=CaptionStyle(size))
                for i, (text, size) in enumerate([("as much", 60), ("applications", 48), ("that folks", 72)])]
    captions[0].layout = EventLayout("c0", 0, 1, "fixture", OverlapCheck(True),
                                   box=Box(.1, .7, .8, .2), scale=.8)
    if mixed_preset:
        from myzing.captions.metrics import font_asset
        captions[0].preset = "clean"
        captions[0].font = font_asset("clean")
    plan = Composition(width=600, height=1000, captions=captions,
                       assets=[AssetRef("a", "fixture.mp4", None)],
                       clips=[CompositionClip("fixture.mp4", 0, 3, 0, id="clip", asset_id="a")])
    def ink(caption, style, *args):
        lines = caption.text.splitlines()
        return 0, 0, max(map(len, lines)) * style.size, len(lines) * style.size
    monkeypatch.setattr(caption_fit, "_measure", ink)
    caption_fit.fit_captions(plan, tmp_path)
    assert len({c.style.size for c in plan.captions}) == 1
    assert len({c.style.size * (c.layout.scale if c.layout else 1.) for c in plan.captions}) == 1
    assert 24 <= captions[0].style.size < 48
    assert [c.text.replace("\n", " ") for c in plan.captions] == ["as much", "applications", "that folks"]


def test_fallback_rewraps_before_lowering_whole_draft_size(tmp_path, monkeypatch):
    from myzing.composition import Composition, CompositionCaption, CaptionStyle, CompositionClip, AssetRef
    from myzing.match import caption_fit
    plan = Composition(width=600, height=1000, captions=[
        CompositionCaption("alpha beta gamma delta", 0, 1, id="long", word_timed=False, style=CaptionStyle(40)),
        CompositionCaption("short", 1, 2, id="short", word_timed=False, style=CaptionStyle(40))],
        assets=[AssetRef("a", "fixture.mp4", None)],
        clips=[CompositionClip("fixture.mp4", 0, 2, 0, id="clip", asset_id="a")])
    monkeypatch.setattr(caption_fit, "_measure", lambda c, s, *a:
                        (0, 0, max(map(len, c.text.splitlines())) * s.size, len(c.text.splitlines()) * s.size))
    caption_fit.fit_captions(plan, tmp_path)
    assert {c.style.size for c in plan.captions} == {40}
    assert "\n" in plan.captions[0].text


def test_answer_after_question_and_sentence_end_not_pause():
    from myzing.director.moments import suggest_moments
    from myzing.director.models import ClipStudy
    words = [Word("Why?", 0, .4), Word("So", .45, .7), Word("we", .7, 1.), Word("tried.", 1., 1.4),
             Word("It", 1.5, 1.7), Word("worked.", 1.7, 2.5), Word("unfinished,", 2.7, 3.5)]
    clip = ClipStudy("a", "a.mp4", "a"*64, 4, "ready", words=words, shots=[Shot(0, 0, 4)])
    rows = suggest_moments(clip, target=3, top=5)
    assert len(rows) == 1 and rows[0]["start"] == .45 and rows[0]["end"] == 2.5
    assert rows[0]["first_sentence"] == "So we tried."


@pytest.mark.parametrize("text", [
    "Is what we learned useful.", "Are is a unit of area.", "Do the work first.",
    "Have a plan before applying.", "Will was our pilot.", "Can is the word we used.",
    "Where do we sit right now in terms of applications because I heard 600.",
])
def test_question_detection_uses_terminal_punctuation(text):
    from myzing.director.moments import opens_question
    assert not opens_question(text)
    assert opens_question(text[:-1] + '?"  ')


@pytest.mark.parametrize("text", [
    "You know, training matters.", "And it's like Anne was saying, training matters.",
    "Like I said, training matters.", "As Anne was saying, training matters.",
    "That's why training matters.", "It takes two years.", "That takes two years.",
    "This takes two years.", "They take two years.", "It's a long process.",
])
def test_filler_and_back_reference_openings_are_rejected_even_after_question(text):
    from myzing.director.moments import usable_opening
    assert not usable_opening(text)
    assert not usable_opening(text, "What happened?")


@pytest.mark.parametrize("conjunction", ["So", "And", "But"])
def test_conjunction_opening_requires_previous_question(conjunction):
    from myzing.director.moments import usable_opening
    text = f"{conjunction} we tried."
    assert not usable_opening(text)
    assert not usable_opening(text, "Training matters.")
    assert usable_opening(text, "What happened?")


@pytest.mark.parametrize("answer_end,expected", [(2., True), (1.8, False)])
def test_moment_stops_before_question_at_minimum_length(answer_end, expected):
    from myzing.director.moments import suggest_moments
    from myzing.director.models import ClipStudy
    words = [Word("Training", 0, .5), Word("changed", .5, 1.), Word("everything.", 1., answer_end),
             Word("Why?", answer_end + .1, answer_end + .6)]
    clip = ClipStudy("a", "a.mp4", "a"*64, 3, "ready", words=words, shots=[Shot(0, 0, 3)])
    rows = suggest_moments(clip, target=3, top=5)
    assert bool(rows) == expected
    if rows:
        assert rows[0]["end"] == answer_end
        assert rows[0]["last_sentence"] == "Training changed everything."


def test_complete_claim_beats_denser_fragment_and_actually_is_not_contrast():
    from myzing.director.moments import suggest_moments
    from myzing.director.models import ClipStudy
    words = [Word("Actually", 0, .5), Word("training", .5, 1), Word("every", 1, 1.5),
             Word("day.", 1.5, 3), Word("Our", 4, 4.4), Word("initial", 4.5, 4.9),
             Word("training", 5, 5.4), Word("is", 5.5, 5.9), Word("two", 6, 6.4), Word("years.", 6.5, 7)]
    clip = ClipStudy("a", "a.mp4", "a"*64, 8, "ready", words=words, shots=[Shot(0, 0, 8)])
    rows = suggest_moments(clip, target=3, top=2)
    assert rows[0]["start"] == 4
    assert not any("contrast" in reason for row in rows for reason in row["reasons"])


def test_misplaced_punctuation_does_not_promote_a_continuation():
    from myzing.director.moments import sentences
    words = [Word(text, i, i+.8) for i, text in enumerate(
        ["We", "need", "to.", "be", "qualified.", "Experience", "matters."])]
    assert [s.complete for s in sentences(words)] == [False, False, True]
    words[2].text = "can."
    assert [s.complete for s in sentences(words)] == [True, False, True]


def test_visual_rejection_one_second_graphics_and_unknown_gaps():
    from myzing.director.visual_quality import excluded_spans, filter_candidates
    from myzing.director.models import ClipStudy
    from myzing.director.selection import Candidate
    clip = ClipStudy("a", "a.mp4", "a"*64, 10, "ready", shots=[Shot(0, 0, 10)],
        text_geometry={"frames": [{"t": 5., "detections": [
        {"text": "How do I apply to be an astronaut?", "confidence": .9, "box": [.1, .1, .9, .4]}]}]})
    samples = [{"time": t, "present": face} for t, face in
               [(0, True), (.5, False), (1., False), (1.5, True), (3, False), (5., False), (8., False)]]
    excluded = excluded_spans(clip, {"samples": samples})
    assert (.5, 1.5) in excluded and (4.75, 5.5) in excluded
    assert not any(a <= 3 <= b or a <= 8 <= b for a, b in excluded)
    pool = [Candidate("a", "a"*64, a, b, 0, 0, None, "", False, False)
            for a, b in [(0, .5), (.4, 2), (4, 6), (6, 7)]]
    assert [(c.start, c.end) for c in filter_candidates(pool, {"a": excluded}, [clip])] == [
        (0, .5), (1.5, 2), (4, 4.75), (5.5, 6), (6, 7)]
    assert excluded_spans(clip, {}) == []
    assert excluded_spans(SimpleNamespace(duration=10, text_geometry={}), {"samples": samples[1:3]}) == []
    for geometry in (
        {"tracks": [{"text": "NASA", "samples": [{"t": 5., "box": [.1, .1, .9, .4]}]}]},
        {"protected_samples": [{"t": 5., "boxes": [[.1, .1, .9, .4]], "words": 1}]},
    ):
        clip.text_geometry = geometry
        assert excluded_spans(clip, {"samples": [{"time": 0., "present": True}, {"time": 5., "present": False}]}) == []


def test_screen_recording_with_large_multiline_text_is_not_excluded():
    from myzing.director.visual_quality import excluded_spans
    clip = SimpleNamespace(duration=10, text_geometry={"protected_samples": [
        {"t": 5., "boxes": [[.1, .1, .9, .8]], "words": 15}]})
    assert excluded_spans(clip, {"samples": [{"time": i*.5, "present": False} for i in range(20)]}) == []


def test_visual_trim_preserves_complete_words_and_recomputes_required_coverage():
    from myzing.director.visual_quality import filter_candidates
    from myzing.director.models import ClipStudy
    from myzing.director.selection import Candidate
    words = [Word("Training", .5, 1), Word("matters.", 1, 2),
             Word("Practice", 2.2, 3), Word("helps.", 3, 4)]
    clip = ClipStudy("a", "a.mp4", "a"*64, 6, "ready", words=words, shots=[Shot(0, 0, 6)])
    candidate = Candidate("a", "a"*64, 0, 6, 0, 4, .5,
                          "Training matters. Practice helps.", False, False, covers=1)
    result = filter_candidates([candidate], {"a": [(0, .8), (5, 6)]}, [clip], [("a", 2.2, 4)])
    assert len(result) == 1
    trim = result[0]
    assert (trim.start, trim.end, trim.covers, trim.word_count) == (2, 5, 1, 2)
    assert trim.first_word == pytest.approx(.2) and trim.text == "Practice helps."
    # A required span that only touches an exclusion stays whole.
    [kept] = filter_candidates([candidate], {"a": [(0, .8), (5, 6)]}, [clip], [("a", .5, 4)])
    assert (kept.start, kept.end, kept.covers, kept.word_count) == (.5, 5, 1, 4)
    # One mostly inside an exclusion cannot be rescued.
    assert all(not c.covers for c in filter_candidates([candidate], {"a": [(0, 2.1), (5, 6)]}, [clip], [("a", .5, 2.3)]))


def test_protect_keeps_partly_excluded_required_spans_only():
    from myzing.director.visual_quality import mostly_excluded, protect
    spans = [(0, 1), (3, 4)]
    assert protect(spans, [(.5, 2)]) == [(0, .5), (3, 4)]
    assert protect(spans, [(3.2, 3.8)]) == spans and protect(spans, [(2.9, 3.8)]) == spans
    assert mostly_excluded((2.9, 3.8), spans) and not mostly_excluded((.5, 2), spans)


@pytest.mark.parametrize("required", ["none", "slate", "partial"])
def test_director_filters_slates_before_choosing_and_keeps_music_exclusions(tmp_path, monkeypatch, required):
    from tools.plan_examples import example_project
    from myzing.director.api import plan_drafts
    from myzing.match.state import read, write
    root, _, _ = example_project(tmp_path / "project")
    brief = read(root / "brief.json")
    brief["picture_crop"] = "off"
    required_is_slate = required == "slate"
    if required_is_slate:
        brief["must_keep"] = [{"clip": "take-0", "start": .25, "end": 1}]
    if required == "partial":
        brief["must_keep"] = [{"clip": "take-0", "start": .5, "end": 2}]
    write(root / "brief.json", brief)
    def subjects(*a, presence=None, **kw):
        # The slate case widens the face-free opening past the whole-word
        # must-keep (0.25-2.0 s), so the required line is itself face-free.
        first_face = 5 if required_is_slate else 2
        presence["samples"] = [{"time": i*.5, "present": i >= first_face} for i in range(16)]
        return [], []
    monkeypatch.setattr("myzing.layout.framing.analyze_subjects", subjects)
    result = plan_drafts(root, root / "recipe.json", tmp_path / "plans")
    if required_is_slate:
        assert not result["plans"]
        assert result["summary"]["shortages"][0]["code"] == "visual_quality"
        return
    assert result["plans"], result
    report = read(result["comparison_path"])
    assert report["visual_selection"]["affected_candidates"] > 0
    if required == "partial":
        # The must-keep only nicks the face-free opening, so it survives whole.
        for path in result["plans"].values():
            assert any(c["src_in"] <= .5 + 1e-6 and c["src_out"] >= 2 - 1e-6 for c in read(path)["clips"])
        return
    for path in result["plans"].values():
        plan = read(path)
        assert all(c["src_in"] >= 1 for c in plan["clips"])
    assert all((0, 1) in [tuple(s) for s in spans]
               for p in report["plans"].values() for spans in p["constraints"]["forbidden_word_safe"].values())


@pytest.mark.parametrize("text,ok", [
    ("We also give applicants an opportunity to describe hobbies.", False),
    ("Also, training takes two years.", False),
    ("Another thing we look for is teamwork.", False),
    ("No, it was fine.", False), ("Well, training matters.", False),
    ("No one expected eighteen thousand applications.", True),
    ("Right now we have eighteen thousand applicants.", True),
    ("incorporate that kind of training whenever we can.", False),
])
def test_additive_and_interjection_openings(text, ok):
    from myzing.director.moments import usable_opening
    assert usable_opening(text) is ok


def test_window_never_stops_before_a_continuation_or_on_a_wh_inversion():
    from myzing.director.moments import suggest_moments
    from myzing.director.models import ClipStudy
    # "Training matters." could end the window at 1.4 s, but the next sentence
    # starts lowercase and continues it, so the window runs to 2.9 s instead.
    words = [Word("Training", 0, .5), Word("matters.", .5, 1.4), Word("every", 1.5, 2.),
             Word("single", 2., 2.4), Word("day.", 2.4, 2.9), Word("Where", 3., 3.3), Word("do", 3.3, 3.5),
             Word("we", 3.5, 3.7), Word("go", 3.7, 3.9), Word("now.", 3.9, 4.2)]
    clip = ClipStudy("a", "a.mp4", "a"*64, 5, "ready", words=words, shots=[Shot(0, 0, 5)])
    rows = suggest_moments(clip, target=4, top=5)
    assert rows and rows[0]["start"] == 0 and rows[0]["end"] == 2.9
    assert rows[0]["last_sentence"] == "every single day."
