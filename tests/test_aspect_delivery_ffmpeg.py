"""Generated-media coverage for all target aspects, display transforms and blurfill."""

import json
import subprocess
from pathlib import Path

import pytest

from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip, CaptionStyle
from myzing.composition.aspects import ASPECTS, SAFE_INSETS, dimensions
from myzing.layout.framing import centered_framing, analyze_subjects, track_framing, visible_content
from myzing.render.composition import render_composition
from myzing.render.framing import probe_dimensions

pytestmark = pytest.mark.ffmpeg


def ffmpeg(*args):
    result = subprocess.run(["ffmpeg","-v","error","-nostdin","-y",*map(str,args)],capture_output=True,timeout=90)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def generated(path,width,height,duration=.4):
    # RGB testsrc preserves odd dimensions; the colored field has no source bars.
    last = ",drawbox=x=0:y=0:w=iw:h=ih:color=0xc06040:t=fill:enable='eq(n,11)'" if duration == .4 else ""
    ffmpeg("-f","lavfi","-i",f"testsrc=s={width}x{height}:r=30:d={duration},drawbox=x=0:y=0:w=iw:h=ih:color=0x406080:t=fill" + last,
           "-c:v","ffv1","-pix_fmt","bgr0",path)
    assert probe_dimensions(path) == (width,height)


def plan_for(path,sw,sh,width,height,mode,duration=.4):
    return Composition(assets=[AssetRef("s",str(path),None)],
        clips=[CompositionClip(str(path),0,duration,0,id="c",asset_id="s",framing=centered_framing(mode,sw,sh,width,height))],
        width=width,height=height)


def pixels(path,width,height):
    np=pytest.importorskip("numpy")
    data=ffmpeg("-i",path,"-vf","scale=in_color_matrix=bt709:in_range=tv,format=rgb24","-f","rawvideo","pipe:1")
    return np.frombuffer(data,dtype=np.uint8).reshape(-1,height,width,3)


@pytest.mark.parametrize("shape",[(320,180),(320,240),(420,180),(180,320),(240,320),(240,240),(321,181)])
@pytest.mark.parametrize("aspect",ASPECTS)
@pytest.mark.parametrize("mode",["fill","blurfill"])
def test_every_source_shape_fills_each_target_without_renderer_bars(tmp_path,shape,aspect,mode):
    source=tmp_path/"source.mkv"
    generated(source,*shape)
    width,height=dimensions(aspect,180)
    plan=plan_for(source,*shape,width,height,mode)
    output=tmp_path/"output.mp4"
    result=render_composition(plan,output)
    frames=pixels(output,width,height)
    assert len(frames)==12
    # The last frame is a different picture. A duplicated penultimate frame
    # would hide an EOF/framesync error while satisfying the frame count.
    center = frames[:,height//2,width//2].astype(int)
    assert (center[:11,2] > center[:11,0] + 30).all()
    assert center[11,0] > center[11,2] + 40
    for edge in (frames[:,0],frames[:,-1],frames[:,:,0],frames[:,:,-1]):
        assert edge.mean()>12
    assert "pad=" not in result.filtergraph.replace("tpad=","temporal=").replace("apad=","audio=")
    if mode=="blurfill":
        assert "gblur=" in result.filtergraph and "lutyuv=" in result.filtergraph
        visible=visible_content(plan.clips[0].framing,width,height)
        if visible.width < .9 or visible.height < .9:
            assert frames[:,0,0].mean() < frames[:,height//2,width//2].mean()*.8


@pytest.mark.parametrize("angle",[0,90,180,270])
@pytest.mark.parametrize("sar",["1:1","3:2"])
def test_phone_rotation_and_sar_preserve_display_geometry_in_all_targets(tmp_path,angle,sar):
    np=pytest.importorskip("numpy")
    raw=tmp_path/"raw.mp4"
    source=tmp_path/"rotated.mp4"
    ffmpeg("-f","lavfi","-i","color=c=0x406080:s=320x240:r=30:d=0.4,drawbox=x=16:y=24:w=32:h=48:color=red:t=fill",
           "-vf",f"setsar={sar.replace(':','/')}","-c:v","libx264","-pix_fmt","yuv420p",raw)
    ffmpeg("-display_rotation",angle,"-i",raw,"-c","copy",source)
    sw,sh=(480,240) if sar=="3:2" else (320,240)
    if angle%180:
        sw,sh=sh,sw
    assert probe_dimensions(source)==(sw,sh)
    target_centers={0:(.1,.2),90:(.2,.9),180:(.9,.8),270:(.8,.1)}
    for aspect in ASPECTS:
        width,height=dimensions(aspect,180)
        plan=plan_for(source,sw,sh,width,height,"blurfill")
        output=tmp_path/(aspect.replace(":","x")+".mp4")
        render_composition(plan,output)
        frame=pixels(output,width,height)[5]
        content=visible_content(plan.clips[0].framing,width,height)
        red=(frame[:,:,0]>150)&(frame[:,:,1]<100)&(frame[:,:,2]<100)
        # Exclude the blurred background from the marker measurement.
        region=np.zeros(red.shape,dtype=bool)
        region[round(content.y*height):round(content.bottom*height),round(content.x*width):round(content.right*width)]=True
        ys,xs=np.nonzero(red&region)
        assert len(xs)>25
        x,y=target_centers[angle]
        assert abs(xs.mean()-(content.x+x*content.width)*width)<3
        assert abs(ys.mean()-(content.y+y*content.height)*height)<3
        if sar=="3:2":
            assert abs((xs.max()-xs.min())-(ys.max()-ys.min()))<=3


@pytest.mark.parametrize("requested_from", ["flag", "brief"])
def test_single_plan_cli_exports_three_independently_adapted_deliveries(tmp_path,monkeypatch,capsys,requested_from):
    from myzing.render.command import run
    from myzing.layout import framing as layout
    from myzing.layout.types import Box,FaceTrack,Keyframe
    source=tmp_path/"source.mkv"
    generated(source,640,360,1)
    cap=CompositionCaption(id="caption",text="CLEAR VIEW",start=.1,end=.9,word_timed=False,style=CaptionStyle(36))
    plan=plan_for(source,640,360,360,640,"fill",1)
    plan.captions=[cap]
    if requested_from=="brief":
        from myzing.brief.models import Brief
        plan.brief=Brief(aspects=list(ASPECTS))
    original=tmp_path/"plan.json"
    original.write_text(plan.to_json(),encoding="utf-8")
    before=original.read_bytes()
    track=FaceTrack("face",[Keyframe(0,Box(.4,.3,.2,.25)),Keyframe(1,Box(.4,.3,.2,.25))])
    import myzing.render.deliveries as deliveries
    monkeypatch.setattr(deliveries,"analyze_subjects",lambda *a,**k:([track],[]))
    options=["--aspect","all"] if requested_from=="flag" else []
    assert run([str(original),*options,"--short-side","180","-o",str(tmp_path/"draft-A.mp4")])==0
    result=json.loads(capsys.readouterr().out)
    assert set(result["deliveries"])==set(ASPECTS) and original.read_bytes()==before
    modes=[]
    for aspect,row in result["deliveries"].items():
        path=Path(row["video"])
        assert path.name=="draft-A."+aspect.replace(":","x")+".mp4"
        assert probe_dimensions(path)==dimensions(aspect,180)
        adapted=Composition.from_json(Path(row["plan"]).read_text())
        modes.append(adapted.clips[0].framing.mode)
        assert len(pixels(path,*dimensions(aspect,180)))==30
        assert adapted.captions[0].layout.overlap.safe
        assert adapted.captions[0].style.size<=18
        box=adapted.captions[0].layout.box
        left,top,right,bottom=SAFE_INSETS[aspect]
        assert box.x>=left-1e-9 and box.right<=1-right+1e-9
        assert box.y>=top-1e-9 and box.bottom<=1-bottom+1e-9
    assert modes==["fit","reframe","reframe"]


def test_bright_moving_exhaust_does_not_pull_crop_off_stable_object(tmp_path,monkeypatch):
    np=pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from myzing.layout import framing as layout
    from myzing.layout.detector import LayoutError
    def unavailable(*a,**k):
        raise LayoutError("generated footage has no face")
    monkeypatch.setattr(layout,"YuNetDetector",unavailable)
    monkeypatch.setattr(layout.PeopleDetector,"detect",lambda *a:[])
    source=tmp_path/"exhaust.mkv"
    # A dim shoulder around the clipped core lowers the component mean below
    # 190, as in archival exhaust. Mean brightness alone must not win saliency.
    ffmpeg("-f","lavfi","-i","color=c=0x202028:s=640x360:r=30:d=3[bg];color=c=0xaaaaaa:s=30x50:r=30:d=3[obj];color=c=0x606060:s=140x65:r=30:d=3,drawbox=x=20:y=10:w=100:h=45:color=white:t=fill[fire];[bg][obj]overlay=x=160:y=120[subject];[subject][fire]overlay=x='370+120*sin(6*t)':y=150:shortest=1",
           "-c:v","ffv1",source)
    tracks,warnings=analyze_subjects(source,3,tmp_path)
    assert tracks
    assert all(abs(k.box.center[0]*640-175)<4 for t in tracks for k in t.keyframes)
    plan=plan_for(source,640,360,180,320,"reframe",3)
    plan.clips[0].framing=track_framing(plan.clips[0].framing,plan.clips[0],tracks)
    output=tmp_path/"tracked.mp4"
    render_composition(plan,output)
    frames=pixels(output,180,320)
    for frame in frames:
        # Restrict the mask to the object's vertical band: resampling at the
        # distant white plume's edge can also produce intermediate gray pixels.
        target=(frame.min(axis=2)>130)&(frame.max(axis=2)<205)
        target[130:]=False
        ys,xs=np.nonzero(target)
        assert len(xs)>100 and abs((xs.min()+xs.max())/2-90)<=3
    assert max(k.center_x for k in plan.clips[0].framing.keyframes)-min(k.center_x for k in plan.clips[0].framing.keyframes)<1


def test_match_brief_exports_all_aspects_and_resumes(tmp_path,monkeypatch,zing_workspace,capsys):
    import sys
    from myzing.match.command import run
    from myzing.match.state import read
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from tools.match_examples import ANSWERS, generate
    for module in ("cv2","numpy","PIL","scenedetect","pysubs2"):
        pytest.importorskip(module)
    reference,clips=generate(tmp_path/"inputs")
    out,trace=tmp_path/"project",tmp_path/"trace.json"
    monkeypatch.setattr("myzing.match.jobs.worker_command",lambda:[sys.executable,"-m","tools.match_examples","--worker",str(trace)])
    args=[str(reference),"--clips",str(clips),"--out",str(out),"--seed","18","--json"]
    assert run([*args,"--answers",json.dumps({**ANSWERS,"aspects":list(ASPECTS)})])==0
    result=json.loads(capsys.readouterr().out)
    assert result["ready"]==result["requested"]==9
    for label,row in result["drafts"].items():
        aspect=label.split(".")[1].replace("x",":")
        assert Path(row["video"]).name==f"draft-{label}.mp4"
        assert probe_dimensions(row["video"])==dimensions(aspect)
        assert read(row["report"])["render"]["full_decode"]
    assert len(read(trace)["calls"])==13 and not read(trace)["network_attempts"]
    assert run([*args,"--resume"])==0
    resumed=json.loads(capsys.readouterr().out)
    assert resumed["ready"]==9
    assert all("render-"+label in resumed["reused_steps"] for label in result["drafts"])
    assert len(read(trace)["calls"])==13
