"""Generated-media broadcast and partial Studio delivery gates. No downloads."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.ffmpeg


def test_generated_composite_encodes_and_delivers_safe_box_in_three_shapes(tmp_path,monkeypatch):
    from dogfood3_media import write_composite
    from test_dogfood3 import track
    from myzing.layout.types import Box
    from myzing.layout.picture import analyze_picture
    from myzing.studio.adapters import load_edit,deliver
    from myzing.composition import CompositionCaption,Composition
    from myzing.schemas import Word
    from myzing.brief.models import Brief
    from myzing.captions.presets import apply_preset
    source=tmp_path/'generated.mp4'
    write_composite(source)
    picture=analyze_picture(source,[(0,6)],(960,540))
    assert picture['confident'] and picture['kind']=='broadcast-composite',picture
    assert picture['confidence'] >= .8
    main=track('face-main',Box(.32,.22,.15,.30))
    guest=track('face-guest',Box(.85,.55,.08,.15))
    monkeypatch.setattr('myzing.render.deliveries.analyze_subjects',lambda *a,**k:([main,guest],[]))
    p=load_edit(source)
    p.brief=Brief(caption_mode='box',target_mb=2,short_side=360)
    words=[Word(t,.2+i*.4,.5+i*.4) for i,t in enumerate(['This','year','was','$3',',000,','at','first.'])]
    p.captions=[CompositionCaption('This year was $3,000, at first.',.2,3.0,id='spoken',words=words)]
    apply_preset(p,'box',vad=False)
    saved=tmp_path/'plan.json'
    saved.write_text(p.to_json(),encoding='utf-8')
    result=deliver(saved,tmp_path/'out.mp4',['16:9','1:1','9:16'])
    assert result['status']=='ready',result
    for shape,row in result['deliveries'].items():
        plan=Composition.from_json(Path(row['plan']).read_text(encoding='utf-8'))
        assert all(c.layout.overlap.safe for c in plan.captions)
        assert any('$3,000,' in c.text for c in plan.captions)
        assert Path(row['video']).stat().st_size < 2_000_000
        assert Path(row['decode']).is_file()
        f=plan.clips[0].framing
        assert f.picture['confidence'] >= .8
        if shape=='9:16':
            assert .50 <= f.assessments[-1].sharp_height_share <= .70
            assert f.assessments[-1].enlargement <= 2.5


def test_cli_and_mcp_keep_two_deliveries_when_landscape_fails(tmp_path,monkeypatch,zing_workspace,capsys):
    from test_dogfood2_ffmpeg import ff
    from myzing.schemas import Word
    from myzing.study.transcribe import TranscribeResult
    from myzing.studio import command,execute,jobs
    from myzing.render import deliveries
    from myzing import mcp_server
    clips=tmp_path/'clips'
    clips.mkdir()
    ff('-f','lavfi','-i','color=c=navy:s=320x180:r=30:d=3','-c:v','libx264','-threads','1',clips/'moment.mp4')
    words=[Word(t,.2+i*.4,.5+i*.4) for i,t in enumerate(['One','useful','moment','can','work.'])]
    monkeypatch.setattr('myzing.study.transcribe.transcribe',lambda *a,**k:TranscribeResult(words=words))
    monkeypatch.setattr('myzing.study.speech_models.prepare',lambda *a,**k:None)
    monkeypatch.setattr(jobs,'execute',lambda a,**k:execute.run_confirmed(a))
    original=deliveries.render_composition
    def render(plan,*args,**kwargs):
        if plan.width > plan.height:
            raise ValueError('caption fixture: no readable caption band fits')
        return original(plan,*args,**kwargs)
    monkeypatch.setattr(deliveries,'render_composition',render)
    root=tmp_path/'studio'
    answers={'path':'b','project':str(root),'clips':str(clips),'topic':'one useful moment',
             'platform':'all','aspects':['16:9','1:1','9:16'],'length':3,'tone':'natural','captions':'box','music':'none'}
    path=tmp_path/'answers.json'
    path.write_text(json.dumps(answers),encoding='utf-8')
    assert command.run(['--answers',str(path),'--yes','--short-side','180','--target-mb','2']) == 2
    result=json.loads((root/'studio-result.json').read_text(encoding='utf-8'))
    assert result['status']=='partial' and not result['ok']
    rows=result['creator_summary']['deliveries']
    assert len(rows)==3 and sum(r['rendered'] for r in rows)==2
    failed=next(r for r in rows if not r['rendered'])
    assert failed['shape']=='16:9' and 'caption' in failed['error'] and failed['next_step']
    output=capsys.readouterr().out
    assert 'Failed A 16:9' in output and 'clean captions' in output
    # Poll the durable job through the actual MCP handler; metadata keeps partial
    # and the failed-shape remedy rather than flattening it into an empty error.
    (root/'studio-job.json').write_text(json.dumps({'status':'partial','project':str(root),'result':result}),encoding='utf-8')
    polled=mcp_server.h_zing_studio_run(project=str(root))
    assert polled['status']=='partial'
    assert polled['result']['creator_summary']['deliveries']==rows


def test_in_place_ingest_never_stages_or_normalizes_original(tmp_path,monkeypatch,zing_workspace):
    from dogfood3_media import write_composite
    from myzing.study import ingest
    from myzing.project.api import hash_file
    source=tmp_path/'original.mp4'
    write_composite(source)
    before=hash_file(source)
    monkeypatch.setenv('ZING_LOCAL_MEDIA_IN_PLACE','1')
    monkeypatch.setattr(ingest,'_stage_local',lambda *a:pytest.fail('source staged'))
    monkeypatch.setattr(ingest,'_normalize',lambda *a:pytest.fail('source normalized'))
    result=ingest.ingest(str(source))
    assert result.media_path==source and result.meta.media_path==str(source)
    assert not list(result.breakdown_dir.glob('*.mp4'))
    assert result.provenance['local_media']['copied'] is False
    with pytest.raises(ingest.MediaError,match='cannot extract'):
        ingest.ingest(str(source),ref_start=1,ref_end=3)
    monkeypatch.setattr(ingest,'_needs_normalize',lambda *a:(True,'fixture VFR'))
    with pytest.raises(ingest.MediaError,match='source kept unchanged'):
        ingest.ingest(str(source))
    assert hash_file(source)==before
