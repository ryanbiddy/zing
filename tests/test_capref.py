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
    assert caption.style.outline_width == 1.92 and caption.style.outline_color == "#123456"
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
        return (0, 0, style.size*12*len(caption.words), style.size)
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
