"""Face-first motion, time coverage, and visible forced-choice disclosures."""

from dataclasses import replace

import pytest

from myzing.composition import CompositionClip
from myzing.composition.framing import CropKeyframe
from myzing.layout.crop_planner import _assess, forced_reframe_warning
from myzing.layout.framing import centered_framing, select_framing
from myzing.layout.types import Box, FaceTrack, Keyframe, TrackObservation, box_at


def clip():
    return CompositionClip('source', 10, 14, 20, id='trim-3', asset_id='source')


def face(head=False):
    box = Box(.43, .2, .07, .18)
    observations = [TrackObservation(10, box, confidence=.95, class_name='person',
                                     detector='mediapipe-person-head')] if head else []
    return FaceTrack('person-head' if head else 'face-main',
                     [Keyframe(10, box), Keyframe(14, box)], .95, observations=observations)


@pytest.mark.parametrize('head', [False, True])
def test_moving_hog_never_pulls_steady_face_out(head):
    primary = face(head)
    body = FaceTrack('person-hog', [Keyframe(10+i, Box(x, .35, .15, .6))
                                   for i, x in enumerate((.05, .8, .02, .8, .1))], .99)
    f = select_framing('reframe', 1280, 720, 1080, 1920, clip(), [body, primary])
    assert f.width == 405 and f.method == ('opencv-dnn' if head else 'yunet')
    for key in f.keyframes:
        b = box_at(primary.keyframes, 10 + key.time)
        assert key.center_x - f.width/2 <= b.x*1280
        assert key.center_x + f.width/2 >= b.right*1280
    assert f.assessments[-1].subject_coverage == 1


def test_coverage_counts_face_track_time_and_not_worst_area_overlap():
    c = clip()
    base = replace(centered_framing('reframe', 1280, 720, 1080, 1920),
                   center_x=600, keyframes=[CropKeyframe(0, 600, 360)])
    assert _assess(base, 1080, 1920, c, [face()], 30).subject_coverage == 1
    # At 2 fps: 4 samples contained, 4 outside. The box crossing the edge
    # counts outside even while part of it is still visible.
    moving = replace(base, keyframes=[CropKeyframe(0, 600, 360),
                                     CropKeyframe(1.5, 600, 360),
                                     CropKeyframe(2, 900, 360), CropKeyframe(4, 900, 360)],
                     max_velocity=1000)
    a = _assess(moving, 1080, 1920, c, [face()], 2)
    assert a.subject_coverage == .5
    assert any('subject outside crop' in r for r in a.reasons)
    absent = _assess(base, 1080, 1920, c, [], 2)
    assert absent.subject_coverage == 0 and absent.evidence_gaps
    assert not any('subject outside crop' in r for r in absent.reasons)
    f = select_framing('reframe', 1280, 720, 1080, 1920, c, [])
    assert f.mode == 'reframe' and any(w.startswith('No subject evidence:') for w in f.warnings)


def test_face_evidence_gaps_are_not_false_outside_samples():
    c = clip()
    f = centered_framing('fit', 1280, 720, 1080, 1920)
    partial = replace(face(), keyframes=[Keyframe(11, face().keyframes[0].box),
                                        Keyframe(12, face().keyframes[0].box)])
    a = _assess(f, 1080, 1920, c, [partial], 2)
    assert a.subject_coverage == 1 and a.evidence_gaps
    assert _assess(f, 1080, 1920, c, [], 2).subject_coverage == 0


def test_missing_held_face_is_not_replaced_by_other_subjects_in_coverage():
    from myzing.composition.speakers import SpeakerTurn
    c = clip()
    f = replace(centered_framing('fit', 1280, 720, 1080, 1920),
                speaker_turns=[SpeakerTurn(0, 4, 'A', 'missing-face', 1, 'supplied')])
    a = _assess(f, 1080, 1920, c, [face()], 2)
    assert a.subject_coverage == 0 and a.evidence_gaps


def test_primary_face_drives_crop_but_secondary_evidence_still_counts():
    c = clip()
    edge = FaceTrack('face-edge', [Keyframe(10, Box(0, .65, .03, .03)),
                                  Keyframe(14, Box(0, .65, .03, .03))], .65)
    f = select_framing('reframe', 1280, 720, 1080, 1920, c, [face(), edge])
    assert all(k.center_x == pytest.approx(.465 * 1280) for k in f.keyframes)
    assert f.assessments[-1].subject_coverage == .5
    assert any('Secondary face detections still count' in w for w in f.warnings)


def test_forced_reframe_discloses_coverage_and_enlargement_once_per_draft():
    c = clip()
    c.framing = select_framing('reframe', 1280, 720, 1080, 1920, c, [])
    other = replace(c, id='trim-4')
    warning = forced_reframe_warning('A', [c, other])
    assert warning.count('Forced reframe retained for draft A') == 1
    assert 'clip trim-3' in warning and 'clip trim-4' in warning
    assert '0.0% (minimum 98%; no subject evidence)' in warning
    assert '2.667x (limit 2.5x)' in warning


def test_coverage_failure_keeps_forced_reframe():
    wide = FaceTrack('face-wide', [Keyframe(10, Box(.1, .2, .8, .2)),
                                   Keyframe(14, Box(.1, .2, .8, .2))])
    c = clip()
    c.framing = select_framing('reframe', 1280, 720, 360, 640, c, [wide])
    assert c.framing.mode == 'reframe' and c.framing.assessments[-1].subject_coverage == 0
    assert 'no subject evidence' not in forced_reframe_warning('A', [c])


def test_match_markdown_promotes_forced_warning_once():
    from myzing.match.evidence import markdown
    warning = 'Forced reframe retained for draft A; clip trim-3: coverage 50%, enlargement 2.667x.'
    text = markdown({'summary': 'Planning complete', 'drafts': {}, 'warnings': [warning]})
    assert text.count(warning) == 1
    assert text.index(warning) < text.index('| Draft |')
