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
    constrained = Framing("reframe", 640, 360, CropBounds(100, 20, 440, 320), 180, 320,
                          320, 180, [CropKeyframe(0, 320, 180)], max_velocity=90)
    constrained = track_framing(constrained, clip, [track])
    assert all(190 <= k.center_x <= 450 and k.center_y == 180 for k in constrained.keyframes)


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


def test_unknown_speaker_centers_the_two_shot_instead_of_guessing_from_confidence():
    clip=CompositionClip("s",0,2,0,id="c",asset_id="s")
    central=FaceTrack("face-main",[Keyframe(0,Box(.4,.2,.2,.3)),Keyframe(2,Box(.4,.2,.2,.3))],.85)
    background=FaceTrack("face-other",[Keyframe(0,Box(.75,.2,.08,.12)),Keyframe(2,Box(.75,.2,.08,.12))],.99)
    f=track_framing(centered_framing("reframe",640,360,180,320),clip,[central,background])
    assert all(k.center_x == pytest.approx((.4 + .83) / 2 * 640) for k in f.keyframes)


def test_swept_subject_crossing_between_offscreen_endpoints_is_protected():
    from myzing.layout.framing import swept_output_box
    f=centered_framing("reframe",640,360,180,320)
    f=replace(f,center_x=100, keyframes=[CropKeyframe(0,100,180),CropKeyframe(10,540,180)])
    obstacle=swept_output_box(Box(.48,.4,.04,.1),f,[0,10],180,320)
    assert obstacle.x==0 and obstacle.right==1


def test_safe_default_captions_stay_v1_and_only_unsafe_ones_get_layout(monkeypatch):
    from myzing.layout import framing as layout_framing
    from myzing.layout.framing import default_caption_box
    ink = (-220, -40, 222, 38)  # Measured "HI THERE" at 1920x1080, 118% pop.
    monkeypatch.setattr(layout_framing, "measure_default_ink", lambda *a, **k: ink)
    clip = CompositionClip("s", 0, 3, 0, id="c", asset_id="s")
    captions = [CompositionCaption(id="clear", text="HI THERE", start=.2, end=1, word_timed=False),
                CompositionCaption(id="covered", text="HI THERE", start=1.5, end=2.5, word_timed=False)]
    plan = Composition(assets=[AssetRef("s", "s", None)], clips=[clip], captions=captions, width=1920, height=1080)
    default = default_caption_box(captions[0], 1920, 1080, ink)
    # A subject sits exactly under the default position during the second caption only.
    face = FaceTrack("face", [Keyframe(1.4, default), Keyframe(3, default)])
    place_captions(plan, {"s": [face]}, {"s": (1920, 1080)}, keep_safe_defaults=True)
    clear, covered = plan.captions
    assert clear.layout is None and clear.style is None and clear.text == "HI THERE"
    assert covered.layout is not None and covered.layout.overlap.safe and covered.style is not None
    assert [b for b in lowering_blockers(plan) if b.startswith("captions[")] == ["captions[1].layout", "captions[1].style"]
    # Without the option every caption is placed explicitly (deliveries).
    plan = Composition(assets=[AssetRef("s", "s", None)], clips=[clip],
                       captions=[CompositionCaption(id="clear", text="HI THERE", start=.2, end=1, word_timed=False)],
                       width=1920, height=1080)
    place_captions(plan, {"s": []}, {"s": (1920, 1080)})
    assert plan.captions[0].layout is not None


def test_framing_upscale_default_matches_auto_policy():
    f = Framing("fill", 640, 360, CropBounds(0, 0, 640, 360), 640, 360, 320, 180)
    assert f.max_upscale == 2.5
    assert f.upscale_warning(1600, 900) == []  # exactly 2.5x
    assert "2.5x" in f.upscale_warning(1920, 1080)[0]


def test_expression_depth_stays_logarithmic_for_the_keyframe_maximum():
    from myzing.render.framing import _expression
    keys = [CropKeyframe(i * .05, 120 + 400 * (i % 2), 180) for i in range(256)]
    f = Framing("reframe", 640, 360, CropBounds(0, 0, 640, 360), 180, 320, 120, 180, keys, max_velocity=20000)
    x = _expression(f, "center_x", "30/1")
    depth = deepest = 0
    for char in x:
        depth += char == "("
        depth -= char == ")"
        deepest = max(deepest, depth)
    assert deepest <= 40 and x.count("if(") == 255  # 255 moving segments + final hold
    assert _expression(f, "center_y", "30/1") == "20"  # Static axis: one constant per piece collapses.


@pytest.mark.parametrize("failure", [OSError("no ffmpeg"), RuntimeError("no libass"), ValueError("bad text")])
def test_unmeasurable_default_captions_are_placed_not_kept(monkeypatch, failure):
    from myzing.layout import framing as layout_framing
    def unavailable(*a, **k):
        raise failure
    monkeypatch.setattr(layout_framing, "measure_default_ink", unavailable)
    clip = CompositionClip("s", 0, 3, 0, id="c", asset_id="s")
    plan = Composition(assets=[AssetRef("s", "s", None)], clips=[clip], width=1920, height=1080,
                       captions=[CompositionCaption(id="cap", text="HI", start=.2, end=1, word_timed=False)])
    place_captions(plan, {"s": []}, {"s": (1920, 1080)}, keep_safe_defaults=True)
    assert plan.captions[0].layout is not None and plan.captions[0].style is not None


def test_default_box_includes_the_stated_margin_and_rejects_off_frame_ink():
    from myzing.layout.framing import default_caption_box, default_ink_margin
    caption = CompositionCaption(id="cap", text="HI", start=0, end=1, word_timed=False)
    box = default_caption_box(caption, 1920, 1080, (-100, -40, 100, 40))
    margin = default_ink_margin(1920, 1080)
    assert margin == 6
    assert box.width * 1920 == pytest.approx(200 + 2 * margin) and box.height * 1080 == pytest.approx(80 + 2 * margin)
    assert default_caption_box(caption, 1920, 1080, (-961, -40, 961, 40)) is None


def test_track_framing_zero_length_clip_keeps_one_keyframe():
    """Coalescing must not emit [0, 0] for a zero-length shot (strictly-increasing check)."""
    from types import SimpleNamespace
    clip = SimpleNamespace(src_in=2.0, src_out=2.0, duration=0.0, timeline_start=0.0, source_at=lambda t: 2.0)
    tracks = [FaceTrack("f", [Keyframe(1.0, Box(.4, .2, .1, .2)), Keyframe(3.0, Box(.5, .2, .1, .2))])]
    framing = track_framing(centered_framing("reframe", 1920, 1080, 1080, 1920), clip, tracks)
    assert [k.time for k in framing.keyframes] == [0.0]


def test_track_framing_velocity_clamp_is_unchanged_when_already_valid():
    """The rounding margin applies only to a step the validator would reject.

    An unconditional margin moved every clamped keyframe of plans that already
    validated (about 1e-7 px in a 3,000-case comparison with 1a2c88c).
    """
    import math
    clip = CompositionClip("x.mp4", 10.0, 11.0, 0, id="c", asset_id="s")
    tracks = [FaceTrack("f", [Keyframe(10.0, Box(.0, .2, .1, .2)), Keyframe(10.5, Box(.85, .2, .1, .2)),
                              Keyframe(11.0, Box(.85, .2, .1, .2))])]
    base = replace(centered_framing("reframe", 1920, 1080, 1080, 1920), max_velocity=90.0)
    keys = track_framing(base, clip, tracks).keyframes
    assert [k.time for k in keys] == [0.0, 0.5, 1.0]
    speeds = [1.5 * math.hypot(b.center_x - a.center_x, b.center_y - a.center_y) / (b.time - a.time)
              for a, b in zip(keys, keys[1:])]
    assert all(speed <= 90.0 + 1e-6 for speed in speeds)
    assert abs(speeds[0] - 90.0) < 1e-10  # clamped exactly at the bound, not shrunk by a margin
