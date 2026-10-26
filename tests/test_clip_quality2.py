"""Vertical geometry, cropped caption bands and display-only stutter rules."""
from copy import deepcopy
from dataclasses import replace

import pytest

from myzing.schemas import Word, Shot
from myzing.composition import Composition, CompositionClip, CompositionCaption, CaptionStyle, AssetRef
from myzing.brief.models import Brief
from myzing.layout.types import Box, FaceTrack, Keyframe, EventLayout, OverlapCheck
from myzing.layout.framing import centered_framing
from myzing.director.models import ClipStudy
from myzing.director.selection import Candidate
from myzing.director.vertical_quality import VerticalQuality, measurements


@pytest.mark.parametrize('words,expected', [
    (['we','We'],['we']), (['we','We.'],['we.']), (['WE','we','We'],['WE']),
    (['we,','We'],['we,','We']), (['we.','We'],['we.','We']),
    (['we','-','We'],['we','-','We']), (['we','"We'],['we','"We']),
    (['that','That'],['that','That']), (['had','Had'],['had','Had'])])
def test_stutters_preserve_punctuation_grammar_and_inputs(words, expected):
    from myzing.captions.stutters import collapse
    source = [Word(t,i*.2,i*.2+.1) for i,t in enumerate(words)]
    before = deepcopy(source)
    result = collapse(source)
    assert [w.text for w in result] == expected
    assert result[0].start == source[0].start and result[-1].end == source[-1].end
    assert source == before


@pytest.mark.parametrize('gap,count',[(.35,1),(.3501,2),(-.01,2)])
def test_stutter_gap_boundary(gap,count):
    from myzing.captions.stutters import collapse
    assert len(collapse([Word('we',0,.2),Word('We',.2+gap,.6+gap)])) == count


def face(start,end,height=.3,x=.43):
    b = Box(x,.2,.12,height)
    return FaceTrack('face-1',[Keyframe(start,b),Keyframe(end,b)],confidence=.95)


def candidate(start,end):
    return Candidate('a','hash',start,end,0,2,0,'Hello world.',False,True)


def quality(rows, required=()):
    q = VerticalQuality([],{}, {}, Brief(), [], required)
    q.rows = {'a':rows}
    return q


def row(a,b,share=.3,bad=False,close=True):
    return dict(start=a,end=b,face_height_share=share,required_enlargement=1.,bad=bad,close=close)


@pytest.mark.parametrize('aspect,size',[('9:16',(1080,1920)),('4:5',(1080,1350))])
def test_face_size_and_enlargement_use_source_pixels(aspect,size):
    from myzing.composition.aspects import dimensions
    assert dimensions(aspect) == size
    clip = CompositionClip('x',0,3,0,id='c',asset_id='a')
    framing = centered_framing('fill',1280,720,*size)
    tiny = measurements(clip,framing,[face(0,3,.05)],*size)
    close = measurements(clip,framing,[face(0,3,.3)],*size)
    assert all(r['bad'] for r in tiny)
    assert all(r['close'] for r in close)
    assert tiny[0]['required_enlargement'] == pytest.approx(.1*size[1]/36)


def test_held_speaker_wins_over_larger_bystander():
    from myzing.composition.speakers import SpeakerTurn
    clip = CompositionClip('x',0,3,0,id='c',asset_id='a')
    framing = centered_framing('fill',1280,720,1080,1920)
    # Use the contract's declared fields; selected identity must not silently
    # become the taller bystander.
    turn = SpeakerTurn(start=0,end=3,speaker='s',face_track_id='speaker',confidence=.9,method='fixture')
    framing.speaker_turns = [turn]
    small = replace(face(0,3,.05),id='speaker')
    rows = measurements(clip,framing,[face(0,3,.3),small],1080,1920)
    assert all(r['bad'] for r in rows)


def test_opening_gate_spans_multiple_candidates_and_wide_run_is_bounded():
    q = quality([row(0,1),row(1,2,.12,False,False),row(2,3),row(3,4,.05,True,False)])
    assert not q.valid([candidate(0,1),candidate(1,2)])
    assert q.valid([candidate(0,1),candidate(2,3),candidate(3,4)])
    q.rows['a'].append(row(4,4.01,.05,True,False))
    assert not q.valid([candidate(0,1),candidate(2,3),candidate(3,4.01)])


def test_wide_trims_are_clause_safe_and_must_keep_survives():
    words = [Word('First.',0,1),Word('Wide.',1,3),Word('Last.',3,4)]
    study = ClipStudy('a','x','hash',4,'ready',words=words,shots=[Shot(0,0,4)])
    rows = [row(0,1),row(1,3,.05,True,False),row(3,4)]
    q = quality(rows)
    pool,_ = q.filter([candidate(0,4)],[study],())
    assert [(c.start,c.end) for c in pool] == [(0,1),(3,4)]
    assert [c.text for c in pool] == ['First.','Last.']
    assert q.actions and all(c.close_share == 1 for c in pool)
    required = [('a',1,3)]
    q = quality(rows,required)
    pool,_ = q.filter([replace(candidate(0,4),covers=1)],[study],required)
    assert [(c.start,c.end) for c in pool] == [(0,4)]
    assert q.warnings[0].startswith('Vertical must_keep retained')


def caption_plan(mode='reference'):
    box = Box(.1,.58,.7,.12)
    captions = [CompositionCaption('Hello',i,i+1,id=f'c{i}',word_timed=False,style=CaptionStyle(60,outline_width=1),
        layout=EventLayout(f'c{i}',i,i+1,'fixture',OverlapCheck(True),box=box)) for i in range(2)]
    return Composition(width=1080,height=1920,brief=Brief(caption_mode=mode),
        assets=[AssetRef('a','x',None)],clips=[CompositionClip('x',0,2,0,id='c',asset_id='a')],captions=captions)


def test_reference_clean_band_is_retained_and_white_shirt_gets_outline():
    np = pytest.importorskip('numpy')
    from myzing.captions.bands import place
    plan = caption_plan()
    report = place(plan,{}, {},frames=[np.full((320,180,3),255,dtype=np.uint8)])
    assert report['status'] == 'Estimated' and not report['moved']
    assert report['contrast_ratio'] == pytest.approx(1)
    assert report['outline_strengthened']
    assert all(1<c.style.outline_width<=.14*c.style.size for c in plan.captions)
    assert len({c.layout.box.center[1] for c in plan.captions}) == 1


def test_clutter_moves_to_nearest_clean_face_safe_band():
    np = pytest.importorskip('numpy')
    from myzing.captions.bands import place
    plan = caption_plan()
    frame = np.zeros((320,180,3),dtype=np.uint8)
    rng = np.random.default_rng(4)
    frame[170:225] = rng.integers(0,256,(55,180,3),dtype=np.uint8)
    report = place(plan,{'a':[face(0,2,.3)]},{'a':(1080,1920)},frames=[frame])
    assert report['moved'] and report['safe'] and report['clutter_score'] <= .18
    assert all(c.layout.overlap.safe for c in plan.captions)
    assert len({c.layout.box.center[1] for c in plan.captions}) == 1
    assert any(w.startswith('Estimated caption band:') for w in plan.warnings)


def test_outline_override_and_moving_style_are_respected():
    np = pytest.importorskip('numpy')
    from myzing.captions.bands import place
    plan = caption_plan()
    plan.brief.caption_options = {'outline_width':1}
    report = place(plan,{}, {},frames=[np.full((320,180,3),255,dtype=np.uint8)])
    assert not report['outline_strengthened']
    c = plan.captions[0]
    c.layout = replace(c.layout,box=None,path=[Keyframe(0,Box(.1,.2,.7,.12)),Keyframe(1,Box(.1,.6,.7,.12))])
    before = c.layout.path
    plan.brief.caption_options = {}
    report = place(plan,{}, {},frames=[np.full((320,180,3),255,dtype=np.uint8)])
    assert report['status'] == 'style motion retained' and report['bands'][0]['outline_strengthened']
    assert c.layout.path == before


def test_contrast_uses_worst_sample_not_mean():
    np = pytest.importorskip('numpy')
    from myzing.captions.bands import measure_band
    dark = np.zeros((100,100,3),dtype=np.uint8)
    light = np.full_like(dark,255)
    result = measure_band([dark,dark,light],Box(.1,.1,.8,.8),'#FFFFFF')
    assert result['contrast_ratio'] == 1 and result['clutter_score'] == 0


def test_face_height_excludes_safety_padding_and_scale_gate_is_independent():
    clip = CompositionClip('x',0,3,0,id='c',asset_id='a')
    framing = centered_framing('fill',1280,720,1080,1920)
    rows = measurements(clip,framing,[face(0,3,.099)],1080,1920)
    assert rows[0]['face_height_share'] == pytest.approx(.099)
    assert all(r['bad'] for r in rows)
    framing = centered_framing('fill',320,180,1080,1920)
    rows = measurements(clip,framing,[face(0,3,.15)],1080,1920)
    assert rows[0]['face_height_share'] >= .15-1e-8
    assert rows[0]['required_enlargement'] > 2.5 and rows[0]['bad']


def test_final_crop_is_rechecked_and_required_opening_is_disclosed():
    plan = caption_plan()
    plan.captions = []
    q = quality([row(0,2)])
    plan.clips[0].framing = centered_framing('fill',1280,720,1080,1920)
    subjects = {'a':([face(0,2,.12)],[])}
    report = q.report(plan,subjects,{'a':(1280,720)})
    assert not report['first_two_seconds_close'] and report['violations']
    q.required = [('a',0,2)]
    report = q.report(plan,subjects,{'a':(1280,720)})
    assert not report['violations'] and report['warnings'][0].startswith('Vertical must_keep retained')


def test_close_dominated_candidates_rank_first():
    from myzing.director.selection import choose, Envelope
    pool = [replace(candidate(i*3,i*3+2),close_share=share) for i,share in enumerate((.5,1.,.8))]
    study = ClipStudy('a','x','hash',9,'ready',shots=[Shot(i,i*3,i*3+3) for i in range(3)])
    style = Envelope(None,None,None,2,0,'lower',{'shot_durations':[]})
    selected = choose(pool,[],[study],style,2,30,0)
    assert selected['A'][0].start == 3


def test_display_cleanup_precedes_caption_grouping_and_never_changes_study():
    from types import SimpleNamespace
    from test_capref import reference
    from myzing.director.plans import captions_for
    from myzing.director.selection import envelope
    recipe = reference()
    words = [Word('we',0,.2),Word('We',.2,.4),Word('tried.',.4,1)]
    study = SimpleNamespace(asset_id='a',words=words)
    before = deepcopy(words)
    sequence = [SimpleNamespace(asset_id='a',start=0,end=1,duration=1)]
    captions = captions_for(sequence,[study],envelope(recipe),recipe,None,Brief())
    displayed = [w for c in captions for w in c.words]
    assert [w.text for w in displayed] == ['we','tried.']
    assert displayed[0].end == .4 and study.words == before


def test_delivery_rebuild_rechecks_band_and_vertical_geometry(monkeypatch):
    import json
    from test_capref import caption_plan as reference_plan
    from myzing.layout.delivery import adapt_plan
    from myzing.director.plans import REPORT_PREFIX
    from myzing.captions import bands
    plan = reference_plan('we We tried again today.')
    plan.warnings.append(REPORT_PREFIX+json.dumps({'vertical_quality':{},'caption_band':{},'constraints':{}}))
    called = []
    monkeypatch.setattr(bands,'place',lambda *a,**kw: called.append(a[0].width) or {'status':'Estimated','center':.72})
    subjects = {'a':[face(0,1,.3)]}
    result = adapt_plan(plan,1080,1920,{'a':(1280,720)},subjects,requested='reframe')
    evidence = next(json.loads(w[len(REPORT_PREFIX):]) for w in result.warnings if w.startswith(REPORT_PREFIX))
    assert called == [1080] and evidence['caption_band']['center'] == .72
    assert evidence['vertical_quality']['first_two_seconds_close']
    with pytest.raises(ValueError,match='Vertical quality'):
        adapt_plan(plan,1080,1920,{'a':(1280,720)},{'a':[face(0,1,.05)]},requested='reframe')
