"""Screen planner/recorder contracts: stdlib, no FFmpeg or desktop required."""

import io
import json
import math
from dataclasses import replace

import pytest

from myzing.screen.models import ScreenPlan, Zoom, read_cursor
from myzing.screen.planner import (dwell_candidates, zoom_candidates, protected_idle,
                                   time_segments, output_time, camera, crop_window, dimensions)
from myzing.screen.recorder import record
from myzing.screen.analysis import parse_freezes


def samples(a,b,x=.3,y=.4):
    return [{"type":"cursor","t":a+i/60,"x":x,"y":y} for i in range(round((b-a)*60)+1)]


def plan(**kwargs):
    return ScreenPlan("demo.mp4","a"*64,960,540,10,**kwargs)


@pytest.mark.parametrize("duration,want",[(.3,0),(.45,1),(1.8,1),(2.6,1),(3,1)])
def test_openscreen_dwell_duration(duration,want):
    assert len(dwell_candidates(samples(0,duration)))==want


def test_dwell_gap_preserves_every_valid_nearby_rest():
    assert not dwell_candidates([{"type":"cursor","t":0,"x":.2,"y":.2},{"type":"cursor","t":1,"x":.2,"y":.2}])
    result=dwell_candidates(samples(0,.6)+samples(.8,1.8,.7)+samples(3.5,4.2))
    assert len(result)==3 and result[1]["x"]==pytest.approx(.7)


def test_merge_clicks_with_dwell_despite_contradictory_freeze():
    events=samples(1,2)+[{"type":"click","t":1.7,"x":.31,"y":.4}]
    zooms=zoom_candidates(events,[],[],10)
    assert len(zooms)==1 and {e['kind'] for e in zooms[0].evidence}=={"click","dwell"}
    assert zooms[0].confidence==.95
    assert zoom_candidates(events,[],[{"start":0,"end":4}],10)
    rapid=[{"type":"click","t":1+i*.01,"x":.2 if i%2 else .8,"y":.5} for i in range(12)]
    scenes=zoom_candidates(rapid,[],[],10)
    cam=camera(plan(zooms=scenes),360,640)
    assert all(s["end"]-s["start"]>=.1-1e-6 for s in cam["segments"] if s["kind"]=="hold")


def test_idle_keeps_activity_speech_and_reading_handles():
    idle=protected_idle([{"start":0,"end":10}],[{"type":"key","t":4}], [{"start":7,"end":8}],10)
    assert idle[0]["start"]==.6 and idle[-1]["end"]==9.4
    assert all(not (s["start"]<4<s["end"] or s["start"]<7.5<s["end"]) for s in idle)
    p=plan(idle=idle)
    spans=time_segments(p)
    assert spans[0]["start"]==0 and spans[-1]["end"]==10
    assert all(a["end"]==b["start"] and a["out_end"]==b["out_start"] for a,b in zip(spans,spans[1:]))
    assert output_time(spans,10)<10


@pytest.mark.parametrize("aspect",["16:9","1:1","9:16"])
def test_camera_motion_and_target_coverage(aspect):
    p=plan(zooms=[Zoom(0,3,.3,.45,[{"kind":"click","t":1}],.95,box=[.15,.2,.3,.5]),
                  Zoom(3.2,7,.65,.5,[{"kind":"click","t":4.5}],.95,box=[.5,.2,.3,.5])])
    cam=camera(p,*dimensions(aspect,360))
    for t,x,y in [(1.2,.3,.45),(5,.65,.5)]:
        k=min(cam["keys"],key=lambda k:abs(k["t"]-t))
        a,b,w,h=crop_window(p,cam,k)
        assert a+.05*w <= x*p.width <= a+.95*w
        assert b+.05*h <= y*p.height <= b+.95*h
    for axis,vel,acc in [("x",.65,4),("y",.65,4),("zoom",1.5,6)]:
        velocities=[(b[axis]-a[axis])*p.fps for a,b in zip(cam["keys"],cam["keys"][1:]) if not b.get("cut")]
        assert max(map(abs,velocities))<=vel+1e-6
        assert max(abs(b-a)*p.fps for a,b in zip(velocities,velocities[1:]))<=acc+.05
    # Check every visible crop edge within shots. Action cuts are discrete;
    # the contained push-in still has to obey velocity/acceleration bounds.
    for shot in cam["shots"]:
        boxes=[crop_window(p,cam,k) for k in shot["keys"]]
        for values in ([x/p.width for x,y,w,h in boxes],[(x+w)/p.width for x,y,w,h in boxes],
                       [y/p.height for x,y,w,h in boxes],[(y+h)/p.height for x,y,w,h in boxes]):
            velocities=[(b-a)*p.fps for a,b in zip(values,values[1:])]
            assert max(map(abs,velocities))<=.65+1e-6
            assert max(abs(b-a)*p.fps for a,b in zip(velocities,velocities[1:]))<=4+.05
    assert all(s["end"]-s["start"]>=.1-1e-6 for s in cam["segments"] if s["kind"]=="hold")


def test_phone_floor_cannot_be_faked_by_excess_zoom():
    p=plan(ui_text_px=4,max_zoom=1.2)
    cam=camera(p,1080,1920)
    assert cam["zoom_cap"]<=1.2
    assert cam["phone_text_floor"]==pytest.approx(86.4)
    assert any("cannot reach" in n for n in cam["warnings"])
    assert all(k["window"][2] >= p.width for k in cam["keys"])


def test_recorder_privacy_jsonl_and_countdown(tmp_path):
    class Clock:
        t=0
        def clock(self): return self.t
        def sleep(self,n): self.t+=n
    class Sampler:
        bounds=(100,200,800,600)
        def poll(self): return 300,500,["left"],True
    clock=Clock()
    messages=[]
    dest=tmp_path/"cursor.jsonl"
    record(dest,duration=.1,countdown=2,source=Sampler(),clock=clock.clock,sleep=clock.sleep,output=messages.append)
    header,events,stopped=read_cursor(dest,offset=2)
    assert header["version"]==1 and header["hz"]==60 and stopped
    assert header["wall_time"].endswith("+00:00") and any("GO" in s for s in messages)
    assert next(s for s in messages if s.startswith("GO")) == "GO - telemetry t=0. Stop with Ctrl+C."
    assert len([e for e in events if e["type"]=="click"])==1
    assert all(set(e)=={"type","t"} for e in events if e["type"]=="key")
    assert next(e for e in events if e["type"]=="cursor")["x"]==.25
    assert len([e for e in events if e["type"]=="cursor"]) in (6,7)
    with pytest.raises(FileExistsError):
        record(dest,duration=.1,source=Sampler())


@pytest.mark.parametrize("extra",["key","code","key_code","text","window_title"])
def test_reader_rejects_key_contents(tmp_path,extra):
    dest=tmp_path/"bad.jsonl"
    dest.write_text(json.dumps({"type":"start","t":0,"version":1})+"\n"+json.dumps({"type":"key","t":1,extra:"secret"})+"\n")
    with pytest.raises(ValueError,match="forbidden"):
        read_cursor(dest)


@pytest.mark.parametrize("value",[float("nan"),-1,0])
def test_invalid_duration_before_desktop_access(tmp_path,value):
    with pytest.raises(ValueError):
        record(tmp_path/"a",duration=value)


def test_model_roundtrip_and_version():
    p=plan(zooms=[Zoom(1,3,.4,.5,[{"kind":"activity","t":2}],.45)])
    assert ScreenPlan.from_dict(p.to_dict()).to_dict()==p.to_dict()
    with pytest.raises(ValueError): ScreenPlan.from_dict({**p.to_dict(),"version":2})
    with pytest.raises(ValueError): ScreenPlan.from_dict({**p.to_dict(),"max_zoom":float("nan")})


def test_freezedetect_tail_and_activity_confidence():
    assert parse_freezes("freeze_start: 2\nfreeze_end: 4\nfreeze_start: 8",10)==[{"start":2.,"end":4.},{"start":8.,"end":10}]
    z=zoom_candidates([], [{"kind":"activity","t":3,"x":.4,"y":.5,"confidence":.45}],[],10)
    assert z[0].confidence==.45


def test_linux_recorder_explains_fallback(monkeypatch):
    from myzing.screen import recorder
    monkeypatch.setattr(recorder.sys,"platform","linux")
    with pytest.raises(RuntimeError,match="not supported"):
        recorder.sampler()


def test_screen_cli_routing_and_optional_doctor(monkeypatch):
    from myzing import cli,doctor
    from myzing.plan import command
    monkeypatch.setattr("myzing.screen.command.run",lambda argv:23)
    assert command.run(["screen","demo.mp4"])==23
    assert "record-cursor" in cli._COMMANDS
    assert doctor.check_screen().name=="screen-cursor"


def test_small_activity_vetoes_global_freeze():
    idle=protected_idle([{"start":0,"end":10}],[{"type":"activity","t":5}],[],10)
    assert all(not s["start"]<5<s["end"] for s in idle)
    assert zoom_candidates([], [{"kind":"activity","t":5,"x":.6,"y":.5,"confidence":.45}],idle,10)


def test_windows_sampler_only_returns_a_key_boolean():
    from myzing.screen.recorder import WindowsSampler
    from types import SimpleNamespace
    class API:
        down={65}
        def GetCursorPos(self,p): return True
        def GetAsyncKeyState(self,k): return 0x8000 if k in self.down else 0
    import ctypes
    from ctypes import wintypes
    s=WindowsSampler.__new__(WindowsSampler)
    s.api=API();s.point=wintypes.POINT(2,3);s.previous_keys=set()
    assert s.poll()==(2,3,[],True)
    assert s.poll()==(2,3,[],False)
    s.api.down={65,66}
    assert s.poll()==(2,3,[],True)


def test_cursor_offset_order_and_stopped_contract(tmp_path):
    p=tmp_path/"log.jsonl"
    p.write_text('\n'.join(json.dumps(r) for r in [
        {"type":"start","version":1,"t":0}, {"type":"cursor","t":1,"x":.5,"y":.5},
        {"type":"stop","t":2,"samples":1}])+"\n")
    assert read_cursor(p,offset=-.5)[1][0]["t"]==.5
    with p.open('a') as handle: handle.write('{"type":"key","t":3}\n')
    with pytest.raises(ValueError,match="after stop"): read_cursor(p)


@pytest.mark.parametrize("box",[[0,.05,.25,.85],[.75,.05,.25,.85],[.05,0,.9,.2],[.05,.8,.9,.2]])
def test_whole_edge_element_fits_every_frame(box):
    z=Zoom(0,5,box[0]+box[2]/2,box[1]+box[3]/2,[{"kind":"click","t":1}],.95,box=box)
    p=plan(zooms=[z])
    cam=camera(p,720,1280)
    for key in cam["keys"]:
        x,y,w,h=crop_window(p,cam,key)
        assert x+box[2]*p.width*.05 <= box[0]*p.width
        assert y+box[3]*p.height*.05 <= box[1]*p.height
        assert x+w-box[2]*p.width*.05 >= (box[0]+box[2])*p.width
        assert y+h-box[3]*p.height*.05 >= (box[1]+box[3])*p.height


def test_distant_target_cuts_on_click_without_empty_travel():
    boxes=[[.02,.1,.2,.8],[.78,.1,.2,.8]]
    p=plan(zooms=[Zoom(0,3,.12,.5,[{"kind":"click","t":1}],.95,box=boxes[0]),
                  Zoom(3,7,.88,.5,[{"kind":"click","t":4.3}],.95,box=boxes[1])])
    cam=camera(p,720,1280)
    assert len(cam["cuts"])==1 and cam["cuts"][0]["t"]==pytest.approx(4.3)
    assert cam["cuts"][0]["reason"]=="distant-target"
    assert cam["cuts"][0]["estimated_pan_seconds"]>.6
    assert {round(k["x"],2) for k in cam["keys"]}=={.12,.88}
    assert all(k["shot"]==(0 if k["t"]<4.3 else 1) for k in cam["keys"])


def test_slow_pan_also_cuts_and_nearby_elements_share_view():
    from myzing.screen.framing import focus_groups
    a=Zoom(0,3,.2,.5,[{"kind":"dwell","t":1}],.75,box=[.15,.3,.1,.4])
    b=Zoom(3,6,.5,.5,[{"kind":"activity","t":4}],.45,box=[.45,.3,.1,.4])
    p=plan(zooms=[a,b],idle=[{"start":2.5,"end":3.9}])
    cam=camera(p,720,1280)
    assert cam["cuts"][0]["reason"]=="pan-over-0.6s"
    assert cam["cuts"][0]["moment"]=="idle-end"
    near=replace(b,box=[.2,.3,.1,.4])
    assert len(focus_groups([a,near]))==1

    # Both controls are readable separately; their union plus margins would
    # miss the floor. Keep both views instead of reporting a false source limit.
    controls=[Zoom(0,3,.31,.45,[{"kind":"click","t":1}],.95,box=[.2,.4,.22,.1]),
              Zoom(3,8,.37,.45,[{"kind":"click","t":4}],.95,box=[.26,.4,.22,.1])]
    fitted=camera(plan(zooms=controls,words=[{"text":"Build","start":1,"end":2}]),720,1280)
    assert len(fitted["shots"])==2
    assert all(24*s["source_enlargement"]>=s["phone_text_floor"]-1e-6 for s in fitted["shots"])


def test_tall_portrait_target_fills_stage_and_missing_bounds_show_source():
    p=plan(zooms=[Zoom(0,5,.5,.5,[{"kind":"activity","t":1}],.45,box=[.4,.02,.2,.96])])
    cam=camera(p,720,1280)
    assert cam["shots"][0]["picture"]["height"]>=.88*1280
    captioned=camera(replace(p,words=[{"text":"Build","start":1,"end":2}]),720,1280)
    picture=captioned["shots"][0]["picture"]
    assert picture["height"]>=.57*1280
    assert picture["y"]+picture["height"]<=.661*1280
    unknown=camera(plan(zooms=[replace(p.zooms[0],box=None)]),720,1280)
    assert any("bounds are unknown" in w for w in unknown["warnings"])
    assert all(k["window"][2]>=960 and k["window"][3]>=540 for k in unknown["keys"])


def test_region_probe_prefers_clicked_control_and_validates_box():
    from myzing.screen.regions import enclosing_region
    w,h=100,80
    pixels=bytearray([0,0,0]*w*h)
    for y in range(5,75):
        for x in range(55,95):
            color=(32,48,64) if not (70<=x<90 and 45<=y<60) else (64,224,160)
            pixels[(y*w+x)*3:(y*w+x)*3+3]=bytes(color)
    box=enclosing_region(pixels,w,h,(.8,.65))
    assert .65<=box[0]<=.70 and .90<=box[0]+box[2]<.95
    assert .50<=box[1]<=.5625 and .75<=box[1]+box[3]<.85
    z=Zoom(0,2,.8,.65,[{"kind":"click","t":1}],.95,box=box)
    assert Zoom.from_dict(z.to_dict()).box==box
    with pytest.raises(ValueError,match="inside"):
        Zoom.from_dict({**z.to_dict(),"box":[.9,.2,.2,.2]})


@pytest.mark.parametrize("duration",[2.,2.6,8.])
def test_dwell_protects_entire_span_and_long_hover_holds(duration):
    events=samples(1,1+duration)
    frozen=[{"start":0,"end":10}]
    idle=protected_idle(frozen,events,[],10)
    zooms=zoom_candidates(events,[],frozen,10)
    assert len(zooms)==1
    assert zooms[0].start==pytest.approx(1)
    assert zooms[0].end==pytest.approx(1+duration)
    assert all(s["end"]<=1 or s["start"]>=1+duration for s in idle)
    spans=time_segments(plan(zooms=zooms,idle=idle))
    assert all(s["speed"]==1 for s in spans if s["end"]>1 and s["start"]<1+duration)


def test_short_nearby_dwell_survives_without_duration_ranking():
    events=samples(0,.55,.2)+samples(.7,2.1,.8)
    zooms=zoom_candidates(events,[],[{"start":0,"end":10}],10)
    assert len(zooms)==2
    assert [n for z in zooms for n in (z.start,z.end)]==pytest.approx([0,.55,.7,2.1])
    assert all(z.evidence[0]["kind"]=="dwell" for z in zooms)


@pytest.mark.parametrize("velocity",[.05,.2,1.0])
def test_slow_pan_is_activity_not_dwell(velocity):
    events=[{"type":"cursor","t":i/60,"x":i/60*velocity,"y":.5} for i in range(60)]
    assert not dwell_candidates(events)
    idle=protected_idle([{"start":0,"end":5}],events,[],5)
    assert all(s["start"]>=1 for s in idle)


def test_subpixel_cursor_travel_vetoes_global_freeze():
    events=[{"type":"cursor","t":i/60,"x":.3+i*.00001,"y":.5} for i in range(300)]
    idle=protected_idle([{"start":0,"end":5}],events,[],5)
    assert idle==[]


def test_true_inactivity_can_still_be_compressed():
    assert protected_idle([{"start":0,"end":10}],[],[],10)==[
        {"start":.6,"end":9.4,"evidence":"freezedetect"}]


@pytest.mark.parametrize("kind",["click","key","activity"])
def test_each_input_protects_idle(kind):
    event={"type":kind,"t":3,"x":.2,"y":.3}
    idle=protected_idle([{"start":0,"end":6}],[event],[],6)
    assert all(s["end"]<=2.4 or s["start"]>=3.8 for s in idle)


def test_countdown_interrupt_removes_empty_log_and_reports_it(tmp_path):
    class Sampler:
        bounds=(0,0,800,600)
    def interrupt(_): raise KeyboardInterrupt
    dest=tmp_path/"cancelled.jsonl"
    messages=[]
    with pytest.raises(KeyboardInterrupt):
        record(dest,source=Sampler(),sleep=interrupt,output=messages.append)
    assert not dest.exists()
    assert any("removed the empty cursor log" in s for s in messages)
    dest.write_text("existing session")
    with pytest.raises(FileExistsError):
        record(dest,source=Sampler(),sleep=interrupt,output=messages.append)
    assert dest.read_text()=="existing session"


def test_interrupt_after_go_has_start_and_stop_markers(tmp_path):
    class Sampler:
        bounds=(0,0,800,600)
        def poll(self): raise KeyboardInterrupt
    dest=tmp_path/"stopped.jsonl"
    record(dest,countdown=0,source=Sampler(),output=lambda _:None)
    rows=[json.loads(s) for s in dest.read_text().splitlines()]
    assert [r["type"] for r in rows]==["start","stop"]


@pytest.mark.parametrize("x",[.01,.72])
def test_phone_floor_focus_width_and_complete_visible_words(x):
    from myzing.screen.regions import contains,intersects
    box=[x,.40,.18,.10]
    words=[[x+.01,.42,.15,.05],[x-.01,.27,.22,.04],[x+.19,.57,.12,.04]]
    z=Zoom(0,9,x+.08,.45,[{"kind":"click","t":1}],.95,box=box,box_evidence={"words":words})
    p=plan(zooms=[z],words=[{"text":"Run","start":1,"end":2}])
    cam=camera(p,720,1280)
    shot=cam["shots"][0]
    assert shot["picture"]["height"]>=.57*1280
    assert shot["picture"]["y"]+shot["picture"]["height"]<=.661*1280
    for k in cam["keys"]:
        view=k["window"]
        assert p.ui_text_px*shot["picture"]["width"]/view[2]>=shot["phone_text_floor"]-1e-6
        assert box[2]*p.width*shot["picture"]["width"]/view[2]>=.60*720-1e-6
        assert contains(view,[box[0]*p.width,box[1]*p.height,box[2]*p.width,box[3]*p.height])
        for word in words:
            b=[word[0]*p.width,word[1]*p.height,word[2]*p.width,word[3]*p.height]
            assert not intersects(view,b) or contains(view,b)
