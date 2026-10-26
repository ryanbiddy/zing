"""Preset contracts run in the lean no-FFmpeg environment, too."""

from dataclasses import replace, asdict
import pytest

from myzing.brief.models import Brief
from myzing.captions.grouping import STOPWORDS, choose_lines, group_words, join, token
from myzing.captions.metrics import font_asset, metrics
from myzing.captions.presets import apply_preset, line_width, rail_width, style_for
from myzing.captions.render import geometry
from myzing.captions.timing import clamp_words
from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip
from myzing.layout.framing import place_captions
from myzing.schemas import Word


def chars(texts):
    return len(join(texts))


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
    p.brief = Brief(caption_options={"size": 28})  # Feasible at this fixed draft size.
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
    lines=choose_lines(timed,chars,30,30,2)
    assert len(lines)==2
    assert all(line.split()[-1].lower() not in STOPWORDS for line in lines[:-1])
    assert max(map(len,lines)) <= 30


def test_sentence_pause_and_speaker_boundaries():
    timed=words("Good ideas. New stories. More fun.",.5)
    groups,_,_,_,_=group_words(timed,chars,100,preset="box",end=5)
    assert [" ".join(w.text for w in g) for g in groups] == ["Good ideas.","New stories.","More fun."]
    timed=words("Good ideas more fun",.5)
    timed[2:]=[replace(w,start=w.start+.5,end=w.end+.5) for w in timed[2:]]
    assert len(group_words(timed,chars,100,preset="box",end=5)[0])==2
    timed=[Word("Here",.25,.5),Word("is",.75,1),Word("our",1.25,1.5),Word("hook.",2,2.25)]
    groups,_,_,_,_=group_words(timed,chars,100,preset="punch",end=3)
    assert all(token(g[-1]) not in STOPWORDS for g in groups)
    groups,_,_,_,_=group_words(words("We go without more hope before new dawn"),chars,100,preset="punch",end=4)
    assert all(len(g)>1 and token(g[-1]) not in STOPWORDS for g in groups)
    assert {"without","within","before","after","unless","whether"} <= STOPWORDS
    timed = [Word("hand?",0,.56),Word("I'm",.78,1.02),Word("not",1.02,1.2)]
    groups,_,_,_,_ = group_words(timed,chars,100,preset="box",end=2)
    assert [join([w.text for w in g]) for g in groups] == ["hand?", "I'm not"]
    # An incomplete fragment of the next sentence is not a short utterance.
    timed = [Word("hand?",0,.56),Word("I'm",.78,1.02),Word("not",1.02,1.2),Word("scared.",1.2,1.6)]
    groups,_,_,_,_ = group_words(timed,chars,12,preset="punch",end=2)
    assert groups[0] == timed[:1]


def test_reading_rate_duration_and_no_overlap():
    timed=words("This clear story makes sense. Another short story works.",.45)
    timed = [replace(w,end=w.end-.05) for w in timed]
    groups,lines,starts,ends,warnings=group_words(timed,chars,42,preset="clean",portrait=False,end=8)
    assert not warnings
    for i,(g,ls,start,end) in enumerate(zip(groups,lines,starts,ends)):
        assert start <= g[0].start and end >= g[-1].end
        assert end-start >= 5/6
        assert sum(map(len,ls))/(end-start) <= 20
        if i+1 < len(groups):
            assert end <= starts[i+1]-2/30+1e-6


def test_impossible_reading_rate_is_reported_without_changing_word_times():
    timed=words("Very fast. More words.",.07)
    original=[asdict(w) for w in timed]
    _,_,_,_,warnings=group_words(timed,chars,100,preset="clean",end=.6)
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
        group_words(words("extraordinarily wide"),chars,5,preset="punch")


def test_vad_clamp_preserves_source_and_is_idempotent():
    original=[Word("Hello",.1,.8),Word("world",.9,1.5)]
    clamped,notes=clamp_words(original,[(.25,.7),(1.,1.4)])
    assert [(w.start,w.end) for w in clamped]==[(.25,.7),(1.,1.4)]
    assert [(w.start,w.end) for w in original]==[(.1,.8),(.9,1.5)]
    assert clamp_words(clamped,[(.25,.7),(1.,1.4)])[0] == clamped
    assert not notes
    assert clamp_words(original,[])[0] == original
    assert len(clamp_words(original,[])[1])==2


def test_aud1_transcript_provenance_survives_mapping_without_second_vad(monkeypatch):
    from myzing.captions.timing import already_clamped, mark_study_clamp
    from myzing.timing import transform_word
    p = plan("Two clear words")
    source = p.captions[0].words
    record = {"timing": {"method": "vad_edge_snap", "adjusted": [
        {"text": w.text, "start": w.start, "end": w.end} for w in source]}}
    marked = mark_study_clamp(source, record)
    assert all(already_clamped(w) for w in marked)
    mapped = [transform_word(w, w.start, w.end, "timeline_mapping", corrected=False) for w in marked]
    assert clamp_words(mapped, [(0.5, 0.6)])[0] == mapped
    p.captions[0].words = mapped
    monkeypatch.setattr("myzing.captions.timing.speech_intervals", lambda *a: pytest.fail("second VAD"))
    apply_preset(p, "clean")
    record["timing"]["status"] = "unavailable"
    assert mark_study_clamp(source, record) == source


@pytest.mark.parametrize("name", ["punch", "box", "clean"])
def test_short_cues_use_silence_and_merge_at_dialogue_cut(name):
    timed = [Word("We", .5, .8), Word("go.", .8, 1.1),
             Word("Yes.", 1.15, 1.29)]
    minimum = 5/6 if name == "clean" else .3
    groups, _, starts, ends, _ = group_words(timed, chars, 50, preset=name, start=0, end=2.4)
    assert all(e-s >= minimum-1e-6 for s, e in zip(starts, ends))
    assert any(e > g[-1].end for g, e in zip(groups, ends))
    # At a hard end, merge adjacent short sentences into a two-line Clean cue.
    if name == "clean":
        groups, _, starts, ends, _ = group_words(timed, chars, 50, preset=name, start=0, end=1.29)
        assert len(groups) == 1 and ends[0]-starts[0] >= minimum


@pytest.mark.parametrize("text", [
    "we sold 3,000 units for $5M with GPT-6 today",
    "Dr. Smith uses U.S.A. data and NASA tools",
    "we can't stop and won't stop till we're done",
    "hello , these new ideas work !",
    "supercalifragilisticexpialidocious tools work well",
    "visit https://example.com/research/very-long-article?q=100 today",
])
@pytest.mark.parametrize("name", ["punch", "box", "clean"])
def test_token_edges_preserve_text_and_measured_width(text, name):
    from myzing.captions.presets import line_widths
    p = plan(text)
    apply_preset(p, name, vad=False)
    place_captions(p, {}, {})
    assert all(token(c.words[-1]) not in STOPWORDS for c in p.captions[:-1])
    for c in p.captions:
        assert max(line_widths(c, metrics(c.font.path, c.font.sha256), c.style)) <= rail_width(p.width, p.height)
        assert len(c.text.splitlines()) <= (2 if name == "clean" else 1)
    original = "".join(text.split())
    actual = "".join(w.text for c in p.captions for w in c.words)
    assert actual == original


def test_unicode_clusters_and_cjk_breaks_without_optional_dependencies():
    from myzing.captions.presets import clusters, normalize_words, split_word
    assert clusters("a\u0301👩‍💻🇬🇧") == ["a\u0301", "👩‍💻", "🇬🇧"]
    pieces = normalize_words([Word("我们一起分享新的故事", 0, 3)])
    groups, lines, _, _, _ = group_words(pieces, lambda ts: len(join(ts))*10, 60, preset="punch", end=4)
    assert len(groups) > 1 and all(len(join([w.text for w in g])) <= 6 for g in groups)
    assert "".join(s for ls in lines for s in ls) == "我们一起分享新的故事"
    assert all(len(g) > 1 for g in groups)
    spans = split_word("👩‍💻👩‍💻", lambda s: len(clusters(s)) <= 1)
    assert spans == [(0, 3), (3, 6)]


@pytest.mark.parametrize("name", ["punch", "box", "clean"])
@pytest.mark.parametrize("w,h", [(360,640), (360,360), (640,360)])
def test_safe_rails_face_avoidance_and_phone_floor(name, w, h):
    from myzing.captions.presets import phone_floor
    from myzing.layout.types import Box, FaceTrack, Keyframe
    from myzing.layout.framing import centered_framing
    p = plan("New ideas make great stories", w, h)
    end = p.clips[0].timeline_end
    p.clips[0].framing = centered_framing("fit", w, h, w, h)
    face = FaceTrack("face", [Keyframe(0, Box(.3,.55,.4,.3)), Keyframe(end, Box(.3,.55,.4,.3))], 1.)
    apply_preset(p, name, vad=False)
    place_captions(p, {"a": [face]}, {"a": (w,h)})
    for c in p.captions:
        assert c.layout.overlap.safe
        assert c.style.size*c.layout.scale >= phone_floor(p, c.start, c.end, name)-1e-6
    assert len({(c.layout.box.center, c.layout.box.bottom, c.layout.scale) for c in p.captions}) == 1


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


def test_clean_minimum_at_cut_keeps_all_25_rendered_frames():
    import math
    from pathlib import Path
    from myzing.captions.render import compile_caption
    from myzing.render.font_files import private_font
    p = plan("Look,")
    p.clips[0].src_out = p.assets[0].duration = 5.
    p.captions[0].words = [Word("Look,",4.24,4.7)]
    apply_preset(p,"clean",vad=False)
    place_captions(p,{}, {})
    c = p.captions[0]
    data = Path(c.font.path).read_bytes()
    lines,_ = compile_caption(c,p,private_font(data)[0],data,150)
    def stamp(value):
        h,m,s = map(float,value.split(":"))
        return 3600*h+60*m+s
    starts = [math.ceil(stamp(line.split(",")[1])*30) for line in lines]
    ends = [math.ceil(stamp(line.split(",")[2])*30) for line in lines]
    assert min(starts) == 125 and max(ends) == 150


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
