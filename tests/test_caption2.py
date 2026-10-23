"""Preset contracts run in the lean no-FFmpeg environment, too."""

from dataclasses import replace, asdict
import pytest

from myzing.brief.models import Brief
from myzing.captions.grouping import STOPWORDS, choose_lines, group_words, token
from myzing.captions.metrics import font_asset, metrics
from myzing.captions.presets import apply_preset, line_width, rail_width, style_for
from myzing.captions.render import geometry
from myzing.captions.timing import clamp_words
from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip
from myzing.layout.framing import place_captions
from myzing.schemas import Word


def words(text, step=.4):
    return [Word(t,.2+i*step,.2+i*step+step-.05) for i,t in enumerate(text.split())]


def plan(text="Fresh ideas make great stories", width=360, height=640):
    timed = words(text)
    duration = timed[-1].end+1
    return Composition(assets=[AssetRef("a","missing.mp4",None,duration)],
        clips=[CompositionClip("missing.mp4",0,duration,0,id="shot",asset_id="a")],
        width=width,height=height,
        captions=[CompositionCaption(text,.2,timed[-1].end,id="source",words=timed,all_caps=False)])


@pytest.mark.parametrize("name", ["punch","box","clean"])
def test_preset_roundtrip_and_width_scaling(name):
    assert Brief.from_dict(Brief(caption_mode=name).to_dict()).caption_mode == name
    from myzing.mcp_server import h_brief_questions
    assert name in str(h_brief_questions())
    assert style_for(name,1080).size == pytest.approx(style_for(name,360).size*3)
    p=plan()
    apply_preset(p,name,vad=False)
    place_captions(p,{}, {})
    assert Composition.from_dict(p.to_dict()) == p
    assert len({(c.layout.box.center[0],c.layout.box.bottom,c.layout.scale) for c in p.captions}) == 1
    assert len({c.style.size for c in p.captions}) == 1
    for c in p.captions:
        face=metrics(c.font.path,c.font.sha256)
        assert max(line_width(s,face,c.style,name) for s in c.text.splitlines()) <= rail_width(p.width,p.height)
        assert len(c.text.splitlines()) <= (2 if name == "clean" else 1)
    apply_preset(p,"clean",vad=False)
    assert [w.text for c in p.captions for w in c.words] == "Fresh ideas make great stories".split()


@pytest.mark.parametrize("name",["punch","box"])
def test_no_orphans_or_stopword_ends_when_partition_is_feasible(name):
    p=plan("we go a way with big hopes and new goals")
    apply_preset(p,name,vad=False)
    assert [w.text.lower() for c in p.captions for w in c.words] == "we go a way with big hopes and new goals".split()
    assert all(len(c.words) > 1 for c in p.captions)
    assert all(token(c.words[-1]) not in STOPWORDS for c in p.captions[:-1])
    assert all(len(c.words) <= (3 if name == "punch" else 4) for c in p.captions)


def test_font_metrics_are_glyph_advances_not_character_count():
    f=font_asset("punch"); m=metrics(f.path,f.sha256)
    assert m.width("WWW",97) > m.width("iii",97)*2
    assert m.width("office",97) == pytest.approx(sum(m.width(c,97) for c in "office"))
    assert m.ascent > m.cap > 0 > m.descent


def test_clean_break_protects_articles_and_prefers_balance():
    timed=words("We share the bright ideas with our friends today")
    lines=choose_lines(timed,len,30,30,2)
    assert len(lines)==2
    assert all(line.split()[-1].lower() not in STOPWORDS for line in lines[:-1])
    assert max(map(len,lines)) <= 30


def test_sentence_pause_and_speaker_boundaries():
    timed=words("Good ideas. New stories. More fun.",.5)
    groups,_,_,_=group_words(timed,len,100,preset="box",end=5)
    assert [" ".join(w.text for w in g) for g in groups] == ["Good ideas.","New stories.","More fun."]
    timed=words("Good ideas more fun",.5)
    timed[2:]=[replace(w,start=w.start+.5,end=w.end+.5) for w in timed[2:]]
    assert len(group_words(timed,len,100,preset="box",end=5)[0])==2
    timed=[Word("Here",.25,.5),Word("is",.75,1),Word("our",1.25,1.5),Word("hook.",2,2.25)]
    groups,_,_,_=group_words(timed,len,100,preset="punch",end=3)
    assert all(token(g[-1]) not in STOPWORDS for g in groups)
    groups,_,_,_=group_words(words("We go without more hope before new dawn"),len,100,preset="punch",end=4)
    assert all(len(g)>1 and token(g[-1]) not in STOPWORDS for g in groups)
    assert {"without","within","before","after","unless","whether"} <= STOPWORDS


def test_reading_rate_duration_and_no_overlap():
    timed=words("This clear story makes sense. Another short story works.",.45)
    timed = [replace(w,end=w.end-.05) for w in timed]
    groups,lines,ends,warnings=group_words(timed,len,42,preset="clean",portrait=False,end=8)
    assert not warnings
    for i,(g,ls,end) in enumerate(zip(groups,lines,ends)):
        assert end-g[0].start >= 5/6
        assert sum(map(len,ls))/(end-g[0].start) <= 20
        if i+1 < len(groups):
            assert end <= groups[i+1][0].start-2/30+1e-6


def test_impossible_reading_rate_is_reported_without_changing_word_times():
    timed=words("Very fast. More words.",.07)
    original=[asdict(w) for w in timed]
    _,_,_,warnings=group_words(timed,len,100,preset="clean",end=.6)
    assert any("reading limit" in w for w in warnings)
    assert original==[asdict(w) for w in timed]
    p=plan("Very fast. More words.")
    p.captions[0].words=timed
    p.captions[0].start=timed[0].start
    p.captions[0].end=timed[-1].end
    apply_preset(p,"clean",vad=False)
    assert all(c.start <= c.words[0].start for c in p.captions)


def test_width_failure_is_explicit_and_never_wraps_pop():
    with pytest.raises(ValueError,match="cannot fit"):
        group_words(words("extraordinarily wide"),len,5,preset="punch")


def test_vad_clamp_preserves_source_and_is_idempotent():
    original=[Word("Hello",.1,.8),Word("world",.9,1.5)]
    clamped,notes=clamp_words(original,[(.25,.7),(1.,1.4)])
    assert [(w.start,w.end) for w in clamped]==[(.25,.7),(1.,1.4)]
    assert [(w.start,w.end) for w in original]==[(.1,.8),(.9,1.5)]
    assert clamp_words(clamped,[(.25,.7),(1.,1.4)])[0] == clamped
    assert not notes
    assert clamp_words(original,[])[0] == original
    assert len(clamp_words(original,[])[1])==2


def test_clean_second_line_grows_up_from_same_metric_baseline():
    p=plan("A clear story makes sense",640,360)
    apply_preset(p,"clean",vad=False); place_captions(p,{}, {})
    c=p.captions[0]
    one=geometry(c,640,360)
    c.text="A clear story\nmakes sense"
    two=geometry(c,640,360)
    assert one["baseline"]==two["baseline"]
    assert two["slots"][-1]["baseline"]==one["slots"][-1]["baseline"]
    assert two["slots"][0]["baseline"] < two["slots"][-1]["baseline"]


def test_legacy_caption_serialization_has_no_preset():
    assert "preset" not in plan().captions[0].to_dict()
    assert "caption_mode" not in Brief().to_dict()


@pytest.mark.parametrize("name",["punch","box","clean"])
def test_delivery_regroups_for_new_width(name,monkeypatch):
    from myzing.layout.delivery import adapt_plan
    p=plan(); apply_preset(p,name,vad=False)
    monkeypatch.setattr("myzing.layout.picture.select_picture_framing",lambda *a,**k:None)
    adapted=adapt_plan(p,640,360,{"a":(640,360)},{},requested="fit")
    assert all(c.preset==name for c in adapted.captions)
    assert all(c.style.size <= style_for(name,640).size for c in adapted.captions)


@pytest.mark.parametrize("name",["punch","box","clean"])
def test_draft_planner_uses_and_reports_final_preset_groups(name,tmp_path,zing_workspace):
    import json
    from pathlib import Path
    from statistics import median
    from tools.plan_examples import example_project, write_json
    from myzing.director import plan_drafts
    from myzing.director.plans import REPORT_PREFIX
    from myzing.delivery_options import apply_plan

    root,_,_=example_project(tmp_path/"project")
    brief=json.loads((root/"brief.json").read_text(encoding="utf-8"))
    write_json(root/"brief.json",{**brief,"caption_mode":name})
    result=plan_drafts(root,root/"recipe.json",root/"plans",seed=17)
    assert result["status"]=="ready",result
    for path in result["plans"].values():
        p=Composition.from_json(Path(path).read_text(encoding="utf-8"))
        assert p.captions and all(c.preset==name and c.layout for c in p.captions)
        evidence=json.loads(next(w[len(REPORT_PREFIX):] for w in p.warnings if w.startswith(REPORT_PREFIX)))
        assert evidence["match"]["words_visible"]["planned"]==median(len(c.words) for c in p.captions)
        apply_plan(p,{"caption_options":{"size":90}})
        for c in p.captions:
            face=metrics(c.font.path,c.font.sha256)
            assert max(line_width(s,face,c.style,name) for s in c.text.splitlines()) <= rail_width(p.width,p.height)
