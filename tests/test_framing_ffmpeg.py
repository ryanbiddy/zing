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
    centers = []
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
            ty,tx=np.nonzero(text)
            assert tx.min() >= box.x*180-2 and tx.max() <= box.right*180+2
            assert ty.min() >= box.y*320-2 and ty.max() <= box.bottom*320+2
            assert not (text & target).any()
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
    assert any("exceeds stated 2x" in w for w in result.warnings)


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
    from myzing.layout.framing import visible_content
    project,_,recipe=example_project(tmp_path/"project",media=True)
    brief=json.loads((project/"brief.json").read_text())
    brief.update(aspect="1:1",framing=requested)
    write_json(project/"brief.json",brief)
    result=plan_drafts(project,project/"recipe.json",project/"plans",seed=17)
    assert result["status"]=="ready" and len(result["plans"])==3
    for label,path in result["plans"].items():
        prepared=_prepare_plan(Path(path),project/"drafts"/f"{label}.json",{},recipe,{"layout":False})
        plan=Composition.from_json(Path(prepared["path"]).read_text())
        assert all(c.framing.mode==expected for c in plan.clips)
        assert plan.captions and all(c.layout.overlap.safe for c in plan.captions)
        for cap in plan.captions:
            for clip in plan.clips:
                if clip.timeline_start < cap.end and clip.timeline_end > cap.start:
                    visible=visible_content(clip.framing,plan.width,plan.height)
                    box=cap.layout.box
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
