"""Render every preset on both aspects; run against each supported FFmpeg gate."""

from dataclasses import replace
import json
import subprocess

import pytest

from myzing.captions.presets import apply_preset
from myzing.captions.render import geometry
from myzing.composition import AssetRef,Composition,CompositionCaption,CompositionClip
from myzing.layout.framing import place_captions
from myzing.render.font_files import private_font
from myzing.render.positioned_captions import generate_positioned_ass
from myzing.schemas import Word

pytestmark=pytest.mark.ffmpeg


@pytest.mark.parametrize("preset",["punch","box","clean"])
@pytest.mark.parametrize("w,h",[(360,640),(360,360),(640,360)])
@pytest.mark.parametrize("missing_font",[False,True])
def test_preset_rendered_glyph_slots_stay_fixed(tmp_path,preset,w,h,missing_font):
    np=pytest.importorskip("numpy")
    timed=[Word("NEW",.1,.6),Word("IDEAS,",.84,1.4)]
    p=Composition(width=w,height=h,assets=[AssetRef("a","unused",None,2.5)],
        clips=[CompositionClip("unused",0,2.5,0,id="shot",asset_id="a")],
        captions=[CompositionCaption("NEW IDEAS,",.1,1.4,id="old",words=timed,all_caps=False)])
    apply_preset(p,preset,vad=False); place_captions(p,{}, {})
    assert len(p.captions)==1
    caption=p.captions[0]
    from pathlib import Path
    fonts={caption.id:private_font(Path(caption.font.path).read_bytes())}
    if missing_font:
        from myzing.render.composition import prepare_composition
        (tmp_path/"unused").write_bytes(b"media identity fixture")
        caption.font.path = str(tmp_path/"font-from-another-machine.ttf")
        prepared = prepare_composition(p, tmp_path)
        assert any("identical bundled face" in w for w in prepared.warnings)
        assert prepared.fonts == fonts
    generate_positioned_ass(p,fonts,tmp_path,"ffmpeg","ass")
    run=subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",f"color=black:s={w}x{h}:r=30:d=2.5",
        "-vf","ass=filename=captions.ass:fontsdir=fonts","-threads","1","-pix_fmt","rgb24","-f","rawvideo","pipe:1"],
        cwd=tmp_path,capture_output=True,timeout=60)
    assert run.returncode==0,run.stderr.decode(errors="replace")
    frames=np.frombuffer(run.stdout,dtype=np.uint8).reshape(-1,h,w,3)
    geo=geometry(caption,w,h)
    assert geo["line_count"] == 1
    # Check all ink, including anything outside the individual crops below.
    ys,xs=np.nonzero(frames[12].max(axis=2)>130)
    left=min(s["plate_x"] for s in geo["slots"])-caption.style.outline_width-2
    right=max(s["plate_x"]+s["plate_width"] for s in geo["slots"])+caption.style.outline_width+2
    assert xs.min() >= left and xs.max() <= right
    assert ys.max()-ys.min() < geo["size"]*1.5
    # A 240 ms gap rounds to eight frames: it must still hold without a blink.
    a,b,gap=frames[12],frames[32],frames[21]
    for slot in geo["slots"]:
        x0,x1=int(slot["x"]),int(np.ceil(slot["x"]+slot["width"]))
        y0,y1=int(slot["plate_y"]+geo["size"]*.08),int(slot["plate_y"]+slot["plate_height"]-geo["size"]*.08)
        def ink(frame,active):
            crop=frame[y0:y1,x0:x1]
            if preset=="box" and active==slot["index"]:
                return crop.max(axis=2)<100
            return crop[:,:,0]>150  # Both white and yellow glyphs.
        ma,mb=ink(a,0),ink(b,1)
        assert ma.sum()>10 and mb.sum()>10
        assert np.mean(ma!=mb)<.08, (preset,slot,ma.sum(),mb.sum())
        # A slot's glyph bounding box cannot move when its color changes.
        ya,xa=np.nonzero(ma); yb,xb=np.nonzero(mb)
        assert max(abs(int(u)-int(v)) for u,v in zip((xa.min(),xa.max(),ya.min(),ya.max()),
                                                       (xb.min(),xb.max(),yb.min(),yb.max())))<=1
    if preset=="box":
        # The whole visible glyph, including commas/descenders, belongs inside
        # the reserved metric plate. A stable but vertically offset plate fails.
        for i,slot in enumerate(geo["slots"]):
            white_frame = b if i==0 else a
            x0,x1=int(slot["x"])-1,int(np.ceil(slot["x"]+slot["width"]))+1
            crop=white_frame[:,x0:x1]
            ys,xs=np.nonzero(crop.min(axis=2)>170)
            assert ys.min() >= slot["plate_y"]-1
            assert ys.max() <= slot["plate_y"]+slot["plate_height"]+1
    if preset!="clean":
        yellow=lambda f:(f[:,:,0]>180)&(f[:,:,1]>130)&(f[:,:,2]<120)
        assert yellow(gap).sum()>20
    if preset=="punch":
        assert np.count_nonzero(frames[3]) < np.count_nonzero(frames[12])
    saved=json.loads((tmp_path/"caption-geometry.json").read_text())
    assert saved[0]["baseline"]==geo["baseline"]


@pytest.mark.parametrize("text", ["我们一起分享", "مرحبا بالعالم", "NEW 👩‍💻 IDEAS"])
def test_libass_fallback_widths_and_rtl_do_not_wrap(tmp_path, text):
    from pathlib import Path
    from myzing.captions.metrics import metrics
    np = pytest.importorskip("numpy")
    timed = [Word(t, .2+i*.8, .8+i*.8) for i,t in enumerate(text.split())]
    duration = timed[-1].end+1
    p = Composition(width=360,height=640,assets=[AssetRef("a","unused",None,duration)],
        clips=[CompositionClip("unused",0,duration,0,id="shot",asset_id="a")],
        captions=[CompositionCaption(text,.2,timed[-1].end,id="old",words=timed,all_caps=False)])
    apply_preset(p,"box",vad=False)
    place_captions(p,{}, {})
    assert any("measured with libass" in w for w in p.warnings)
    fonts = {c.id:private_font(Path(c.font.path).read_bytes()) for c in p.captions}
    generate_positioned_ass(p,fonts,tmp_path,"ffmpeg","ass")
    run = subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",f"color=black:s=360x640:r=30:d={duration}",
        "-vf","ass=filename=captions.ass:fontsdir=fonts","-threads","1","-pix_fmt","rgb24","-f","rawvideo","pipe:1"],
        cwd=tmp_path,capture_output=True,timeout=60)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    frames = np.frombuffer(run.stdout,dtype=np.uint8).reshape(-1,640,360,3)
    for c in p.captions:
        geo = geometry(c,360,640)
        assert geo["line_count"] == 1
        frame = frames[int((c.start+c.end)*15)]
        ys,xs = np.nonzero(frame.max(axis=2)>150)
        assert len(xs)>10
        assert xs.min() >= min(s["plate_x"] for s in geo["slots"])-2
        assert xs.max() <= max(s["plate_x"]+s["plate_width"] for s in geo["slots"])+2
        assert ys.max()-ys.min() <= geo["size"]*1.6
        face = metrics(c.font.path,c.font.sha256)
        for slot in geo["slots"]:
            assert slot["width"] == pytest.approx(face.width(slot["text"],geo["size"]))
