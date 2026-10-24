"""Real-footage workflow regressions, with no models or external media."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import reference_range as rr


@pytest.mark.parametrize("start,end", [("0:30", "1:20"), (30, 80), ("30", "80")])
def test_reference_times(start, end):
    assert rr.parse(start, end) == (30., 80.)
    assert rr.parse(reference_range="0:30-1:20") == (30., 80.)
    assert rr.slug("video.mp4", start, end) == rr.slug("video.mp4", reference_range="0:30-1:20")
    assert rr.slug("video.mp4", start, end) != rr.slug("video.mp4")


@pytest.mark.parametrize("values", [("nan", 30, None), (-1, 2, None), (4, 3, None),
                                    (True, 2, None), ("1:60", 130, None), (0, 20, "0-20")])
def test_bad_reference_ranges(values):
    with pytest.raises(ValueError):
        rr.parse(*values)


def test_repeated_url_trim_keeps_original_download(zing_workspace, monkeypatch):
    from myzing.study import ingest
    def acquire(source, slug, folder, *args):
        path = folder / "media.mp4"
        if not path.exists():
            path.write_bytes(b"original source")
        assert path.read_bytes() == b"original source"
        return path, {}, None
    def select(source, folder, *args, **kwargs):
        assert source.read_bytes() == b"original source"
        path = folder / "reference-selection.mp4"
        path.write_bytes(b"selected interval")
        return path, {"analysis_limited": False}
    monkeypatch.setattr(ingest, "_acquire_url_media", acquire)
    monkeypatch.setattr(rr, "select_local", select)
    monkeypatch.setattr(ingest, "probe", lambda p: {"streams": [{"codec_type": "video", "width": 320,
                        "height": 180, "duration": "12", "avg_frame_rate": "30/1"}]})
    monkeypatch.setattr(ingest, "_needs_normalize", lambda stream: (False, ""))
    monkeypatch.setattr(ingest, "_check_frame_timing", lambda *a: (False, ""))
    for _ in range(2):
        result = ingest.ingest("https://example.invalid/reference.mp4", ref_start=30, ref_end=42)
        assert result.media_path.read_bytes() == b"selected interval"
        assert result.meta.media_path == "media.mp4"


def test_explain_url_acquisition_does_not_normalize_full_reference(tmp_path, monkeypatch):
    from myzing.explain.api import _resolve
    from myzing.study import ingest
    monkeypatch.setattr(ingest, "ingest", lambda *a, **k: pytest.fail("full reference ingest before analysis budget"))
    def acquire(source, slug, folder, *args):
        media = folder / "media.mp4"
        media.write_bytes(b"download fixture; no network")
        return media, {}, None
    monkeypatch.setattr(ingest, "_acquire_url_media", acquire)
    assert _resolve("https://example.invalid/reference.mp4", tmp_path, allow_download=True).is_file()


def test_reference_interview_refuses_long_before_preview_or_study(tmp_path, monkeypatch):
    from myzing.studio import flow
    source = tmp_path / "long.mp4"
    source.touch()
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(to_dict=lambda: {"duration": 1236.366}))
    monkeypatch.setattr(flow.evidence, "collect", lambda *a: pytest.fail("preview must not run before trim choice"))
    result = flow.next_step({"path": "a", "reference": str(source)})
    assert result["status"] == "question"
    assert result["question"]["id"] == "reference_range"
    assert "60s" in result["question"]["prompt"] and "0:30-1:20" in result["question"]["prompt"]
    with pytest.raises(ValueError, match="supported limit"):
        flow.next_step({"path": "a", "reference": str(source), "reference_range": "all"})


def test_match_checks_duration_before_study(tmp_path, monkeypatch):
    from myzing.match import api
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(duration=1236.366))
    monkeypatch.setattr(api, "study", lambda *a, **k: pytest.fail("must fail before study"))
    with pytest.raises(ValueError, match="--ref-start 0:30 --ref-end 1:20"):
        api._study(tmp_path / "long.mp4", tmp_path, max_seconds=60)


def test_video_duration_ignores_container_audio_padding():
    from myzing.project.probe import parse_probe
    from myzing.study.ingest import _duration
    video = {"codec_type": "video", "width": 640, "height": 360, "avg_frame_rate": "30/1",
             "r_frame_rate": "30/1", "duration_ts": 192512, "time_base": "1/15360",
             "duration": "12.533333", "nb_frames": "376"}
    data = {"streams": [video, {"codec_type": "audio"}], "format": {"duration": "12.566341"}}
    assert parse_probe(data).duration == 376 / 30
    assert _duration(data, video) == 376 / 30


@pytest.mark.parametrize("tokens,expected", [(["$3", ",000"], "$3,000"),
    (["$", "3", ",", "000", ".", "50"], "$3,000.50"), (["12", ".5", "%"], "12.5%"),
    (["€", "2", ",000"], "€2,000"), (["cost", "$", "3", "today"], "cost $3 today"),
    (["hello,", "world"], "hello, world"), (["2026", "10"], "2026 10")])
def test_number_join_preserves_word_tokens_and_timing(tokens, expected):
    from myzing.captions.grouping import join
    from myzing.schemas import Word
    words = [Word(t, i*.3, (i+1)*.3) for i, t in enumerate(tokens)]
    before = [(w.text, w.start, w.end) for w in words]
    assert join(w.text for w in words) == expected
    assert [(w.text, w.start, w.end) for w in words] == before
    from myzing.captions.presets import normalize_words
    normalized = normalize_words(words)
    assert [(w.text, w.start, w.end) for w in normalized] == before


def test_brief_only_one_twelve_second_moment_is_a_variety_limit():
    from myzing.director.selection import choose, Candidate, Envelope
    from myzing.director.models import ClipStudy
    from myzing.schemas import Shot
    study = ClipStudy("clip", "clip.mp4", "sha", 12, "ready", shots=[Shot(0, 0, 12)])
    pool = [Candidate("clip", "sha", 0, 12, 0, 0, None, "", False, False)]
    evidence = {}
    selected = choose(pool, [], [study], Envelope(2, None, None, 3, 0, "lower", {}), 12, 30, 0,
                      timing_evidence=evidence)
    assert list(selected) == ["A"] and selected["A"][0].duration == 12
    search = next(iter(evidence["A"].values()))["search"]["distinctness_relaxed"]
    assert search["missing_drafts"] == ["B", "C"] and "VARIETY" in search["reason"]


def test_creator_summary_names_variety_even_with_resolution_warnings(tmp_path):
    from myzing.studio.presentation import creator_summary
    result = {"project": str(tmp_path), "status": "ready", "warnings": ["VARIETY limit: one distinct draft"],
              "result": {"deliveries": {"A": {"deliveries": {"9:16": {"video": "draft.mp4"}}}}}}
    summary = creator_summary(result, {"path": "b", "aspects": ["9:16"]}, {"clips": [{"width": 360, "height": 640}]})
    assert summary["notes"][0].startswith("VARIETY limit: delivered 1")
    assert "Add clips or shorten" not in str(summary)


def test_studio_short_side_and_caption_box_survive_brief():
    from myzing.studio.flow import normalize_answers, brief_answers
    answers = normalize_answers({"path": "b", "short_side": 720, "caption_mode": "box",
                                "topic": "A moment", "tone": "natural", "platform": "original",
                                "aspects": ["16:9", "1:1", "9:16"], "length": 12, "music": "original"})
    brief = brief_answers(answers)
    assert brief["short_side"] == 720 and brief["caption_mode"] == "box"
    with pytest.raises(ValueError, match="multiple of 18"):
        normalize_answers({"short_side": 721})


def test_brief_cli_short_side(tmp_path, monkeypatch, capsys):
    from myzing.brief import command
    monkeypatch.setattr(command, "load_project", lambda p: None)
    monkeypatch.setattr(command, "save_brief", lambda p, b, **k: b)
    monkeypatch.setattr(command, "brief_result", lambda p, b: {"short_side": b.short_side})
    assert command.run(["new", str(tmp_path), "--answers", "{}", "--short-side", "720", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["short_side"] == 720


@pytest.mark.parametrize("tokens", [["$3", ",000", ".50"], ["$", "3", ",", "000", ".", "50"]])
def test_box_numeric_slots_have_no_inserted_space_or_changed_timing(tokens):
    from test_caption2 import plan
    from myzing.schemas import Word
    from myzing.captions.presets import apply_preset
    from myzing.layout.framing import place_captions
    from myzing.captions.render import geometry
    p = plan("Cost three thousand dollars", width=1280, height=720)
    words = [Word(t, .2+i*.2, .2+(i+1)*.2) for i,t in enumerate(tokens)]
    p.captions[0].words = words
    p.captions[0].text = " ".join(tokens)
    apply_preset(p, "box", vad=False)
    place_captions(p, {}, {})
    assert len(p.captions) == 1 and p.captions[0].text == "$3,000.50"
    slots = geometry(p.captions[0], p.width, p.height)["slots"]
    assert all(a["x"]+a["width"] == pytest.approx(b["x"]) for a,b in zip(slots,slots[1:]))
    assert [(w.start,w.end) for w in p.captions[0].words] == [(w.start,w.end) for w in words]


def test_cli_reference_options_reach_match_and_explain(tmp_path, monkeypatch):
    from myzing.match import command as match
    from myzing.explain import command as explain
    seen = []
    monkeypatch.setattr(match, "validate", lambda **k: None)
    monkeypatch.setattr(match, "execute", lambda k, **kw: seen.append(k) or {"status": "ready"})
    assert match.run(["ref.mp4", "--clips", str(tmp_path), "--out", str(tmp_path / "out"),
                      "--answers", "{}", "--ref-start", "0:30", "--ref-end", "1:20", "--short-side", "720"]) == 0
    assert seen[0]["ref_start"] == "0:30" and seen[0]["answers"]["short_side"] == 720
    monkeypatch.setattr(explain, "_explain", lambda *a, **k: seen.append(k) or {"ok": False, "error": "fixture"})
    assert explain.run(["ref.mp4", "--reference-range", "0:30-1:20"]) == 1
    assert seen[1]["reference_range"] == "0:30-1:20"


def test_mcp_reference_options_reach_study_and_explain(tmp_path, monkeypatch, zing_workspace):
    from myzing import mcp_server as mcp
    path = tmp_path / "ref.mp4"
    path.touch()
    seen = []
    monkeypatch.setattr(mcp.shutil, "which", lambda s: s)
    monkeypatch.setattr(mcp, "_study_api", lambda: SimpleNamespace(study=lambda **k: None))
    monkeypatch.setattr(mcp, "_dispatch_study", lambda *a, **k: seen.append(k) or {"ok": True})
    assert mcp.h_study_video(str(path), ref_start="0:30", ref_end="1:20")["ok"]
    assert seen[0]["trim"] == {"ref_start": "0:30", "ref_end": "1:20"}
    monkeypatch.setattr("myzing.explain.api._explain", lambda *a, **k: seen.append(k) or {"ok": True})
    assert mcp.h_zing_explain(str(path), str(tmp_path / "out"), reference_range="0:30-1:20")["ok"]
    assert seen[1]["reference_range"] == "0:30-1:20"
    def validate(**kwargs):
        seen.append(kwargs)
        raise ValueError("stop before starting worker")
    monkeypatch.setattr("myzing.match.api.validate", validate)
    assert not mcp.h_match_start(str(path), str(tmp_path), str(tmp_path / "match"), answers={},
                                ref_start=30, ref_end=80)["ok"]
    assert seen[2]["ref_start"] == 30 and seen[2]["ref_end"] == 80


def test_geometry_schedule_tracks_gaps_and_writer_are_bounded(tmp_path, monkeypatch):
    from myzing.study import caption_geometry as cg
    assert len(cg.sample_schedule(86400)) == cg.MAX_FRAMES
    assert cg.sample_schedule(60) == cg.captions.sample_schedule(60)
    frames = [cg.FrameSample(i, i, 1, i, 640, 360, status="ocr_error") for i in range(600)]
    geometry = cg.CaptionGeometry(600, frames)
    geometry.coverage = cg._coverage(geometry, [(i, 1) for i in range(600)])
    assert geometry.coverage["gap_count"] == 600
    assert len(geometry.coverage["gaps"]) == cg.MAX_GAPS
    assert geometry.coverage["gaps_omitted"] == 600-cg.MAX_GAPS
    # Writer must never allocate a whole-geometry deep copy.
    monkeypatch.setattr(geometry, "to_dict", lambda: pytest.fail("whole geometry serialization"))
    data = json.loads(geometry.write(tmp_path).read_text(encoding="utf-8"))
    assert len(data["frames"]) == 600 and data["coverage"]["gap_count"] == 600


def test_geometry_caps_tracks_samples_and_counts_reused_frames(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    from myzing.study import caption_geometry as cg, caption_models, caption_pixels, caption_regions
    monkeypatch.setattr("myzing.layout.detector.verified_model", lambda p: False)
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    boxes = [[[20, 20], [180, 20], [180, 30], [20, 30]]] * 20
    out = SimpleNamespace(boxes=boxes, txts=["CAPTION SAMPLE"]*20, scores=[.99]*20)
    monkeypatch.setattr(caption_models, "engine", lambda: (lambda f: out, "fixture"))
    monkeypatch.setattr(caption_pixels, "measure", lambda *a: {})
    monkeypatch.setattr(caption_regions, "assess", lambda frames: None)
    monkeypatch.setattr(cg, "iter_frames", lambda *a: ((i/8, i/8, .125, i, frame) for i in range(100)))
    result = cg.read_geometry(tmp_path / "fixture.mp4", 12.5)
    assert result.provenance["counts"]["detections_observed"] == 2000
    assert result.provenance["counts"]["detections_omitted"] == 400
    assert all(len(f.detections) == cg.MAX_DETECTIONS for f in result.frames)
    assert result.tracks and all(len(t.samples) <= cg.MAX_TRACK_SAMPLES for t in result.tracks)
    assert any(t.classification["samples_omitted"] > 0 for t in result.tracks)
    frames = [cg.FrameSample(i, i, 1, i, 200, 100, [cg.Detection("SAMPLE", .99,
              [[.1, .2], [.9, .2], [.9, .3], [.1, .3]], [.1, .2, .9, .3])]) for i in range(200)]
    counts = {}
    assert len(cg.track_frames(frames, 200, counts=counts)) == cg.MAX_TRACKS
    assert counts == {"tracks_observed": 200, "tracks_omitted": 72}


def test_font_work_budget_caps_total_observations_without_changing_geometry():
    from myzing.study.caption_geometry import CaptionGeometry, CaptionTrack
    from myzing.study.font_match import budget_geometry
    samples = [{"sample_index": i, "detection_indices": list(range(6))} for i in range(10)]
    tracks = [CaptionTrack(str(i), "fixture", "caption", samples, .05, 6, "center", .9, "static", [], {}) for i in range(20)]
    original = CaptionGeometry(60, tracks=tracks)
    bounded, counts = budget_geometry(original)
    assert len(bounded.tracks) == 16 and counts["observations_measured"] == 96
    assert counts["observations_total"] == 1200 and counts["observations_omitted"] == 1104
    assert len(original.tracks) == 20 and all(len(t.samples) == 10 for t in original.tracks)


def dark_chrome():
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(12)
    frames = np.tile(np.linspace(6, 19, 100, dtype=np.uint8)[None, :, None], (12, 1, 160))
    # Dark live picture: no persistent >10-luma border in every frame.
    frames[:, 12:80, 16:144] = rng.integers(8, 29, (12, 68, 128), dtype=np.uint8)
    frames[:, 3:8, 12:42] = 130  # logo
    frames[:, 87:94, 12:110] = 75  # lower-third
    return frames


def test_dark_gradient_chrome_and_negative_guards():
    np = pytest.importorskip("numpy")
    from myzing.layout.picture import detect_picture
    frames = dark_chrome()
    result = detect_picture(frames)
    assert result["confident"] and result["confidence"] >= .8, result
    assert result["bounds_normalized"] == [.1, .12, .8, .68]
    letterbox = frames.copy()
    letterbox[:, :12] = 8
    letterbox[:, 80:] = 8
    letterbox[:, :, :16] = 8
    letterbox[:, :, 144:] = 8
    assert not detect_picture(letterbox)["confident"]
    desk = frames.copy()
    texture = np.random.default_rng(3).integers(0, 200, (100, 160), dtype=np.uint8)
    desk[:, :12] = texture[:12]
    desk[:, 80:] = texture[80:]
    assert not detect_picture(desk)["confident"]


def test_single_head_does_not_shrink_to_fit_duplicate_hog_desk_box():
    from myzing.layout.crop_planner import select_framing
    from myzing.layout.types import Box, FaceTrack, Keyframe
    from myzing.composition import CompositionClip, SpeechWord
    face = FaceTrack("face-0", [Keyframe(0, Box(.4, .15, .15, .35)), Keyframe(12, Box(.4, .15, .15, .35))], .95)
    hog = FaceTrack("person-hog", [Keyframe(0, Box(.02, .02, .96, .96)), Keyframe(12, Box(.02, .02, .96, .96))], .5)
    clip = CompositionClip("v", 0, 12, 0, id="c", asset_id="v")
    # The normal director route need not carry separate speech-word metadata.
    framed = select_framing("auto", 640, 360, 720, 1280, clip, [face, hog])
    assert .50 <= framed.assessments[-1].sharp_height_share <= .70
    assert framed.assessments[-1].enlargement <= 2.5
    assert any("enclosing HOG" in w and "50-70%" in w for w in framed.warnings)
    # A separate person is still a subject that must stay visible.
    other = FaceTrack("person-other", [Keyframe(0, Box(.8, .2, .2, .7)), Keyframe(12, Box(.8, .2, .2, .7))], .8)
    separate = select_framing("auto", 1920, 1080, 720, 1280, clip, [face, other],
                            speech_words=[SpeechWord("v", "Hello", 0, 12)])
    assert not any("enclosing HOG" in w for w in separate.warnings)
    assert separate.assessments[-1].subject_coverage >= .98
