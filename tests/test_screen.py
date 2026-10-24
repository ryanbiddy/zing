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


@pytest.mark.parametrize("duration,want",[(.3,0),(.45,1),(1.8,1),(2.6,1),(3,0)])
def test_openscreen_dwell_duration(duration,want):
    assert len(dwell_candidates(samples(0,duration)))==want


def test_dwell_gap_and_stronger_candidate_spacing():
    assert not dwell_candidates([{"type":"cursor","t":0,"x":.2,"y":.2},{"type":"cursor","t":1,"x":.2,"y":.2}])
    result=dwell_candidates(samples(0,.6)+samples(.8,1.8,.7)+samples(3.5,4.2))
    assert len(result)==2 and result[0]["x"]==pytest.approx(.7)


def test_merge_clicks_with_dwell_and_idle_no_zoom():
    events=samples(1,2)+[{"type":"click","t":1.7,"x":.31,"y":.4}]
    zooms=zoom_candidates(events,[],[],10)
    assert len(zooms)==1 and {e['kind'] for e in zooms[0].evidence}=={"click","dwell"}
    assert zooms[0].confidence==.95
    assert not zoom_candidates(events,[],[{"start":0,"end":4}],10)
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
def test_spring_camera_motion_and_target_coverage(aspect):
    p=plan(zooms=[Zoom(0,3,.3,.45,[{"kind":"click","t":1}],.95),Zoom(3.2,7,.65,.5,[{"kind":"click","t":4.5}],.95)])
    cam=camera(p,*dimensions(aspect,360))
    for t,x,y in [(1.2,.3,.45),(5,.65,.5)]:
        k=min(cam["keys"],key=lambda k:abs(k["t"]-t))
        a,b,w,h=crop_window(p,cam,k)
        assert a+.05*w <= x*p.width <= a+.95*w
        assert b+.05*h <= y*p.height <= b+.95*h
    for axis,vel,acc in [("x",.65,4),("y",.65,4),("zoom",1.5,6)]:
        velocities=[(b[axis]-a[axis])*p.fps for a,b in zip(cam["keys"],cam["keys"][1:])]
        assert max(map(abs,velocities))<=vel+1e-6
        assert max(abs(b-a)*p.fps for a,b in zip(velocities,velocities[1:]))<=acc+.05
    # Validate the visible camera, including frame-edge clamping, not merely
    # the unconstrained spring state.
    boxes=[crop_window(p,cam,k) for k in cam["keys"]]
    for values in ([(x+w/2)/p.width for x,y,w,h in boxes],[(y+h/2)/p.height for x,y,w,h in boxes]):
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
    assert cam["zoom_cap"]==1
    assert any("already exceeds 2.5x" in n for n in cam["warnings"])


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
