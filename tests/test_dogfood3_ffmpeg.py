"""Generated-media broadcast and partial Studio delivery gates. No downloads."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.ffmpeg


@pytest.mark.parametrize("preset", ["box", "punch"])
@pytest.mark.parametrize("detached_comma", [False, True])
def test_joined_number_highlights_whole_display_unit_on_every_piece(tmp_path, preset, detached_comma):
    import subprocess
    np = pytest.importorskip("numpy")
    from test_caption2 import plan
    from myzing.schemas import Word
    from myzing.captions.presets import apply_preset
    from myzing.captions.render import geometry
    from myzing.layout.framing import place_captions
    from myzing.render.font_files import private_font
    from myzing.render.positioned_captions import generate_positioned_ass
    p = plan("WANTED $5,000.", 1920, 1080)
    p.clips[0].src_out = p.assets[0].duration = 2.3
    c = p.captions[0]
    c.start, c.end = .2, 2.1
    pieces = ([Word("$5", .8, .95), Word(",", .95, 1.), Word("000.", 1.9, 2.1)] if detached_comma
              else [Word("$5", .8, 1.), Word(",000.", 1.9, 2.1)])
    c.words = [Word("WANTED", .2, .7), *pieces]
    apply_preset(p, preset, vad=False)
    place_captions(p, {}, {})
    assert len(p.captions) == 1 and p.captions[0].text == "WANTED $5,000."
    c = p.captions[0]
    slots = geometry(c, p.width, p.height)["slots"]
    fonts = {c.id: private_font(Path(c.font.path).read_bytes())}
    generate_positioned_ass(p, fonts, tmp_path, "ffmpeg", "ass")
    # White reference, first piece, 0.9-second pause, and final piece.
    # Return only four frames (25 MB) instead of buffering the whole render.
    run = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "color=black:s=1920x1080:r=30:d=2.2", "-vf",
        r"ass=filename=captions.ass:fontsdir=fonts,select=eq(n\,18)+eq(n\,24)+eq(n\,42)+eq(n\,60)",
        "-vsync", "0", "-threads", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
        cwd=tmp_path, capture_output=True, timeout=60)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    frames = np.frombuffer(run.stdout, dtype=np.uint8).reshape(4, 1080, 1920, 3)
    for slot in slots[1:]:
        x0,x1 = int(slot["x"]), int(np.ceil(slot["x"]+slot["width"]))
        ys,xs = np.nonzero(frames[0][:,x0:x1].min(axis=2) > 220)
        assert len(xs) > 5
        for active in frames[1:]:
            # Chroma subsampling softens tiny punctuation; compare hue as
            # well as brightness so pale yellow counts but white cannot.
            rgb = active.astype(np.int16)
            yellow = (rgb[:,:,0] > 180) & (rgb[:,:,1] > 130) & (rgb[:,:,0]-rgb[:,:,2] > 60) & (rgb[:,:,1]-rgb[:,:,2] > 40)
            if preset == "punch":
                assert yellow[ys,xs+x0].mean() > .95, slot["text"]
            else:
                assert (active[ys,xs+x0].max(axis=1) < 100).mean() > .95, slot["text"]
                for y in np.unique(ys):
                    span, ink = np.flatnonzero(yellow[y]), xs[ys==y]+x0
                    assert len(span) and span.min() <= ink.min() and span.max() >= ink.max(), slot["text"]
    # Selecting a numeric unit must not select the previous ordinary word.
    first = slots[0]
    assert (frames[1][:,int(first["x"]):int(first["x"]+first["width"])].min(axis=2) > 220).sum() > 100


def test_landscape_active_plate_covers_were_during_first_80ms(tmp_path):
    import subprocess
    np = pytest.importorskip('numpy')
    from test_caption2 import plan
    from myzing.captions.presets import apply_preset
    from myzing.captions.render import geometry
    from myzing.layout.framing import place_captions
    from myzing.render.font_files import private_font
    from myzing.render.positioned_captions import generate_positioned_ass
    p = plan('WHEN WE WERE TRYING', 1920, 1080)
    apply_preset(p, 'box', vad=False)
    place_captions(p, {}, {})
    assert len(p.captions) == 1
    c = p.captions[0]
    assert c.style.size == 81 and c.layout.scale == 1
    geo = geometry(c, 1920, 1080)
    word = geo['slots'][2]
    assert word['text'] == 'WERE'
    fonts = {c.id: private_font(Path(c.font.path).read_bytes())}
    generate_positioned_ass(p, fonts, tmp_path, 'ffmpeg', 'ass')
    # Frame 24 supplies this word's white ink bounds; 30/31 are 0/33 ms
    # into WERE, before the old 80 ms plate glide finished. Only three RGB
    # frames are returned, keeping the 1080p regression's memory bounded.
    run = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
        'color=black:s=1920x1080:r=30:d=1.2', '-vf',
        r'ass=filename=captions.ass:fontsdir=fonts,select=eq(n\,24)+eq(n\,30)+eq(n\,31)',
        '-vsync', '0', '-threads', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
        cwd=tmp_path, capture_output=True, timeout=60)
    assert run.returncode == 0, run.stderr.decode(errors='replace')
    frames = np.frombuffer(run.stdout, dtype=np.uint8).reshape(3, 1080, 1920, 3)
    x0,x1 = int(word['x'])-1, int(np.ceil(word['x']+word['width']))+1
    ys,xs = np.nonzero(frames[0][:,x0:x1].min(axis=2) > 170)
    assert len(xs) > 100
    for early in frames[1:]:
        yellow = (early[:,:,0]>180)&(early[:,:,1]>130)&(early[:,:,2]<120)
        for y in np.unique(ys):
            span = np.flatnonzero(yellow[y])
            ink = xs[ys==y]+x0
            assert len(span) and span.min() <= ink.min() and span.max() >= ink.max(), (y, span, ink)


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
    # Start and poll a real durable job; never manufacture its status file.
    mcp_root=tmp_path/'mcp-studio'
    started=mcp_server.h_zing_studio_run(answers={**answers,'project':str(mcp_root),
        'short_side':180,'target_mb':2},confirmed=True)
    assert started['ok'] and started['status']=='started'
    active=jobs._JOBS.get(str(mcp_root.resolve()))
    if active:
        active[0].join(timeout=60)
        assert not active[0].is_alive()
    polled=mcp_server.h_zing_studio_run(project=str(mcp_root))
    assert polled['status']=='partial' and polled['ok'] is False
    assert polled['result']['ok'] is False
    mcp_rows=polled['result']['creator_summary']['deliveries']
    assert len(mcp_rows)==3 and sum(r['rendered'] for r in mcp_rows)==2
    assert next(r for r in mcp_rows if not r['rendered'])['next_step']


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
