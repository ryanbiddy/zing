"""Executed review regressions: punctuation, UI chrome, shot ends and URL guards."""

from dataclasses import replace
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("tokens,expected", [
    (["in", "2026,", "40", "people"], "in 2026, 40 people"),
    (["in", "2026", ",", "40", "people"], "in 2026, 40 people"),
    (["1,", "2,", "3"], "1, 2, 3"),
    (["1", ",", "2", ",", "3"], "1, 2, 3"),
    (["see", "3.", "2", "people"], "see 3. 2 people"),
    (["about", "2024,", "100", "people"], "about 2024, 100 people"),
    (["about", "2024", ",", "100", "people"], "about 2024, 100 people"),
    (["$3", ",000"], "$3,000"),
    (["3", ".5", "%"], "3.5%"),
    (["1", ",200", ",000"], "1,200,000"),
    (["$", "3", ",", "000", ".", "50"], "$3,000.50"),
    (["cost", "$", "3", ",000", ".50", "today"], "cost $3,000.50 today"),
])
def test_executed_numeric_cases(tokens, expected):
    from myzing.captions.grouping import join, group_words
    from myzing.schemas import Word
    words = [Word(t, i * .15, (i+1) * .15) for i, t in enumerate(tokens)]
    original = [(w.text, w.start, w.end) for w in words]
    assert join(w.text for w in words) == expected
    from myzing.captions.presets import normalize_words
    assert [(w.text, w.start, w.end) for w in normalize_words(words)] == original
    groups, lines, *_ = group_words(words, lambda ts: len(join(ts)), 100,
                                    preset="box", end=len(words) * .15 + 1)
    assert " ".join(" ".join(line) for line in lines) == expected
    assert [(w.text, w.start, w.end) for g in groups for w in g] == original


@pytest.mark.parametrize("tokens", [["1,", "2,", "3"], ["1", ",", "2", ",", "3"], ["3.", "2"]])
def test_list_and_sentence_numbers_can_split_cues(tokens):
    from myzing.captions.grouping import join, group_words
    from myzing.schemas import Word
    words = [Word(t, i * .3, (i+1) * .3) for i, t in enumerate(tokens)]
    groups, *_ = group_words(words, lambda ts: len(join(ts)), 3, preset="box", end=3)
    assert len(groups) >= 2
    assert [w for g in groups for w in g] == words


def test_dark_mode_ui_with_sparse_icons_and_titles_stays_uncropped():
    np = pytest.importorskip("numpy")
    from myzing.layout.picture import detect_picture
    frames = np.full((12, 100, 160), 18, dtype=np.uint8)
    frames[:, 12:80, 16:144] = np.random.default_rng(42).integers(8, 29, (12, 68, 128), dtype=np.uint8)
    frames[:, 3:8, 12:32] = 240
    frames[:, 87:91, 20:35] = 200
    frames[:, 87:91, 40:55] = 200
    result = detect_picture(frames)
    assert result["geometric_confidence"] >= .8
    assert result["surround"]["spatial_std"] > 6
    assert result["surround"]["flat_fraction"] >= .75
    assert not result["confident"] and result["surround"]["kind"] != "chrome"
    assert "no wide" in result["reason"]


@pytest.mark.parametrize("faces,detector", [(0, "hog-fallback"), (2, "hog-fallback"),
                                          (1, "yolox-s-int8"), (1, "mediapipe-person-head"), (1, "")])
def test_single_head_rule_keeps_other_or_unattributed_people(faces, detector):
    from myzing.layout.crop_planner import select_framing
    from myzing.layout.types import Box, FaceTrack, Keyframe, TrackObservation
    from myzing.composition import CompositionClip
    box = Box(.02, .02, .96, .96)
    person = FaceTrack("person-enclosing", [Keyframe(0, box), Keyframe(12-1e-7, box)], .9,
                       observations=[TrackObservation(0, box, detector=detector)] if detector else [])
    face = FaceTrack("face-0", [Keyframe(0, Box(.4, .15, .15, .35)), Keyframe(12-1e-7, Box(.4, .15, .15, .35))], .95)
    tracks = [person, *[replace(face, id=f"face-{i}") for i in range(faces)]]
    framed = select_framing("auto", 640, 360, 720, 1280, CompositionClip("v", 0, 12, 0, id="c", asset_id="v"), tracks)
    assert not any("enclosing HOG" in w for w in framed.warnings)


@pytest.mark.parametrize("trim", [{}, {"ref_start": 30, "ref_end": 80}])
def test_http_reference_is_checked_before_normalize_or_study(tmp_path, monkeypatch, zing_workspace, trim):
    from myzing.match import api
    clips = tmp_path / "clips"
    clips.mkdir()
    source = tmp_path / "download.mp4"
    source.write_bytes(b"acquisition only; no network")
    events = []
    def acquire(*args, **kwargs):
        events.append("acquire")
        return source, {}, None
    def probe(path):
        assert path == source
        events.append("probe")
        return SimpleNamespace(duration=120)
    def study(path, *args, **kwargs):
        assert trim and kwargs["ref_start"] == 30 and kwargs["ref_end"] == 80
        assert events == ["acquire", "probe"]
        events.append("study selected range")
        raise RuntimeError("selected range reached study")
    monkeypatch.setattr("myzing.study.ingest._acquire_url_media", acquire)
    monkeypatch.setattr("myzing.study.ingest.ingest", lambda *a, **k: pytest.fail("full ingest before duration guard"))
    monkeypatch.setattr("myzing.study.ingest._normalize", lambda *a, **k: pytest.fail("normalize before duration guard"))
    monkeypatch.setattr("myzing.project.probe.probe_file", probe)
    monkeypatch.setattr(api, "_study", study)
    monkeypatch.setattr("myzing.match.preflight.check", lambda *a, **k: {"problems": [], "warnings": []})
    monkeypatch.setattr("myzing.match.preflight.check_reference", lambda *a, **k: None)
    result = api.match("https://example.invalid/long.mp4", str(clips), str(tmp_path / "out"),
                       answers={}, allow_download=True, **trim)
    if trim:
        assert events == ["acquire", "probe", "study selected range"]
        assert result["failures"][0]["step"] == "reference-study"
    else:
        assert events == ["acquire", "probe"]
        assert result["failures"][0]["step"] == "reference-resolve"
        assert "supported limit is 60s" in result["failures"][0]["error"]


@pytest.mark.parametrize("extra,expected", [({}, 10), ({"duration_ts": 1, "time_base": "1/90000"}, 10),
                                         ({"nb_frames": None, "duration": "10.0"}, 10)])
def test_picture_duration_fallback_is_a_span_not_an_absolute_timestamp(extra, expected):
    from myzing.project.probe import video_duration
    stream = {"nb_frames": "300", "avg_frame_rate": "30/1", "start_time": "1.5", **extra}
    assert video_duration(stream, {"duration": "12.5"}) == expected


def test_analysis_budget_has_distinct_cache_identity():
    from myzing.reference_range import slug
    assert len({slug("a.mp4"), slug("a.mp4", analysis_seconds=60), slug("a.mp4", analysis_seconds=30),
                slug("a.mp4", analysis_seconds=60, analysis_max_side=960)}) == 4


def test_actual_length_shortage_does_not_get_variety_label(tmp_path):
    from myzing.director.selection import candidates, Envelope
    from myzing.director.models import ClipStudy, PlanningShortage
    from myzing.schemas import Shot
    from myzing.studio.presentation import creator_summary
    study = ClipStudy("clip", "clip.mp4", "sha", 12, "ready", shots=[Shot(0, 0, 12)])
    with pytest.raises(PlanningShortage) as error:
        candidates([study], {}, {}, Envelope(2, None, None, 3, 0, "lower", {}), 20)
    result = {"project": str(tmp_path), "status": "shortage", "warnings": [],
              "result": {"shortages": [error.value.shortage.to_dict()]}}
    notes = creator_summary(result, {"path": "b"}, {})["notes"]
    assert "not enough usable moments" in notes[0] and "VARIETY" not in str(notes)


@pytest.mark.parametrize("duration", [59.99, 60, 60.01, 600, 86400])
def test_geometry_schedule_and_coverage_remain_bounded(duration):
    from myzing.study import caption_geometry as cg
    schedule = cg.sample_schedule(duration)
    assert len(schedule) <= cg.MAX_FRAMES
    result = cg.CaptionGeometry(duration, [cg.FrameSample(t, t, step, i, 640, 360, status="low_confidence")
                                          for i, (t, step) in enumerate(schedule)])
    coverage = cg._coverage(result, schedule)
    assert len(coverage["low_confidence_frames"]) <= cg.MAX_FRAMES
    assert len(coverage["unsampled_intervals"]) <= cg.MAX_FRAMES + 1


def test_uoink_study_trim_dispatch_is_local_mock_only(monkeypatch, zing_workspace):
    from myzing import mcp_server as mcp
    seen = []
    monkeypatch.setattr(mcp.shutil, "which", lambda s: s)
    monkeypatch.setattr(mcp, "_study_api", lambda: SimpleNamespace(study=lambda source, kept_media=None, handoff=None: None))
    monkeypatch.setattr("myzing.uoink_bridge.resolve_kept_media", lambda ref: {"ok": True, "data": {
        "item_ref": ref, "state": "available", "source_url": "https://example.invalid/ref.mp4",
        "media": {"path": "fixture.mp4", "sha256": "0"*64, "byte_length": 10}}})
    monkeypatch.setattr(mcp, "_dispatch_study", lambda *a, **k: seen.append(k) or {"ok": True})
    assert mcp.h_study_uoink_item("uoink://item/fixture", reference_range="0:30-1:20")["ok"]
    assert seen[0]["trim"] == {"reference_range": "0:30-1:20"}
    assert not mcp.h_study_uoink_item("uoink://item/fixture", ref_start=30, ref_end=20)["ok"]
    assert len(seen) == 1
