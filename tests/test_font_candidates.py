"""Font provenance, offline boundaries, sidecar persistence and CLI contracts."""

from __future__ import annotations

import hashlib
import io
import json
import warnings

import pytest

from myzing.fonts import library, command
from myzing.study import caption_geometry as cg, font_match as fm


def test_manifest_pins_permitted_sources_and_bundled_bytes(tmp_path):
    manifest = library.manifest()
    assert len(manifest["fonts"]) == 13
    assert len({row["id"] for row in manifest["fonts"]}) == 13
    for row in manifest["fonts"]:
        assert row["license"] in {"OFL-1.1", "Apache-2.0"}
        for prefix in ("", "license_"):
            assert f"google/fonts/{manifest['source_revision']}/" in row[prefix + "url"]
            assert len(row[prefix + "sha256"]) == 64
        if row["bundled"]:
            assert library.sha256(library.DATA / row["file"]) == row["sha256"]
            assert library.sha256(library.DATA / row["license_file"]) == row["license_sha256"]
    assert [r["id"] for r in library.inventory(tmp_path) if r["available"]] == ["anton", "ibmplexsans"]


def test_inventory_and_list_never_download(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(library, "urlopen", lambda *a, **k: pytest.fail("inventory downloaded"))
    assert command.run(["list", "--workspace", str(tmp_path), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["fonts"]
    assert sum(r["available"] for r in rows) == 2
    assert not tmp_path.joinpath("fonts").exists()


def fake_manifest(monkeypatch):
    payloads = {"https://example.test/font": b"font", "https://example.test/license": b"license"}
    entry = dict(id="example", family="Example", bundled=False, file="font.ttf", license_file="LICENSE.txt",
                 url="https://example.test/font", license_url="https://example.test/license", weights=[None],
                 sha256=hashlib.sha256(b"font").hexdigest(), license_sha256=hashlib.sha256(b"license").hexdigest(),
                 license="OFL-1.1")
    monkeypatch.setattr(library, "manifest", lambda: {"version": 1, "fonts": [entry]})
    return payloads


def test_explicit_fetch_reuses_verified_pair_and_repairs_corruption(tmp_path, monkeypatch):
    payloads = fake_manifest(monkeypatch)
    calls = []
    def download(url, **kwargs):
        calls.append(url)
        return io.BytesIO(payloads[url])
    monkeypatch.setattr(library, "urlopen", download)
    assert library.fetch(["example"], tmp_path)[0]["available"]
    assert len(calls) == 2
    assert library.fetch(["example"], tmp_path)[0]["available"]
    assert len(calls) == 2
    font = tmp_path / "fonts/example/font.ttf"
    font.write_bytes(b"broken")
    assert not library.inventory(tmp_path)[0]["available"]
    assert library.fetch(["example"], tmp_path)[0]["available"]
    assert font.read_bytes() == b"font" and len(calls) == 4


@pytest.mark.parametrize("bad", ["font", "license"])
def test_hash_failure_leaves_existing_pair_and_cleans_partial(tmp_path, monkeypatch, bad):
    payloads = fake_manifest(monkeypatch)
    monkeypatch.setattr(library, "urlopen", lambda url, **k: io.BytesIO(payloads[url]))
    library.fetch(["example"], tmp_path)
    folder = tmp_path / "fonts/example"
    (folder / "font.ttf").write_bytes(b"old")
    payloads[f"https://example.test/{bad}"] = b"bad download"
    with pytest.raises(ValueError, match="SHA-256"):
        library.fetch(["example"], tmp_path)
    assert (folder / "font.ttf").read_bytes() == b"old"
    assert (folder / "LICENSE.txt").read_bytes() == b"license"
    assert not list(folder.glob("*.part"))


def test_unknown_font_rejected_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "urlopen", lambda *a, **k: pytest.fail("unknown font downloaded"))
    with pytest.raises(ValueError, match="unknown font"):
        library.fetch(["../../escape"], tmp_path)


def test_versioned_font_section_round_trips_and_default_shape_stays_v1():
    geometry = cg.CaptionGeometry(1)
    assert "font_candidates" not in geometry.to_dict()
    section = fm.FontCandidates(tracks=[{"track_id": "t", "status": "best substitute"}])
    geometry.font_candidates = section.to_dict()
    assert cg.CaptionGeometry.from_dict(geometry.to_dict()).to_dict() == geometry.to_dict()
    assert fm.FontCandidates.from_dict(section.to_dict()).to_dict() == section.to_dict()
    geometry.font_candidates["version"] = 99
    with pytest.raises(ValueError, match="font_candidates version"):
        cg.CaptionGeometry.from_dict(geometry.to_dict())


def test_match_study_only_replaces_section_and_uses_workspace(zing_workspace, monkeypatch):
    from myzing import storage
    folder = storage.breakdown_dir("example")
    folder.mkdir(parents=True)
    media = folder / "media.mp4"
    media.write_bytes(b"mock media")
    raw = cg.CaptionGeometry(1, provenance={"keep": "me"}).to_dict()
    raw["future_measurement"] = {"keep": [1, 2, 3]}
    sidecar = folder / cg.FILENAME
    sidecar.write_text(json.dumps(raw), encoding="utf-8")
    (folder / "breakdown.json").write_text('{"judgment":"keep"}', encoding="utf-8")
    section = fm.FontCandidates(provenance={"network_used": False})
    def match(path, geometry):
        assert path == media and geometry.provenance == {"keep": "me"}
        assert storage.resolve_workspace() == zing_workspace
        return section
    monkeypatch.setattr(fm, "match_geometry", match)
    path, result = fm.match_study("example", zing_workspace)
    assert path == sidecar and result == section
    assert json.loads(sidecar.read_text(encoding="utf-8")) == dict(raw, font_candidates=section.to_dict())
    assert (folder / "breakdown.json").read_text(encoding="utf-8") == '{"judgment":"keep"}'
    assert command.run(["match", "example", "--workspace", str(zing_workspace), "--json"]) == 0
    with pytest.raises(ValueError):
        fm.match_study("../escape", zing_workspace)


def test_failed_match_does_not_replace_existing_sidecar(zing_workspace, monkeypatch):
    from myzing import storage
    folder = storage.breakdown_dir("example")
    folder.mkdir(parents=True)
    sidecar = cg.CaptionGeometry(1).write(folder)
    before = sidecar.read_bytes()
    with pytest.raises(ValueError, match="media missing"):
        fm.match_study("example", zing_workspace)
    assert sidecar.read_bytes() == before
    (folder / "media.mp4").write_bytes(b"mock")
    monkeypatch.setattr(fm, "match_geometry", lambda *a: fm.FontCandidates())
    import os
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        fm.match_study("example", zing_workspace)
    assert sidecar.read_bytes() == before and not list(folder.glob("*.part"))


def test_study_opt_in_and_failure_are_explicit(zing_workspace, monkeypatch):
    from test_study_api import wire_stages, SOURCE
    from myzing import storage
    from myzing.study import api
    wire_stages(monkeypatch)
    geometry = cg.CaptionGeometry(20)
    monkeypatch.setattr(cg, "read_geometry", lambda *a: geometry)
    calls = []
    def match(*args):
        calls.append(args)
        return fm.FontCandidates()
    monkeypatch.setattr(fm, "match_geometry", match)
    api.study(SOURCE, caption_geometry=True)
    assert not calls
    api.study(SOURCE, caption_geometry=True, fonts=True)
    assert len(calls) == 1
    path = storage.breakdown_dir("tiktok-777") / cg.FILENAME
    assert json.loads(path.read_text(encoding="utf-8"))["font_candidates"] == fm.FontCandidates().to_dict()
    def missing(*args):
        raise RuntimeError("install myzing[fonts]")
    monkeypatch.setattr(fm, "match_geometry", missing)
    result = api.study(SOURCE, caption_geometry=True, fonts=True)
    assert any("no font comparison was made" in w for w in result.warnings)
    with pytest.raises(ValueError, match="require"):
        api.study(SOURCE, fonts=True)


def test_study_cli_requires_geometry_and_forwards_fonts(zing_workspace, monkeypatch):
    from myzing.study import command as study_command
    from myzing.schemas import Breakdown, VideoMeta
    calls = []
    def study(source, **kwargs):
        calls.append(kwargs)
        return Breakdown(VideoMeta(source, "file"))
    monkeypatch.setattr("myzing.study.api.study", study)
    with pytest.raises(SystemExit):
        study_command.run(["clip.mp4", "--fonts"])
    assert not calls
    assert study_command.run(["clip.mp4", "--caption-geometry", "--fonts"]) == 0
    assert calls == [{"workspace": zing_workspace, "caption_geometry": True, "fonts": True}]


def test_doctor_names_missing_runtime_and_assets(monkeypatch):
    from myzing import doctor
    monkeypatch.setattr(doctor, "_has_module", lambda name: name != "PIL")
    check = doctor.check_fonts()
    assert not check.ok and "myzing[fonts]" in check.fix
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(library, "inventory", lambda: [{"id": "anton", "available": False}])
    check = doctor.check_fonts()
    assert not check.ok and "fetch" in check.fix and not check.data["network_used"]


def test_match_refuses_changed_media_before_decoding(tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("PIL.Image")
    path = tmp_path / "media.mp4"
    path.write_bytes(b"changed")
    geometry = cg.CaptionGeometry(1, provenance={"media": {"sha256": "0" * 64}})
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        fm.match_geometry(path, geometry, tmp_path)


def test_blank_and_plate_masks_do_not_become_matches():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    detection = cg.Detection("FAKE", .99, [[.1, .1], [.9, .1], [.9, .9], [.1, .9]], [.1, .1, .9, .9],
                             {"fill": {"lab": [0., 0., 0.], "confidence": .9}})
    mask, reason = fm.crop_ink(frame, detection)
    assert mask is None and "insufficient" in reason


def test_missing_glyph_is_rejected_instead_of_matching_tofu():
    pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    with pytest.raises(ValueError, match="lacks OCR character"):
        fm.render_mask(str(library.DATA / "Anton-Regular.ttf"), "AB\U0010ffff", 32)


def matching_fixture(tmp_path, monkeypatch, indices=(0,)):
    """Two tracks share frames; the decoder records every seek and read."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    pytest.importorskip("PIL.Image")
    media = tmp_path / "media.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"mock media")
    polygon = [[.1, .1], [.9, .1], [.9, .9], [.1, .9]]
    detections = [cg.Detection(text, .99, polygon, [.1, .1, .9, .9]) for text in ("FIRST", "SECOND")]
    frames = [cg.FrameSample(i / 24, i / 24, 1 / 24, i, 100, 80, detections) for i in indices]
    tracks = [cg.CaptionTrack(f"track-{j}", detection.text, "caption",
                             [{"sample_index": i, "detection_indices": [j]} for i in range(len(frames))],
                             .1, 1, "center", 1., "static", [], {})
              for j, detection in enumerate(detections)]
    geometry = cg.CaptionGeometry((indices[-1] + 1) / 24, frames=frames, tracks=tracks,
                                  provenance={"media": {"sha256": library.sha256(media)}})

    class Capture:
        def __init__(self):
            self.position = 0
            self.seeks = []
            self.reads = []
            self.released = False

        def isOpened(self):
            return True

        def set(self, prop, index):
            assert prop == cv2.CAP_PROP_POS_FRAMES
            self.position = index
            self.seeks.append(index)
            return True

        def get(self, prop):
            assert prop == cv2.CAP_PROP_POS_FRAMES
            return self.position

        def read(self):
            self.reads.append(self.position)
            pixels = np.full((80, 100, 3), self.position % 256, dtype=np.uint8)
            self.position += 1
            return True, pixels

        def release(self):
            self.released = True

    capture = Capture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda *args: capture)
    mask = np.zeros((12, 24), dtype=bool)
    mask[2:10, 3:8] = True
    monkeypatch.setattr(fm, "crop_ink", lambda pixels, detection: (
        mask, {"mask_sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
               "pixel_value": int(pixels[0, 0, 0])}))
    monkeypatch.setattr(fm, "render_mask", lambda *args: (mask, {}))
    return media, geometry, capture


@pytest.mark.parametrize("failure", ["opencv", "unexpected", "missing-runtime"])
def test_study_font_failure_saves_tracks_and_provenance(zing_workspace, monkeypatch, failure):
    from test_study_api import wire_stages, SOURCE
    from myzing import storage
    from myzing.study import api
    cv2 = pytest.importorskip("cv2")
    wire_stages(monkeypatch)
    folder = storage.breakdown_dir("tiktok-777")
    media, geometry, _ = matching_fixture(folder, monkeypatch)
    monkeypatch.setattr(cg, "read_geometry", lambda *args: geometry)
    if failure == "missing-runtime":
        import builtins
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("OpenCV unavailable")
            return original(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", missing)
    else:
        error = cv2.error("OpenCV failed") if failure == "opencv" else Exception("backend failed")
        def fail(*args):
            raise error
        monkeypatch.setattr(fm, "match_geometry", fail)
    result = api.study(SOURCE, caption_geometry=True, fonts=True)
    saved = json.loads((folder / "breakdown.json").read_text(encoding="utf-8"))
    section = json.loads((folder / cg.FILENAME).read_text(encoding="utf-8"))["font_candidates"]
    assert saved["warnings"] == result.warnings
    assert [r["id"] for r in section["available_fonts"]] == ["anton", "ibmplexsans"]
    assert all(r["sha256"] and r["license"] and r["weights"] and r["path"] for r in section["available_fonts"])
    provenance = section["provenance"]
    assert provenance["media_sha256"] == library.sha256(media)
    assert provenance["manifest_sha256"] == library.sha256(library.MANIFEST)
    assert provenance["geometry_media_hash_verified"] is True
    assert provenance["network_used"] is False and provenance["method"] == "glyph-mask-v1"
    assert set(provenance["versions"]) == {"Pillow", "OpenCV", "NumPy"}
    assert len(provenance["unavailable_font_ids"]) == 11
    assert len(section["tracks"]) == 2
    for track in section["tracks"]:
        assert track["status"] == "unmeasured" and track["original_font"] == "unknown"
        assert not track["candidates"] and track["warnings"]
        assert all(w in result.warnings and track["track_id"] in w for w in track["warnings"])


@pytest.mark.parametrize("failure_site", ["inventory", "media_sha256"])
def test_failure_provenance_preserves_fields_that_can_be_read(tmp_path, monkeypatch, failure_site):
    media = tmp_path / "media.mp4"
    media.write_bytes(b"media")
    if failure_site == "inventory":
        def fail(*args):
            raise OSError("inventory unreadable")
        monkeypatch.setattr(library, "inventory", fail)
    else:
        media.unlink()
    result = fm.failed_candidates(media, cg.CaptionGeometry(1), RuntimeError("comparison failed"), tmp_path)
    assert failure_site in result.provenance["errors"]
    assert result.provenance["manifest_sha256"] == library.sha256(library.MANIFEST)
    if failure_site == "inventory":
        assert result.provenance["media_sha256"] == library.sha256(media)
    else:
        assert len(result.available_fonts) == 2 and result.provenance["media_sha256"] is None


@pytest.mark.parametrize("failure_site", ["crop", "compare", "empty-mask", "empty-interior"])
def test_font_failures_warn_only_affected_track_and_save_study(zing_workspace, monkeypatch, failure_site):
    from test_study_api import wire_stages, SOURCE
    from myzing import storage
    from myzing.study import api
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    wire_stages(monkeypatch)
    folder = storage.breakdown_dir("tiktok-777")
    crop_ink = fm.crop_ink
    _, geometry, capture = matching_fixture(folder, monkeypatch)
    monkeypatch.setattr(cg, "read_geometry", lambda *args: geometry)
    name = "compare_masks" if failure_site == "compare" else "crop_ink"
    original = getattr(fm, name)
    calls = []
    def fail_once(*args):
        calls.append(args)
        if len(calls) == 1:
            if failure_site == "empty-mask":
                return np.zeros((0, 0), dtype=bool), {"mask_sha256": "empty"}
            if failure_site == "empty-interior":
                detection = cg.Detection("OUTSIDE", .99, [[-.2, .01], [.01, -.2], [-.2, -.2]],
                                         [-.2, -.2, .01, .01])
                return crop_ink(args[0], detection)
            raise cv2.error("synthetic OpenCV failure")
        return original(*args)
    monkeypatch.setattr(fm, name, fail_once)
    result = api.study(SOURCE, caption_geometry=True, fonts=True)
    section = json.loads((folder / cg.FILENAME).read_text(encoding="utf-8"))["font_candidates"]
    first, second = section["tracks"]
    assert first["warnings"] and all(w in result.warnings for w in first["warnings"])
    assert first["gaps"] or first["rejected_candidates"]
    assert second["candidates"] and not second["warnings"]
    assert len(section["available_fonts"]) == 2 and section["provenance"]["media_sha256"]
    assert json.loads((folder / "breakdown.json").read_text(encoding="utf-8"))["warnings"] == result.warnings
    assert capture.released


def test_empty_polygon_interior_does_not_reach_otsu(monkeypatch):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    # Its bounding box intersects the frame, but the triangle lies outside it.
    polygon = [[-.2, .01], [.01, -.2], [-.2, -.2]]
    detection = cg.Detection("OUTSIDE", .99, polygon, [-.2, -.2, .01, .01],
                             {"fill": {"lab": [0., 0., 0.], "confidence": .9}})
    monkeypatch.setattr(cv2, "threshold", lambda *a: pytest.fail("empty interior reached Otsu"))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        mask, reason = fm.crop_ink(np.zeros((100, 100, 3), dtype=np.uint8), detection)
    assert mask is None and reason == "empty polygon interior"


@pytest.mark.parametrize("shape", [(0, 0), (0, 8), (8, 0), (8, 8)])
def test_compare_rejects_empty_masks_before_opencv(shape, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    monkeypatch.setattr(cv2, "resize", lambda *a, **k: pytest.fail("empty mask reached OpenCV"))
    empty = np.zeros(shape, dtype=bool)
    ink = np.ones((8, 8), dtype=bool)
    for observed, rendered in ((empty, ink), (ink, empty)):
        with pytest.raises(ValueError, match="empty glyph mask"):
            fm.compare_masks(observed, rendered)


def test_sparse_tracks_decode_only_selected_unique_frames(tmp_path, monkeypatch):
    indices = tuple(100000 + i * 10000 for i in range(100))
    media, geometry, capture = matching_fixture(tmp_path, monkeypatch, indices)
    result = fm.match_geometry(media, geometry, tmp_path)
    expected = [indices[round(i * 99 / 7)] for i in range(8)]
    assert capture.seeks == capture.reads == expected
    assert capture.released
    for track in result.tracks:
        assert [d["frame_index"] for d in track["evidence"]] == expected
        assert [d["pixel_value"] for d in track["evidence"]] == [i % 256 for i in expected]
        assert not track["warnings"]


@pytest.mark.parametrize("failure", ["seek", "read", "wrong-index", "opencv"])
def test_failed_frame_seek_is_a_gap_without_linear_decode(tmp_path, monkeypatch, failure):
    cv2 = pytest.importorskip("cv2")
    media, geometry, capture = matching_fixture(tmp_path, monkeypatch, (100000, 200000))
    if failure == "seek":
        monkeypatch.setattr(capture, "set", lambda *args: False)
    elif failure == "read":
        monkeypatch.setattr(capture, "read", lambda: (False, None))
    elif failure == "wrong-index":
        monkeypatch.setattr(capture, "get", lambda *args: 1)
    else:
        def fail(*args):
            raise cv2.error("seek failed")
        monkeypatch.setattr(capture, "set", fail)
    result = fm.match_geometry(media, geometry, tmp_path)
    assert len(capture.reads) <= 2 and capture.released
    for track in result.tracks:
        assert track["status"] == "unmeasured" and not track["evidence"]
        assert [g["frame_index"] for g in track["gaps"]] == [100000, 200000]
        assert track["warnings"]


def test_documented_top_three_gate_applies_per_style():
    from test_font_match_ffmpeg import assert_top_three
    # 24/26 pooled hits exceed 90%, but a style with 11/13 must still fail.
    weak = [{"rank": 1}] * 11 + [{"rank": 4}, {"rank": None}]
    strong = [{"rank": 3}] * 13
    assert_top_three(weak + strong)
    with pytest.raises(AssertionError):
        assert_top_three(weak)
    assert_top_three(strong)
    assert_top_three([{"rank": 3}] * 12 + [{"rank": 4}])
    assert_top_three([{"rank": 1}, {"rank": 2}])
    with pytest.raises(AssertionError):
        assert_top_three([{"rank": 1}, {"rank": 4}])
