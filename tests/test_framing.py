"""Framing contracts, compatibility and conservative output-space safety."""

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from myzing.brief.models import Brief, BriefError
from myzing.composition import AssetRef, Composition, CompositionClip, CompositionCaption, lowering_blockers
from myzing.composition.framing import CropBounds, CropKeyframe, Framing
from myzing.layout.framing import centered_framing, framing_mode, place_captions, track_framing, visible_content, output_box
from myzing.layout.types import Box, FaceTrack, Keyframe
from myzing.render.framing import display_dimensions
from myzing.render.graph import build_graph
from myzing.render.validation import MediaInfo, ResolvedClip, ValidatedEDL
from myzing.schemas import EDL, Clip


def test_absent_framing_keeps_json_and_graph_bytes():
    clip = CompositionClip("source.mp4", 0, 2, 0, id="c", asset_id="s")
    plan = Composition(assets=[AssetRef("s", "source.mp4", None)], clips=[clip])
    assert "framing" not in clip.to_dict()
    data = plan.to_json()
    assert Composition.from_json(data).to_json() == data
    assert "framing" not in Brief().to_dict()
    assert Brief.from_dict(Brief().to_dict()).framing == "auto"
    edl = EDL(clips=[Clip("source.mp4", 0, 2, 0)])
    validated = ValidatedEDL(edl, (ResolvedClip(edl.clips[0], Path("source.mp4"), MediaInfo(2, True, False)),), (), 2, ())
    for rate in (None, "30/1"):
        original = build_graph(validated, False, fps_rate=rate).graph
        assert build_graph(validated, False, fps_rate=rate, clip_framings=(None,)).graph == original
        explicit_fit = centered_framing("fit", 640, 360, 1080, 1920)
        fitted = build_graph(validated, False, fps_rate=rate, clip_framings=(explicit_fit,)).graph
        assert "scale=640:360,setsar=1,scale=1080:1920" in fitted
        assert "scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p" in original


@pytest.mark.parametrize("field,value", [("source_width", 0), ("width", 1000), ("center_x", -1),
    ("center_y", float("nan")), ("max_velocity", 0), ("max_upscale", .5), ("confidence", 1.1),
    ("version", 2), ("mode", "auto"), ("interpolation", "linear")])
def test_rejects_invalid_geometry(field, value):
    data = centered_framing("reframe", 640, 360, 180, 320).to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        Framing.from_dict(data)


def test_rejects_bad_keyframe_windows_order_velocity_and_version():
    f = centered_framing("reframe", 640, 360, 180, 320)
    for keys in ([CropKeyframe(.1, 320, 180)], [CropKeyframe(0, 320, 180), CropKeyframe(0, 320, 180)],
                 [CropKeyframe(0, 320, 180), CropKeyframe(.1, 500, 180)],
                 [CropKeyframe(0, 320, 180), CropKeyframe(2, 600, 180)]):
        with pytest.raises(ValueError):
            replace(f, keyframes=keys)
    with pytest.raises(ValueError, match="bounds"):
        replace(f, bounds=CropBounds(0, 0, 641, 360))
    with pytest.raises(ValueError, match="duration"):
        CompositionClip("s", 0, 1, 0, id="c", asset_id="s", framing=replace(f, keyframes=[CropKeyframe(0,320,180), CropKeyframe(2,320,180)]))
    data = f.to_dict()
    del data["keyframes"][0]["version"]
    with pytest.raises(ValueError, match="version"):
        Framing.from_dict(data)


@pytest.mark.parametrize("sw,sh,ow,oh,mode", [(640,360,1080,1920,"reframe"), (640,360,1080,1080,"reframe"),
    (360,640,1920,1080,"reframe"), (640,360,1920,1080,"fit"), (360,640,1080,1920,"fit")])
def test_auto_orientation_and_explicit_override(sw,sh,ow,oh,mode):
    assert framing_mode("auto",sw,sh,ow,oh) == mode
    for explicit in ("fit", "fill", "reframe"):
        assert framing_mode(explicit,sw,sh,ow,oh) == explicit
        assert Brief.from_dict(Brief(framing=explicit).to_dict()).framing == explicit
    with pytest.raises(BriefError, match="framing"):
        Brief(framing="crop")


def test_smoothing_is_bounded_and_roundtrips_without_losing_instructions():
    clip = CompositionClip("s", 2, 6, 0, id="c", asset_id="s")
    track = FaceTrack("face", [Keyframe(2, Box(.2,.3,.1,.2)), Keyframe(6,Box(.65,.3,.1,.2))])
    f = track_framing(centered_framing("reframe",640,360,180,320),clip,[track])
    assert Framing.from_json(f.to_json()) == f
    positions = [f.center_at(i / 1000) for i in range(4001)]
    import math
    assert max(math.dist(a,b)*1000 for a,b in zip(positions,positions[1:])) <= f.max_velocity + .001
    assert all(f.width/2 <= x <= 640-f.width/2 and f.height/2 <= y <= 360-f.height/2 for x,y in positions)
    clip.framing = f
    p = Composition(assets=[AssetRef("s","s",None)], clips=[clip], width=180,height=320)
    assert "clips[0].framing" in lowering_blockers(p)
    assert f.upscale_warning(1080,1920)


@pytest.mark.parametrize("mode", ["fit", "fill", "reframe"])
def test_captions_inside_visible_content_and_off_subject(mode):
    clip = CompositionClip("s",0,3,0,id="c",asset_id="s",framing=centered_framing(mode,640,360,180,320))
    track = FaceTrack("face", [Keyframe(0,Box(.43,.32,.14,.32)),Keyframe(3,Box(.45,.32,.14,.32))])
    clip.framing = track_framing(clip.framing,clip,[track])
    caption = CompositionCaption(id="cap",text="SPACE",start=.2,end=2.8,word_timed=False)
    plan = Composition(assets=[AssetRef("s","s",None)],clips=[clip],captions=[caption],width=180,height=320)
    place_captions(plan,{"s":[track]})
    box = caption.layout.box
    assert caption.layout.overlap.safe
    visible = visible_content(clip.framing,180,320)
    assert visible.x <= box.x < box.right <= visible.right
    assert visible.y <= box.y < box.bottom <= visible.bottom
    from myzing.layout.types import box_at
    for i in range(300):
        subject = output_box(box_at(track.keyframes,i/100),clip.framing,i/100,180,320)
        assert subject is not None
        assert box.right <= subject.x or box.x >= subject.right or box.bottom <= subject.y or box.y >= subject.bottom


def test_display_geometry_accounts_for_sar_and_rotation():
    assert display_dimensions({"width":720,"height":480,"sample_aspect_ratio":"4:3"}) == (960,480)
    assert display_dimensions({"width":640,"height":360,"side_data_list":[{"rotation":90}]}) == (360,640)


def test_prominent_face_wins_over_more_confident_background_face():
    clip=CompositionClip("s",0,2,0,id="c",asset_id="s")
    central=FaceTrack("face-main",[Keyframe(0,Box(.4,.2,.2,.3)),Keyframe(2,Box(.4,.2,.2,.3))],.85)
    background=FaceTrack("face-other",[Keyframe(0,Box(.75,.2,.08,.12)),Keyframe(2,Box(.75,.2,.08,.12))],.99)
    f=track_framing(centered_framing("reframe",640,360,180,320),clip,[central,background])
    assert all(k.center_x==320 for k in f.keyframes)


def test_swept_subject_crossing_between_offscreen_endpoints_is_protected():
    from myzing.layout.framing import swept_output_box
    f=centered_framing("reframe",640,360,180,320)
    f=replace(f,center_x=100, keyframes=[CropKeyframe(0,100,180),CropKeyframe(10,540,180)])
    obstacle=swept_output_box(Box(.48,.4,.04,.1),f,[0,10],180,320)
    assert obstacle.x==0 and obstacle.right==1
