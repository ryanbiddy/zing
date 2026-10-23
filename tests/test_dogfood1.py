"""No binaries or layout extras needed for the dogfood contracts/policies."""

from dataclasses import replace

import pytest

from myzing.brief.models import Brief
from myzing.composition import CaptionStyle
from myzing.composition.encoding import DeliveryEncoding
from myzing.layout.readability import phone_size
from myzing.layout.tracking import stitch_tracks
from myzing.layout.types import Box, FaceTrack, Keyframe, TrackObservation


def fragment(name, start, end, *, x=.3, color=None, hold=.5, width=.2):
    box = Box(x, .25, width, .3)
    hist = [1., 0., 0.] if color is None else color
    return FaceTrack(name, [Keyframe(max(0, start-hold), box), Keyframe(end+hold, box)], .95,
                     observations=[TrackObservation(start, box, hist), TrackObservation(end, box, hist)])


@pytest.mark.parametrize("gap", [.1, .8, 1.2])
def test_stitches_gaps_and_overlapping_held_intervals(gap):
    a, b = fragment("a", 0, 1), fragment("b", 1+gap, 3, x=.32)
    joined = stitch_tracks([a, b])
    assert len(joined) == 1
    assert joined[0].stitching[0]["confidence"] > .8
    assert joined[0].stitching[0]["gap_seconds"] == pytest.approx(gap)
    assert FaceTrack.from_dict(joined[0].to_dict()) == joined[0]


@pytest.mark.parametrize("b", [fragment("b", 0, 1, x=.65), fragment("b", 0, 1, x=.3),
    fragment("b", 1.2, 3, color=[0., 1., 0.]), fragment("b", 3, 4),
    fragment("b", 1.2, 3, x=.65), fragment("b", 1.2, 3, width=.4)])
def test_no_merge_of_covisible_different_appearance_distant_or_long_gap(b):
    assert len(stitch_tracks([fragment("a", 0, 1), b])) == 2


def test_ambiguous_and_missing_appearance_stay_separate():
    a = fragment("a", 0, 1)
    assert len(stitch_tracks([a, fragment("b", 1.2, 3), fragment("c", 1.2, 3, x=.31)])) == 3
    assert len(stitch_tracks([replace(a, observations=[]), fragment("b", 1.2, 3)])) == 2


def test_phone_minimum_scales_to_picture_and_phone_width():
    assert phone_size(720, 1280) == pytest.approx(57.6)
    assert phone_size(720, 720) == pytest.approx(46.8)
    assert phone_size(1280, 720) == pytest.approx(46.8)
    assert phone_size(720, 1280, 360) == pytest.approx(50.4)
    assert phone_size(1080, 1920) / phone_size(720, 1280) == pytest.approx(1.5)


def test_opt_in_style_and_brief_roundtrip_defaults_unchanged():
    assert "highlight_box_color" not in CaptionStyle(48).to_dict()
    assert "caption_options" not in Brief().to_dict()
    brief = Brief(caption_mode="phone", caption_options={"highlight_box_color": "#FFD23F", "highlight": "#000000",
                    "highlight_box_opacity": .8, "highlight_box_radius": 4}, target_mb=2.5, picture_crop="on")
    assert Brief.from_dict(brief.to_dict()) == brief
    assert DeliveryEncoding(target_mb=2.5).video_rate(10) == 1778000


@pytest.mark.parametrize("values", [{"target_mb": 2.5, "video_bitrate_kbps": 500}, {"target_mb": float("nan")},
    {"caption_options": {"highlight_box_padding": -1}}, {"caption_options": {"highlight_box_opacity": 2}},
    {"caption_options": {"highlight_box_color": "yellow"}}, {"picture_crop": "guess"}])
def test_rejects_invalid_options(values):
    with pytest.raises(ValueError):
        Brief.from_answers(values)


def test_picture_detector_rejects_static_or_unframed_motion(monkeypatch):
    np = pytest.importorskip("numpy")
    from myzing.layout.picture import detect_picture
    rng = np.random.default_rng(3)
    assert not detect_picture(np.full((12, 100, 160), 70))["confident"]
    assert not detect_picture(rng.integers(0, 255, (12, 100, 160)))["confident"]
    framed = np.full((12, 100, 160), 10, dtype=np.uint8)
    framed[:, 12:80] = rng.integers(100, 220, (12, 68, 160))
    result = detect_picture(framed)
    assert result["confident"]
    assert result["bounds_normalized"] == [0, .12, 1, .68]
    framed[:, :12] = rng.integers(0, 255, (12, 12, 160))
    assert not detect_picture(framed)["confident"]
    import sys
    from myzing.layout.picture import analyze_picture, select_picture_framing
    monkeypatch.setitem(sys.modules, "numpy", None)
    missing = analyze_picture("unused.mp4", [(0, 3)], (640, 360))
    assert 'pip install "myzing[color]"' in missing["reason"]
    with pytest.raises(ValueError, match="needs NumPy"):
        select_picture_framing("auto", 640, 360, 360, 640, None, [], picture=missing, policy="on")


def test_picture_inset_removes_side_chrome_too():
    np = pytest.importorskip("numpy")
    from myzing.layout.picture import detect_picture
    frames = np.full((12, 100, 160), 10, dtype=np.uint8)
    frames[:, 12:80, 24:136] = np.random.default_rng(7).integers(100, 220, (12, 68, 112))
    evidence = detect_picture(frames)
    assert evidence["confident"]
    assert evidence["bounds_normalized"] == [.15, .12, .7, .68]


def test_four_fragments_keep_all_link_evidence():
    tracks = [fragment(str(i), i*2, i*2+1) for i in range(4)]
    joined = stitch_tracks(tracks)
    assert len(joined) == 1
    assert len(joined[0].stitching) == 3
    assert len(joined[0].observations) == 8


def test_match_cli_forwards_caption_and_delivery_choices(monkeypatch, tmp_path):
    from myzing.match import command
    seen = {}
    monkeypatch.setattr(command, "validate", lambda **kwargs: None)
    def execute(options, **kwargs):
        seen.update(options)
        return {"status": "ready"}
    monkeypatch.setattr(command, "execute", execute)
    assert command.run(["local.mp4", "--clips", str(tmp_path), "--out", str(tmp_path/'out'),
        "--answers", "{}", "--target-mb", "2.5", "--picture-crop", "on", "--caption-mode", "phone",
        "--caption-options", '{"highlight_box_color":"#FFD23F"}', "--json"]) == 0
    assert seen["answers"]["target_mb"] == 2.5
    assert seen["answers"]["caption_options"]["highlight_box_color"] == "#FFD23F"
    assert seen["answers"]["caption_mode"] == "phone"
    assert seen["answers"]["picture_crop"] == "on"


def test_studio_preferences_reach_redelivery_plan():
    from myzing.studio.flow import normalize_answers
    from myzing.delivery_options import apply_plan
    from myzing.composition import Composition
    options = normalize_answers({"target_mb": 2.5, "caption_options": {"highlight_box_color": "#FFD23F"}, "picture_crop": "on"})
    plan = Composition()
    apply_plan(plan, options)
    assert plan.delivery.target_mb == 2.5
    assert plan.brief.picture_crop == "on"
    assert normalize_answers({"captions": "phone", "caption_mode": "none"})["captions"] == "none"
    assert normalize_answers({"captions": "none", "caption_mode": "reference"})["captions"] == "reference"
    with pytest.raises(ValueError):
        normalize_answers({"target_mb": 2.5, "video_bitrate_kbps": 2000})
