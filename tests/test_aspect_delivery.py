"""Aspect policy, subject priority and delivery safety on generated geometry."""

from dataclasses import replace

import pytest

from myzing.brief.models import Brief, BriefError
from myzing.composition import AssetRef, CaptionStyle, Composition, CompositionCaption, CompositionClip
from myzing.composition.aspects import ASPECTS, SAFE_INSETS, dimensions, parse_aspects
from myzing.layout.delivery import adapt_plan
from myzing.layout.framing import centered_framing, select_framing, track_framing, visible_content
from myzing.layout.types import Box, FaceTrack, Keyframe, box_at
from myzing.render.framing import display_dimensions


def clip():
    return CompositionClip("source", 0, 2, 0, id="c", asset_id="s")


def subject(kind="face", box=Box(.45, .3, .1, .2)):
    return FaceTrack(kind, [Keyframe(0, box), Keyframe(2, box)], .8)


def test_brief_deliveries_roundtrip_and_absent_fields():
    original = Brief().to_dict()
    assert not {"aspects", "framing", "framing_max_upscale"} & original.keys()
    brief = Brief(aspects=list(ASPECTS), framing="blurfill", framing_max_upscale=3)
    assert Brief.from_dict(brief.to_dict()) == brief
    plan = Composition(brief=Brief())
    assert not {"aspects", "framing", "framing_max_upscale"} & plan.to_dict()["brief"].keys()
    assert parse_aspects("all") == list(ASPECTS)
    assert parse_aspects("9:16,1:1") == ["9:16", "1:1"]
    for kwargs in ({"aspects": ["4:3"]}, {"aspects": ["1:1", "1:1"]}, {"aspects": "all"},
                   {"framing_max_upscale": float("nan")}, {"framing_max_upscale": .5}):
        with pytest.raises(BriefError):
            Brief(**kwargs)


def test_auto_enlargement_uses_configured_limit_and_retains_evidence():
    f = select_framing("auto", 640, 360, 1080, 1920, clip(), [subject()], max_upscale=2.5)
    assert f.mode == "zoomfill"
    assert f.assessments[-1].enlargement <= 2.5
    assert any("5.455x exceeds 2.5x" in w for w in f.warnings)
    allowed = select_framing("auto", 640, 360, 1080, 1920, clip(), [subject()], max_upscale=6)
    assert allowed.mode == "reframe"
    assert select_framing("reframe", 640, 360, 1080, 1920, clip(), [subject()]).mode == "reframe"
    assert select_framing("reframe", 640, 360, 1080, 1920, clip(), [subject()]).upscale_warning(1080, 1920)


@pytest.mark.parametrize("source,target,reason", [((2520,1080),(1080,1920),"retained area"),
    ((1080,1920),(1920,1080),"retained source height"), ((1080,1920),(1080,1080),"retained source height")])
def test_auto_rejects_excessive_loss(source,target,reason):
    f = select_framing("auto", *source, *target, clip(), [subject()])
    assert f.mode == ("zoomfill" if source[0] > source[1] else "blurfill")
    assert reason in " ".join(f.warnings)


def test_auto_rejects_subject_loss_and_unmeasured_large_crops():
    tracks = [subject("face-left", Box(.05,.3,.1,.2)), subject("face-right", Box(.85,.3,.1,.2))]
    f = select_framing("auto", 3840,2160,1080,1920,clip(),tracks)
    assert f.mode == "zoomfill" and "tracked-subject coverage" in " ".join(f.warnings)
    assert f.assessments[-1].subject_coverage >= .98
    f = select_framing("auto",3840,2160,1080,1920,clip(),[])
    assert f.mode == "zoomfill" and "evidence has gaps" in " ".join(f.warnings)
    assert f.height == 2160 and f.width / 3840 >= 2 / 3


def test_faces_and_people_are_preserved_ahead_of_saliency():
    face = subject("face-main", Box(.3,.3,.1,.15))
    person = subject("person-main", Box(.5,.1,.2,.8))
    bright = subject("saliency-fire", Box(.8,.1,.15,.7))
    base = centered_framing("reframe",640,360,180,320)
    f = track_framing(base,clip(),[bright,person,face])
    assert f.method == "yunet" and f.center_x == pytest.approx(.35*640)
    f = track_framing(base,clip(),[bright,person])
    assert f.method == "people-hog" and f.center_x == pytest.approx(.6*640)
    assert f.confidence <= .35 and any("No face/head evidence" in w for w in f.warnings)


def test_sparse_scene_wide_highlights_are_not_an_object_box():
    np=pytest.importorskip("numpy")
    cv2=pytest.importorskip("cv2")
    from myzing.layout.framing import saliency_detection
    image=np.full((360,640,3),40,dtype=np.uint8)
    cv2.rectangle(image,(20,20),(620,340),(210,210,210),5)
    assert not saliency_detection(image,cv2)
    cv2.rectangle(image,(160,120),(190,170),(170,170,170),-1)
    detected=saliency_detection(image,cv2)
    assert len(detected)==1 and abs(detected[0].box.center[0]*640-175)<1


@pytest.mark.parametrize("source", [(1920,1080),(1440,1080),(2520,1080),(1080,1920),(1080,1440),(1080,1080),(1921,1081)])
@pytest.mark.parametrize("aspect", ASPECTS)
def test_each_source_shape_to_each_delivery_is_bounded(source,aspect):
    width,height = dimensions(aspect)
    f = select_framing("auto",*source,width,height,clip(),[subject()])
    f.validate_output(width,height,2)
    assert f.mode in ("fit","reframe","zoomfill","blurfill")
    for i in range(61):
        x,y = f.center_at(i/30)
        assert 0 <= x-f.width/2 <= x+f.width/2 <= source[0]
        assert 0 <= y-f.height/2 <= y+f.height/2 <= source[1]


@pytest.mark.parametrize("aspect", ASPECTS)
def test_caption_safe_area_content_and_short_side_scaling(aspect):
    from myzing.layout.framing import output_box
    source = (360,640)
    c = clip()
    cap = CompositionCaption(id="cap",text="A GOOD VIEW",start=.1,end=1.9,word_timed=False,style=CaptionStyle(36))
    plan = Composition(assets=[AssetRef("s","source",None)],clips=[c],captions=[cap],width=360,height=640)
    tracks = [subject("face", Box(.38,.25,.24,.18))]
    adapted = adapt_plan(plan,*dimensions(aspect,180),{"s":source},{"s":tracks})
    caption = adapted.captions[0]
    assert caption.style.size <= 18 and caption.layout.overlap.safe
    assert plan.captions[0].style.size == 36 and plan.captions[0].layout is None
    f = adapted.clips[0].framing
    content = visible_content(f,adapted.width,adapted.height)
    box = caption.layout.box
    left,top,right,bottom = SAFE_INSETS[aspect]
    assert box.x >= max(left,content.x)-1e-9 and box.right <= min(1-right,content.right)+1e-9
    assert box.y >= max(top,content.y)-1e-9 and box.bottom <= min(1-bottom,content.bottom)+1e-9
    for frame in range(60):
        face = output_box(box_at(tracks[0].keyframes,frame/30),f,frame/30,adapted.width,adapted.height)
        assert box.right <= face.x or face.right <= box.x or box.bottom <= face.y or face.bottom <= box.y


@pytest.mark.parametrize("angle", [0,90,180,270,-90])
def test_rotation_tags_and_matrix_use_displayed_sar_dimensions(angle):
    expected = (240,480) if angle % 180 else (480,240)
    stream = dict(width=320,height=240,sample_aspect_ratio="3:2",tags={"rotate":str(angle)})
    assert display_dimensions(stream) == expected
    stream.update(tags={"rotate":"0"},side_data_list=[{"rotation":angle}])
    assert display_dimensions(stream) == expected


def test_aspect_arguments_reject_nonstring_items_and_duplicates():
    for value in ([], [1], ["16:9",1], "1:1,1:1", "4:3"):
        with pytest.raises(ValueError):
            parse_aspects(value)


def test_closeup_caption_reflows_into_a_safe_side_gap():
    from myzing.layout.framing import output_box
    caption = CompositionCaption(id="cap", text="destroy the world.", start=0, end=1.5,
                                 word_timed=False, style=CaptionStyle(60))
    plan = Composition(assets=[AssetRef("s", "source", None)], clips=[clip()], captions=[caption],
                       width=1080, height=1080)
    tracks = [subject("face-closeup", Box(.28, .02, .44, .96))]
    adapted = adapt_plan(plan, 1080, 1080, {"s": (862, 360)}, {"s": tracks}, requested="blurfill")
    result = adapted.captions[0]
    assert result.layout.overlap.safe and "\n" in result.text
    assert result.text.split() == caption.text.split()
    face = output_box(tracks[0].keyframes[0].box, adapted.clips[0].framing, 0, 1080, 1080)
    box = result.layout.box
    assert box.right <= face.x or face.right <= box.x
    assert result.start == caption.start and result.end == caption.end


@pytest.mark.parametrize("plan_name,asset_name,output_name", [
    ("draft.9x16.json", "source.mp4", "draft.mp4"),  # The per-aspect plan would replace the input plan.
    ("plan.json", "draft.9x16.mp4", "draft.mp4"),    # The per-aspect video would replace an asset.
])
def test_delivery_refuses_to_overwrite_any_input_before_analysis(tmp_path, capsys, plan_name, asset_name, output_name):
    from myzing.render.command import run
    (tmp_path / asset_name).write_bytes(b"never decoded: the guard runs before any probe")
    plan = Composition(assets=[AssetRef("s", asset_name, None)],
                       clips=[CompositionClip(asset_name, 0, 1, 0, id="c", asset_id="s")], width=1920, height=1080)
    edl = tmp_path / plan_name
    edl.write_text(plan.to_json(), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert run([str(edl), "--aspect", "9:16", "-o", str(tmp_path / output_name)]) == 1
    error = capsys.readouterr().err
    assert "would overwrite input" in error and "choose a different -o" in error
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_adapt_plan_clamps_scaled_caption_style_to_its_contract():
    for size, outline, short_side, expected in ((300, 12, 4320, (512, 20)), (36, 2, 18, (1, 2 * 18 / 1080))):
        cap = CompositionCaption(id="cap", text="A", start=.1, end=1.9, word_timed=False,
                                 style=CaptionStyle(size, outline_width=outline))
        plan = Composition(assets=[AssetRef("s", "source", None)], clips=[clip()], captions=[cap], width=1080, height=1080)
        width, height = dimensions("1:1", short_side)
        source = adapt_plan(plan, width, height, {"s": (1080, 1080)}, {"s": []}, requested="fit")
        style = source.captions[0].style
        assert style.size <= expected[0] + 1e-9 and style.size >= 1
        assert style.outline_width <= 20


def test_shared_source_measurement_is_reused_across_drafts(tmp_path, monkeypatch):
    from myzing.render import deliveries
    media = tmp_path / "source.mp4"
    media.write_bytes(b"not decoded")
    calls = []
    monkeypatch.setattr(deliveries, "probe_dimensions", lambda path, ffprobe="ffprobe": (1920, 1080))
    monkeypatch.setattr(deliveries, "probe_duration", lambda path: 600.0)
    monkeypatch.setattr(deliveries, "detect_shots", lambda *a: type("Shots", (), {"shots": [], "warnings": []})())
    def analyze(path, duration, directory, cuts, ranges=None):
        calls.append(sorted(ranges))
        return [subject()], []
    monkeypatch.setattr(deliveries, "analyze_subjects", analyze)
    drafts = [Composition(assets=[AssetRef("s", str(media), None)],
                          clips=[CompositionClip(str(media), start, start + 2, 0, id="c", asset_id="s")],
                          width=1920, height=1080) for start in (100, 400)]
    sources = {}
    for draft in drafts:
        for path, ranges in deliveries.used_ranges(draft).items():
            sources.setdefault(media.resolve(), []).extend(ranges)
    measured = deliveries.measure_sources(sources, tmp_path / "analysis", fps=30)
    assert calls == [[(100, 102), (400, 402)]]  # Only used trims, once per source.
    for draft in drafts:
        plans, evidence = deliveries.delivery_plans(draft, ["1:1"], tmp_path / "work", measured=measured)
        assert plans["1:1"].clips[0].framing is not None
        assert evidence["sources"]["s"]["analyzed_ranges"] == [[100, 102], [400, 402]]
    assert len(calls) == 1
    # Without shared evidence a plan measures its own trims only.
    deliveries.delivery_plans(drafts[1], ["1:1"], tmp_path / "solo")
    assert calls[-1] == [(400, 402)]


def test_prepare_plan_without_captions_skips_face_layout_and_its_warning(tmp_path):
    from types import SimpleNamespace
    from myzing.match.api import _prepare_plan
    plan = Composition(assets=[AssetRef("s", "source", None)], clips=[clip()], width=1920, height=1080)
    source = tmp_path / "plan.json"
    source.write_text(plan.to_json(), encoding="utf-8")
    result = _prepare_plan(source, tmp_path / "drafts" / "plan-A.json", {}, SimpleNamespace(measured=[]), {"layout": True})
    assert not any("Face layout" in w for w in result["warnings"])
    assert not (tmp_path / "drafts" / "plan-A" / "layout.json").exists()
