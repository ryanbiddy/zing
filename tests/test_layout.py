"""Model-free PF geometry and serialization gates (stdlib runtime only)."""

import json
import random

import pytest

from myzing.layout import (
    Box, CaptionEvent, Detection, FaceTrack, FrameDetections, Keyframe,
    LayoutPlan, Mask, build_tracks, check_overlap, choose_layout, platform_masks,
)
from myzing.layout.types import box_at


def track(boxes, times=(0, 4), name="face"):
    return FaceTrack(name, [Keyframe(t, b) for t, b in zip(times, boxes)])


def area(a, b):
    # Independent geometric oracle; never reuse the chooser's collision code.
    return max(0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x)) * max(
        0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))


def assert_clear_every_frame(plan, fps=240):
    for event in plan.events:
        assert event.overlap.safe, event.warnings
        for frame in range(round(event.start * fps), round(event.end * fps) + 1):
            time = frame / fps
            caption = box_at(event.as_path(), time)
            for face in plan.tracks:
                if face.keyframes[0].time <= time <= face.keyframes[-1].time:
                    assert area(caption, box_at(face.keyframes, time)) < 1e-12
            for mask in plan.masks:
                assert area(caption, mask.box) < 1e-12


def test_stationary_face_has_no_jitter_and_roundtrips():
    face = Box(.28, .38, .44, .42).pad(.04)
    events = [CaptionEvent(str(i), i / 4, (i + 1) / 4, .5, .1) for i in range(16)]
    plan = choose_layout(events, [track([face, face])], platform_masks("tiktok"), platform="tiktok")
    assert_clear_every_frame(plan)
    assert len({e.box for e in plan.events}) == 1
    assert plan.events[1].reason == "previous-position"
    assert LayoutPlan.from_dict(json.loads(json.dumps(plan.to_dict()))) == plan


def test_preferred_anchor_then_previous_then_nearest():
    face = Box(.2, .57, .6, .25)
    plan = choose_layout([CaptionEvent("a", 0, 1, .4, .1), CaptionEvent("b", 1, 2, .4, .1),
                          CaptionEvent("c", 2, 3, .4, .1, "top")], [track([face, face])], [])
    assert [e.reason for e in plan.events] == ["nearest-free-zone", "previous-position", "preferred-anchor"]
    assert_clear_every_frame(plan)


def test_moving_face_crossing_checks_whole_interval():
    faces = [track([Box(0, .5, .2, .3).pad(.02), Box(.8, .5, .2, .3).pad(.02)])]
    plan = choose_layout([CaptionEvent("crossing", 0, 4, .35, .1)], faces, platform_masks("shorts"))
    assert_clear_every_frame(plan)
    assert plan.events[0].reason != "preferred-anchor"


def test_two_faces():
    faces = [track([Box(.05, .3, .4, .4).pad(.03)] * 2, name="left"),
             track([Box(.55, .2, .4, .4).pad(.03)] * 2, name="right")]
    plan = choose_layout([CaptionEvent("two", 0, 4, .6, .1, "center")], faces, [])
    assert_clear_every_frame(plan)


def test_full_frame_face_is_infeasible_and_plate_does_not_claim_safe():
    face = Box(.02, .02, .96, .96).pad(.04)
    plan = choose_layout([CaptionEvent("full", 0, 4, .6, .15)], [track([face] * 2)], [])
    event = plan.events[0]
    assert not event.overlap.safe
    assert event.overlap.face_ids == ["face"]
    assert event.fallback == "plate"
    assert any("infeasible:" in warning for warning in event.warnings)


def test_smaller_box_fallback_is_checked_and_disclosed():
    masks = [Mask("lower", Box(0, .09, 1, .91))]
    plan = choose_layout([CaptionEvent("small", 0, 1, .5, .15)], [], masks)
    event = plan.events[0]
    assert event.scale == .55 and event.fallback == "smaller-box"
    assert "infeasible_requested_size" in event.warnings[0]
    assert_clear_every_frame(plan)


def test_short_motion_path_when_no_static_box_is_free():
    # Two faces leave a corridor that moves down; no static box fits throughout.
    faces = [track([Box(0, 0, 1, .2), Box(0, 0, 1, .65)], name="above"),
             track([Box(0, .5, 1, .5), Box(0, .95, 1, .05)], name="below")]
    plan = choose_layout([CaptionEvent("motion", 0, 4, .4, .2, "top")], faces, [],
                         shrink_scales=())
    event = plan.events[0]
    assert event.path and len(event.path) == 3
    assert event.reason == "short-motion-path"
    assert_clear_every_frame(plan)


def test_explicit_motion_checks_midsegment_not_just_endpoints():
    face = track([Box(.4, .4, .2, .2)] * 2)
    path = [Keyframe(0, Box(0, .4, .2, .1)), Keyframe(4, Box(.8, .4, .2, .1))]
    assert not check_overlap(path, [face], []).safe
    event = CaptionEvent("explicit", 0, 4, .2, .1, path=path)
    plan = choose_layout([event], [face], [])
    assert "explicit_path_blocked" in plan.events[0].warnings[0]
    assert_clear_every_frame(plan)


def test_safe_explicit_motion_is_preserved():
    path = [Keyframe(0, Box(0, .1, .2, .1)), Keyframe(4, Box(.8, .1, .2, .1))]
    plan = choose_layout([CaptionEvent("path", 0, 4, .2, .1, path=path)], [], [])
    assert plan.events[0].path == path
    assert plan.events[0].reason == "explicit-path"


def test_tiny_collision_between_temporal_probes_is_detected():
    path = [Keyframe(0, Box(0, .4, .0001, .1)), Keyframe(1, Box(.9999, .4, .0001, .1))]
    face = track([Box(.123456, .4, .0001, .1)] * 2, times=(0, 1))
    assert not check_overlap(path, [face], []).safe


def test_touching_edges_are_safe_but_small_overlap_is_not():
    face = track([Box(.5, .5, .2, .2)] * 2)
    assert check_overlap([Keyframe(0, Box(.3, .5, .2, .2))], [face], []).safe
    assert not check_overlap([Keyframe(0, Box(.300001, .5, .2, .2))], [face], []).safe


def test_occlusion_gap_is_bridged_and_long_gap_is_not_silently_linked():
    frames = [FrameDetections(t, [] if t in (.5, 1.5, 2, 2.5, 3) else
                              [Detection(Box(.3 + t * .02, .4, .3, .3), .9)])
              for t in (0, .5, 1, 1.5, 2, 2.5, 3, 3.5)]
    tracks = build_tracks(frames, duration=4, max_gap=1.1)
    assert len(tracks) == 2
    assert "occlusion_gap" in tracks[0].warnings[0]
    assert any("track_limited" in w for w in tracks[0].warnings)
    assert area(box_at(tracks[0].keyframes, .5), Box(.3, .4, .3, .3)) > 0
    plan = choose_layout([CaptionEvent("gap", .25, .75, .4, .1, "center")], tracks, [])
    assert_clear_every_frame(plan)


def test_smoothing_never_shrinks_a_measured_face_and_margin_is_preserved():
    boxes = [Box(.3, .3, .25, .3), Box(.32, .31, .26, .28), Box(.29, .3, .24, .3)]
    frames = [FrameDetections(t, [Detection(box, .9)]) for t, box in zip((0, .5, 1), boxes)]
    result = build_tracks(frames, duration=1.5, margin=.04)
    assert len(result) == 1
    for frame in frames:
        padded = frame.detections[0].box.pad(.04)
        actual = box_at(result[0].keyframes, frame.time)
        assert actual.x <= padded.x and actual.y <= padded.y
        assert actual.right >= padded.right and actual.bottom >= padded.bottom


def test_tracker_deterministically_keeps_two_faces_and_rejects_distant_jump():
    frames = [FrameDetections(0, [Detection(Box(.05, .3, .1, .1), .9),
                                  Detection(Box(.8, .3, .1, .1), .8)]),
              FrameDetections(.5, [Detection(Box(.79, .3, .1, .1), .8),
                                   Detection(Box(.06, .3, .1, .1), .9)]),
              FrameDetections(1, [Detection(Box(.45, .8, .1, .1), .9)])]
    tracks = build_tracks(frames, duration=2)
    assert len(tracks) == 3
    assert tracks == build_tracks(frames, duration=2)
    assert box_at(tracks[0].keyframes, .5).center[0] < .2


@pytest.mark.parametrize("platform", ["tiktok", "reels", "shorts", "none", "custom"])
def test_masks(platform):
    masks = platform_masks(platform, [] if platform == "custom" else None)
    assert len(masks) == (0 if platform in ("none", "custom") else 3)
    plan = choose_layout([CaptionEvent("ui", 0, 1, .5, .1, "bottom")], [], masks)
    assert_clear_every_frame(plan)


def test_small_gap_between_grid_points_is_found():
    masks = [Mask("above", Box(0, 0, 1, .427)), Mask("below", Box(0, .528, 1, .472))]
    plan = choose_layout([CaptionEvent("gap", 0, 1, .5, .1)], [], masks, shrink_scales=())
    assert plan.events[0].scale == 1
    assert_clear_every_frame(plan)


def test_seeded_crossings_match_independent_dense_oracle():
    rng = random.Random(19)
    for index in range(12):
        boxes = [Box(rng.uniform(0, .7), rng.uniform(.2, .65), .3, .25).pad(.025) for _ in range(3)]
        plan = choose_layout([CaptionEvent(str(index), 0, 4, .35, .1)],
                             [track(boxes, times=(0, 2, 4))], platform_masks("reels"))
        assert_clear_every_frame(plan, fps=120)


@pytest.mark.parametrize("data", [
    {"id": "x", "start": 1, "end": 0, "width": .2, "height": .1},
    {"id": "x", "start": 0, "end": float("nan"), "width": .2, "height": .1},
    {"id": "x", "start": True, "end": 1, "width": .2, "height": .1},
    {"id": "x", "start": 0, "end": 1, "width": 1.2, "height": .1},
    {"id": "x", "start": 0, "end": 1, "width": .2, "height": .1, "version": 2},
    {"id": "x", "start": 0, "end": 1, "width": .2, "height": .1, "preferred_anchor": "unknown"},
])
def test_invalid_events_fail(data):
    with pytest.raises(ValueError):
        CaptionEvent.from_dict(data)


def test_versioned_nested_records_reject_future_versions():
    data = FaceTrack("face", [Keyframe(0, Box(0, 0, .1, .1))]).to_dict()
    data["keyframes"][0]["box"]["version"] = 999
    with pytest.raises(ValueError, match="unsupported Box version"):
        FaceTrack.from_dict(data)


def test_event_order_and_duplicate_ids():
    events = [CaptionEvent("late", 1, 2, .5, .1), CaptionEvent("early", 0, 1, .5, .1)]
    assert [e.id for e in choose_layout(events, [], []).events] == ["early", "late"]
    with pytest.raises(ValueError, match="unique"):
        choose_layout([events[0], events[0]], [], [])
