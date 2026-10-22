"""CG2 rejection boundaries; plausible subtitles must survive contextual hints."""

import copy
import json

import pytest

from myzing.study import caption_geometry as cg
from myzing.study.caption_regions import assess
from test_caption_geometry import detection, frame


def ink(d):
    d.appearance = {"ink_box": d.box, "text_height": d.box[3] - d.box[1],
        "ink_evidence": {"component_count": max(1, len(d.text)), "edge_density": .15,
                         "ink_density": .25, "stroke_fraction": .12}}
    return d


def test_full_frame_character_over_face_is_explained_not_tracked():
    f = frame(2.4, [ink(detection("福", (.01, .01, .98, .98), .753))])
    f.face_boxes = [[.2, .1, .8, .7]]
    assess([f])
    d, = f.detections
    assert d.confidence == .753 and d.text == "福"
    assert {"full_frame_region", "size_or_aspect_inconsistent_with_string", "isolated_region_over_face"} <= set(d.validation["reasons"])
    assert not cg.track_frames([f], 3)
    geometry = cg.CaptionGeometry(3, [f])
    assert any(g["reason"] == "rejected_text_region" for g in cg._coverage(geometry, []) ["gaps"])
    assert f.status == "low_confidence"


@pytest.mark.parametrize("evidence", [None, {"edge_density": 0}, {"ink_density": .99},
                                      {"component_count": 0}, {"stroke_fraction": .9}])
def test_high_ocr_score_cannot_replace_stroke_evidence(evidence):
    d = ink(detection(confidence=.999))
    if evidence is None:
        d.appearance = {}
    else:
        d.appearance["ink_evidence"].update(evidence)
    samples = [frame(t/8, [copy.deepcopy(d)]) for t in range(3)]
    assess(samples)
    assert not cg.track_frames(samples, 1)
    assert "insufficient_text_strokes" in samples[0].detections[0].validation["reasons"]


def test_short_lived_text_survives_with_independent_pixel_evidence():
    f = frame(0, [ink(detection(box=(.2, .6, .5, .67)))])
    assess([f])
    assert len(cg.track_frames([f], .1)) == 1
    assert not f.detections[0].validation["temporal_stability"]


def test_borderline_recognition_needs_two_distinct_neighbor_samples():
    f = frame(0, [ink(detection(confidence=.72))])
    assess([f])
    assert not cg.track_frames([f], 1)
    samples = [frame(t/8, [ink(detection(box=(.2, .6, .5, .67), confidence=.72))]) for t in range(3)]
    assess(samples)
    assert len(cg.track_frames(samples, 1)) == 1
    assert all(f.detections[0].validation["neighbor_samples"] == 2 for f in samples)
    duplicates = [frame(0, [ink(detection(confidence=.72))]) for _ in range(3)]
    assess(duplicates)
    assert not cg.track_frames(duplicates, 1)


def test_unrelated_text_or_distant_frames_cannot_corroborate():
    samples = [frame(t, [ink(detection(text, confidence=.72))])
               for t, text in ((0, "HELLO"), (.125, "OTHER"), (2, "HELLO"))]
    assess(samples)
    assert not cg.track_frames(samples, 3)


def test_script_and_face_hints_do_not_veto_real_multilingual_text():
    samples = [frame(t/8, [ink(detection("HELLO WORLD AGAIN")),
                          ink(detection("日本語", (.2, .3, .4, .4)))]) for t in range(3)]
    for sample in samples:
        sample.face_boxes = [[.1, .2, .7, .8]]
    assess(samples)
    assert all(d.validation["accepted"] for f in samples for d in f.detections)
    assert samples[0].detections[1].validation["script_consistent"] is False
    assert samples[0].detections[1].validation["temporal_stability"] is True


def test_isolated_script_outlier_is_rejected_with_context():
    samples = [frame(t/8, [ink(detection("HELLO WORLD"))]) for t in range(4)]
    samples[1].detections.append(ink(detection("福", (.2, .3, .25, .4))))
    assess(samples)
    assert "isolated_script_disagreement" in samples[1].detections[1].validation["reasons"]
    assert all(t.text == "HELLO WORLD" for t in cg.track_frames(samples, 1))


def test_v1_sidecar_reads_and_v2_rejections_roundtrip(tmp_path):
    legacy = {"version": 1, "duration": 1, "frames": [], "tracks": []}
    assert cg.CaptionGeometry.from_dict(legacy).version == 1
    f = frame(0, [detection()])
    assess([f])
    geometry = cg.CaptionGeometry(1, [f])
    restored = cg.CaptionGeometry.from_dict(json.loads(geometry.write(tmp_path).read_text()))
    assert restored.version == 2 and restored.to_dict() == geometry.to_dict()
    assert not cg.caption_events(restored)


def test_oversized_or_wrong_aspect_proposals_fail_even_when_persistent():
    samples = [frame(t/8, [ink(detection("I", (.01, .3, .99, .35)))]) for t in range(4)]
    assess(samples)
    assert not cg.track_frames(samples, 1)
