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


# A centered fill crop would cut the nose, so explicit fill falls back to zoomfill.
@pytest.mark.parametrize('mode,expected', [('fill', 'zoomfill'), ('reframe', 'reframe'),
                                           ('auto', 'reframe'), ('zoomfill', 'zoomfill')])
def test_top_at_source_edge_and_headroom_are_never_clipped(mode, expected):
    rocket = track('saliency-rocket', Box(.46, 0, .08, .9))
    f = select_framing(mode, 640, 360, 1080, 1920, clip(), [rocket], max_upscale=6)
    assert f.mode == expected
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
    # One speaker label: the dominant face is a disclosed, uncalibrated guess.
    single = [replace(w, speaker='A') for w in words]
    large = select_framing('auto', 640, 360, 360, 640, clip(6), tracks, speech_words=single)
    assert [t.face_track_id for t in large.speaker_turns] == ['face-left', 'face-left']
    assert all(t.confidence == .55 and 'heuristic' in t.method for t in large.speaker_turns)
    # Two speakers: size alone would make the big face "the speaker" for both,
    # framing B's turn on A's face. The association must be one-to-one.
    both = select_framing('auto', 640, 360, 360, 640, clip(6), tracks, speech_words=words)
    assert all(t.face_track_id is None and 'ambiguous' in t.method for t in both.speaker_turns)
    assert both.assessments[-1].subject_coverage >= .98  # every face is kept in the two-shot


def test_partially_visible_face_blocks_the_only_face_heuristic():
    tracks, words = dialogue()
    words = [replace(w, face_track_id=None, speaker='A') for w in words]
    # face-right appears only for the second half of the first turn.
    tracks[1] = FaceTrack('face-right', [Keyframe(.5, Box(.6, .2, .1, .25)), Keyframe(6, Box(.6, .2, .1, .25))], .9)
    f = select_framing('auto', 640, 360, 360, 640, clip(6), tracks, speech_words=words)
    assert f.speaker_turns[0].face_track_id is None


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


@pytest.mark.parametrize('sw,sh,width,height,mode', [(1080, 1920, 1920, 1080, 'reframe'),
                                                     (1080, 1920, 1080, 1080, 'reframe'),
                                                     (1440, 1080, 1920, 1080, 'auto')])
def test_crop_follows_a_low_subject_vertically_without_losing_headroom(sw, sh, width, height, mode):
    # A face in the lower part of a taller source. One vertical position per
    # shot must still contain it (REFRAME2 pinned the crop at or above center).
    face = track('face-low', Box(.4, .74, .15, .18))
    f = select_framing(mode, sw, sh, width, height, clip(), [face])
    assert f.mode == 'reframe'
    a = f.assessments[-1]
    assert a.subject_coverage >= .98 and a.headroom_safe
    top = f.center_at(1)[1] - f.height / 2
    assert top <= face.keyframes[0].box.y * sh - .02 * sh and top + f.height >= face.keyframes[0].box.bottom * sh


def test_speaker_hold_is_checked_through_the_silence_it_holds():
    # One early word, then the only face walks across the frame in silence.
    walk = FaceTrack('face-a', [Keyframe(i, Box(.1 + .07 * i, .2, .1, .25)) for i in range(11)], .9)
    words = [SpeechWord('s', 'Hi', .2, .5, 'A', 'face-a')]
    from myzing.layout.types import box_at
    for mode in ('auto', 'reframe', 'zoomfill'):
        f = select_framing(mode, 640, 360, 360, 640, clip(10), [walk], speech_words=words)
        for frame in range(0, 300, 5):
            t = frame / 30
            box = output_box(box_at(walk.keyframes, t), f, t, 360, 640)
            assert box is not None, (mode, t)
        assert f.assessments[-1].subject_coverage >= .98
        assert 'speaker hold failed' in f.speaker_turns[0].method


def test_width_search_skips_impossible_widths_and_matches_exhaustive(monkeypatch):
    from myzing.layout import crop_planner
    def edge_pair(duration):
        return [FaceTrack(name, [Keyframe(i / 2, Box(x + .005 * (i % 3), .2, .1, .2)) for i in range(int(duration * 2) + 1)], .9)
                for name, x in (('face-a', .01), ('face-b', .88))]
    calls = []
    real = crop_planner._assess
    monkeypatch.setattr(crop_planner, '_assess', lambda *a, **k: calls.append(1) or real(*a, **k))
    f = select_framing('auto', 1920, 1080, 1080, 1920, clip(10), edge_pair(10))
    assert f.mode == 'zoomfill' and f.assessments[-1].subject_coverage >= .98
    assert len(calls) < 40  # REFRAME2 assessed ~1,050 widths (17 s for a 30 s clip).
    # Pruning only removes widths that cannot pass anywhere: same choice as
    # the exhaustive scan across positions, motion and speaker evidence.
    cases = [([track('face', Box(.05, .2, .3, .5), 3)], ()),
             (edge_pair(3), ()),
             ([FaceTrack('face-m', [Keyframe(0, Box(.1, .2, .1, .2)), Keyframe(3, Box(.75, .2, .1, .2))], .9)], ()),
             (dialogue()[0], dialogue()[1])]
    for tracks, words in cases:
        pruned = select_framing('auto', 640, 360, 360, 640, clip(3 if not words else 6), tracks, speech_words=words)
        monkeypatch.setattr(crop_planner, '_zoomfill_floor', lambda *a: 0)
        exhaustive = select_framing('auto', 640, 360, 360, 640, clip(3 if not words else 6), tracks, speech_words=words)
        monkeypatch.undo()
        monkeypatch.setattr(crop_planner, '_assess', real)
        assert (pruned.mode, pruned.width, pruned.keyframes) == (exhaustive.mode, exhaustive.width, exhaustive.keyframes)
    evidence = crop_planner.Evidence(clip(3), edge_pair(3), 30, 640, 360)
    assert crop_planner._zoomfill_floor(evidence, [], 640) > 290  # The edge pair really prunes widths.
    # The one-pass sampler is Framing.center_at.
    f = select_framing('reframe', 640, 360, 360, 640, clip(3), cases[2][0])
    times = [i / 30 for i in range(91)]
    assert crop_planner._centers(f, times) == [f.center_at(t) for t in times]


def test_safe_vertical_default_caption_stays_v1_and_unsafe_one_gets_the_plate(monkeypatch):
    from myzing.layout import framing as layout_framing
    from myzing.layout.framing import default_caption_box
    ink = (-120, -60, 120, 60)  # Deterministic stand-in for the measured 118% default.
    monkeypatch.setattr(layout_framing, 'measure_default_ink', lambda *a, **k: ink)
    c = CompositionClip('s', 0, 3, 0, id='c', asset_id='s')
    captions = [CompositionCaption(id='clear', text='HI THERE', start=.2, end=1, word_timed=False),
                CompositionCaption(id='covered', text='HI THERE', start=1.5, end=2.5, word_timed=False)]
    plan = Composition(assets=[AssetRef('s', 's', None)], clips=[c], captions=captions, width=1080, height=1920)
    default = default_caption_box(captions[0], 1080, 1920, ink)
    face = FaceTrack('face', [Keyframe(1.4, default), Keyframe(3, default)])
    place_captions(plan, {'s': [face]}, {'s': (1080, 1920)}, keep_safe_defaults=True)
    clear, covered = plan.captions
    assert clear.layout is None and clear.style is None  # Unchanged: still lowers to v1.
    assert covered.layout is not None and covered.layout.overlap.safe and covered.style.box_color == '#111111'


def test_zoomfill_needs_no_integer_aspect_crop():
    from myzing.layout.framing import centered_framing
    f = centered_framing('zoomfill', 640, 12, 1080, 1920)  # 12 rows < 16: no 9:16 integer crop exists.
    assert (f.width, f.height) == (640, 12)
