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
    assert f.mode == "blurfill"
    assert any("5.455x exceeds 2.5x" in w for w in f.warnings)
    allowed = select_framing("auto", 640, 360, 1080, 1920, clip(), [subject()], max_upscale=6)
    assert allowed.mode == "reframe"
    assert select_framing("reframe", 640, 360, 1080, 1920, clip(), [subject()]).mode == "reframe"
    assert select_framing("reframe", 640, 360, 1080, 1920, clip(), [subject()]).upscale_warning(1080, 1920)


@pytest.mark.parametrize("source,target,reason", [((2520,1080),(1080,1920),"retained area"),
    ((1080,1920),(1920,1080),"retained source height"), ((1080,1920),(1080,1080),"retained source height")])
def test_auto_rejects_excessive_loss(source,target,reason):
    f = select_framing("auto", *source, *target, clip(), [subject()])
    assert f.mode == "blurfill"
    assert reason in " ".join(f.warnings)


def test_auto_rejects_subject_loss_and_unmeasured_large_crops():
    tracks = [subject("face-left", Box(.05,.3,.1,.2)), subject("face-right", Box(.85,.3,.1,.2))]
    f = select_framing("auto", 3840,2160,1080,1920,clip(),tracks)
    assert f.mode == "blurfill" and "tracked-subject coverage" in " ".join(f.warnings)
    f = select_framing("auto",3840,2160,1080,1920,clip(),[])
    assert f.mode == "blurfill" and "evidence has gaps" in " ".join(f.warnings)


def test_subject_priority_is_faces_then_people_then_objects():
    face = subject("face-main", Box(.3,.3,.1,.15))
    person = subject("person-main", Box(.5,.1,.2,.8))
    bright = subject("saliency-fire", Box(.8,.1,.15,.7))
    base = centered_framing("reframe",640,360,180,320)
    f = track_framing(base,clip(),[bright,person,face])
    assert f.method == "yunet" and f.center_x == pytest.approx(.35*640)
    f = track_framing(base,clip(),[bright,person])
    assert f.method == "people-hog" and f.center_x == pytest.approx(.6*640)


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
    assert f.mode in ("fit","reframe","blurfill")
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
