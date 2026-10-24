"""Generated UI recording, telemetry, pixel coverage and FFmpeg compatibility."""

import json
import subprocess
from pathlib import Path

import pytest

from myzing.screen.api import plan_screen,save_plan
from myzing.screen.render import render_screen,expression
from myzing.screen.planner import camera,output_time,crop_window

pytestmark=pytest.mark.ffmpeg


def generate(folder):
    folder.mkdir(parents=True,exist_ok=True)
    source=folder/"screen.mp4"
    graph=("[0:v]drawbox=x=20:y=55:w=600:h=275:color=0x182838:t=fill,"
           "drawtext=text='LOCAL BUILD CONSOLE':x=25:y=18:fontsize=22:fontcolor=white,"
           "drawbox=x=110:y=110:w=110:h=60:color=red:t=fill:enable='between(t,0.8,3)',"
           "drawtext=text='READY':x=120:y=125:fontsize=22:fontcolor=white:enable='between(t,0.8,3)',"
           "drawbox=x=400:y=170:w=110:h=60:color=blue:t=fill:enable='gte(t,4)',"
           "drawtext=text='PASS':x=415:y=185:fontsize=22:fontcolor=white:enable='gte(t,4)'[ui];"
           "[ui][1:v]overlay=x='if(lt(t,2.5),165,if(lt(t,3.5),165+(t-2.5)*290,455))':"
           "y='if(lt(t,2.5),140,if(lt(t,3.5),140+(t-2.5)*60,200))':shortest=1[v]")
    p=subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=c=0x0c1018:s=640x360:r=30:d=9",
        "-f","lavfi","-i","color=white:s=8x12:r=30:d=9","-filter_complex",graph,"-map","[v]",
        "-c:v","libx264","-pix_fmt","yuv420p","-threads","1",str(source)],capture_output=True)
    assert p.returncode==0,p.stderr.decode(errors="replace")
    events=[{"type":"start","t":0,"version":1,"wall_time":"2026-10-24T00:00:00+00:00","hz":60,"bounds":[0,0,640,360]}]
    for i in range(540):
        t=i/60
        f=max(0,min(1,t-2.5))
        events.append({"type":"cursor","t":t,"x":(165+f*290)/640,"y":(140+f*60)/360})
        if i in (72,270):
            events.append({"type":"click","t":t,"x":events[-1]["x"],"y":events[-1]["y"],"button":"left"})
    events.append({"type":"stop","t":9,"samples":540})
    log=folder/"session.jsonl"
    log.write_text("".join(json.dumps(e)+"\n" for e in events),encoding="utf-8")
    return source,log


@pytest.fixture(scope="module")
def screen_fixture(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("screen"))


def frame(path,t,w,h):
    p=subprocess.run(["ffmpeg","-v","error","-ss",str(t),"-i",str(path),"-frames:v","1","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],capture_output=True)
    assert p.returncode==0 and len(p.stdout)==w*h*3
    return p.stdout


@pytest.mark.parametrize("telemetry",[True,False])
@pytest.mark.parametrize("aspect",["16:9","1:1","9:16"])
def test_screen_render_target_pixels_and_camera(tmp_path,screen_fixture,telemetry,aspect):
    source,log=screen_fixture
    plan=plan_screen(source,cursor=log if telemetry else None)
    assert plan.zooms
    assert not plan.idle if telemetry else plan.idle
    if not telemetry:
        assert all(z.confidence==.45 for z in plan.zooms)
    out=tmp_path/"demo.mp4"
    result=render_screen(plan,out,aspect=aspect,short_side=180)
    assert result["duration"]==pytest.approx(plan.duration,abs=.05) if telemetry else result["duration"]<plan.duration
    cam=json.loads(Path(result["camera"]).read_text())
    # Colored UI target must be visible at the right source/output times.
    for t,color in [(1.6,0),(4.8,2)]:
        when=output_time(cam["time_map"],t)
        data=frame(out,when,result["width"],result["height"])
        count=sum(data[i+color]>120 and data[i+(2 if color==0 else 0)]<100 for i in range(0,len(data),3))
        assert count>50,(aspect,t,color,count)
        # Independently compare the raster target box with the source-space
        # crop. This catches wrong zoompan coordinates/time after idle retiming.
        points=[(i//3%result["width"],i//3//result["width"]) for i in range(0,len(data),3)
                if data[i+color]>160 and data[i+1]<100 and data[i+(2 if color==0 else 0)]<100]
        cx=(min(p[0] for p in points)+max(p[0] for p in points))/2
        cy=(min(p[1] for p in points)+max(p[1] for p in points))/2
        key=min(cam["keys"],key=lambda k:abs(k["t"]-when))
        left,top,cw,ch=crop_window(plan,cam,key)
        sx,sy=(165,140) if color==0 else (455,200)
        picture=cam["shots"][key["shot"]]["picture"]
        assert abs(cx-(picture["x"]+(sx-left)*picture["width"]/cw))<4
        assert abs(cy-(picture["y"]+(sy-top)*picture["height"]/ch))<4
    for axis,limit in [("x",.65),("y",.65),("zoom",1.5)]:
        velocities=[(b[axis]-a[axis])*30 for a,b in zip(cam["keys"],cam["keys"][1:]) if not b.get("cut")]
        assert max(map(abs,velocities))<limit+.01
        assert max(abs(b-a)*30 for a,b in zip(velocities,velocities[1:]))<6.1


@pytest.mark.parametrize("preset",["clean","punch","box"])
def test_screen_caption_presets_clear_ui(tmp_path,screen_fixture,preset):
    source,log=screen_fixture
    words=[{"text":"Build","start":1,"end":1.5},{"text":"ready","start":1.5,"end":2}]
    p=plan_screen(source,cursor=log,words=words,caption_preset=preset,click_highlights=True)
    result=render_screen(p,tmp_path/"captions.mp4",aspect="9:16",short_side=360)
    layout=json.loads((Path(result["camera"]).parent/"caption-plan.json").read_text())
    assert layout["captions"] and all(c["preset"]==preset for c in layout["captions"])
    assert all(c["layout"]["overlap"]["safe"] for c in layout["captions"])
    assert all(c["layout"]["box"]["y"]>.60 for c in layout["captions"])


def test_screen_cli_plan_render_and_source_identity(tmp_path,screen_fixture,capsys):
    from myzing.plan.command import run as plan_run
    from myzing.render.command import run as render_run
    from dataclasses import replace
    source,log=screen_fixture
    dest=tmp_path/"plan.json"
    assert plan_run(["screen",str(source),"--cursor",str(log),"--out",str(dest)])==0
    assert render_run([str(dest),"--short-side","180","-o",str(tmp_path/"cli.mp4")])==0
    p=plan_screen(source,cursor=log)
    with pytest.raises(ValueError,match="changed"):
        render_screen(replace(p,sha256="0"*64),tmp_path/"bad.mp4")


def test_long_balanced_expression_renders(tmp_path):
    keys=[{"t":i/30,"zoom":1+.1*(i%100)/100} for i in range(600)]
    expr=expression(keys,"zoom","on/30")
    script=tmp_path/"long.txt"
    script.write_text(f"[0:v]zoompan=z='{expr}':d=1:s=160x90:fps=30[v]")
    from myzing.render.pipeline import filter_script_args
    p=subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=black:s=320x180:r=30:d=20",
        *filter_script_args("ffmpeg",script),"-map","[v]","-f","null","-"],capture_output=True)
    assert p.returncode==0,p.stderr.decode(errors="replace")


def test_screen_audio_unknown_speech_not_sped_up(tmp_path,screen_fixture):
    source,log=screen_fixture
    dest=tmp_path/"audio.mp4"
    p=subprocess.run(["ffmpeg","-v","error","-i",str(source),"-f","lavfi","-i","sine=frequency=440:duration=9",
                      "-c:v","copy","-c:a","aac","-shortest",str(dest)],capture_output=True)
    assert p.returncode==0
    plan=plan_screen(dest,cursor=log)
    assert not plan.idle and any("narration" in s for s in plan.warnings)
    result=render_screen(plan,tmp_path/"audio-demo.mp4",short_side=180)
    assert result["duration"]==pytest.approx(9,abs=.08)


@pytest.fixture(scope="module")
def edge_fixture(tmp_path_factory):
    root=tmp_path_factory.mktemp("screen-edges")
    video=root/"edges.mp4"
    filters=("drawbox=x=2:y=12:w=180:h=336:color=red:t=fill,"
             "drawtext=text='LEFT COMPLETE':x=8:y=60:fontsize=18:fontcolor=white,"
             "drawbox=x=450:y=16:w=188:h=330:color=blue:t=fill,"
             "drawtext=text='RIGHT COMPLETE':x=455:y=70:fontsize=18:fontcolor=white")
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=0x101820:s=640x360:r=30:d=6",
                    "-vf",filters,"-c:v","libx264","-threads","1","-pix_fmt","yuv420p",str(video)],check=True)
    rows=[{"type":"start","version":1,"t":0}]
    for i in range(360):
        t=i/60
        x=.14 if t<4.3 else .85
        rows.append({"type":"cursor","t":t,"x":x,"y":.5})
        if i in (72,258):
            rows.append({"type":"click","t":t,"x":x,"y":.5,"button":"left"})
    rows.append({"type":"stop","t":6,"samples":360})
    log=root/"cursor.jsonl"
    log.write_text("".join(json.dumps(e)+"\n" for e in rows))
    return video,log


@pytest.mark.parametrize("aspect",["16:9","1:1","9:16"])
def test_edge_elements_no_clip_or_empty_travel_frames(tmp_path,edge_fixture,aspect):
    source,log=edge_fixture
    plan=plan_screen(source,cursor=log,idle_speed=1)
    assert len(plan.zooms)==2 and all(z.box for z in plan.zooms)
    result=render_screen(plan,tmp_path/"edge.mp4",aspect=aspect,short_side=180)
    cam=json.loads(Path(result["camera"]).read_text())
    assert len(cam["cuts"])==1 and cam["cuts"][0]["t"]==pytest.approx(4.3)
    # Decode every output frame. Both complete outer color rectangles must
    # match the predicted picture coordinates. No dark travel frame is exempt.
    raw=subprocess.run(["ffmpeg","-v","error","-i",result["video"],"-f","rawvideo","-pix_fmt","rgb24","pipe:1"],
                       capture_output=True,check=True).stdout
    fw,fh=result["width"],result["height"]
    size=fw*fh*3
    assert len(raw)//size==180
    for index in range(180):
        key=cam["keys"][index]
        picture=cam["shots"][key["shot"]]["picture"]
        data=raw[index*size:(index+1)*size]
        color=0 if index<129 else 2
        points=[(i//3%fw,i//3//fw) for i in range(0,len(data),3)
                if data[i+color]>140 and data[i+1]<100 and data[i+2-color]<100]
        assert len(points)>150,(index,"empty travel frame")
        actual=[min(p[0] for p in points),min(p[1] for p in points),
                max(p[0] for p in points)+1,max(p[1] for p in points)+1]
        x,y,w,h=key["window"]
        target=(2,12,182,348) if color==0 else (450,16,638,346)
        expected=[picture["x"]+(target[0]-x)*picture["width"]/w,
                  picture["y"]+(target[1]-y)*picture["height"]/h,
                  picture["x"]+(target[2]-x)*picture["width"]/w,
                  picture["y"]+(target[3]-y)*picture["height"]/h]
        assert all(abs(a-b)<3 for a,b in zip(actual,expected)),(index,actual,expected)
        assert picture["x"]<actual[0]<actual[2]<picture["x"]+picture["width"]
        assert picture["y"]<actual[1]<actual[3]<picture["y"]+picture["height"]
    if aspect=="9:16":
        assert min(s["picture"]["height"] for s in cam["shots"])>=fh*.88


def test_old_screen_plan_measures_bounds_before_render(tmp_path,screen_fixture):
    source,log=screen_fixture
    plan=plan_screen(source,cursor=log)
    for z in plan.zooms:
        z.box=None
    result=render_screen(plan,tmp_path/"legacy.mp4",aspect="9:16",short_side=180)
    cam=json.loads(Path(result["camera"]).read_text())
    assert all(s["box"]!=[0,0,1,1] for s in cam["shots"])


@pytest.mark.parametrize("side",["left","right"])
def test_generated_focus_phone_floor_and_no_midword_crop(tmp_path,side):
    """Independent drawtext masks check actual ink, not detector-owned boxes."""
    from myzing.screen.regions import contains,intersects
    font=(Path(__file__).resolve().parents[1]/"src/myzing/_data/fonts/Anton-Regular.ttf").as_posix().replace(":",r"\:")
    bx=4 if side=="left" else 448
    text_x=bx+14
    words=[("READY",text_x,173),("COMPLETE",text_x,108),
           ("BACKGROUND",175 if side=="left" else 325,235),("FINAL",text_x,305)]
    def draw(text,x,y):
        return f"drawtext=fontfile='{font}':text='{text}':x={x}:y={y}:fontsize=22:fontcolor=white"
    filters=[f"drawbox=x=1:y=10:w=638:h=340:color=0x203040:t=fill",
             f"drawbox=x={bx}:y=155:w=188:h=62:color=blue:t=fill"]
    filters += [draw(*item) for item in words]
    video=tmp_path/"focus.mp4"
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=0x101820:s=640x360:r=30:d=3",
        "-vf",",".join(filters),"-c:v","libx264","-threads","1","-pix_fmt","yuv420p",str(video)],check=True)
    truth=[]
    for text,x,y in words:
        raw=subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=black:s=640x360",
            "-vf",draw(text,x,y),"-frames:v","1","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],
            capture_output=True,check=True).stdout
        points=[(i//3%640,i//3//640) for i in range(0,len(raw),3) if min(raw[i:i+3])>150]
        left,top=min(x for x,y in points),min(y for x,y in points)
        truth.append([left,top,max(x for x,y in points)+1-left,max(y for x,y in points)+1-top])
    rows=[{"type":"start","version":1,"t":0}]
    rows += [{"type":"cursor","t":i/60,"x":(bx+80)/640,"y":185/360} for i in range(180)]
    rows += [{"type":"stop","t":3,"samples":180}]
    log=tmp_path/"cursor.jsonl"
    log.write_text("".join(json.dumps(r)+"\n" for r in rows))
    p=plan_screen(video,cursor=log,ui_text_px=22,words=[{"text":"Run","start":.5,"end":2}])
    assert not p.idle and len(p.zooms)==1  # Long static hover is attention.
    assert p.zooms[0].box[2]<.4  # Focus control, not the almost-full-frame panel.
    result=render_screen(p,tmp_path/"portrait.mp4",aspect="9:16",short_side=360)
    assert result["duration"]==pytest.approx(3,abs=.05)
    cam=json.loads(Path(result["camera"]).read_text())
    for shot in cam["shots"]:
        for key in shot["keys"]:
            view=key["window"]
            scale=shot["picture"]["width"]/view[2]
            assert 22*scale>=shot["phone_text_floor"]-1e-6
            assert p.zooms[0].box[2]*640*scale>=.60*360-1e-6
            assert contains(view,[bx,155,188,62])
            for word in truth:
                assert not intersects(view,word) or contains(view,word),(side,view,word)
    # Verify rendered READY ink occupies the independently predicted full box.
    key=cam["keys"][30]
    pic=cam["shots"][key["shot"]]["picture"]
    x,y,w,h=key["window"]
    target=truth[0]
    expected=[pic["x"]+(target[0]-x)*pic["width"]/w,
              pic["y"]+(target[1]-y)*pic["height"]/h,
              target[2]*pic["width"]/w,target[3]*pic["height"]/h]
    data=frame(result["video"],1,360,640)
    points=[(i//3%360,i//3//360) for i in range(0,len(data),3)
            if min(data[i:i+3])>170 and expected[0]-3<=i//3%360<=expected[0]+expected[2]+3
            and expected[1]-3<=i//3//360<=expected[1]+expected[3]+3]
    assert points
    actual=[min(a for a,b in points),min(b for a,b in points),
            max(a for a,b in points)+1-min(a for a,b in points),max(b for a,b in points)+1-min(b for a,b in points)]
    assert all(abs(a-b)<=3 for a,b in zip(actual,expected)),(actual,expected)


def test_tall_rendered_text_guards_portrait_crop(tmp_path):
    """Large glyph ink must survive region detection and protect every frame."""
    from myzing.screen.regions import contains,intersects,geometry
    font=(Path(__file__).resolve().parents[1]/"src/myzing/_data/fonts/Anton-Regular.ttf").as_posix().replace(":",r"\:")
    text=f"drawtext=fontfile='{font}':text='MMMM':x=40:y=192:fontsize=34:fontcolor=white"
    raw=subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=black:s=640x360",
        "-vf",text,"-frames:v","1","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],
        capture_output=True,check=True).stdout
    points=[(i//3%640,i//3//640) for i in range(0,len(raw),3) if min(raw[i:i+3])>150]
    left,top=min(x for x,y in points),min(y for x,y in points)
    truth=[left,top,max(x for x,y in points)+1-left,max(y for x,y in points)+1-top]
    assert truth[3]>360*.065
    _,_,words=geometry(raw,640,360)
    normalized=[truth[0]/640,truth[1]/360,truth[2]/640,truth[3]/360]
    assert any(contains(b,normalized) for b in words)
    video=tmp_path/"tall-text.mp4"
    filters="drawbox=x=60:y=150:w=100:h=32:color=blue:t=fill,"+text
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=black:s=640x360:r=30:d=2",
        "-vf",filters,"-c:v","libx264","-threads","1","-pix_fmt","yuv420p",str(video)],check=True)
    rows=[{"type":"start","version":1,"t":0}]
    rows += [{"type":"cursor","t":i/60,"x":110/640,"y":166/360} for i in range(120)]
    rows += [{"type":"stop","t":2,"samples":120}]
    log=tmp_path/"cursor.jsonl"
    log.write_text("".join(json.dumps(r)+"\n" for r in rows),encoding="utf-8")
    p=plan_screen(video,cursor=log,words=[{"text":"Run","start":.5,"end":1.5}])
    assert any(contains(b,normalized) for b in p.zooms[0].box_evidence["words"])
    result=render_screen(p,tmp_path/"portrait.mp4",aspect="9:16",short_side=360)
    cam=json.loads(Path(result["camera"]).read_text())
    for key in cam["keys"]:
        assert not intersects(key["window"],truth) or contains(key["window"],truth)
    # The renderer must use that crop, including the whole line when visible.
    key=cam["keys"][30]
    if intersects(key["window"],truth):
        pic=cam["shots"][key["shot"]]["picture"]
        x,y,w,h=key["window"]
        expected=[pic["x"]+(truth[0]-x)*pic["width"]/w,pic["y"]+(truth[1]-y)*pic["height"]/h,
                  truth[2]*pic["width"]/w,truth[3]*pic["height"]/h]
        data=frame(result["video"],1,360,640)
        ink=[(i//3%360,i//3//360) for i in range(0,len(data),3)
             if min(data[i:i+3])>150 and i//3//360<pic["y"]+pic["height"]]
        actual=[min(a for a,b in ink),min(b for a,b in ink),
                max(a for a,b in ink)+1-min(a for a,b in ink),max(b for a,b in ink)+1-min(b for a,b in ink)]
        assert all(abs(a-b)<=3 for a,b in zip(actual,expected)),(actual,expected)
