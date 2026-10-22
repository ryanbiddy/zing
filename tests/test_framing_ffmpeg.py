"""Generated-media pixel and frame-clock acceptance; no external footage."""

import subprocess
from dataclasses import replace

import pytest

from myzing.composition import AssetRef, Composition, CompositionClip, CompositionCaption, CaptionStyle
from myzing.layout.framing import centered_framing, analyze_subjects, track_framing, place_captions
from myzing.project.models import Rational
from myzing.render.composition import render_composition
from myzing.render.validation import EDLValidationError

pytestmark = pytest.mark.ffmpeg


def ffmpeg(*args):
    result = subprocess.run(["ffmpeg","-v","error","-nostdin","-y",*map(str,args)],capture_output=True,timeout=90)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def source_at(tmp_path):
    path = tmp_path / "moving.mkv"
    ffmpeg("-f","lavfi","-i", "color=c=0x303050:s=640x360:r=30:d=4[bg];color=white:s=24x24:r=30:d=4[dot];[bg][dot]overlay=x='128+24*t':y=80:shortest=1",
           "-c:v","ffv1",path)
    return path


def make_plan(source, mode, width, height, rate=Rational(30,1)):
    clip = CompositionClip(str(source),0,4,0,id="c",asset_id="s",framing=centered_framing(mode,640,360,width,height))
    return Composition(assets=[AssetRef("s",str(source),None)],clips=[clip],width=width,height=height,fps=rate)


@pytest.mark.parametrize("mode",["fill","reframe"])
@pytest.mark.parametrize("size",[(180,320),(240,240)])
def test_fill_and_reframe_have_no_padding_bars(tmp_path,mode,size):
    np = pytest.importorskip("numpy")
    source = source_at(tmp_path)
    plan = make_plan(source,mode,*size)
    output = tmp_path / "output.mp4"
    result = render_composition(plan,output)
    assert "pad=" not in result.filtergraph.replace("tpad=", "temporal=").replace("apad=", "audio=")
    decoded = np.frombuffer(ffmpeg("-i",output,"-f","rawvideo","-pix_fmt","rgb24","pipe:1"),dtype=np.uint8).reshape(-1,size[1],size[0],3)
    assert len(decoded) == 120
    for pixels in (decoded[:,0],decoded[:,-1],decoded[:,:,0],decoded[:,:,-1]):
        assert pixels.min() > 20


@pytest.mark.parametrize("rate",[Rational(30,1),Rational(30000,1001)])
def test_measured_target_following_caption_safety_and_frame_clock(tmp_path,monkeypatch,rate):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from myzing.layout.detector import LayoutError
    from myzing.layout import framing as layout
    def unavailable(*a,**k):
        raise LayoutError("test deliberately exercises saliency without a face model")
    monkeypatch.setattr(layout,"YuNetDetector",unavailable)
    source = source_at(tmp_path)
    tracks,warnings = analyze_subjects(source,4,tmp_path)
    assert tracks and all(t.id.startswith("saliency-") for t in tracks)
    plan = make_plan(source,"reframe",180,320,rate)
    # Fractional trim tests clip-local n, independent of source and timeline PTS.
    plan.clips[0].src_in = .253
    plan.clips[0].src_out = 3.753
    plan.clips[0].framing = track_framing(plan.clips[0].framing,plan.clips[0],tracks)
    plan.captions = [CompositionCaption(id="cap",text="SPACE",start=.2,end=3.2,word_timed=False,style=CaptionStyle(18,color="#FF0000"))]
    place_captions(plan,{"s":tracks})
    assert plan.captions[0].layout.overlap.safe
    output = tmp_path / "tracked.mp4"
    result = render_composition(plan,output)
    assert "Saliency/center fallback" in " ".join(result.warnings)
    frames = np.frombuffer(ffmpeg("-i",output,"-f","rawvideo","-pix_fmt","rgb24","pipe:1"),dtype=np.uint8).reshape(-1,320,180,3)
    from myzing.composition import frame_index
    assert len(frames) == frame_index(3.5,rate,rounding="nearest")
    centers, caption_frames = [], 0
    box = plan.captions[0].layout.box
    for n,frame in enumerate(frames):
        target = (frame.min(axis=2)>180)
        ys,xs=np.nonzero(target)
        assert len(xs)>100
        centers.append((xs.min()+xs.max())/2)
        # Target remains near horizontal crop center. Endpoint averaging and
        # source 30 fps quantization are included in this 12-output-pixel bound.
        assert abs(centers[-1]-90) <= 12
        text = (frame[:,:,0]>140)&(frame[:,:,1]<100)&(frame[:,:,2]<100)
        if text.any():
            caption_frames += 1
            ty,tx=np.nonzero(text)
            assert tx.min() >= box.x*180-2 and tx.max() <= box.right*180+2
            assert ty.min() >= box.y*320-2 and ty.max() <= box.bottom*320+2
            assert not (text & target).any()
    # The caption spans .2-3.2s of 3.5s: placement checks must not pass vacuously.
    assert caption_frames >= .75 * len(frames)
    assert max(abs(b-a) for a,b in zip(centers,centers[1:])) < 3


def test_render_refuses_stale_dimensions_and_warns_on_upscale(tmp_path):
    source=source_at(tmp_path)
    plan=make_plan(source,"fill",180,320)
    plan.clips[0].framing.source_width=642
    with pytest.raises(EDLValidationError,match="probed display dimensions"):
        render_composition(plan,tmp_path/"bad.mp4")
    assert not (tmp_path/"bad.mp4").exists()
    plan.clips[0].framing.source_width=640
    plan.width,plan.height=720,1280
    result=render_composition(plan,tmp_path/"upscaled.mp4")
    assert any("exceeds stated 2.5x" in w for w in result.warnings)


@pytest.mark.parametrize("requested,expected",[("auto","blurfill"),("fit","fit"),("fill","fill")])
def test_director_and_match_preserve_output_framing_and_caption_bounds(tmp_path,requested,expected):
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from tools.plan_examples import example_project, write_json
    from myzing.director import plan_drafts
    from myzing.match.api import _prepare_plan
    from myzing.style_recipe import StyleRecipe
    from myzing.layout.framing import default_caption_box, measure_default_ink, visible_content
    project,_,recipe=example_project(tmp_path/"project",media=True)
    brief=json.loads((project/"brief.json").read_text())
    brief.update(aspect="1:1",framing=requested)
    write_json(project/"brief.json",brief)
    result=plan_drafts(project,project/"recipe.json",project/"plans",seed=17)
    assert result["status"]=="ready" and len(result["plans"])==3
    for label,path in result["plans"].items():
        prepared=_prepare_plan(Path(path),project/"drafts"/f"{label}.json",{},recipe,{"layout":False})
        plan=Composition.from_json(Path(prepared["path"]).read_text())
        # Square-pixel fit is the absent default (v1-representable).
        assert all((c.framing.mode if c.framing else "fit")==expected for c in plan.clips)
        assert expected!="fit" or all(c.framing is None for c in plan.clips)
        assert plan.captions and all(c.layout is None or c.layout.overlap.safe for c in plan.captions)
        for cap in plan.captions:
            for clip in plan.clips:
                if clip.timeline_start < cap.end and clip.timeline_end > cap.start:
                    framing=clip.framing or centered_framing("fit",320,180,plan.width,plan.height)
                    visible=visible_content(framing,plan.width,plan.height)
                    # A caption left at its preset position was checked clear.
                    box=cap.layout.box if cap.layout else default_caption_box(cap,plan.width,plan.height,
                                                                                    measure_default_ink(cap,plan.width,plan.height))
                    assert visible.x <= box.x < box.right <= visible.right
                    assert visible.y <= box.y < box.bottom <= visible.bottom


def test_short_source_shot_reacquires_subject_between_regular_samples(tmp_path,monkeypatch):
    np=pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from myzing.layout.detector import LayoutError
    from myzing.layout import framing as layout
    def unavailable(*a,**k):
        raise LayoutError("generated target has no face")
    monkeypatch.setattr(layout,"YuNetDetector",unavailable)
    source=tmp_path/"short-shot.mkv"
    ffmpeg("-f","lavfi","-i", "color=c=0x303050:s=640x360:r=30:d=2[bg];color=white:s=24x24:r=30:d=2[dot];[bg][dot]overlay=x='if(between(t,1.1,1.29),480,128)':y=80:shortest=1",
           "-c:v","ffv1",source)
    tracks,_=analyze_subjects(source,2,tmp_path,cut_times=[1.1,1.3])
    plan=make_plan(source,"reframe",180,320)
    clip=plan.clips[0]
    clip.src_in,clip.src_out=1.1,1.3
    clip.framing=track_framing(clip.framing,clip,tracks)
    output=tmp_path/"reacquired.mp4"
    render_composition(plan,output)
    frames=np.frombuffer(ffmpeg("-i",output,"-f","rawvideo","-pix_fmt","rgb24","pipe:1"),dtype=np.uint8).reshape(-1,320,180,3)
    assert len(frames)==6
    for frame in frames:
        ys,xs=np.nonzero(frame.min(axis=2)>180)
        assert len(xs)>100
        assert abs((xs.min()+xs.max())/2-90)<=3


@pytest.mark.parametrize("rate",[Rational(30,1),Rational(30000,1001)])
def test_maximum_keyframe_count_renders_frame_accurately_on_both_axes(tmp_path,rate):
    """256 keys (the contract maximum), every segment moving on x and y.

    A flat per-segment sum fails on FFmpeg 8 beyond ~93 terms. The luma ramp
    encodes the source column and a dark band at rows 240-243 the source row,
    so each output frame's crop origin is measured and compared with
    Framing.center_at at that frame's own clip-local time, and +-1 frame.
    """
    np = pytest.importorskip("numpy")
    from myzing.composition import frame_index
    from myzing.composition.framing import CropBounds, CropKeyframe, Framing
    ramp = tmp_path/"ramp.png"
    ffmpeg("-f","lavfi","-i","nullsrc=s=640x360:d=0.04,format=gray,geq=lum='if(between(Y,240,243),16,16+X*219/639)'",
           "-frames:v","1",ramp)
    source = tmp_path/"ramp.mkv"
    ffmpeg("-loop","1","-framerate","30","-i",ramp,"-t","13","-pix_fmt","yuv420p","-c:v","ffv1",source)
    keys = [CropKeyframe(i*.05, 120+400*(i%2), 165+30*(i%2)) for i in range(256)]
    framing = Framing("reframe",640,360,CropBounds(0,0,640,360),180,320,keys[0].center_x,keys[0].center_y,keys,
                      max_velocity=20000)
    clip = CompositionClip(str(source),0,12.8,0,id="c",asset_id="s",framing=framing)
    plan = Composition(assets=[AssetRef("s",str(source),None)],clips=[clip],width=180,height=320,fps=rate)
    output = tmp_path/"keys.mp4"
    render_composition(plan,output)
    frames = np.frombuffer(ffmpeg("-i",output,"-f","rawvideo","-pix_fmt","gray","pipe:1"),dtype=np.uint8).reshape(-1,320,180).astype(float)
    assert len(frames) == frame_index(12.8,rate,rounding="nearest")
    clock = rate.numerator/rate.denominator
    def expected(n):
        x,y = framing.center_at(n/clock)
        return int(x-90), int(y-160)
    columns = np.arange(180)
    residual, shifted, rows = [], {-1: [], 1: []}, []
    for n,frame in enumerate(frames):
        x_measured = float(np.median((np.median(frame,axis=0)-16)/(219/639)-columns))
        row_mean = frame.mean(axis=1)
        band = np.nonzero(row_mean < (16+np.median(row_mean))/2)[0]
        assert len(band) >= 3
        y_measured = 241.5-band.mean()
        x,y = expected(n)
        residual.append(x_measured-x)
        rows.append(abs(y_measured-y))
        for d in shifted:
            shifted[d].append(abs(x_measured-expected(max(0,n+d))[0]))
    bias = float(np.median(residual))
    assert abs(bias) <= 2
    assert max(abs(r-bias) for r in residual) <= 1.5
    assert max(rows) <= 1
    for d,errors in shifted.items():  # A one-frame clock error would be visible.
        assert np.mean(errors) > 20


def test_long_source_analysis_samples_only_used_trims_and_never_fails_on_length(tmp_path,monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from myzing.layout.detector import LayoutError
    from myzing.layout import framing as layout
    def unavailable(*a,**k):
        raise LayoutError("generated target has no face")
    monkeypatch.setattr(layout,"YuNetDetector",unavailable)
    monkeypatch.setattr(layout.PeopleDetector,"detect",lambda *a:[])
    source=tmp_path/"long.mkv"
    # 320 s exceeds the old whole-source limit (600 samples at 2 fps).
    ffmpeg("-f","lavfi","-i","color=c=0x303050:s=320x180:r=5:d=320[bg];color=white:s=16x16:r=5:d=320[dot];[bg][dot]overlay=x=200:y=60:shortest=1",
           "-c:v","ffv1",source)
    windows=[]
    original=layout._sample_window
    def recording(video,folder,start,end,interval,limit):
        windows.append((start,end,interval))
        return original(video,folder,start,end,interval,limit)
    monkeypatch.setattr(layout,"_sample_window",recording)
    tracks,warnings=analyze_subjects(source,320,tmp_path/"trim",ranges=[(150,152)])
    assert windows==[(149.5,152.5,.5)]
    assert tracks and all(149-1e-6 <= k.time <= 153+1e-6 for t in tracks for k in t.keyframes)
    for track in tracks:
        center=track.keyframes[0].box.center
        assert abs(center[0]-208/320)<.03 and abs(center[1]-68/180)<.05
    # Whole-source analysis past the budget lowers the rate; it never returns
    # zero tracks just because the source is long.
    monkeypatch.setattr(layout,"MAX_SAMPLES",40)
    windows.clear()
    tracks,warnings=analyze_subjects(source,320,tmp_path/"whole")
    assert len(windows)==1 and windows[0][2]>.5
    assert tracks and any("analysis budget" in w for w in warnings)
    assert not any("failed" in w for w in warnings)


def _estimate_box(caption, width, height):
    """The pre-fix 0.8 em/char estimate, kept here to prove each case mattered."""
    from myzing.layout.types import Box
    from myzing.render.captions import caption_anchor
    size, outline = max(24, round(min(width, height) / 12)), max(2, round(min(width, height) / 270))
    w = (len(caption.text) * size * .8 + outline * 2 + 6) / width
    h = (size * 1.4 + outline * 2 + 6) / height
    x, y = caption_anchor(caption.position, width, height)
    return Box(x / width - w / 2, y / height - h / 2, w, h)


@pytest.mark.parametrize("aspect,text", [("9:16", "M"*11), ("1:1", "W"*13), ("16:9", "W"*23)])
def test_wide_default_caption_is_placed_from_measured_ink_not_the_estimate(aspect, text):
    from myzing.composition.aspects import SAFE_INSETS, dimensions
    width, height = dimensions(aspect)
    caption = CompositionCaption(id="wide", text=text, start=.2, end=1.8, word_timed=False)
    plan = Composition(assets=[AssetRef("s","s",None)], clips=[CompositionClip("s",0,2,0,id="c",asset_id="s")],
                       captions=[caption], width=width, height=height)
    left, top, right, bottom = SAFE_INSETS[aspect]
    estimate = _estimate_box(caption, width, height)
    # The old estimate cleared every output reserve, so the caption was kept.
    assert estimate.x >= left and estimate.right <= 1 - right
    place_captions(plan, {"s": []}, {"s": (width, height)}, keep_safe_defaults=True)
    placed = plan.captions[0]
    assert placed.layout is not None and placed.layout.overlap.safe and placed.style is not None
    box = placed.layout.box
    assert box.x >= left - 1e-9 and box.right <= 1 - right + 1e-9


def test_subject_touching_only_the_measured_ink_moves_the_caption():
    from myzing.layout.framing import default_caption_box, measure_default_ink
    from myzing.layout.types import Box, FaceTrack, Keyframe
    caption = CompositionCaption(id="www", text="WWW", start=.2, end=1.8, word_timed=False)
    estimate = _estimate_box(caption, 1920, 1080)
    measured = default_caption_box(caption, 1920, 1080, measure_default_ink(caption, 1920, 1080))
    assert measured.right > estimate.right + 10 / 1920  # Real bold W ink is wider than 0.8 em.
    # A subject just right of the estimate but inside the real glyph box.
    subject = Box(estimate.right + 2 / 1920, estimate.y, .05, estimate.height)
    face = FaceTrack("face", [Keyframe(0, subject), Keyframe(2, subject)])
    plan = Composition(assets=[AssetRef("s","s",None)], clips=[CompositionClip("s",0,2,0,id="c",asset_id="s")],
                       captions=[caption], width=1920, height=1080)
    place_captions(plan, {"s": [face]}, {"s": (1920, 1080)}, keep_safe_defaults=True)
    placed = plan.captions[0]
    assert placed.layout is not None and placed.layout.overlap.safe
    box = placed.layout.box
    assert box.right <= subject.x or box.x >= subject.right or box.bottom <= subject.y or box.y >= subject.bottom
    # Control: with no subject the same measured default is kept (v1-representable).
    plan.captions = [CompositionCaption(id="www", text="WWW", start=.2, end=1.8, word_timed=False)]
    place_captions(plan, {"s": []}, {"s": (1920, 1080)}, keep_safe_defaults=True)
    assert plan.captions[0].layout is None and plan.captions[0].style is None


def test_separate_trims_in_one_shot_never_share_tracks_at_a_lowered_rate(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from myzing.layout.detector import LayoutError
    from myzing.layout import framing as layout
    from myzing.layout.types import box_at
    def unavailable(*a,**k):
        raise LayoutError("generated target has no face")
    monkeypatch.setattr(layout,"YuNetDetector",unavailable)
    monkeypatch.setattr(layout.PeopleDetector,"detect",lambda *a:[])
    source=tmp_path/"one-shot.mkv"
    # One continuous shot: the target sits at x=120 before 13 s and x=170 after.
    ffmpeg("-f","lavfi","-i","color=c=0x303050:s=320x180:r=10:d=30[bg];color=white:s=16x16:r=10:d=30[dot];[bg][dot]overlay=x='if(lt(t,13),120,170)':y=60:shortest=1",
           "-c:v","ffv1",source)
    # Budget 6 for two 3 s windows: one sample per 1.5 s and a 2.25 s gap
    # allowance, wider than the 1.5 s unused gap between the windows.
    monkeypatch.setattr(layout,"MAX_SAMPLES",6)
    tracks,warnings=analyze_subjects(source,30,tmp_path/"a",ranges=[(10,12),(14.5,16.5)])
    assert any("analysis budget" in w for w in warnings)
    windows=[(9.5,12.5),(14,17)]
    early,late=(120+8)/320,(170+8)/320
    assert tracks
    for track in tracks:
        times=[k.time for k in track.keyframes]
        inside=[i for i,(a,b) in enumerate(windows) if a-1e-6<=min(times) and max(times)<=b+1e-6]
        assert inside, (track.id, times)  # No track spans the unused gap.
        expected=early if inside[0]==0 else late
        for t in [k.time for k in track.keyframes]:
            assert abs(box_at(track.keyframes,t).center[0]-expected)<.02
    for t in (10,11,12):
        active=[k for k in tracks if k.keyframes[0].time<=t<=k.keyframes[-1].time]
        assert active and all(abs(box_at(k.keyframes,t).center[0]-early)<.02 for k in active)
    for t in (14.5,15.5,16.5):
        active=[k for k in tracks if k.keyframes[0].time<=t<=k.keyframes[-1].time]
        assert active and all(abs(box_at(k.keyframes,t).center[0]-late)<.02 for k in active)
