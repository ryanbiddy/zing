"""Composite, caption, partial-delivery and usable-length regressions."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.composition import CompositionClip
from myzing.layout.types import Box, FaceTrack, Keyframe, TrackObservation
from myzing.schemas import Word
from test_studio import inputs


def track(name,box,confidence=.95):
    return FaceTrack(name,[Keyframe(0,box),Keyframe(12.533333,box)],confidence)


def test_generated_composite_stage_and_guards():
    from dogfood3_media import composite_frames, gray
    from myzing.layout.picture import detect_picture
    data = gray(composite_frames())
    result = detect_picture(data)
    assert result["confident"] and result["kind"] == "broadcast-composite", result
    assert result["confidence"] >= .8
    assert result["bounds_normalized"] == pytest.approx([3/320,20/180,247/320,140/180],abs=.02)
    assert result["chrome_regions"][0]["kind"] == "lower-third"
    assert result["sustained_motion_fraction"] >= .8
    assert not detect_picture(gray(composite_frames(frozen=True)))["confident"]
    assert not detect_picture(gray(composite_frames(split=True)))["confident"]
    # The existing bordered-picture detector has independent positive evidence
    # on this fixture; an uncertain inner-stage candidate must not erase it.
    assert detect_picture(gray(composite_frames(ui=True)))["confident"]
    # Existing matte/scenery/UI fixtures exercise the original path too.
    from test_dogfood2 import dark_chrome
    import numpy as np
    for kind in ("matte","desk","ui"):
        negative = dark_chrome()
        mask = np.ones((100,160),dtype=bool)
        mask[12:80,16:144] = False
        negative[:,mask] = 8 if kind == "matte" else np.random.default_rng(7).integers(0,200,mask.sum()) if kind == "desk" else 18
        if kind == "ui":
            negative[:,3:8,12:32] = 240
            negative[:,87:91,20:35] = 200
        assert not detect_picture(negative)["confident"], kind


def test_stage_framing_excludes_secondary_face_and_focuses_persistent_speaker():
    from myzing.layout.picture import select_picture_framing
    primary = track("face-main",Box(.36,.22,.19,.38))
    secondary = track("face-guest",Box(.91,.55,.08,.18))
    tiny = track("face-background",Box(.26,.48,.06,.08),.65)
    tiny = replace(tiny, keyframes=[Keyframe(1, tiny.keyframes[0].box), Keyframe(1.3, tiny.keyframes[0].box)])
    hog = track("person-hog",Box(.60,.29,.25,.70),.5)
    hog.observations.append(TrackObservation(0,hog.keyframes[0].box,detector="hog-fallback"))
    picture = {"confident":True,"confidence":.86,"kind":"broadcast-composite","bounds_pixels":[18,120,1494,838]}
    clip = CompositionClip("source",0,12.533333,0,id="clip",asset_id="a")
    f = select_picture_framing("auto",1920,1080,720,1280,clip,[primary,secondary,tiny,hog],picture=picture)
    assert .50 <= f.assessments[-1].sharp_height_share <= .70
    assert f.assessments[-1].enlargement <= 2.5
    assert f.picture["subject_selection"]["main_face"] == primary.id
    assert secondary.id in f.picture["subject_selection"]["outside_stage_tracks"]
    # Tracks from another trim cannot turn this shot into a multi-person shot.
    future = FaceTrack("face-future",[Keyframe(5,Box(.02,.22,.19,.38)),Keyframe(6,Box(.02,.22,.19,.38))],.99)
    early = select_picture_framing("auto",1920,1080,720,1280,replace(clip,src_out=4.5),
                                    [primary,secondary,tiny,hog,future],picture=picture)
    assert early.picture["subject_selection"]["focused"]
    # Two substantial stage speakers must both remain constraints.
    peer = track("face-peer",Box(.02,.22,.19,.38))
    two = select_picture_framing("auto",1920,1080,720,1280,clip,[primary,peer,secondary],picture=picture)
    assert not two.picture["subject_selection"]["focused"]
    assert two.assessments[-1].subject_coverage >= .98


@pytest.mark.parametrize("preset",["punch","box","clean"])
def test_timed_numeric_runs_never_split_cues_lines_or_presets(preset):
    from myzing.captions.grouping import group_words, join, choose_lines
    from myzing.captions.presets import apply_preset
    from test_caption2 import plan
    tokens = ["Last","year","was","$3",",000,","at","first."]
    words = [Word(t,i*.31,(i+1)*.31) for i,t in enumerate(tokens)]
    measure = lambda texts: len(join(texts))
    groups,lines,*_ = group_words(words,measure,18,preset=preset,portrait=False,end=3)
    assert any(words[3] in g and words[4] in g for g in groups)
    assert "$3,000," in " ".join(line for ls in lines for line in ls)
    lines = choose_lines(words,measure,24,30,2)
    assert "$3,000," in " ".join(lines)
    p = plan("placeholder",640,360)
    p.clips[0].src_out = p.assets[0].duration = 3
    p.captions[0].words = words
    p.captions[0].start,p.captions[0].end = 0,words[-1].end
    apply_preset(p,preset,vad=False)
    containing = [c for c in p.captions if "$3" in c.text]
    assert len(containing) == 1 and "$3,000," in containing[0].text
    assert [(w.text,w.start,w.end) for c in p.captions for w in c.words] == [(w.text,w.start,w.end) for w in words]


def test_oversize_numeric_run_is_refused_without_digit_splitting():
    from myzing.captions.presets import fit_long_words
    from myzing.captions.grouping import join
    with pytest.raises(ValueError,match="joined number"):
        fit_long_words([Word("$12345678901234567890",0,1)],str,lambda ts:len(join(ts)),6)


def test_numeric_pause_phone_grouping_and_legacy_wrap_keep_whole_run():
    from myzing.captions.grouping import group_words,join
    from myzing.layout.readability import phone_word_groups
    from myzing.match.caption_fit import _wrap
    words=[Word(t,i*.5,i*.5+.2) for i,t in enumerate(['Last','year','was','$3',',000,','at','first'])]
    words[4:]=[replace(w,start=w.start+.6,end=w.end+.6) for w in words[4:]]
    for groups in (phone_word_groups(words),group_words(words,lambda ts:len(join(ts)),20,preset='box',end=5)[0]):
        assert any(words[3] in group and words[4] in group for group in groups)
    assert '$3,000,' in _wrap([w.text for w in words],8)


@pytest.mark.parametrize("blocked",[False,True])
@pytest.mark.parametrize("region_kind",["lower-third","secondary-tile"])
def test_landscape_caption_moves_above_card_or_reports_readable_limit(blocked,region_kind):
    from test_caption2 import plan
    from myzing.captions.presets import apply_preset, phone_floor
    from myzing.layout.framing import centered_framing, place_captions
    p = plan("This useful caption fits",1280,720)
    f = centered_framing("fit",1280,720,1280,720)
    f.picture = {"chrome_regions":[{"kind":region_kind,"bounds_normalized":
                                   [0,0,1,1] if blocked else [.05,.78,.9,.18]}]}
    p.clips[0].framing = f
    face = track("face-main",Box(.3,.12,.35,.43))
    apply_preset(p,"box",vad=False)
    place_captions(p,{"a":[face]},{"a":(1280,720)})
    for c in p.captions:
        if blocked:
            assert not c.layout.overlap.safe
            assert "No readable caption band fits" in c.layout.warnings[0]
            assert region_kind in c.layout.warnings[0]
        else:
            assert c.layout.overlap.safe
            assert .55 <= c.layout.box.y < c.layout.box.bottom <= .78
            assert c.style.size*c.layout.scale >= phone_floor(p,c.start,c.end,"box")


def test_delivery_continues_after_failed_shape_and_records_next_step(tmp_path,monkeypatch):
    from test_caption2 import plan
    from myzing.render import deliveries
    shapes = {"16:9":plan(width=640,height=360),"1:1":plan(width=360,height=360),"9:16":plan(width=360,height=640)}
    monkeypatch.setattr(deliveries,"delivery_plans",lambda *a,**k:(shapes,{"resolution":{s:{} for s in shapes}}))
    seen = []
    def render(p,video,**kwargs):
        seen.append((p.width,p.height))
        video.write_bytes(b"generated test placeholder")
        if p.width > p.height:
            raise ValueError("caption fixture: no readable caption band fits")
        return SimpleNamespace(warnings=[],audio_measurements=None)
    monkeypatch.setattr(deliveries,"render_composition",render)
    result = deliveries._render_deliveries(shapes["16:9"],tmp_path/"out.mp4",tmp_path,list(shapes),tmp_path/"deliveries.json",
                                            tmp_path,None,None,None,"ffmpeg","ffprobe",True)
    assert len(seen) == 3 and result["status"] == "partial" and result["ready"] == 2
    failed = result["deliveries"]["16:9"]
    assert failed["status"] == "failed" and "video" not in failed
    assert not (tmp_path/"out.16x9.mp4").exists()
    assert "caption" in failed["error"] and "clean" in failed["next_step"]
    assert all(Path(result["deliveries"][s]["video"]).is_file() for s in ("1:1","9:16"))
    assert json.loads((tmp_path/"deliveries.json").read_text())["status"] == "partial"


def test_shape_adaptation_failure_keeps_remaining_plans(tmp_path,monkeypatch):
    from test_caption2 import plan
    from myzing.render import deliveries
    source=tmp_path/"generated-placeholder.mp4"
    source.write_bytes(b"metadata-only unit fixture")
    p=plan(width=640,height=360)
    p.assets[0].path=p.clips[0].src=str(source)
    p.captions=[]
    monkeypatch.setattr(deliveries,"_verify",lambda *a:None)
    original=deliveries.adapt_plan
    def adapt(p,w,h,*args,**kwargs):
        if w>h:
            raise ValueError("caption band unavailable in landscape")
        return original(p,w,h,*args,**kwargs)
    monkeypatch.setattr(deliveries,"adapt_plan",adapt)
    measured={deliveries._key(source):{"display_dimensions":(640,360),"tracks":[],"cuts":[],
                                       "picture":{},"ranges":[(0,2)],"warnings":[]}}
    plans,evidence=deliveries.delivery_plans(p,["16:9","1:1","9:16"],tmp_path,
                                           measured=measured,continue_on_error=True,short_side=360)
    assert set(plans)=={"1:1","9:16"}
    assert evidence["failures"]["16:9"]["status"]=="failed"
    assert evidence["failures"]["16:9"]["next_step"]


def test_decode_timeout_keeps_other_studio_deliveries(tmp_path,monkeypatch):
    from subprocess import TimeoutExpired
    from test_caption2 import plan
    from myzing.studio import adapters
    p=plan(width=640,height=360)
    saved=tmp_path/"plan.json"
    saved.write_text(p.to_json(),encoding="utf-8")
    monkeypatch.setattr(adapters,"load_edit",lambda *a:p)
    shapes=["16:9","1:1","9:16"]
    rows={shape:{"status":"ready","video":str(tmp_path/(shape.replace(":","x")+".mp4")),"plan":str(saved)} for shape in shapes}
    for row in rows.values():
        Path(row["video"]).write_bytes(b"generated decode placeholder")
    monkeypatch.setattr("myzing.render.deliveries.render_deliveries",lambda *a,**k:{"deliveries":rows})
    checked=[]
    def decode(path,plan):
        checked.append(path.name)
        if path.name=="16x9.mp4":
            raise TimeoutExpired("ffprobe",180)
        return {"full_decode":True}
    monkeypatch.setattr("myzing.match.evidence.decode",decode)
    result=adapters.deliver(saved,tmp_path/"out.mp4",shapes)
    assert len(checked)==3 and result["status"]=="partial" and result["ready"]==2
    failed=result["deliveries"]["16:9"]
    assert "timed out" in failed["error"] and failed["next_step"] and "video" not in failed
    assert not (tmp_path/"16x9.mp4").exists()
    assert (tmp_path/"1x1.mp4").is_file() and (tmp_path/"9x16.mp4").is_file()


def test_usable_default_uses_same_whole_word_trims_as_selection():
    from myzing.director.models import ClipStudy, PlanningShortage
    from myzing.director.selection import usable_length,candidates,Envelope
    from myzing.schemas import Shot
    clip = ClipStudy("a","a.mp4","sha",12.533,"ready",shots=[Shot(0,0,12.533)],
                     dead_air=[{"start":0,"end":.3},{"start":3,"end":3.2},{"start":7,"end":7.4},{"start":12.177,"end":12.533}])
    usable = usable_length([clip],{}, {})
    assert usable == pytest.approx(11.277)
    style = Envelope(2,None,None,3,0,"lower",{})
    assert candidates([clip],{}, {},style,usable)[0]
    with pytest.raises(PlanningShortage,match="12.533"):
        candidates([clip],{}, {},style,12.533)


def test_usable_length_retains_pause_inside_protected_clause():
    from myzing.director.models import ClipStudy
    from myzing.director.selection import usable_length,candidates,choose,Envelope
    from myzing.schemas import Shot
    clip = ClipStudy("a","generated.mp4","sha",12.533,"ready",shots=[Shot(0,0,12.533)],
                     words=[Word("A",.08,.7),Word("complete",.74,2),Word("sentence.",2,4.34),
                            Word("Another",4.976,5.4),Word("sentence.",5.4,6.44),
                            Word("Third",7.22,8),Word("sentence.",8,9.04),
                            Word("Fourth",9.38,9.7),Word("sentence.",9.7,10.39),
                            Word("Final",10.39,11),Word("sentence.",11,12.3)],
                     dead_air=[{"start":.7,"end":.74},{"start":4.5,"end":4.976},
                               {"start":6.6,"end":7},{"start":9.04,"end":9.38}])
    target = usable_length([clip],{}, {})
    assert target == pytest.approx(11.317)
    style = Envelope(12.533,None,None,3,0,"lower",{"shot_durations":[12.533]})
    pool,required = candidates([clip],{}, {},style,target)
    chosen = choose(pool,required,[clip],style,target,30,0)
    assert chosen and any(c.start < .7 and c.end >= 4 for c in chosen["A"])
    assert sum(c.duration for c in chosen["A"]) == pytest.approx(target,abs=2/30)


@pytest.mark.parametrize("count,noun",[(1,"draft"),(2,"drafts")])
def test_creator_pluralizes_distinct_drafts(tmp_path,count,noun):
    from myzing.studio.presentation import creator_summary
    rows = {f"{label}.1x1":{"status":"ready","video":"out.mp4"} for label in "AB"[:count]}
    result = {"project":str(tmp_path),"status":"ready","warnings":["VARIETY limit"],"result":{"drafts":rows}}
    notes = creator_summary(result,{}, {})["notes"]
    assert f"delivered {count} distinct {noun} (" in notes[0]
    assert "draft(s)" not in str(notes)
    result["result"]["shortages"] = [{"code":"edit_constraints"}]
    assert "not enough usable moments" not in str(creator_summary(result,{}, {}))


@pytest.mark.parametrize("default",[True,False])
def test_reference_director_defaults_to_usable_length_but_honors_explicit_target(tmp_path,monkeypatch,zing_workspace,default):
    from tools.plan_examples import example_project,write_json
    from myzing.director import api
    from myzing.director.models import ClipStudy
    from myzing.project.api import load_project
    from myzing.schemas import Shot
    from myzing.style_recipe import StyleRecipe,ObservationProvenance
    from myzing.studio.presentation import creator_summary
    root,_,_=example_project(tmp_path/'project')
    manifest=load_project(root)
    asset=manifest.assets[0]
    clip=ClipStudy(asset.id,asset.path,asset.sha256,12.533,'ready',shots=[Shot(0,0,12.533)],
                   dead_air=[{'start':0,'end':1.256}])
    monkeypatch.setattr(api,'inventory',lambda *a,**k:([clip],[]))
    monkeypatch.setattr('myzing.layout.framing.analyze_subjects',lambda *a,**k:([],[]))
    monkeypatch.setattr('myzing.layout.picture.analyze_picture',lambda *a,**k:{'confident':False,'reason':'fixture'})
    brief=json.loads((root/'brief.json').read_text())
    write_json(root/'brief.json',{**brief,'target_length_seconds':12.533,'must_keep':[],'forbidden':[],
                                 'caption_language':'none','caption_mode':'none','music':{'source':'none'}})
    recipe=StyleRecipe(ObservationProvenance('generated fixture',detector='test'))
    write_json(root/'recipe.json',recipe.to_dict())
    result=api.plan_drafts(root,root/'recipe.json',root/'plans',studio_options={'target_length_mode':'usable'} if default else {})
    if default:
        assert result['status']=='ready',result
        assert result['summary']['target_length']['target_seconds']==pytest.approx(11.277)
        assert all(json.loads(Path(path).read_text())['brief']['target_length_seconds']==pytest.approx(11.277)
                   for path in result['plans'].values())
        summary=creator_summary({'project':str(root),'status':'ready','warnings':result['summary']['warnings'],
                                 'result':{'shortages':result['summary']['shortages'],
                                           'target_length':result['summary']['target_length']}},{'path':'a'}, {})
        assert 'not enough usable moments' not in str(summary)
    else:
        assert result['status']=='shortage'
        assert result['summary']['shortages'][0]['code']=='target_length'


@pytest.mark.parametrize("override",[False,True])
def test_reference_resume_only_overrides_default_when_seconds_are_supplied(inputs,tmp_path,monkeypatch,override):
    from test_studio import complete
    from myzing.studio import command
    from myzing.studio.models import Session,save_session
    answers,_ = complete("a",inputs)
    answers["length_mode"] = "usable"
    save_session(inputs["project"],Session(answers=answers))
    supplied = tmp_path/"override.json"
    supplied.write_text(json.dumps({"length":20} if override else {}))
    seen = []
    def execute(a,**kwargs):
        seen.append(a)
        return {"ok":True,"status":"ready","outputs":[]}
    monkeypatch.setattr("myzing.studio.execute.run_confirmed",execute)
    assert command.run(["--resume",inputs["project"],"--answers",str(supplied),"--yes","--json"]) == 0
    assert (seen[0].get("length_mode") == "usable") is (not override)
    if override:
        assert seen[0]["length"] == 20
