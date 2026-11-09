"""Measured reference face sizes, bounded crops and honest plan disclosures."""

from dataclasses import replace
from statistics import median
from types import SimpleNamespace

import pytest

from myzing.brief.models import Brief
from myzing.composition import CompositionCaption, CompositionClip
from myzing.composition.framing import Framing
from myzing.composition.speakers import SpeechWord
from myzing.director.models import ClipStudy
from myzing.director.plans import attach_report, make_plan
from myzing.director.selection import Candidate, envelope
from myzing.layout.crop_planner import select_framing
from myzing.layout.face_size import match_face_framing, measurements
from myzing.layout.types import Box, FaceTrack, Keyframe
from myzing.schemas import Breakdown, Shot, VideoMeta
from myzing.style_recipe import (Coverage, MeasuredFact, ObservationProvenance, StyleRecipe,
                                Unknown, add_face_framing, reference_face_share)


def clip(duration=2):
    return CompositionClip('source.mp4', 0, duration, 0, id='clip', asset_id='s')


def face(name='face', height=.06, x=.45, duration=2):
    box = Box(x, .2, .05, height)
    return FaceTrack(name, [Keyframe(0, box), Keyframe(duration, box)], .95)


def recipe(share=.27):
    result = StyleRecipe(ObservationProvenance('reference.mp4'))
    if share is not None:
        result.measured.append(MeasuredFact('framing.face_height_share', share, 'fraction of frame height',
                                           Coverage(3, None, 'fixture face boxes'), None, result.reference))
    return result


def planned(tmp_path, *, reference=None, tracks=None, geometry=None, required=None, **options):
    reference = reference or recipe()
    tracks = [face()] if tracks is None else tracks
    study = ClipStudy('s', 'source.mp4', 'a'*64, 2, 'ready', shots=[Shot(0, 0, 2)], text_geometry=geometry or {})
    candidate = Candidate('s', 'a'*64, 0, 2, 0, 0, None, '', False, True)
    probe = SimpleNamespace(width=1920, height=1080, rotation=0, streams=[])
    manifest = SimpleNamespace(assets=[SimpleNamespace(id='s', probe=probe)])
    brief = Brief(aspect='9:16', short_side=720, target_length_seconds=2, caption_mode='none',
                  picture_crop='off', **options)
    plan, report = make_plan('A', [candidate], [study], reference, tmp_path, envelope(reference),
                            brief, manifest, tmp_path, 0, required or {}, {}, subject_evidence={'s': (tracks, [])})
    return attach_report(plan, report), report


@pytest.mark.parametrize('width,height,expected', [(720, 1280, 640), (1080, 1920, 768)])
def test_wide_face_punches_in_to_height_or_enlargement_cap(width, height, expected):
    c, tracks = clip(), [face()]
    old = select_framing('auto', 1920, 1080, width, height, c, tracks)
    before = old.to_dict()
    new = match_face_framing(old, c, tracks, width, height, .27)
    assert old.to_dict() == before
    assert new.height == expected and new.width < old.width
    assert new.height >= max(640, .55 * 1080)
    assert new.assessments[-1].enlargement <= old.max_upscale
    assert new.assessments[-1].subject_coverage == 1 and new.assessments[-1].headroom_safe
    assert not new.assessments[-1].reasons
    assert new.face_match.reached_share > median(r['face_height_share'] for r in measurements(c, old, tracks, width, height))
    assert new.face_match.reached_share == pytest.approx(.06 * 1080 / expected)
    assert new.face_match.limited_by == ['source resolution']
    assert new.center_x == old.center_x
    assert Framing.from_dict(new.to_dict()) == new
    new.validate_output(width, height, c.duration)


def test_zoomfill_keeps_its_sharp_picture_share_and_hits_relative_floor():
    c, tracks = clip(), [face()]
    old = select_framing('auto', 5040, 2160, 720, 1280, c, tracks)
    new = match_face_framing(old, c, tracks, 720, 1280, .27)
    assert new.mode == 'zoomfill' and new.height == 1188
    assert new.face_match.source_height_floor == 1188
    assert new.assessments[-1].sharp_height_share <= old.assessments[-1].sharp_height_share
    assert new.face_match.reached_share > measurements(c, old, tracks, 720, 1280)[0]['face_height_share']


def test_reachable_target_stops_before_floor():
    c, tracks = clip(), [face(height=.2)]
    old = select_framing('auto', 1920, 1080, 720, 1280, c, tracks)
    new = match_face_framing(old, c, tracks, 720, 1280, .27)
    assert new.height == 800
    assert new.face_match.reached_share == pytest.approx(.27)
    assert not new.face_match.limited_by


def test_source_already_below_floor_keeps_its_crop_and_discloses_size():
    c, tracks = clip(), [face()]
    old = select_framing('auto', 640, 360, 1080, 1920, c, tracks)
    new = match_face_framing(old, c, tracks, 1080, 1920, .27)
    assert (new.width, new.height, new.keyframes) == (old.width, old.height, old.keyframes)
    assert new.face_match.reached_share == measurements(c, old, tracks, 1080, 1920)[0]['face_height_share']
    assert new.face_match.limited_by == ['source resolution']
    assert any(w.startswith('Reference face size limited.') for w in new.warnings)
    assert not any(w.startswith('Punched in') for w in new.warnings)


@pytest.mark.parametrize('share', [None, 0, -.1, 1.1, True, '27%'])
def test_missing_or_invalid_measurements_leave_framing_identical(share):
    c, tracks = clip(), [face()]
    old = select_framing('auto', 1920, 1080, 720, 1280, c, tracks)
    assert match_face_framing(old, c, tracks, 720, 1280, share).to_dict() == old.to_dict()


@pytest.mark.parametrize('size', [(720, 720), (1280, 720), (720, 900)])
def test_other_aspects_are_identical(size):
    c, tracks = clip(), [face()]
    old = select_framing('auto', 1920, 1080, *size, c, tracks)
    assert match_face_framing(old, c, tracks, *size, .27).to_dict() == old.to_dict()


@pytest.mark.parametrize('tracks', [[], [face('person-hog')], [replace(face(), keyframes=[Keyframe(1, Box(.45, .2, .05, .06))])]])
def test_absent_or_gapped_face_evidence_is_unchanged(tracks):
    c = clip()
    old = select_framing('auto', 1920, 1080, 720, 1280, c, tracks)
    assert match_face_framing(old, c, tracks, 720, 1280, .27).to_dict() == old.to_dict()


@pytest.mark.parametrize('mode', ['fit', 'fill', 'reframe', 'zoomfill', 'blurfill'])
def test_explicit_brief_choices_are_identical(tmp_path, mode):
    old, _ = planned(tmp_path, reference=recipe(None), framing=mode)
    new, _ = planned(tmp_path, framing=mode)
    assert [c.to_dict() for c in new.clips] == [c.to_dict() for c in old.clips]


def test_only_measured_facts_drive_planning(tmp_path):
    ref = recipe(None)
    old, _ = planned(tmp_path, reference=ref)
    ref.unknowns.append(Unknown('framing.face_height_share', 'estimate only', evidence={'value': .27}))
    ref.reference.details['face_height_share'] = .27
    new, _ = planned(tmp_path, reference=ref)
    assert new.clips == old.clips
    assert reference_face_share(ref.measured) is None
    empty = replace(recipe().measured[0], coverage=Coverage(0, None, 'unmeasured'))
    assert reference_face_share([empty]) is None


def test_recipe_collects_only_observed_face_boxes(tmp_path):
    from myzing.match.api import _recipe
    from myzing.match.state import read, write
    from myzing.explain.sections import framing
    b = Breakdown(VideoMeta('reference.mp4', 'file', duration=2, width=720, height=1280, fps=30),
                  provenance={'source_sha256': 'a'*64})
    geometry = {'frames': [{'t': 0, 'face_boxes': None}, {'t': .5, 'face_boxes': []},
                           {'t': 1, 'face_boxes': [[.4, .2, .6, .47]]}], 'tracks': []}
    ref = recipe(None)
    add_face_framing(ref, geometry)
    assert reference_face_share(ref.measured) == pytest.approx(framing(b.to_dict(), geometry).facts['face_height_percent']/100)
    write(tmp_path/'breakdown.json', b.to_dict())
    write(tmp_path/'geometry.json', geometry)
    _recipe({'path': str(tmp_path/'breakdown.json'), 'geometry': str(tmp_path/'geometry.json')}, {}, {}, tmp_path/'recipe.json')
    saved = StyleRecipe.from_dict(read(tmp_path/'recipe.json'))
    assert reference_face_share(saved.measured) == pytest.approx(.27)
    assert saved.measured[-1].provenance.sample_timestamps == [.5, 1]
    empty = recipe(None)
    add_face_framing(empty, {'frames': geometry['frames'][:2]})
    assert empty.measured == []


def test_speaker_holds_and_headroom_survive():
    c = clip(6)
    tracks = [face('face-left', x=.3, duration=6), face('face-right', x=.6, duration=6)]
    words = [SpeechWord('s', 'Left', .2, .8, 'A', 'face-left'), SpeechWord('s', 'Right', 5, 5.8, 'B', 'face-right')]
    old = select_framing('auto', 1920, 1080, 720, 1280, c, tracks, speech_words=words)
    new = match_face_framing(old, c, tracks, 720, 1280, .27, speech_words=words)
    assert new.height < old.height and new.speaker_turns == old.speaker_turns
    assert new.assessments[-1].headroom_safe and new.assessments[-1].subject_coverage == 1
    for word in words:
        assert new.center_at(word.start) == new.center_at((word.start+word.end)/2) == new.center_at(word.end)


def test_source_text_guard_overrides_punch_in(tmp_path):
    geometry = {'protected_samples': [{'t': 1, 'boxes': [[.38, .4, .57, .9]], 'words': 10}]}
    old, _ = planned(tmp_path, reference=recipe(None), geometry=geometry)
    assert old.clips[0].framing.mode == 'reframe'
    plan, report = planned(tmp_path, geometry=geometry)
    assert plan.clips[0].framing.mode == 'blurfill'
    assert plan.clips[0].framing.face_match is None
    assert not any(w.startswith('Punched in') for w in report['warnings'])


def test_caption_safety_uses_new_crop(tmp_path):
    from myzing.layout.framing import place_captions, output_box
    plan, _ = planned(tmp_path)
    plan.captions = [CompositionCaption(id='cap', text='Hello', start=.2, end=1.8, word_timed=False)]
    place_captions(plan, {'s': [face()]}, {'s': (1920, 1080)})
    caption = plan.captions[0]
    box = output_box(face().keyframes[0].box, plan.clips[0].framing, 1, 720, 1280)
    assert caption.layout.overlap.safe
    assert caption.layout.box.bottom <= box.y or caption.layout.box.y >= box.bottom


def test_plan_report_and_deliveries_disclose_reached_share(tmp_path):
    from myzing.layout.delivery import adapt_plan
    from myzing.match import evidence
    plan, report = planned(tmp_path, required={'s': [(0, 2)]})
    assert report['framing'][0]['framing']['face_match']['reached_share'] == pytest.approx(.10125)
    assert 'framing.face_height_share' not in report['unmatched_recipe_facts']
    note = next(w for w in plan.warnings if w.startswith('Punched in'))
    assert '10%' in note and '27%' in note and 'Limited by source resolution' in note
    rendered = Breakdown(VideoMeta('output.mp4', 'file', duration=2, width=720, height=1280, fps=30))
    result = evidence.report(recipe(), rendered, {}, None, {}, plan)
    assert result['face_size']['clips'][0]['reached_share'] == pytest.approx(.10125)
    assert note in result['warnings']
    assert note in evidence.markdown({'summary': 'Ready', 'drafts': {}, 'warnings': result['warnings']})
    portrait = adapt_plan(plan, 720, 1280, {'s': (1920, 1080)}, {'s': [face()]})
    assert portrait.clips[0].framing.face_match == plan.clips[0].framing.face_match
    square = adapt_plan(plan, 720, 720, {'s': (1920, 1080)}, {'s': [face()]})
    assert square.clips[0].framing.face_match is None
    assert not any(w.startswith('Punched in') for w in square.warnings)


def test_vertical_candidate_check_uses_the_same_crop():
    from myzing.director.vertical_quality import VerticalQuality
    study = ClipStudy('s', 'source.mp4', 'a'*64, 2, 'ready', shots=[Shot(0, 0, 2)])
    pool = [Candidate('s', 'a'*64, 0, 2, 0, 0, None, '', False, True)]
    args = ([study], {'s': ([face(height=.1)], [])}, {'s': (1920, 1080)},
            Brief(aspect='9:16', short_side=720), pool, [])
    old = VerticalQuality(*args)
    new = VerticalQuality(*args, reference_share=.27)
    assert not old.valid(pool) and new.valid(pool)
    assert new.rows['s'][0]['face_height_share'] == pytest.approx(.16875)


@pytest.mark.ffmpeg
@pytest.mark.parametrize('source_width,mode', [(1920, 'reframe'), (2520, 'zoomfill')])
def test_rendered_face_standin_has_the_planned_height(tmp_path, source_width, mode):
    import subprocess
    from myzing.composition import AssetRef, Composition
    from myzing.render.composition import render_composition

    def ffmpeg(*args):
        result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', *map(str, args)],
                                capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        return result.stdout

    source = tmp_path/'source.mkv'
    ffmpeg('-f', 'lavfi', '-i', f'color=c=0x303030:s={source_width}x1080:r=30:d=1,'
           'drawbox=x=900:y=216:w=96:h=64:color=white:t=fill', '-c:v', 'ffv1', source)
    c = replace(clip(1), src=str(source))
    box = Box(900/source_width, .2, 96/source_width, 64/1080)
    tracks = [FaceTrack('face', [Keyframe(0, box), Keyframe(1, box)], .95)]
    old = select_framing('auto', source_width, 1080, 180, 320, c, tracks)
    c.framing = match_face_framing(old, c, tracks, 180, 320, .27)
    assert c.framing.mode == mode and c.framing.height == 640
    plan = Composition(assets=[AssetRef('s', str(source), None)], clips=[c], width=180, height=320)
    output = tmp_path/'output.mp4'
    render_composition(plan, output)
    pixels = ffmpeg('-i', output, '-frames:v', 1, '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1')
    rows = sum(max(pixels[y*180:(y+1)*180]) > 220 for y in range(320))
    assert rows/320 == pytest.approx(c.framing.face_match.reached_share, abs=2/320)
    assert rows/320 > measurements(c, old, tracks, 180, 320)[0]['face_height_share']
