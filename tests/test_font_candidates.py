"""Font provenance, offline boundaries, sidecar persistence and CLI contracts."""

from __future__ import annotations

import hashlib
import io
import json

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
