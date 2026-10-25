"""CARD1 model, measured units, abstention, comparisons and public boundaries."""

import inspect
import json
from copy import deepcopy

import pytest

from myzing.explain.api import explain_video
from myzing.explain.compare import compare_cards
from myzing.explain.models import Section, StyleCard
from myzing.explain.sections import build_sections, captions, pacing, transitions
from myzing.schemas import Breakdown, VideoMeta, Shot


def breakdown():
    return Breakdown(VideoMeta("test.mp4", "file", duration=12, width=360, height=640, fps=30),
                     shots=[Shot(0, 0, 4), Shot(1, 4, 8), Shot(2, 8, 12)],
                     provenance={"shot_detector": "synthetic oracle", "transition_evidence": []}).to_dict()


def card():
    return StyleCard("test.mp4", "a"*64, 12, build_sections(breakdown()), "recipe.json", [], ["one", "two", "three"])


def test_card_roundtrip_and_copy():
    original = card()
    wire = original.to_dict()
    restored = StyleCard.from_dict(json.loads(json.dumps(wire)))
    assert restored == original
    wire["sections"]["pacing"]["facts"]["cut_times"].append(9)
    assert restored.sections["pacing"].facts["cut_times"] == [4, 8]


@pytest.mark.parametrize("version", [None, 2, True, "1"])
def test_version_rejected(version):
    wire = card().to_dict()
    wire["version"] = version
    with pytest.raises(ValueError):
        StyleCard.from_dict(wire)


def test_nested_version_and_nonfinite_rejected():
    wire = card().to_dict()
    wire["sections"]["audio"]["version"] = 20
    with pytest.raises(ValueError):
        StyleCard.from_dict(wire)
    with pytest.raises(ValueError):
        Section("bad", {"x": float("nan")})


def test_pacing_rates_distribution_and_beats():
    section = pacing(breakdown(), {"beats": [4.03, 8.2], "structure": {"moments": [{"kind": "drop", "time": 8}]}})
    assert section.facts["cuts_per_minute"] == 10
    assert section.facts["shot_seconds"] == {"min": 4, "median": 4, "max": 4, "values": [4, 4, 4]}
    assert section.facts["cuts_on_beats"] == 1
    assert section.facts["drop_alignment"][-1]["delta_seconds"] == 0
    assert section.facts["windows"][1]["change"] == "slower"


def test_missing_measurement_is_not_zero():
    b = breakdown()
    b["shots"] = []
    b["provenance"] = {}
    sections = build_sections(b)
    assert sections["pacing"].facts == {}
    assert sections["audio"].facts["speech_share"] is None
    assert sections["audio"].facts["music_presence_candidate"] is None
    assert sections["color"].facts == {}
    assert all(s.unknowns for s in sections.values())


def test_transitions_keep_unknown_apart():
    b = breakdown()
    b["provenance"]["transition_evidence"] = [dict(signature=kind, start_seconds=i, end_seconds=i+.3, confidence=.8, reason="test") for i, kind in enumerate(["dissolve", "unknown"])]
    s = transitions(b)
    assert len(s.facts["events"]) == len(s.facts["abstentions"]) == 1
    assert s.facts["events"][0]["signature"] == "dissolve"
    assert "Unclassified" in s.unknowns[-1]


def test_caption_height_uses_short_side_and_low_font_score_is_substitute():
    geometry = {"version": 2, "tracks": [dict(id="t1", text="HELLO WORLD", kind="caption", motion="popping", median_text_height=.05,
                   samples=[{"t": 0, "text": "HELLO WORLD", "box": [.1, .7, .9, .75]}])],
                "font_candidates": {"tracks": [{"track_id": "t1", "candidates": [{"family": "Anton", "score": .72}]}]}}
    s = captions(breakdown(), geometry)
    assert s.facts["tracks"][0]["size_percent_short_side"] == pytest.approx(.05*640/360*100)
    assert s.facts["tracks"][0]["zone"] == "lower"
    assert s.facts["tracks"][0]["display"] == "cumulative word popping"
    assert s.facts["font_candidates"][0]["candidates"][0]["label"] == "best substitute"
    assert s.facts["caption_geometry_summary"] is None  # no speech-supported caption role


def test_rejected_ocr_never_becomes_appearance_evidence():
    geometry = {"version": 2, "frames": [{"t": 0, "detections": [{"text": "FAKE", "confidence": .99, "validation": {"accepted": False}, "appearance": {"stroke_width_px": 3}}]}]}
    assert captions(breakdown(), geometry).facts["appearance_samples"] == []


def test_comparison_close_differs_unknown_have_numbers():
    a, b = card(), card()
    result = compare_cards(a, b)["sections"]
    assert result["pacing"]["status"] == "close"
    assert result["color"]["status"] == "unknown"
    assert result["captions"]["status"] == "unknown"
    b.sections["pacing"].facts["shot_seconds"]["median"] = 2
    result = compare_cards(a, b)["sections"]["pacing"]
    assert result["status"] == "differs"
    assert result["metrics"]["median_shot_seconds"]["target"] == 4
    assert result["metrics"]["median_shot_seconds"]["observed"] == 2
    assert result["metrics"]["median_shot_seconds"]["tolerance"] == .4


def test_public_signature_and_download_consent(tmp_path, monkeypatch):
    assert list(inspect.signature(explain_video).parameters) == ["source", "out_dir", "transitions", "offline", "ref_start", "ref_end", "reference_range"]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("unexpected network"))
    result = explain_video("https://example.com/video.mp4", tmp_path / "out")
    assert not result["ok"] and "consent" in result["error"]
    assert not (tmp_path / "out").exists()


def test_no_overwrite_or_source_output(tmp_path):
    media = tmp_path / "clips" / "source.mp4"
    media.parent.mkdir()
    media.write_bytes(b"test")
    assert not explain_video(media, media.parent / "out")["ok"]
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("keep")
    assert "not empty" in explain_video(media, out)["error"]
    assert (out / "keep.txt").read_text() == "keep"


def test_cli_against_and_mcp_wire_contract(monkeypatch, capsys):
    from myzing.explain import command
    from myzing import mcp_server
    seen = []
    def fake(*args, **kwargs):
        seen.append((args, kwargs))
        return {"ok": True, "card_json": "card.json", "card_md": "card.md", "card_png": "card.png", "summary": ["a", "b", "c"]}
    monkeypatch.setattr(command, "_explain", fake)
    assert command.run(["a.mp4", "--against", "b.mp4", "--out", "out", "--json"]) == 0
    assert seen[-1][1]["against"] == "b.mp4"
    assert json.loads(capsys.readouterr().out)["ok"]
    monkeypatch.setattr("myzing.explain.api._explain", fake)
    assert mcp_server.h_zing_explain("a.mp4", "out")["ok"]
    assert seen[-1][1]["allow_download"] is False


def test_palette_known_neutrals():
    from myzing.explain.palette import lab_hex
    assert lab_hex([0, 0, 0]) == "#000000"
    assert lab_hex([100, 0, 0]) == "#ffffff"


# --- CARD1 review fixes: readable card, honest wording, failure hygiene ---

from myzing.explain import plain  # noqa: E402
from myzing.explain.notices import viewer_notices  # noqa: E402
from myzing.explain.presentation import markdown  # noqa: E402
from myzing.explain.sections import audio_section, color, framing, music_evidence  # noqa: E402


def lab(a, b):
    return {"aggregate": {"ab_mean": [a, b], "contrast": 84.1, "saturation": [1, 5, 13.2, 20, 30],
                          "luma_percentiles": [.1, .5, .9], "palette": []},
            "coverage": {}, "confidence": .6, "swatches": []}


def test_moment_events_print_one_time_not_a_zero_range():
    b = breakdown()
    b["provenance"]["transition_evidence"] = [dict(signature="hard_cut", start_seconds=.8, end_seconds=.8, confidence=.9, reason="x")]
    lines = transitions(b).lines
    assert lines[0] == "1 hard cut at 0.80s (score 0.90)."
    assert "0.80-0.80" not in " ".join(lines)
    assert plain.time_span(7.0, 7.7) == "7.00-7.70s"


@pytest.mark.parametrize("a, b, words, banned", [
    (7.0, -10.8, ("cool", "blue"), ("red", "warm")),     # Korky: a* > 0 with b* < 0 is blue, not red
    (20.2, 2.8, ("warm", "red"), ("cool",)),
    (4.7, -1.6, ("have a noticeable magenta",), ("warm", "cool")),
    (0.5, -0.4, ("neutral",), ("warm", "cool", "tint")),
    (-8, 9, ("green",), ("warm", "cool")),
])
def test_color_wording_agrees_with_lab_numbers(a, b, words, banned):
    line = color(lab(a, b)).lines[1]
    head = line.split("(Lab")[0]
    assert all(w in head for w in words), line
    assert not any(w in head for w in banned), line


def test_color_failure_states_the_real_reason():
    section = color(None, "No usable frames were sampled. Check FFmpeg and the input video.")
    assert "No usable frames" in section.lines[0]
    assert "install" not in section.unknowns[0]


@pytest.mark.parametrize("text, ok", [
    ("n 151 mo of run time → T's on M1/conedtor ~ 113 1bs/RFTA → Process", False),
    ("a 151 ha of run time or ~113 16s/RFTA", False),
    ("4RFTA APP Now plurbig AVo/ +131bs brine ARTA Ulege ARTA QD2", False),
    ("CoveR\"", False), ("→ drain backfll with Brne", False), ("Bln", False), ("and", False),
    ("Mission Elapsed Time: 0h 16m 14s", True), ("Solar Panels Deployed Altitude: 484 km/301 miles", True),
    ("Ascent/Entry Simulator", True), ("NASA", True), ("IAN HUBERT", True),
    ("THIS IS AN OFFICIAL CIVIL DEFENSE FILM PRODUCED IN CO-OPERATION WITH", True),
])
def test_only_plausible_ocr_is_quotable(text, ok):
    assert plain.plausible_text(text) is ok


def geometry_with(text, confidences, kind="caption"):
    frames = [{"t": i * .5, "detections": [{"text": text, "confidence": c, "validation": {"accepted": True}}]}
              for i, c in enumerate(confidences)]
    samples = [{"sample_index": i, "t": i * .5, "text": text, "box": [.1, .1, .9, .2], "detection_indices": [0]}
               for i in range(len(confidences))]
    return {"version": 2, "frames": frames,
            "tracks": [dict(id="t1", text=text, kind=kind, motion="static", median_text_height=.05, samples=samples)]}


def test_garbled_or_weak_ocr_stays_in_json_not_in_readable_lines():
    garbled = "n 151 mo of run time → T's on M1/conedtor ~ 113 1bs/RFTA"
    section = captions(breakdown(), geometry_with(garbled, [.92, .93]))
    assert section.facts["tracks"][0]["text"] == garbled and section.facts["tracks"][0]["quotable"] is False
    assert garbled[:20] not in " ".join(section.lines)
    weak = captions(breakdown(), geometry_with("Mission Elapsed Time", [.7, .72]))
    assert weak.facts["tracks"][0]["ocr_confidence"] == pytest.approx(.71)
    assert "Mission" not in " ".join(weak.lines)
    good = captions(breakdown(), geometry_with("Mission Elapsed Time", [.97, .98]))
    assert '"Mission Elapsed Time"' in " ".join(good.lines)


def test_weak_music_candidate_is_never_a_headline_fact():
    b = breakdown()
    b["audio"] = {"has_music": True, "music_confidence": .777, "speech_ratio": .773}
    b["provenance"]["vad"] = "silero"
    section = audio_section(b, None)
    text = " ".join(section.lines)
    assert "candidate detected" not in text and "music not confirmed" in text
    assert section.facts["music_evidence"] == "weak"
    assert music_evidence(.77, True, .8, {"bpm": 120.0})[0] == "moderate"
    assert "probably music" in music_evidence(0.0, True, .6, None)[1]


def test_no_audio_stream_is_said_plainly():
    b = breakdown()
    b["warnings"] = ["no audio stream: transcription and audio measurements will be skipped"]
    section = audio_section(b, None)
    assert section.lines == ["No audio track in this file."]
    assert section.facts["has_audio_stream"] is False


def full_card():
    b = breakdown()
    b["audio"] = {"has_music": True, "music_confidence": .777, "speech_ratio": .773}
    b["provenance"]["vad"] = "silero"
    b["shots"] = [{"index": 0, "start": 0, "end": 12}]
    geometry = {"version": 2, "frames": [{"t": t, "detections": [], "face_boxes": [[.3, .2, .7, .58]]} for t in (1, 5, 10)], "tracks": []}
    matte = {"version": 1, "status": "measured", "kind": "none", "samples_informative": 7, "active_size": [360, 640],
             "bars": {"top": 0, "bottom": 0, "left": 0, "right": 0}, "active_box": [0, 0, 1, 1]}
    sections = build_sections(b, geometry, None, lab(7.0, -10.8), matte=matte)
    from myzing.explain.api import get_look_commands
    return StyleCard("ref.mp4", "a"*64, 12, sections, "card/style-recipe.json",
                     get_look_commands("clips/ref.mp4", "card/style-recipe.json"), viewer_notices(sections, 12))


def test_viewer_notices_lead_in_editor_language():
    card = full_card()
    assert 3 <= len(card.summary) <= 5
    first = card.summary[0]
    assert "continuous" in first and "vertical 9:16" in first and "talking-head" in first and "full frame" in first
    joined = " ".join(card.summary)
    assert "No on-screen text" in joined and "music not confirmed" in joined and "cool" in joined
    md = markdown(card)
    assert md.index("## What a viewer notices") < md.index("## Get this look") < md.index("## Cuts and pacing")


def test_markdown_has_one_short_not_knowable_line_per_section_and_real_commands():
    card = full_card()
    md = markdown(card)
    assert md.count("Not knowable from pixels:") == len(card.sections)
    assert "further limitations" not in md and "Unknown:" not in md and "Open card.md" not in md
    for section in card.sections.values():
        for unknown in section.unknowns:
            assert unknown not in md  # the full lists stay in card.json
    assert "zing match 'clips" in md and "--clips ./my-clips" in md
    assert "zing plan drafts ./my-edit --recipe 'card" in md and "style-recipe.json" in md
    assert "zing color match --reference 'clips" in md and "zing color apply --lut ./my-look/look.cube" in md


def test_framing_reports_display_size_and_baked_bars():
    b = breakdown()
    display = {"stored_width": 640, "stored_height": 360, "display_width": 360, "display_height": 640,
               "rotation": 90, "sample_aspect_ratio": "1:1"}
    matte = {"version": 1, "status": "measured", "kind": "pillarbox", "samples_informative": 7, "active_size": [202, 640],
             "bars": {"top": 0, "bottom": 0, "left": .22, "right": .22}, "active_box": [.22, 0, .78, 1]}
    section = framing(b, {}, display, matte)
    assert section.facts["width"] == 360 and section.facts["aspect"] == pytest.approx(.5625)
    assert "stored 640 x 360, rotated 90 degrees" in section.lines[0]
    assert "Pillarboxed" in section.lines[1] and "202 x 640" in section.lines[1]


def test_bars_in_frame_finds_solid_edges_and_ignores_blank_frames():
    from myzing.explain.matte import bars_in_frame
    w, h = 40, 20
    rows = [bytes(0 if x < 8 or x >= 32 else (y * 7 + x * 13) % 200 + 40 for x in range(w)) for y in range(h)]
    result = bars_in_frame(b"".join(rows), w, h)
    assert result["left"] == pytest.approx(.2) and result["right"] == pytest.approx(.2)
    assert result["top"] == 0 and result["bottom"] == 0
    assert bars_in_frame(bytes(w * h), w, h) is None


def test_pacing_windows_never_end_in_a_sliver():
    b = breakdown()
    b["meta"]["duration"] = 20.0005
    b["shots"] = [{"index": 0, "start": 0, "end": 10}, {"index": 1, "start": 10, "end": 20.0005}]
    windows = pacing(b, None).facts["windows"]
    assert all(w["end"] - w["start"] >= 2 for w in windows)
    assert windows[-1]["end"] == 20.0005


def test_transition_comparison_uses_rates_for_different_durations():
    def with_cuts(n, duration):
        c = card()
        c.duration_seconds = duration
        c.sections["transitions"] = Section("Transitions", {"events": [
            {"signature": "hard_cut", "start_seconds": i, "end_seconds": i, "confidence": .9} for i in range(n)]})
        return c
    reference = with_cuts(21, 20.0)
    assert compare_cards(reference, with_cuts(7, 6.0))["sections"]["transitions"]["status"] == "close"
    assert compare_cards(reference, with_cuts(0, 6.0))["sections"]["transitions"]["status"] == "differs"
    none = compare_cards(with_cuts(0, 20.0), with_cuts(0, 6.0))["sections"]["transitions"]
    assert none["status"] == "close" and "either" in none["reason"]


def test_failed_explain_removes_its_partial_output_so_retry_works(tmp_path, monkeypatch):
    from myzing.explain import api
    media = tmp_path / "clips" / "source.mp4"
    media.parent.mkdir()
    media.write_bytes(b"x")
    monkeypatch.setattr(api, "probe_video", lambda path: {})
    def broken(source, out, **kw):
        (out / "evidence").mkdir()
        (out / "style-recipe.json").write_text("{}")
        raise RuntimeError("measurement failed")
    monkeypatch.setattr(api, "_measure", broken)
    out = tmp_path / "card"
    assert api.explain_video(media, out)["error"] == "measurement failed"
    assert not out.exists()
    out.mkdir()  # an existing empty folder is kept, emptied of this call's files
    assert not api.explain_video(media, out)["ok"]
    assert out.is_dir() and list(out.iterdir()) == []
    (out / "keep.txt").write_text("keep")  # a nonempty folder is refused and untouched
    assert "not empty" in api.explain_video(media, out)["error"]
    assert [p.name for p in out.iterdir()] == ["keep.txt"]


def test_unreadable_inputs_fail_before_outputs(tmp_path):
    empty = tmp_path / "clips" / "empty.mp4"
    empty.parent.mkdir()
    empty.write_bytes(b"")
    result = explain_video(empty, tmp_path / "card")
    assert "empty (0 bytes)" in result["error"] and not (tmp_path / "card").exists()


def test_probe_applies_rotation_and_pixel_aspect(monkeypatch):
    from types import SimpleNamespace
    from myzing.explain import api
    from myzing.study import proc
    def fake(streams):
        payload = json.dumps({"streams": streams, "format": {"duration": "4.0"}})
        monkeypatch.setattr(proc, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=payload, stderr=""))
    fake([{"codec_type": "video", "width": 320, "height": 180, "avg_frame_rate": "30/1", "r_frame_rate": "30/1",
           "side_data_list": [{"rotation": -90}]}])
    rotated = api.probe_video("rotated.mp4")
    assert (rotated["display_width"], rotated["display_height"], rotated["rotation"]) == (180, 320, 270)
    fake([{"codec_type": "video", "width": 360, "height": 360, "sample_aspect_ratio": "16:9", "avg_frame_rate": "30/1",
           "r_frame_rate": "30/1"}, {"codec_type": "audio"}])
    anamorphic = api.probe_video("anamorphic.mp4")
    assert (anamorphic["display_width"], anamorphic["display_height"], anamorphic["has_audio"]) == (640, 360, True)
    fake([{"codec_type": "audio"}])
    with pytest.raises(ValueError, match="no video stream"):
        api.probe_video("audio.m4a")


def test_png_is_optional_when_pillow_is_missing(tmp_path, monkeypatch):
    from myzing.explain import api, presentation
    def missing(*a, **k):
        raise ImportError("The PNG card needs Pillow; install myzing[memes] (no model download).")
    monkeypatch.setattr(presentation, "render_png", missing)
    result = api._publish(full_card(), tmp_path / "media.mp4", tmp_path)
    assert result["ok"] and result["card_png"] is None
    stored = json.loads((tmp_path / "card.json").read_text(encoding="utf-8"))
    assert any("Pillow" in w for w in stored["warnings"]) and (tmp_path / "card.md").exists()


@pytest.mark.parametrize("kwargs, message", [
    ({"out_dir": 5}, "nonempty folder path"), ({"out_dir": "  "}, "nonempty folder path"),
    ({"out_dir": "out", "against": ""}, "against must be"), ({"out_dir": "out", "against": 7}, "against must be"),
    ({"out_dir": "out", "offline": "false"}, "booleans"),
])
def test_mcp_explain_validates_arguments_before_any_work(kwargs, message, tmp_path, monkeypatch):
    from myzing import mcp_server
    monkeypatch.chdir(tmp_path)
    result = mcp_server.h_zing_explain("a.mp4", **kwargs)
    assert not result["ok"] and message in result["error"]
    assert list(tmp_path.iterdir()) == []


def test_zero_duration_is_unknown_pacing_not_a_crash():
    b = Breakdown(VideoMeta("z.mp4", "file", duration=0, width=360, height=640, fps=30), shots=[Shot(0, 0, 0)],
                  provenance={"transition_evidence": []}).to_dict()
    sections = build_sections(b)
    assert sections["pacing"].facts == {} and "no measurable duration" in sections["pacing"].lines[0]
    zero = StyleCard("z.mp4", "a"*64, 0, sections, "r.json", [], viewer_notices(sections, 0))
    assert "cut timing unknown" in zero.summary[0]
    assert compare_cards(card(), zero)["sections"]["transitions"]["status"] == "unknown"
    with pytest.raises(ValueError):
        StyleCard("z.mp4", "a"*64, -1, sections, "r.json", [], ["a", "b", "c"])


def test_interrupted_run_leaves_a_marker_that_allows_a_retry(tmp_path, monkeypatch):
    from myzing.explain import api
    media = tmp_path / "clips" / "source.mp4"
    media.parent.mkdir()
    media.write_bytes(b"x")
    monkeypatch.setattr(api, "probe_video", lambda path: {})
    out = tmp_path / "card"
    def interrupted(source, out, **kw):
        (out / "evidence").mkdir()
        raise KeyboardInterrupt
    monkeypatch.setattr(api, "_measure", interrupted)
    with pytest.raises(KeyboardInterrupt):
        api.explain_video(media, out)
    assert not out.exists()  # Ctrl-C still cleans up before stopping
    # A hard kill (power loss) leaves the marker; the same --out is reusable.
    (out / "evidence" / "breakdowns").mkdir(parents=True)
    (out / "style-recipe.json").write_text("{}")
    (out / api.PARTIAL_MARKER).write_text("{}")
    def failed(source, out, **kw):
        raise RuntimeError("second attempt reached measurement")
    monkeypatch.setattr(api, "_measure", failed)
    assert api.explain_video(media, out)["error"] == "second attempt reached measurement"
    # The marker never licenses removing someone else's files.
    out.mkdir(exist_ok=True)
    (out / api.PARTIAL_MARKER).write_text("{}")
    (out / "notes.txt").write_text("mine")
    assert "not empty" in api.explain_video(media, out)["error"]
    assert (out / "notes.txt").read_text() == "mine"


def test_default_output_guard_resolves_a_linked_cwd(tmp_path, monkeypatch):
    import os
    from myzing.explain import api
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "a.mp4").write_bytes(b"x")
    link = tmp_path / "link"
    try:
        os.symlink(clips, link, target_is_directory=True)
    except OSError:  # Windows without symlink rights: a junction needs none
        import _winapi
        _winapi.CreateJunction(str(clips), str(link))
    monkeypatch.chdir(link)
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(api, "probe_video", lambda path: {})
    chosen = []
    def stop(source, out, **kw):
        chosen.append(out)
        raise RuntimeError("stop")
    monkeypatch.setattr(api, "_measure", stop)
    assert api.explain_video(clips / "a.mp4", None)["error"] == "stop"
    assert clips.resolve() not in chosen[0].resolve().parents


def test_one_unreadable_caption_role_track_is_hedged(monkeypatch):
    import myzing.study.text_roles as text_roles
    def roles(b, geometry):
        return {"events": [{"role": "caption", "features": {"matched_tracks": ["t1"]}}], "counts": {"caption": 1}}
    monkeypatch.setattr(text_roles, "classify_text", roles)
    monkeypatch.setattr(text_roles, "caption_geometry", lambda geometry, r: {"tracks": []})
    section = captions(breakdown(), geometry_with('CoveR"', [.86, .88]))
    text = " ".join(section.lines)
    assert "1 speech caption," in text or "1 speech caption." in text
    assert "Caption-like text (role uncertain) style" in text
    sections = build_sections(breakdown())
    sections["captions"] = section
    assert "uncertain" in viewer_notices(sections, 12)[2]


def test_ranges_and_signs_read_cleanly():
    b = breakdown()
    b["provenance"]["transition_evidence"] = [dict(signature="dissolve", start_seconds=7, end_seconds=7.7, confidence=.83, reason="x")]
    assert transitions(b).lines[0] == "1 dissolve (7.00-7.70s, score 0.83)."
    assert plain.signed(-0.04) == "+0.0" and plain.signed(-10.84) == "-10.8"
    assert "b* +0.0" in color(lab(0.2, -0.0001)).lines[1]


def test_card_json_lists_are_bounded_with_totals():
    from myzing.explain import sections as S
    text = "Mission Elapsed Time"
    many = geometry_with(text, [.97] * 30)
    track = many["tracks"][0]
    many["tracks"] = [{**track, "id": f"t{i}"} for i in range(S.MAX_TRACKS + 25)]
    section = captions(breakdown(), many)
    assert len(section.facts["tracks"]) == S.MAX_TRACKS
    assert section.facts["truncated"]["totals"]["tracks"] == S.MAX_TRACKS + 25
    row = section.facts["tracks"][0]
    assert row["sample_count"] == 30 and len(row["samples"]) == S.MAX_TRACK_SAMPLES
    assert f"{S.MAX_TRACKS + 25} text regions read" in section.lines[0]  # prose uses the full count


def test_truncated_audio_says_which_part_was_measured():
    b = breakdown()
    b["meta"]["duration"] = 1200
    audio = {"tempo": {"status": "none", "bpm": None, "confidence": 0}, "loudness": {"integrated_lufs": -29.5, "true_peak_dbtp": -18.4},
             "structure": {"moments": []}, "duration_seconds": 600.0, "truncated": True, "warnings": []}
    lines = audio_section(b, audio).lines
    assert any("first 600.0s of 1200.0s only" in line for line in lines)
