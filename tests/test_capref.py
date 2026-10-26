"""CAPREF: preserve reference cadence/appearance and source graphic text."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from myzing.brief.models import Brief
from myzing.captions.reference import appearance, groups, place, word_band
from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip, CaptionStyle
from myzing.director.plans import captions_for
from myzing.director.selection import envelope
from myzing.layout.framing import centered_framing
from myzing.layout.text_safety import protect_text
from myzing.match.caption_fit import fit_captions
from myzing.match.evidence import report
from myzing.schemas import Breakdown, CaptionEvent, Shot, VideoMeta, Word
from myzing.study import caption_geometry as cg
from myzing.study.captions import Line, Observation, cluster_regions
from myzing.style_recipe import build_style_recipe


def reference():
    b = Breakdown(VideoMeta("fixture", "file", duration=4, fps=30), shots=[Shot(0, 0, 4)],
        captions=[CaptionEvent(text, i, i+.8, "lower", False, 2) for i, text in enumerate(
            ("Trust your", "own gut", "Be brave", "Stay curious"))],
        words=[Word(text, i, i+.8) for i, text in enumerate(("Trust your", "own gut", "Be brave", "Stay curious"))])
    return build_style_recipe(b)


def caption_plan(text="What do you have to do to stand out from all the other applicants?"):
    recipe = reference()
    words = [Word(t, i*.2, (i+1)*.2) for i, t in enumerate(text.split())]
    brief = Brief(caption_mode="reference", aspect="9:16")
    sequence = [SimpleNamespace(asset_id="a", start=0, end=len(words)*.2, duration=len(words)*.2)]
    study = SimpleNamespace(asset_id="a", words=words)
    captions = captions_for(sequence, [study], envelope(recipe), recipe, None, brief)
    plan = Composition(captions=captions, brief=brief, width=1080, height=1920,
        assets=[AssetRef("a", "card.mp4", None)],
        clips=[CompositionClip(id="source", asset_id="a", src="card.mp4", src_in=0,
                               src_out=len(words)*.2, timeline_start=0)])
    place(plan, recipe, {}, {})
    return plan


def test_reference_groups_are_two_words_white_word_timed_without_plate():
    plan = caption_plan()
    assert [c.text for c in plan.captions[:3]] == ["What do", "you have", "to do"]
    assert all(len(c.text.split()) == 2 and c.word_timed and not c.all_caps for c in plan.captions)
    assert all(c.style.box_color is None and c.style.color == c.style.highlight == "#FFFFFF" for c in plan.captions)
    assert all(c.position == "lower" and c.layout.box.center[1] == pytest.approx(2/3) for c in plan.captions)
    assert any("Estimated" in w for w in plan.warnings)


def test_reference_spread_case_rate_and_indivisible_numbers():
    assert word_band([1, 2, 2, 2, 3])["lower"] == 2
    assert word_band([1, 2, 2, 2, 3])["upper"] == 2
    words = [Word(t, i, i+.8) for i, t in enumerate(["18", ",", "000", "applications", "arrived"])]
    assert [[w.text for w in g] for g in groups(words, 2)] == [["18", ",", "000", "applications"], ["arrived"]]
    plan = caption_plan("One two three")
    assert any("1 words outside reference band" in w for w in plan.warnings)


def test_reference_appearance_excludes_title_and_requires_measured_plate():
    geometry = {"frames": [{"detections": [
        {"appearance": {"fill": {"rgb": [250, 240, 230], "confidence": .9},
                        "outline": {"rgb": [10, 20, 30], "confidence": .9}}},
        {"appearance": {"plate_present": True, "plate_color": {"rgb": [255, 0, 0], "confidence": .9}}}]}],
        "tracks": [{"kind": "caption", "alignment": "left", "alignment_confidence": .8,
                    "samples": [{"sample_index": 0, "detection_indices": [0]}]},
                   {"kind": "overlay", "samples": [{"sample_index": 0, "detection_indices": [1]}]}]}
    measured = appearance(geometry)
    assert measured == {"color": "#FAF0E6", "outline_color": "#0A141E", "alignment": "left"}
    geometry["frames"][0]["detections"][0]["appearance"].update(
        plate_present=True, plate_color={"rgb": [12, 12, 12], "confidence": .8})
    assert appearance(geometry)["box_color"] == "#0C0C0C"


def test_measured_position_alignment_and_appearance_reach_plan():
    recipe = reference()
    template = recipe.measured[0]
    recipe.measured.extend([
        replace(template, name="caption_geometry.summary", value={"box": [.1,.55,.5,.6]}),
        replace(template, name="caption_appearance", value={"color":"#FAF0E6", "outline_color":"#123456",
                  "outline_fraction":.001, "alignment":"left", "box_color":"#111111"})])
    plan = caption_plan("Hello there")
    plan.captions[0].layout = None
    place(plan,recipe,{}, {})
    caption = plan.captions[0]
    assert caption.alignment == "left" and caption.layout.box.x == .1
    assert caption.layout.box.center[1] == pytest.approx(.575)
    assert caption.style.color == caption.style.highlight == "#FAF0E6"
    # Unmeasured shadow gets a disclosed legibility outline, even when the
    # measured outline alone is thinner; retain its measured color.
    assert caption.style.outline_width == pytest.approx(5.76) and caption.style.outline_color == "#123456"
    assert caption.style.box_color == "#111111"


def test_merged_persistent_title_is_removed_before_caption_facts():
    phrases = ["I've ever done", "Trust your", "own gut", "Stay curious"]
    observations = [Observation(i*.25, .25, [Line(phrases[i//4], .95, .66, .5),
        Line("LEARN TO TRUST YOUR GUT", .95, .72, .5)]) for i in range(16)]
    events, notes = cluster_regions(observations, 4)
    assert [c.text for c in events] == phrases
    assert [c.words_visible for c in events] == [3, 2, 2, 2]
    assert all(c.position == "lower" and not c.all_caps for c in events)
    assert any("before region merging" in n for n in notes)


def test_background_cannot_become_a_thick_caption_outline():
    geometry = {"frames": [{"detections": [{"appearance": {
        "outline": {"rgb": [29,20,21], "confidence": .6}, "stroke_confidence": .6,
        "stroke_width_fraction": .009375, "text_height": .035}}]}],
        "tracks": [{"kind": "caption", "samples": [{"sample_index": 0, "detection_indices": [0]}]}]}
    measured = appearance(geometry)
    assert "outline_color" not in measured and "outline_fraction" not in measured
    assert measured["outline_rejected_samples"] == 1
    geometry["frames"][0]["detections"][0]["appearance"]["stroke_width_fraction"] = .002
    assert appearance(geometry)["outline_fraction"] == .002


def test_geometry_tracks_split_title_from_changing_line():
    frames = []
    phrases = ["I've ever done", "Trust your", "own gut", "Stay curious"]
    for i in range(16):
        detections = []
        for text, y in ((phrases[i//4], .61), ("LEARN TO TRUST YOUR GUT", .68)):
            box = [.15, y, .85, y+.05]
            detections.append(cg.Detection(text, .95, [[.15,y],[.85,y],[.85,y+.05],[.15,y+.05]], box))
        frames.append(cg.FrameSample(i*.25, i*.25, .25, i*6, 640, 360, detections))
    geometry = cg.CaptionGeometry(8, frames, cg.track_frames(frames, 8))
    events = cg.caption_events(geometry)
    assert [c.text for c in events] == phrases
    assert [c.words_visible for c in events] == [3, 2, 2, 2]
    assert any(t.kind == "overlay" and t.text == "LEARN TO TRUST YOUR GUT" for t in geometry.tracks)
    # Raw text geometry remains available for source crop protection.
    assert len(geometry.frames[0].detections) == 2


def card_geometry():
    return {"frames": [{"t": 1., "detections": [{"text": "What do you have to do to stand out from all the other applicants?",
            "confidence": .95, "box": [.05, .15, .95, .7]}]}]}


def test_text_card_forces_full_source_blurfill_and_is_shot_local():
    clip = CompositionClip(id="card", asset_id="a", src="card.mp4", src_in=0, src_out=2, timeline_start=0)
    framing = centered_framing("fill", 1920, 1080, 1080, 1920)
    result = protect_text(framing, clip, card_geometry(), "reframe", 1080, 1920)
    assert result.mode == "blurfill" and result.width == 1920 and result.height == 1080
    assert result.picture["text_safety"]["decision"] == "full-source blurfill"
    assert "Shot card (0-2s)" in result.warnings[-1]
    other = replace(clip, src_in=2, src_out=4)
    assert protect_text(framing, other, card_geometry(), "reframe", 1080, 1920) is framing
    full = centered_framing("fit", 1920, 1080, 1920, 1080)
    assert protect_text(full, clip, card_geometry(), "reframe", 1920, 1080).mode == "fit"


def test_reference_fit_splits_before_shrinking_and_discloses(monkeypatch, tmp_path):
    plan = caption_plan("extraordinarily astronomical")
    original = plan.captions[0].style.size
    def measure(caption, style, *args):
        return (0, 0, style.size*10*len(caption.words), style.size)
    monkeypatch.setattr("myzing.match.caption_fit._measure", measure)
    fit_captions(plan, tmp_path)
    assert len(plan.captions) == 2
    assert all(c.style.size == original and "\n" not in c.text for c in plan.captions)
    assert all(c.layout.start == c.start and c.layout.end == c.end for c in plan.captions)
    assert sum("reference grouping deviation" in w for w in plan.warnings) == 2


def test_indivisible_word_fails_at_floor_without_multiline_fallback(monkeypatch,tmp_path):
    plan = caption_plan("indivisible")
    monkeypatch.setattr("myzing.match.caption_fit._measure", lambda *args: (0,0,2000,50))
    with pytest.raises(ValueError, match="readability floor"):
        fit_captions(plan,tmp_path)
    assert "\n" not in plan.captions[0].text and plan.captions[0].style.box_color is None
    plan.captions[0].words = []
    with pytest.raises(ValueError, match="require ordered word timings"):
        fit_captions(plan,tmp_path)
    assert plan.captions[0].text == "indivisible"  # failure must not erase authored text


def test_track_only_text_card_combines_simultaneous_lines():
    geometry = {"tracks": [{"text":"four words per line", "samples":[{"t":1.,
        "box":[.05,.1+i*.15,.95,.2+i*.15]}]} for i in range(3)]}
    clip = CompositionClip(id="card",asset_id="a",src="card.mp4",src_in=0,src_out=2,timeline_start=0)
    cropped = centered_framing("fill",1920,1080,1080,1920)
    assert protect_text(cropped,clip,geometry,"reframe",1080,1920).mode == "blurfill"


def test_sentence_block_and_wrong_case_are_reported_as_misses():
    text = "WHAT DO YOU HAVE TO DO TO STAND OUT FROM ALL THE OTHER APPLICANTS"
    output = Breakdown(VideoMeta("fixture", "file", duration=4, fps=30), shots=[Shot(0, 0, 4)],
        words=[Word(text, 0, 3)], captions=[CaptionEvent(text, 0, 3, "lower", True, len(text.split()))])
    dimensions = report(reference(), output, {}, None, {}, Composition())["dimensions"]
    assert dimensions["caption_words"]["status"] == dimensions["caption_case"]["status"] == "miss"
    assert dimensions["caption_words"]["target"] == 2


def test_delivery_retains_reference_style_and_text_card_protection():
    from myzing.layout.delivery import adapt_plan
    plan = caption_plan()
    clip = CompositionClip(id="card", asset_id="a", src="card.mp4", src_in=0, src_out=3, timeline_start=0)
    clip.framing = protect_text(centered_framing("fill", 1920, 1080, 1080, 1920), clip,
                                card_geometry(), "reframe", 1080, 1920)
    plan.clips = [clip]
    adapted = adapt_plan(plan, 720, 1280, {"a": (1920,1080)}, {}, requested="reframe")
    assert adapted.clips[0].framing.mode == "blurfill"
    assert all(c.style.box_color is None and c.style.highlight == c.style.color and c.word_timed for c in adapted.captions)


def timed(text):
    return [Word(t, i*.2, (i+1)*.2) for i, t in enumerate(text.split())]


def test_band_keeps_three_word_clause_and_rebalances_tails():
    band = {"median": 2, "lower": 2, "upper": 3}
    words = timed("From the web,")
    assert groups(words, band) == [words]
    for count in range(2, 41):
        words = timed(" ".join(f"word{i}" for i in range(count)))
        parts = groups(words, band)
        assert all(2 <= len(p) <= 3 for p in parts)
        assert [w for p in parts for w in p] == words
    plan = caption_plan("Yes.")
    assert [c.text for c in plan.captions] == ["Yes."]
    assert any("single-word caption retained" in w for w in plan.warnings)


def test_reference_uses_band_in_planner_and_glues_contractions_and_hyphens():
    recipe = reference()
    for fact in recipe.measured:
        if fact.name.startswith("captions["):
            fact.value["words_visible"] = 3 if fact.value["text"] in ("Be brave", "Stay curious") else 2
    words = timed("From the web, I 'm well - known and do n't worry.")
    # Make the opening a separate source clause.
    words = [replace(w, start=w.start+.4, end=w.end+.4) if i >= 3 else w for i,w in enumerate(words)]
    seq = [SimpleNamespace(asset_id="a", start=0, end=4, duration=4)]
    captions = captions_for(seq, [SimpleNamespace(asset_id="a", words=words)], envelope(recipe), recipe, None,
                            Brief(caption_mode="reference"))
    assert captions[0].text == "From the web,"
    displayed = " ".join(c.text for c in captions)
    assert "I'm" in displayed and "well-known" in displayed and "don't" in displayed
    assert all(2 <= len(c.text.split()) <= 3 for c in captions)
    assert captions[-1].words[-1].end == words[-1].end


@pytest.mark.parametrize("ratio,weight", [(.07,400), (.13,700), (.21,None)])
def test_fill_stroke_selects_weight_only_with_plausible_measured_ink(ratio, weight):
    sample = {"text_height": .03, "geometry_confidence": .9,
              "ink_evidence": {"stroke_to_ink_height": ratio, "component_count": 8}}
    geometry = {"frames": [{"height": 1920, "detections": [{"appearance": sample}]}],
                "tracks": [{"kind": "caption", "samples": [{"sample_index": 0, "detection_indices": [0]}]}]}
    measured = appearance(geometry)
    assert measured.get("weight") == weight
    assert measured["text_height"] == .03
    sample["geometry_confidence"] = .2
    assert "weight" not in appearance(geometry)


def test_cached_stroke_fraction_uses_proposal_pixels_and_ink_height():
    sample = {"text_height": .03, "geometry_confidence": .9,
              "ink_evidence": {"stroke_fraction": .09, "component_count": 8}}
    geometry = {"frames": [{"height": 2000, "detections": [{"appearance": sample,
        "polygon": [[.1,.1],[.8,.1],[.8,.14],[.1,.14]]}]}],
        "tracks": [{"kind": "caption", "samples": [{"sample_index": 0, "detection_indices": [0]}]}]}
    measured = appearance(geometry)
    assert measured["ink_stroke_ratio"] == pytest.approx(.12)
    assert measured["weight"] == 700
    assert "stroke_to_ink_height" not in sample["ink_evidence"]  # cached evidence is immutable


def test_bold_substitute_ink_size_and_shadow_fallback_are_disclosed():
    from myzing.captions.metrics import font_asset, metrics
    recipe = reference()
    recipe.measured.append(replace(recipe.measured[0], name="caption_appearance", value={"text_height": .03}))
    plan = caption_plan("Trust yourself")
    place(plan, recipe, {}, {})
    c = plan.captions[0]
    assert c.font == font_asset("clean")
    assert metrics(c.font.path, c.font.sha256).ink_height(c.text, c.style.size) == pytest.approx(57.6)
    assert c.style.outline_width == pytest.approx(57.6*.06)
    note = next(w for w in plan.warnings if w.startswith("CAPREF typography:"))
    assert "Estimated weight 700" in note and "Estimated shadow" in note and "not a font match" in note
    assert any("Measured median text_height" in w for w in plan.warnings)


def test_matching_median_does_not_hide_outside_band_distribution():
    events = [CaptionEvent(text, i, i+.8, "lower", False, len(text.split())) for i,text in enumerate(
        ["One", "Two words", "Three words here", "Four", "Five words", "Six words here"])]
    output = Breakdown(VideoMeta("fixture", "file", duration=6, fps=30), shots=[Shot(0,0,6)],
        captions=events, words=[Word(c.text, c.start, c.end) for c in events])
    metric = report(reference(), output, {}, None, {}, Composition())["dimensions"]["caption_words"]
    assert metric["target"] == metric["observed"] == 2
    assert metric["status"] == "miss"
    assert metric["outside_band_share"]["observed"] == pytest.approx(4/6)
    assert metric["outside_band_share"]["reference"] == 0


def test_two_second_caption_beside_three_changes_is_not_a_title():
    from myzing.study.captions import persistent_lines
    observations = [Observation(i*.25, .25, [Line("Hold this thought", .95, .66, .5),
        Line(("One phrase", "Next phrase", "Last phrase")[min(i//3,2)], .95, .72, .5)]) for i in range(8)]
    assert persistent_lines(observations, 8) == []
    _, notes = cluster_regions(observations, 8)
    assert not any("persistent" in n for n in notes)
    frames = []
    for obs in observations:
        detections = [cg.Detection(l.text, l.score, [[.15,l.y_center],[.85,l.y_center],
            [.85,l.y_center+.04],[.15,l.y_center+.04]], [.15,l.y_center,.85,l.y_center+.04]) for l in obs.lines]
        frames.append(cg.FrameSample(obs.t,obs.t,obs.step,round(obs.t*30),640,360,detections))
    assert all(t.kind == "caption" for t in cg.track_frames(frames, 8))


def test_square_text_card_preserves_full_source():
    clip = CompositionClip(id="square-card",asset_id="a",src="card.mp4",src_in=0,src_out=2,timeline_start=0)
    cropped = centered_framing("fill",1920,1080,1080,1080)
    protected = protect_text(cropped,clip,card_geometry(),"auto",1080,1080)
    assert protected.mode == "blurfill" and (protected.width,protected.height) == (1920,1080)
    square = centered_framing("fit",1080,1080,1080,1080)
    retained = protect_text(square,clip,card_geometry(),"auto",1080,1080)
    assert retained.mode == "fit" and retained.picture["text_safety"]["decision"] == "retain crop"


@pytest.mark.ffmpeg
def test_reference_bold_fill_ink_matches_measured_height_in_libass(tmp_path):
    from pathlib import Path
    from myzing.render.font_files import private_font, ass_em_scale
    from myzing.render.positioned_captions import _measure, caption_runs
    recipe = reference()
    recipe.measured.append(replace(recipe.measured[0],name="caption_appearance",value={"text_height":.03}))
    plan = caption_plan("Trust yourself")
    place(plan,recipe,{}, {})
    c = plan.captions[0]
    alias, payload = private_font(Path(c.font.path).read_bytes())
    (tmp_path/"fonts").mkdir()
    (tmp_path/"fonts"/(alias+".ttf")).write_bytes(payload)
    left,top,right,bottom = _measure(c,replace(c.style,outline_width=0),alias,caption_runs(c),
        plan.width,plan.height,tmp_path,"ffmpeg","ass",ass_em_scale(payload))
    assert bottom-top == pytest.approx(.03*plan.height,abs=2)
    assert right-left < .84*plan.width


def test_low_resolution_reference_leaves_weight_estimated():
    # Grok R2: 360x640 reference, ~18 px ink; ratio .1333 is within 1 px of the 0.10 cut.
    sample = {"text_height": .028, "geometry_confidence": .9,
              "ink_evidence": {"stroke_to_ink_height": .1333, "component_count": 8}}
    geometry = {"frames": [{"height": 640, "detections": [{"appearance": sample}]}],
                "tracks": [{"kind": "caption", "samples": [{"sample_index": 0, "detection_indices": [0]}]}]}
    measured = appearance(geometry)
    assert "weight" not in measured and "weight_basis" not in measured
    assert "within 1 px" in measured["weight_unmeasured"]
    assert "weight" not in appearance({**geometry, "frames": [{"detections": [{"appearance": sample}]}]})


@pytest.mark.parametrize("tokens,expected", [
    ("I 'm here", ["I'm", "here"]), ("do n't go", ["don't", "go"]),
    ("well - known", ["well-known"]), ("well -known", ["well-known"]),
    ("the students' work", ["the", "students'", "work"]),
    ("rock 'n' roll", ["rock", "'n'", "roll"]),
    ("the end. -next", ["the", "end.", "-next"]),
    ("it was -5 today", ["it", "was", "-5", "today"]),
])
def test_normalize_words_glues_only_clitics_and_compound_hyphens(tokens, expected):
    from myzing.captions.presets import normalize_words
    from myzing.schemas import Word
    words = [Word(t, i * .5, i * .5 + .4) for i, t in enumerate(tokens.split())]
    assert [w.text for w in normalize_words(words)] == expected
