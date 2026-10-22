"""Intermediate geometry, top protection and source-clock speaker evidence."""

import math
from dataclasses import replace

import pytest

from myzing.composition import AssetRef, Composition, CompositionClip, CompositionCaption, lowering_blockers
from myzing.composition.framing import Framing
from myzing.composition.speakers import SpeechWord
from myzing.layout.delivery import adapt_plan
from myzing.layout.framing import select_framing, visible_content, output_box, place_captions
from myzing.layout.types import Box, FaceTrack, Keyframe


def clip(duration=2):
    return CompositionClip('s', 0, duration, 0, id='clip', asset_id='s')


def track(name='face', box=Box(.4, .2, .2, .4), duration=2):
    return FaceTrack(name, [Keyframe(0, box), Keyframe(duration, box)], .9)


def dialogue():
    tracks = [track('face-left', Box(.3, .2, .1, .25), 6), track('face-right', Box(.6, .2, .1, .25), 6)]
    words = [SpeechWord('s', 'Left', .2, .8, 'A', 'face-left'),
             SpeechWord('s', 'Right', 5, 5.8, 'B', 'face-right')]
    return tracks, words


@pytest.mark.parametrize('sw,sh', [(640, 360), (641, 361), (862, 360)])
def test_zoomfill_enlargement_and_coverage_are_measured(sw, sh):
    f = select_framing('auto', sw, sh, 1080, 1920, clip(), [track()])
    assert f.mode == 'zoomfill'
    assert f.height == sh and f.width == 432
    assert f.assessments[-1].enlargement == 2.5
    content = visible_content(f, 1080, 1920)
    assert content.height == math.floor(sh * 2.5 / 2) * 2 / 1920
    assert f.assessments[-1].sharp_height_share == content.height
    assert f.assessments[-1].sharp_area_share == content.height
    assert '50-70%' in ' '.join(f.warnings)
    assert Framing.from_dict(f.to_dict()) == f


def test_hd_intermediate_reaches_target_without_exceeding_it():
    f = select_framing('auto', 2520, 1080, 1080, 1920, clip(), [track()])
    assert f.mode == 'zoomfill'
    assert .69 <= f.assessments[-1].sharp_height_share <= .70
    assert f.assessments[-1].enlargement <= 2.5
    assert f.assessments[0].reasons  # full crop's rejected source loss is retained


@pytest.mark.parametrize('mode', ['fill', 'reframe', 'auto', 'zoomfill'])
def test_top_at_source_edge_and_headroom_are_never_clipped(mode):
    rocket = track('saliency-rocket', Box(.46, 0, .08, .9))
    f = select_framing(mode, 640, 360, 1080, 1920, clip(), [rocket], max_upscale=6)
    for frame in range(60):
        _, cy = f.center_at(frame / 30)
        assert cy - f.height / 2 == 0
    assert f.assessments[-1].headroom_safe


def test_headroom_survives_fast_top_motion_and_smoothing():
    face = FaceTrack('face', [Keyframe(0, Box(.4, .3, .2, .2)), Keyframe(.5, Box(.4, .01, .2, .2)),
                              Keyframe(2, Box(.4, .3, .2, .2))])
    f = select_framing('auto', 1080, 1920, 1080, 1080, clip(), [face])
    assert f.assessments[-1].headroom_safe


@pytest.mark.parametrize('mode', ['reframe', 'zoomfill'])
def test_speaker_switches_only_during_silence_with_bounded_motion(mode):
    tracks, words = dialogue()
    f = select_framing(mode, 640, 360, 360, 640, clip(6), tracks, speech_words=words)
    assert [t.face_track_id for t in f.speaker_turns] == ['face-left', 'face-right']
    assert f.center_at(.2)[0] < f.center_at(5)[0]
    for word in words:
        positions = [f.center_at(word.start + (word.end - word.start) * i / 100) for i in range(101)]
        assert all(p == positions[0] for p in positions)
    positions = [f.center_at(i / 1000) for i in range(6001)]
    assert max(math.dist(a, b) * 1000 for a, b in zip(positions, positions[1:])) <= f.max_velocity + .001


@pytest.mark.parametrize('problem', ['unknown', 'short-gap', 'missing-track', 'overlap'])
def test_ambiguous_speech_keeps_two_shot(problem):
    tracks, words = dialogue()
    if problem == 'unknown':
        words = [replace(w, speaker=None, face_track_id=None) for w in words]
    elif problem == 'short-gap':
        words[1] = replace(words[1], start=.9, end=1.5)
    elif problem == 'missing-track':
        words = [replace(w, face_track_id='not-present') for w in words]
    else:
        words[1] = replace(words[1], start=.5, end=1.5)
    f = select_framing('auto', 640, 360, 360, 640, clip(6), tracks, speech_words=words)
    assert f.mode == 'zoomfill'
    assert all(t.face_track_id is None for t in f.speaker_turns)
    for subject in tracks:
        box = output_box(subject.keyframes[0].box, f, 0, 360, 640)
        content = visible_content(f, 360, 640)
        assert box and content.x <= box.x < box.right <= content.right
    assert f.assessments[-1].subject_coverage >= .98


def test_size_heuristic_is_disclosed_and_equal_faces_remain_unknown():
    tracks, words = dialogue()
    words = [replace(w, face_track_id=None) for w in words]
    equal = select_framing('auto', 640, 360, 360, 640, clip(6), tracks, speech_words=words)
    assert all(t.face_track_id is None for t in equal.speaker_turns)
    tracks[0] = track('face-left', Box(.25, .15, .2, .4), 6)
    large = select_framing('auto', 640, 360, 360, 640, clip(6), tracks, speech_words=words)
    assert all(t.confidence == .55 and 'heuristic' in t.method for t in large.speaker_turns)


def test_speech_evidence_roundtrip_delivery_cut_reset_and_v1_guard():
    tracks, words = dialogue()
    plan = Composition(assets=[AssetRef('s', 's', None)], clips=[clip(6)], speech_words=words, width=640, height=360)
    assert Composition.from_json(plan.to_json()).speech_words == words
    assert 'speech_words' in lowering_blockers(plan)
    result = adapt_plan(plan, 360, 640, {'s': (640, 360)}, {'s': tracks}, cuts={'s': [3]})
    assert len(result.clips) == 2
    assert result.clips[0].framing.center_at(0)[0] < result.clips[1].framing.center_at(0)[0]
    assert all(c.framing.keyframes[0].time == 0 for c in result.clips)


def test_default_vertical_caption_has_stroke_plate_and_safe_band():
    c = clip()
    c.framing = select_framing('auto', 640, 360, 1080, 1920, c, [])
    cap = CompositionCaption(id='cap', text='CLEAR WORDS', start=.1, end=1.9, word_timed=False)
    plan = Composition(assets=[AssetRef('s', 's', None)], clips=[c], captions=[cap], width=1080, height=1920)
    place_captions(plan, {})
    assert cap.style.outline_width >= 4 and cap.style.box_color == '#111111'
    assert cap.layout.overlap.safe and 'blur band' in cap.layout.overlap.scope
    assert .06 <= cap.layout.box.x and cap.layout.box.right <= .84
    assert .08 <= cap.layout.box.y and cap.layout.box.bottom <= .8


def test_zoomfill_rejects_foreground_taller_than_output():
    from myzing.layout.framing import centered_framing
    f = centered_framing('zoomfill', 360, 640, 1080, 1080)
    with pytest.raises(ValueError, match='output height'):
        f.validate_output(1080, 1080, 1)
