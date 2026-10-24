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
    assert plan.zooms and plan.idle
    if not telemetry:
        assert all(z.confidence==.45 for z in plan.zooms)
    out=tmp_path/"demo.mp4"
    result=render_screen(plan,out,aspect=aspect,short_side=180)
    assert result["duration"]<plan.duration
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
        assert abs(cx-(sx-left)*result["width"]/cw)<4
        assert abs(cy-(sy-top)*result["height"]/ch)<4
    for axis,limit in [("x",.65),("y",.65),("zoom",1.5)]:
        velocities=[(b[axis]-a[axis])*30 for a,b in zip(cam["keys"],cam["keys"][1:])]
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
