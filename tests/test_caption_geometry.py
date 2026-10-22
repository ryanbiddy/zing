"""Contract, tracking, coverage and offline failure boundaries (no models needed)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.study import caption_geometry as cg, caption_models


def detection(text="HELLO", box=(.2, .6, .6, .67), confidence=.95):
    a, b, c, d = box
    return cg.Detection(text, confidence, [[a, b], [c, b], [c, d], [a, d]], list(box))


def frame(t, detections, status="ok"):
    return cg.FrameSample(t, t, .125, round(t * 24), 640, 360, detections, status)


def test_sidecar_roundtrip_and_version_rejection(tmp_path):
    import json
    frames = [frame(t / 8, [detection()]) for t in range(8)]
    geometry = cg.CaptionGeometry(1, frames, cg.track_frames(frames, 1))
    geometry.coverage = cg._coverage(geometry, cg.captions.sample_schedule(1))
    saved = json.loads(geometry.write(tmp_path).read_text(encoding="utf-8"))
    restored = cg.CaptionGeometry.from_dict(saved)
    assert restored.to_dict() == geometry.to_dict()
    assert isinstance(restored.frames[0].detections[0], cg.Detection)
    for record in (cg.CaptionGeometry, cg.CaptionTrack, cg.FrameSample, cg.Detection):
        with pytest.raises(ValueError, match="version"):
            record.from_dict({"version": 2})


def test_raw_polygons_retained_even_without_confidence():
    output = SimpleNamespace(boxes=[[[-10, 20], [80, 20], [80, 40], [-10, 40]]], txts=["hello"], scores=None)
    d, = cg.parse_ocr(output, SimpleNamespace(shape=(100, 100, 3)))
    assert d.confidence is None
    assert d.polygon == [[0, .2], [.8, .2], [.8, .4], [0, .4]]
    frames = [frame(0, [d], "low_confidence")]
    assert cg.track_frames(frames, 1) == []


@pytest.mark.parametrize("boxes,texts,scores", [
    ([[[0, 0], [10, 0], [10, 10]]], ["a", "b"], [.9, .9]),
    ([[[0, 0], [10, 0], [10, 10]]], ["a"], [.9, .9]),
    ([[[0, 0], [float("nan"), 0], [10, 10]]], ["a"], [.9]),
    ([[[0, 0], [0, 0], [0, 0]]], ["a"], [.9]),
])
def test_malformed_ocr_cannot_silently_truncate_or_invent(boxes, texts, scores):
    with pytest.raises(ValueError):
        cg.parse_ocr(SimpleNamespace(boxes=boxes, txts=texts, scores=scores), SimpleNamespace(shape=(100, 100, 3)))


def test_simultaneous_identical_text_keeps_separate_tracks():
    frames = [frame(t / 8, [detection(box=(.05, .1, .25, .16)),
                            detection(box=(.65, .1, .85, .16))]) for t in range(4)]
    tracks = cg.track_frames(frames, 1)
    assert len(tracks) == 2
    assert all(len(t.samples) == 4 for t in tracks)
    assert all(len({s["sample_index"] for s in t.samples}) == 4 for t in tracks)


@pytest.mark.parametrize("alignment,second", [
    ("left", (.2, .69, .4, .76)), ("center", (.3, .69, .5, .76)), ("right", (.4, .69, .6, .76)),
])
def test_multiline_alignment_and_line_count(alignment, second):
    frames = [frame(t / 8, [detection("HELLO WORLD"), detection("NEXT", second)]) for t in range(4)]
    track, = cg.track_frames(frames, 1)
    assert track.line_count == 2
    assert track.alignment == alignment
    assert track.alignment_confidence == .8
    assert track.median_text_height is None  # OCR height is not silently called measured ink.


def test_full_duration_moving_text_is_not_overlay():
    frames = [frame(t / 8, [detection(box=(.1 + .025 * t, .6, .3 + .025 * t, .67))]) for t in range(8)]
    track, = cg.track_frames(frames, 1)
    assert track.kind == "caption" and track.motion == "moving"


def test_truncated_decode_is_not_whole_clip_overlay():
    frames = [frame(t / 8, [detection()]) for t in range(4)]
    track, = cg.track_frames(frames, 10)
    assert track.kind == "caption"
    geometry = cg.CaptionGeometry(10, frames, [track])
    coverage = cg._coverage(geometry, cg.captions.sample_schedule(10))
    assert any(g["t"] == 9.75 and g["reason"] == "frame_unavailable" for g in coverage["gaps"])


def test_fractional_container_tail_does_not_turn_watermark_into_caption():
    frames = [frame(t / 8, [detection()]) for t in range(8)]
    track, = cg.track_frames(frames, 1.001)
    # A fractional tail adds a scheduled sample; the 90% occupancy rule still
    # governs whether a nearly complete short clip supports classification.
    assert track.kind == "caption"  # 8/9 is below the persistence threshold.
    frames = [frame(t / 8, [detection()]) for t in range(16)]
    track, = cg.track_frames(frames, 2.001)
    assert track.kind == "overlay"  # 16/17 samples; a fractional trailing packet.


def test_coarse_projection_preserves_submillisecond_valid_interval():
    frames = [frame(0, [detection()])]
    result = cg.CaptionGeometry(.0004, frames, cg.track_frames(frames, .0004))
    event, = cg.caption_events(result)
    assert event.start == 0 and event.end == .0004


def test_low_confidence_neighbor_does_not_hide_confident_geometry():
    f = frame(0, [detection(), detection("FAINT", (.1, .1, .3, .15), .2)], "low_confidence")
    track, = cg.track_frames([f], 1)
    assert track.text == "HELLO"
    assert track.samples[0]["detection_indices"] == [0]
    geometry = cg.CaptionGeometry(1, [f], [track])
    coverage = cg._coverage(geometry, cg.captions.sample_schedule(1))
    assert coverage["low_confidence_frames"] == [0]


def test_persistent_watermark_cannot_hide_occluded_caption_gap():
    frames = [frame(t / 8, [detection("LOGO", (.1, .1, .2, .15))]
                    + ([] if t == 2 else [detection()])) for t in range(8)]
    tracks = cg.track_frames(frames, 1)
    geometry = cg.CaptionGeometry(1, frames, tracks)
    coverage = cg._coverage(geometry, cg.captions.sample_schedule(1))
    caption = next(t for t in tracks if t.text == "HELLO")
    assert any(g["reason"] == "track_not_detected" and g["track_id"] == caption.id
               and g["t"] == .25 for g in coverage["gaps"])


def test_long_absence_splits_repeated_text_and_error_frame_has_no_geometry():
    frames = [frame(0, [detection()]), frame(.125, [detection()], "ocr_error"), frame(1, [detection()])]
    tracks = cg.track_frames(frames, 2)
    assert len(tracks) == 2
    assert [s["t"] for t in tracks for s in t.samples] == [0, 1]


def test_missing_backend_keeps_full_coverage_failure(monkeypatch):
    def missing():
        raise ImportError("rapidocr")
    monkeypatch.setattr(caption_models, "engine", missing)
    result = cg.read_geometry(Path("missing.mp4"), 1)
    assert len(result.coverage["gaps"]) == 8
    assert result.frames == result.tracks == []
    assert "myzing[study]" in result.warnings[0]


def test_missing_models_are_offline_and_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(caption_models, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(caption_models, "find_spec", lambda name: None)
    monkeypatch.setattr(caption_models.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    with pytest.raises(RuntimeError, match="--fetch"):
        caption_models.model_paths()


def test_doctor_geometry_checks_packages_and_assets_without_inference(tmp_path, monkeypatch):
    from myzing import doctor
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    missing = doctor.check_caption_geometry()
    assert not missing.ok and "myzing[study]" in missing.fix
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(caption_models, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(caption_models, "find_spec", lambda name: None)
    monkeypatch.setattr(caption_models, "engine", lambda: pytest.fail("doctor started inference"))
    no_models = doctor.check_caption_geometry()
    assert not no_models.ok and "--fetch" in no_models.fix
    assert no_models.data["network_used"] is False
    monkeypatch.setattr(caption_models, "model_paths", lambda: {})
    assert doctor.check_caption_geometry().ok


def test_explicit_provision_checks_hash_and_reuses_cache(tmp_path, monkeypatch):
    import hashlib
    import io
    payload = b"model-test"
    monkeypatch.setattr(caption_models, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(caption_models, "MODELS", {"Det": ("det.onnx", hashlib.sha256(payload).hexdigest())})
    monkeypatch.setattr(caption_models.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))
    path, = caption_models.fetch_models()
    assert path.read_bytes() == payload
    monkeypatch.setattr(caption_models.urllib.request, "urlopen", lambda *a, **k: pytest.fail("cache fetched"))
    assert caption_models.fetch_models() == [path]
    path.write_bytes(b"corrupt")
    monkeypatch.setattr(caption_models.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"bad"))
    with pytest.raises(RuntimeError, match="SHA-256"):
        caption_models.fetch_models()
    assert path.read_bytes() == b"corrupt" and not list(tmp_path.glob("*.part"))


def test_geometry_opt_in_persists_only_summary_in_breakdown(zing_workspace, monkeypatch):
    import json
    from test_study_api import wire_stages, SOURCE
    from myzing import storage
    from myzing.study import api
    wire_stages(monkeypatch)
    frames = [frame(t / 8, [detection()]) for t in range(4)]
    geometry = cg.CaptionGeometry(20, frames, cg.track_frames(frames, 20))
    calls = []
    def measure(*args):
        calls.append(args)
        return geometry
    monkeypatch.setattr(cg, "read_geometry", measure)
    disabled = api.study(SOURCE)
    folder = storage.breakdown_dir("tiktok-777")
    assert not calls and "caption_geometry" not in disabled.provenance
    assert not (folder / cg.FILENAME).exists()
    enabled = api.study(SOURCE, caption_geometry=True)
    assert enabled.schema_version == 1
    assert enabled.provenance["caption_geometry"] == geometry.summary()
    assert all(isinstance(v, (str, int)) for v in geometry.summary().values())
    assert json.loads((folder / cg.FILENAME).read_text(encoding="utf-8")) == geometry.to_dict()
    assert enabled.captions[0].text == "HELLO"


def test_cli_forwards_geometry_and_announces_sidecar(zing_workspace, monkeypatch, capsys):
    from myzing.schemas import Breakdown, VideoMeta
    from myzing.study import command
    seen = {}
    def study(source, **kwargs):
        seen.update(kwargs)
        return Breakdown(VideoMeta(source, "file"), provenance={"caption_geometry": {"file": cg.FILENAME}})
    monkeypatch.setattr("myzing.study.api.study", study)
    assert command.run(["clip.mp4", "--caption-geometry"]) == 0
    assert seen == {"workspace": zing_workspace, "caption_geometry": True}
    assert cg.FILENAME in capsys.readouterr().out


def test_sidecar_write_failure_is_named_without_success_summary(zing_workspace, monkeypatch):
    from test_study_api import wire_stages, SOURCE
    from myzing.study import api
    wire_stages(monkeypatch)
    geometry = cg.CaptionGeometry(20)
    monkeypatch.setattr(cg, "read_geometry", lambda *a: geometry)
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(cg.CaptionGeometry, "write", fail)
    result = api.study(SOURCE, caption_geometry=True)
    assert "caption_geometry" not in result.provenance
    assert any("disk full" in w for w in result.warnings)
