"""Final review probes: consistent face measurements and caption edge cases."""
from dataclasses import replace
from math import sqrt
from pathlib import Path
import struct

import pytest

from myzing.layout.tracking import build_tracks
from myzing.layout.types import Box, Detection, FaceTrack, FrameDetections
from test_dogfood3_repair import frame


def built_faces(ratios, margin=None):
    boxes = [Box(.36, .22, .19, .38), *(Box(x, .43, .19*sqrt(r), .38*sqrt(r))
             for x,r in zip((.12, .62, .23), ratios))]
    samples = [FrameDetections(t, [Detection(b, .95 if i == 0 else .70, class_name="face")
                                   for i,b in enumerate(boxes)]) for t in (0, 6, 12.533333)]
    result = build_tracks(samples, duration=12.533333, smooth_radius=0, max_gap=10,
                          **({"margin": margin} if margin is not None else {}))
    # The real builder, including non-default margins, survives serialization.
    return [FaceTrack.from_dict(t.to_dict()) for t in result]


@pytest.mark.parametrize("margin", [None, .025])
@pytest.mark.parametrize("raw,ratios,focused", [
    ([True, False], [.05], True),
    ([False, True], [.199], False),
    ([False, False, False, False], [.03, .05, .08], True),
])
def test_stage_comparison_uses_one_unpadded_basis(raw, ratios, focused, margin):
    tracks = built_faces(ratios, margin)
    tracks = [t if keep else replace(t, observations=[replace(o, time=o.time+20) for o in t.observations])
              for t,keep in zip(tracks, raw)]
    selection = frame(tracks).picture["subject_selection"]
    assert selection["focused"] is focused
    assert selection["primary_measurement_basis"] == "keyframes minus tracking padding"
    for peer,ratio in zip(tracks[1:], ratios):
        evidence = selection["participant_evidence"][peer.id]
        assert evidence["basis"] == selection["primary_measurement_basis"]
        assert evidence["padding_removed"] == tracks[0].padding == peer.padding
        assert evidence["face_area_ratio"] == pytest.approx(ratio)
        assert evidence["plausible_participant"] is (ratio >= .12)
        assert (peer.id in selection["persistent_stage_faces"]) is (ratio >= .12)


def test_legacy_padding_comes_from_build_tracks_parameter(monkeypatch):
    # A changed builder default must change the legacy fallback too.
    monkeypatch.setitem(build_tracks.__kwdefaults__, "margin", .03)
    tracks = []
    for t in built_faces([.05]):
        data = t.to_dict()
        data.pop("padding")
        data["observations"] = []
        tracks.append(FaceTrack.from_dict(data))
    selection = frame(tracks).picture["subject_selection"]
    peer = selection["participant_evidence"][tracks[1].id]
    assert selection["focused"] and peer["face_area_ratio"] == pytest.approx(.05)
    assert peer["padding_removed"] == .03
    assert peer["padding_source"] == "build_tracks default (legacy track)"


def test_unpadding_preserves_clipped_frame_edges_and_positive_boxes():
    from myzing.layout.picture import _stage_subjects
    from myzing.layout.types import Keyframe
    from myzing.composition import CompositionClip
    tracks = built_faces([.05])
    main = replace(tracks[0], observations=[])
    box = Box(0, .43, .19*sqrt(.05), .38*sqrt(.05))
    peer = replace(tracks[1], observations=[], keyframes=[Keyframe(t, box.pad(tracks[1].padding))
                                                        for t in (0, 12.533333)])
    clip = CompositionClip("generated", 0, 12.533333, 0, id="clip", asset_id="a")
    _, selection = _stage_subjects(clip, [main, peer])
    assert selection["participant_evidence"][peer.id]["face_area_ratio"] == pytest.approx(.05)
    tiny = replace(peer, keyframes=[Keyframe(t, Box(.5, .4, 1e-5, 1e-5)) for t in (0, 12.533333)])
    _, selection = _stage_subjects(clip, [main, tiny])
    assert 0 < selection["participant_evidence"][tiny.id]["face_area_ratio"] < .12


def test_farther_panelist_remains_disclosed_bystander_at_current_thresholds():
    from test_dogfood3_repair import track
    main = track("face-main", Box(.36, .22, .19, .38))
    peer = track("face-peer", Box(.12, .43, .19*.10/.32, .38*.32), .70)
    selection = frame([main, peer]).picture["subject_selection"]
    evidence = selection["participant_evidence"][peer.id]
    assert evidence["face_area_ratio"] == pytest.approx(.10)
    assert evidence["relative_height"] == pytest.approx(.32)
    assert selection["focused"] and peer.id in selection["bystander_tracks"]


def test_cff_metrics_keep_cap_height_and_glyf_missing_glyph_uses_ascent():
    from myzing.captions.metrics import FontMetrics, font_asset
    data = bytearray(Path(font_asset("box").path).read_bytes())
    glyf = FontMetrics(data)
    # A CFF-style table directory has no glyf/loca. No fontTools dependency.
    for i in range(struct.unpack_from(">H", data, 4)[0]):
        offset = 12+16*i
        if data[offset:offset+4] == b"glyf":
            data[offset:offset+4] = b"CFF "
        elif data[offset:offset+4] == b"loca":
            data[offset:offset+4] = b"xxxx"
    cff = FontMetrics(data)
    assert cff.glyph_tops is None and cff.ascent > cff.cap
    assert cff.ink_top("A$\U0010ffff", 81) == pytest.approx(cff.cap*81/cff.units)
    assert glyf.ink_top("\U0010ffff", 81) == pytest.approx(glyf.ascent*81/glyf.units)
    # An outline-free glyph present in cmap is not a missing glyph.
    glyf.glyph_tops.pop(glyf.cmap[ord("A")])
    assert glyf.ink_top("A", 81) == pytest.approx(glyf.cap*81/glyf.units)


def test_wrapped_numeric_unit_has_one_plate_per_baseline():
    import re
    from test_caption2 import plan
    from myzing.schemas import Word
    from myzing.captions.presets import apply_preset
    from myzing.captions.render import geometry, _plate_rects, compile_caption
    from myzing.layout.framing import place_captions
    p = plan("WAS $5,000. MORE", 1920, 1080)
    p.captions[0].words = [Word("WAS", .2, .7), Word("$5", .8, 1.1),
                            Word(",000.", 1.2, 1.5), Word("MORE", 1.6, 1.9)]
    p.captions[0].end = 1.9
    apply_preset(p, "box", vad=False)
    place_captions(p, {}, {})
    c = p.captions[0]
    c.text = "WAS $5\n,000. MORE"
    slots = geometry(c, 1920, 1080)["slots"]
    rects = _plate_rects(slots[1:3])
    assert len(rects) == 2
    for rect,slot in zip(rects, slots[1:3]):
        assert rect == pytest.approx(tuple(slot[k] for k in ("plate_x", "plate_y", "plate_width", "plate_height")))
    for x,y,w,h in rects:
        for other in (slots[0], slots[3]):
            assert (x+w <= other["x"] or x >= other["x"]+other["width"] or
                    y+h <= other["plate_y"] or y >= other["plate_y"]+other["plate_height"])
    lines,_ = compile_caption(c, p, "fixture", Path(c.font.path).read_bytes(), 90)
    seconds = lambda t: sum(float(v)*m for v,m in zip(t.split(":"), (3600,60,1)))
    active = [line for line in lines if (parts := line.split(",", 3))[0] == "Dialogue: 0"
              and seconds(parts[1]) <= .9 < seconds(parts[2])]
    assert len(active) == 2
    for event,rect in zip(active, rects):
        assert tuple(map(float, re.search(r"\\pos\(([^)]+)\)", event).group(1).split(","))) == pytest.approx(rect[:2], abs=.001)
