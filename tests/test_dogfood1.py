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
    # Uniform bars are a letterbox matte, not broadcast chrome.
    matte = detect_picture(framed)
    assert not matte["confident"] and matte["surround"]["kind"] == "matte"
    assert matte["bounds_normalized"] == [0, .12, 1, .68]
    framed[:, 86:94, 10:70] = 230  # a static lower-third name card
    result = detect_picture(framed)
    assert result["confident"] and result["surround"]["kind"] == "chrome"
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
    frames[:, 86:94, 10:70] = 230
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


def test_picture_detector_refuses_textured_static_scenery():
    """A desk vlog's straight shelf and desk edges with a static textured
    surround are camera scenery, not flat broadcast graphics."""
    np = pytest.importorskip("numpy")
    from myzing.layout.picture import detect_picture
    rng = np.random.default_rng(11)
    texture = rng.integers(40, 200, (100, 160)).astype(np.uint8)
    frames = np.repeat(texture[None], 12, axis=0)
    frames[:, 20:22] = 5  # shelf
    frames[:, 22:78] = rng.integers(60, 220, (12, 56, 160))  # moving subject band
    frames[:, 78:80] = 250  # desk edge
    evidence = detect_picture(frames)
    assert not evidence["confident"]
    assert evidence["surround"]["kind"] == "scenery"


def test_picture_bounds_step_inward_and_small_sources_keep_full_frame(monkeypatch):
    np = pytest.importorskip("numpy")
    import subprocess
    from myzing.layout import picture
    sample = np.zeros((12, 180, 320), dtype=np.uint8)

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, sample.tobytes(), b"")
    monkeypatch.setattr(picture.subprocess, "run", run)
    found = {"confident": True, "confidence": .9, "bounds_normalized": [0, 10/180, 1, 140/180]}
    monkeypatch.setattr(picture, "detect_picture", lambda frames: dict(found))
    # Sample rows 10..150 of 180 from 1280x720: one 4 px sample row inward.
    assert picture.analyze_picture("x.mp4", [(0, 4)], (1280, 720))["bounds_pixels"] == [0, 44, 1280, 552]
    sample = np.zeros((12, 16, 16), dtype=np.uint8)
    found["bounds_normalized"] = [0, .34, 1, .32]
    tiny = picture.analyze_picture("x.mp4", [(0, 4)], (16, 16))
    assert not tiny["confident"] and "keeping the full frame" in tiny["reason"]


def _words(spec):
    from myzing.schemas import Word
    return [Word(text, start, end) for text, start, end in spec]


def test_phone_groups_are_balanced_and_never_flash_a_single_word():
    from myzing.layout.readability import phone_word_groups
    # The acceptance clause: 4+1 left "born" alone for 0.26 s.
    born = _words([("Paul", 2.46, 2.74), ("and", 2.74, 3.1), ("I", 3.1, 3.18), ("was", 3.18, 3.4), ("born", 3.4, 3.66)])
    assert [[w.text for w in g] for g in phone_word_groups(born)] == [["Paul", "and", "I", "was", "born"]]
    slow = _words([(str(i), i * .4, i * .4 + .35) for i in range(5)])
    assert [len(g) for g in phone_word_groups(slow)] == [3, 2]
    assert [len(g) for g in phone_word_groups(_words([(str(i), i, i + .9) for i in range(9)]))] == [3, 3, 3]
    assert phone_word_groups([]) == []


def test_short_phone_events_hold_into_silence_only():
    from myzing.composition import CompositionCaption
    from myzing.layout.readability import hold_short_events
    a = CompositionCaption("born", 1.0, 1.2, id="a", word_timed=False)
    b = CompositionCaption("children's", 1.3, 1.5, id="b", word_timed=False)
    c = CompositionCaption("ok", 3.0, 3.1, id="c", word_timed=False)
    assert hold_short_events([a, b, c], 3.3) == 2
    assert (a.end, b.end, c.end) == (1.3, pytest.approx(1.8), 3.3)


def test_phone_redelivery_has_no_orphan_word_events():
    from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip
    from myzing.delivery_options import apply_plan
    words = _words([("Paul", 2.46, 2.74), ("and", 2.74, 3.1), ("I", 3.1, 3.18), ("was", 3.18, 3.4), ("born", 3.4, 3.66),
                    ("in", 3.7, 4.0), ("Harare", 4.0, 4.42)])
    plan = Composition(assets=[AssetRef("v", "v.mp4", None, 10)], clips=[CompositionClip("v.mp4", 0, 10, 0, id="c", asset_id="v")],
                       captions=[CompositionCaption(" ".join(w.text for w in words[:5]), 2.46, 3.66, words=words[:5], id="one", word_timed=True),
                                 CompositionCaption("in Harare", 3.7, 4.42, words=words[5:], id="two", word_timed=True)])
    apply_plan(plan, {"caption_mode": "phone"})
    assert all(len(c.words) > 1 for c in plan.captions)
    assert all(c.end - c.start >= .5 for c in plan.captions)


def test_stable_anchor_stays_put_and_prefers_the_smallest_move():
    from myzing.layout.chooser import choose_stable
    from myzing.layout.types import CaptionEvent
    event = CaptionEvent("e", 0, 1, .4, .1)
    home = (.5, .75)
    assert choose_stable(event, [], [], home=home).reason == "stable-anchor"
    # Previous position wins over returning home: no move without a reason.
    stay = choose_stable(event, [], [], home=home, previous=(.35, .75))
    assert stay.reason == "previous-position" and stay.box.center[0] == pytest.approx(.35)
    # A face over home: shift sideways just past it on the same baseline.
    face = FaceTrack("face", [Keyframe(0, Box(.45, .5, .1, .3)), Keyframe(1, Box(.45, .5, .1, .3))], .9)
    moved = choose_stable(event, [face], [], home=home)
    # Just below the face (a .105 move) beats a .25 sideways shift.
    assert moved.reason == "smallest-move" and moved.box.y == pytest.approx(.8)
    assert moved.box.center[0] == pytest.approx(.5)
    # A slightly smaller box in place beats a jump across the frame.
    sides = [FaceTrack(name, [Keyframe(0, box), Keyframe(1, box)], .9)
             for name, box in (("left", Box(0, .4, .075, .5)), ("right", Box(.925, .4, .075, .5)))]
    wide = CaptionEvent("e", 0, 1, .96, .1)
    from myzing.layout.types import Mask
    bottom = [Mask("bottom", Box(0, .8, 1, .2))]
    jump = choose_stable(wide, sides, bottom, home=home, shrink_scales=())
    assert jump.scale == 1 and jump.box.bottom <= .4 + 1e-9
    small = choose_stable(wide, sides, bottom, home=home, shrink_penalty=1.0, shrink_scales=(.85,))
    assert small.scale == .85 and small.box.bottom == pytest.approx(.75)


def test_vertical_picture_rises_to_open_the_lower_caption_band():
    from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip
    from myzing.layout.framing import select_framing, visible_content, place_captions
    clip = CompositionClip("s", 0, 4, 0, id="clip", asset_id="s")
    clip.framing = select_framing("zoomfill", 1280, 560, 720, 1280, clip, [])
    centered = visible_content(clip.framing, 720, 1280)
    captions = [CompositionCaption(text, start, start + 1, id=f"c{i}", word_timed=False)
                for i, (text, start) in enumerate((("one two three four five six seven", 0),
                                                   ("eight nine ten eleven", 1.2), ("twelve", 2.4)))]
    plan = Composition(assets=[AssetRef("s", "s", None)], clips=[clip], captions=captions, width=720, height=1280)
    place_captions(plan, {})
    raised = visible_content(clip.framing, 720, 1280)
    assert clip.framing.foreground_top is not None and raised.y < centered.y and raised.y >= .08
    assert any("raised" in w for w in clip.framing.warnings)
    tops = {round(c.layout.box.y, 6) for c in captions}
    assert all("lower blur band" in c.layout.overlap.scope for c in captions)
    assert tops == {round(raised.bottom, 6)} and all(c.layout.box.bottom <= .8 + 1e-9 for c in captions)
    assert len({round(c.layout.box.center[0], 6) for c in captions}) == 1
    from myzing.composition.framing import Framing
    assert Framing.from_dict(clip.framing.to_dict()) == clip.framing
    with pytest.raises(ValueError):
        replace(clip.framing, mode="fit", keyframes=[], foreground_top=.1).__post_init__()


def test_phone_floor_uses_the_visible_picture_in_match_fit(monkeypatch):
    from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip
    from myzing.layout.framing import centered_framing
    from myzing.layout.readability import phone_minimum
    from myzing.match import caption_fit
    clip = CompositionClip("s", 0, 2, 0, id="clip", asset_id="s")
    clip.framing = centered_framing("fit", 360, 640, 1280, 720)  # pillarboxed 9:16 source in 16:9
    caption = CompositionCaption("narrow picture", 0, 2, id="cap", word_timed=False, style=CaptionStyle(60))
    plan = Composition(assets=[AssetRef("s", "s", None)], clips=[clip], captions=[caption], width=1280, height=720,
                       brief=Brief(caption_mode="phone"))
    assert phone_minimum(plan, caption) == pytest.approx(.065 * 404)
    # Ink twice the box: the fitted size (~28 px) clears the 26 px picture floor,
    # though not the 46.8 px full-frame floor the old check used.
    monkeypatch.setattr(caption_fit, "_measure", lambda caption, style, *a, **k:
                        (-5 * style.size, -.66 * style.size, 5 * style.size, .66 * style.size))
    style, failure = caption_fit._fit(caption, CaptionStyle(60), 1, 300, 80, "Arial", 1, plan, None)
    assert failure is None and 26 < style.size < 46.8


def test_audio_budget_reads_packets_and_survives_unknown_rates(monkeypatch):
    import subprocess
    from myzing.render import encoding
    outputs = iter(["120,\n130,\n", "", "N/A\n"])
    monkeypatch.setattr(encoding.subprocess, "run",
                        lambda args, **k: subprocess.CompletedProcess(args, 0, next(outputs), ""))
    assert encoding._audio_bytes("a.mp4", "ffprobe") == 250
    assert encoding._audio_bytes("a.mp4", "ffprobe") == 0
    assert encoding._audio_bytes("a.mp4", "ffprobe") is None


def test_budget_retries_short_overshoot_and_respects_x264_floor(monkeypatch, tmp_path):
    import subprocess
    from myzing.render import encoding
    calls = []
    sizes = iter([130_000, 96_000])

    def run(args, **kwargs):
        calls.append(list(args))
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(args, 0, "4000\n" * 10, "")
        rate = int(args[args.index("-b:v") + 1])
        if args[args.index("-pass") + 1] == "1":
            (tmp_path / "budget-pass1.mp4").write_bytes(b"1")
            return subprocess.CompletedProcess(args, 0, "", "")
        if rate < 40_000:
            return subprocess.CompletedProcess(args, 1, "", "requested bitrate is too low. estimated minimum is 40 kbps")
        (tmp_path / "rendered.mp4").write_bytes(b"x" * next(sizes))
        return subprocess.CompletedProcess(args, 0, "", "frame I:1 Avg QP:20.00 size: 1\n")
    monkeypatch.setattr(encoding.subprocess, "run", run)
    command = ["ffmpeg", "-loglevel", "error", "-crf", "20", str(tmp_path / "rendered.mp4")]
    _, _, receipt = encoding.encode(command, DeliveryEncoding(target_mb=.1), 1, 640, 360, 30, tmp_path)
    # Pass two overshot (130 kB), so it ran again with a smaller video share.
    assert [p["bytes"] for p in receipt["second_passes"]] == [130_000, 96_000]
    assert receipt["achieved_bytes"] <= 100_000 and receipt["audio_bytes"] == 40_000
    assert not receipt["warnings"]
    # A budget below x264's own minimum encodes at that floor and reports the overrun.
    sizes = iter([150_000, 120_000])
    _, _, tight = encoding.encode(command, DeliveryEncoding(target_mb=.05), 1, 640, 360, 30, tmp_path)
    assert tight["video_target_bps"] == 42_000 and any("over the 0.05 MB target" in w for w in tight["warnings"])


def test_captions_keep_one_anchor_instead_of_jumping_between_free_spots():
    import math
    from copy import deepcopy
    from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip
    from myzing.layout.framing import place_captions
    clip = CompositionClip("s", 0, 12, 0, id="clip", asset_id="s")
    # A speaker drifting across the lower half of a 16:9 frame.
    face = FaceTrack("face", [Keyframe(t, Box(.3 + .03 * t, .35, .18, .45)) for t in range(0, 13, 2)], .9)
    texts = ["Hello there", "my name is somebody", "and I make", "very small books for", "children", "every day"]
    captions = [CompositionCaption(text, i * 2 + .1, i * 2 + 1.9, id=f"c{i}", word_timed=False) for i, text in enumerate(texts)]
    plan = Composition(assets=[AssetRef("s", "s", None)], clips=[clip], captions=captions, width=1280, height=720)
    independent = deepcopy(plan)
    place_captions(independent, {"s": [face]}, {"s": (1280, 720)}, _survey=True)
    place_captions(plan, {"s": [face]}, {"s": (1280, 720)})

    def moves(p):
        boxes = [c.layout.box for c in p.captions]
        return [math.hypot((b.center[0] - a.center[0]) * 1280, (b.bottom - a.bottom) * 720) for a, b in zip(boxes, boxes[1:])]
    assert all(c.layout.overlap.safe for c in plan.captions)
    # Independently each event takes its own nearest free spot (jumps of ~400-500 px);
    # with one anchor the free spot beside the drifting speaker holds for all six.
    assert max(moves(independent)) > 400
    assert max(moves(plan)) < 1


def test_one_alignment_and_one_anchor_per_shot():
    from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip
    from myzing.layout.framing import place_captions
    clips = [CompositionClip("s", 0, 6, 0, id="one", asset_id="s"), CompositionClip("s", 6, 12, 6, id="two", asset_id="s")]
    # The speaker sits left in the first shot and right in the second (source clock).
    face = FaceTrack("face", [Keyframe(0, Box(.15, .3, .2, .5)), Keyframe(5.99, Box(.15, .3, .2, .5)),
                              Keyframe(6, Box(.65, .3, .2, .5)), Keyframe(12, Box(.65, .3, .2, .5))], .9)
    texts = ["at first so", "last year was three thousand", "at first when we", "were trying to set", "it up", "for everyone"]
    captions = [CompositionCaption(text, i * 2 + .1, i * 2 + 1.9, id=f"c{i}", word_timed=False,
                                   alignment="left" if i % 2 else "center") for i, text in enumerate(texts)]
    plan = Composition(assets=[AssetRef("s", "s", None)], clips=clips, captions=captions, width=1280, height=720)
    place_captions(plan, {"s": [face]}, {"s": (1280, 720)})
    assert {c.alignment for c in captions} == {"center"} and any("centered" in w for w in plan.warnings)
    assert all(c.layout.overlap.safe for c in captions)
    for shot in (captions[:3], captions[3:]):
        # One baseline per shot; only the widest phrase steps aside (by < 2% of the
        # width) to clear the speaker, and the next phrase stays where it went.
        assert len({round(c.layout.box.bottom, 6) for c in shot}) == 1
        centers = [c.layout.box.center[0] for c in shot]
        assert max(centers) - min(centers) < .02
        assert all(c.layout.reason in ("stable-anchor", "previous-position", "smallest-move") for c in shot)
