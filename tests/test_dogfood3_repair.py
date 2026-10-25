"""Grok's caption, speaker selection and delivery-status counterexamples."""
from pathlib import Path

import pytest

from myzing.composition import CompositionClip
from myzing.layout.types import Box, FaceTrack, Keyframe
from test_dogfood3 import track


def stage():
    return {"confident": True, "confidence": .86, "kind": "broadcast-composite",
            "bounds_pixels": [18, 120, 1494, 838],
            "secondary_bounds_normalized": [.81, .50, .19, .35]}


def frame(tracks, picture=None):
    from myzing.layout.picture import select_picture_framing
    return select_picture_framing("auto", 1920, 1080, 720, 1280,
        CompositionClip("generated", 0, 12.533333, 0, id="clip", asset_id="a"),
        tracks, picture=picture or stage())


def test_persistent_unequal_second_speaker_is_not_incidental():
    main = track("face-main", Box(.36, .22, .19, .38))
    peer = track("face-peer", Box(.04, .25, .10, .143678), .70)
    assert peer.keyframes[0].box.width * peer.keyframes[0].box.height / (.19*.38) == pytest.approx(.199)
    result = frame([main, peer])
    selection = result.picture["subject_selection"]
    assert not selection["focused"]
    assert peer.id not in selection.get("incidental_tracks", [])
    assert result.assessments[-1].subject_coverage >= .98


def test_one_edge_keyframe_does_not_drop_a_stage_speaker():
    main = track("face-main", Box(.36, .22, .19, .38))
    inside, edge = Box(.65, .25, .10, .20), Box(.73, .25, .10, .20)
    peer = FaceTrack("face-peer", [Keyframe(0, inside), Keyframe(6, edge), Keyframe(12.533333, inside)], .70)
    result = frame([main, peer])
    selection = result.picture["subject_selection"]
    assert peer.id not in selection["outside_stage_tracks"]
    assert not selection["focused"]


def test_persistent_peer_does_not_restore_incidental_hog_caption_obstacle():
    from test_caption2 import plan
    from myzing.layout.types import TrackObservation
    from myzing.layout.picture import select_picture_framing
    from myzing.captions.presets import apply_preset
    from myzing.layout.framing import place_captions
    main = track("face-main", Box(.36, .22, .19, .38))
    peer = track("face-peer", Box(.04, .25, .10, .143678), .70)
    hog = track("person-hog", Box(0, 0, 1, 1), .5)
    hog.observations.append(TrackObservation(0, hog.keyframes[0].box, detector="hog-fallback"))
    p = plan("One useful caption fits", 1280, 720)
    p.clips[0].framing = select_picture_framing("auto", 1920, 1080, 1280, 720,
        p.clips[0], [main, peer, hog], picture=stage())
    selection = p.clips[0].framing.picture["subject_selection"]
    assert not selection["focused"] and peer.id not in selection.get("incidental_tracks", [])
    apply_preset(p, "box", vad=False)
    place_captions(p, {"a": [main, peer, hog]}, {"a": (1920, 1080)})
    assert all(c.layout.overlap.safe for c in p.captions)


def test_only_confident_full_shot_face_in_inset_vetoes_large_stage_crop():
    from dogfood3_media import composite_frames, gray
    from myzing.layout.picture import detect_picture
    detected = detect_picture(gray(composite_frames()))
    assert detected["confident"]
    detected["bounds_pixels"] = [18, 120, 1494, 838]
    x,y,w,h = detected["secondary_bounds_normalized"]
    guest = track("face-guest", Box(x+w*.2, y+h*.2, w*.5, h*.5))
    result = frame([guest], detected)
    assert (result.bounds.x, result.bounds.y, result.bounds.width, result.bounds.height) == (0, 0, 1920, 1080)
    assert not result.picture["confident"]
    assert "inset" in result.picture["reason"]
    assert result.picture["subject_selection"]["inset_speaker"] == guest.id


def test_unconfident_stage_keeps_established_bordered_picture():
    from dogfood3_media import composite_frames, gray
    from myzing.layout.picture import detect_picture, _detect_bordered_picture
    frames = gray(composite_frames(ui=True))
    bordered = _detect_bordered_picture(frames)
    assert bordered["confident"]
    result = detect_picture(frames)
    assert result["confident"]
    assert result["bounds_normalized"] == bordered["bounds_normalized"]


@pytest.mark.parametrize("detached_comma", [False, True])
def test_numeric_continuation_plate_spans_long_silence(detached_comma):
    from test_caption2 import plan
    from myzing.schemas import Word
    from myzing.captions.presets import apply_preset
    from myzing.captions.render import compile_caption
    from myzing.layout.framing import place_captions
    p = plan("WAS $3,000,", 1920, 1080)
    p.clips[0].src_out = p.assets[0].duration = 3.5
    p.captions[0].start = 1.0
    number = ([Word("$3", 1.1, 1.6), Word(",", 1.6, 1.7), Word("000,", 2.6, 3.0)] if detached_comma
              else [Word("$3", 1.1, 1.7), Word(",000,", 2.6, 3.0)])
    p.captions[0].words = [Word("WAS", 1.0, 1.1), *number]
    p.captions[0].end = 3.0
    apply_preset(p, "box", vad=False)
    place_captions(p, {}, {})
    assert len(p.captions) == 1 and "$3,000," in p.captions[0].text
    c = p.captions[0]
    lines,_ = compile_caption(c, p, "fixture", Path(c.font.path).read_bytes(), 105)
    seconds = lambda t: sum(float(v)*m for v,m in zip(t.split(":"), (3600,60,1)))
    plates = [(seconds(parts[1]), seconds(parts[2])) for line in lines
              if (parts := line.split(",", 3))[0] == "Dialogue: 0"]
    assert any(start <= 1.8 and end >= 2.5 for start,end in plates), plates
    assert all(any(start <= frame/30 < end for start,end in plates) for frame in range(51,78)), plates


@pytest.mark.parametrize("status", ["partial", "failed", "interrupted", "cancelled"])
def test_mcp_studio_envelope_reports_unsuccessful_terminal_status(monkeypatch, status):
    from myzing import mcp_server
    monkeypatch.setattr("myzing.studio.jobs.job", lambda *a, **k: {"status": status, "result": {"ok": False}})
    result = mcp_server.h_zing_studio_run(project="fixture")
    assert result["ok"] is False and result["status"] == status


def test_failed_screen_delivery_is_not_presented_as_ready(tmp_path):
    from myzing.studio.presentation import creator_summary
    result = {"project": str(tmp_path), "status": "partial", "result": {"screens": [{"deliveries": {
        "16:9": {"status": "failed", "video": "failed.mp4", "error": "decode failed", "next_step": "Retry this shape."},
        "9:16": {"status": "ready", "video": "portrait.mp4"}}}]}}
    rows = creator_summary(result, {}, {})["deliveries"]
    assert rows[0]["status"] == "render failed" and not rows[0]["rendered"]
    assert rows[0]["error"] == "decode failed" and rows[0]["next_step"]
    assert rows[1]["rendered"]
