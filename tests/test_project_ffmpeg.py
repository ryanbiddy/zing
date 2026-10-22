"""Real generated media proves the project probe and immutable-source contract."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from myzing import cli
from myzing.project import api
from myzing.project.probe import probe_file
from myzing.study.proc import MediaError

pytestmark = pytest.mark.ffmpeg


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)],
                   check=True, capture_output=True, timeout=30)


def generate(path, size, *, audio=False, color="blue", extra=()):
    inputs = ["-f", "lavfi", "-i", f"color=c={color}:s={size}:r=30000/1001:d=1.001"]
    if audio:
        inputs += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1.001", "-c:a", "aac"]
    ffmpeg(*inputs, "-c:v", "libx264", "-pix_fmt", "yuv420p", *extra, path)


def hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


@pytest.fixture
def clips(tmp_path):
    folder = tmp_path / "creator's clips"
    folder.mkdir()
    generate(folder / "portrait.mp4", "90x160", audio=True)
    generate(folder / "landscape.mp4", "160x90")
    return folder


def test_mixed_inventory_once_via_cli(tmp_path, clips, capsys, monkeypatch):
    root = tmp_path / "project"
    before = hashes(clips)
    assert cli.main(["project", "init", "--reference", "https://example.test/reference",
                     "--clips", str(clips), "--out", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["ready"] == 2
    manifest = api.load_project(root)
    assets = {Path(a.path).name: a for a in manifest.assets}
    portrait, landscape = assets["portrait.mp4"], assets["landscape.mp4"]
    assert portrait.probe.orientation == "portrait" and landscape.probe.orientation == "landscape"
    assert portrait.probe.has_audio and not landscape.probe.has_audio
    assert (portrait.probe.width, portrait.probe.height) == (90, 160)
    assert portrait.probe.duration == pytest.approx(1.001, abs=0.05)
    assert (portrait.probe.fps.numerator, portrait.probe.fps.denominator) == (30000, 1001)
    assert portrait.sha256 == before["portrait.mp4"]
    assert portrait.size == (clips / "portrait.mp4").stat().st_size
    assert portrait.mtime_ns == (clips / "portrait.mp4").stat().st_mtime_ns
    assert {s["codec_type"] for s in portrait.probe.streams} == {"video", "audio"}
    saved = (root / "project.json").read_bytes()
    assert hashes(clips) == before

    def forbidden(*args):
        pytest.fail("An unchanged inventory must reuse hashes and probes")

    monkeypatch.setattr(api, "hash_file", forbidden)
    monkeypatch.setattr(api, "probe_file", forbidden)
    api.scan_project(root)
    assert (root / "project.json").read_bytes() == saved
    assert hashes(clips) == before
    assert api.project_status(root)["counts"]["ready"] == 2
    assert hashes(clips) == before


def test_interrupted_real_probe_resumes(tmp_path, clips, monkeypatch):
    root = tmp_path / "interrupted"
    before = hashes(clips)
    expected = api.init_project("uoink:fixture", clips, tmp_path / "complete")
    assert hashes(clips) == before
    real_probe = api.probe_file
    calls = []

    def interrupt(path):
        calls.append(path)
        if len(calls) == 2:
            raise RuntimeError("simulated mid-scan interruption")
        return real_probe(path)

    with monkeypatch.context() as patch:
        patch.setattr(api, "probe_file", interrupt)
        with pytest.raises(RuntimeError, match="mid-scan"):
            api.init_project("uoink:fixture", clips, root)
    assert hashes(clips) == before
    assert api.load_project(root).assets == []
    assert api.scan_project(root).to_dict() == expected.to_dict()
    assert hashes(clips) == before


def test_real_change_move_delete_add(tmp_path, clips, monkeypatch):
    root = tmp_path / "project"
    before = hashes(clips)
    original = api.init_project("uoink:fixture", clips, root)
    assert hashes(clips) == before
    landscape = next(a for a in original.assets if a.path.endswith("landscape.mp4"))
    portrait = next(a for a in original.assets if a.path.endswith("portrait.mp4"))
    generate(clips / "portrait.mp4", "90x160", color="red")
    before = hashes(clips)
    probes, hashed = [], []
    real_probe, real_hash = api.probe_file, api.hash_file

    def probe(path):
        probes.append(path.name)
        return real_probe(path)

    def hash_file(path):
        hashed.append(path.name)
        return real_hash(path)

    monkeypatch.setattr(api, "probe_file", probe)
    monkeypatch.setattr(api, "hash_file", hash_file)
    changed = api.scan_project(root)
    assert probes == hashed == ["portrait.mp4"]
    assert hashes(clips) == before
    assert next(a for a in changed.assets if a.id == landscape.id) == landscape
    assert next(a for a in changed.assets if a.id == portrait.id).revision == 2
    (clips / "portrait.mp4").rename(clips / "moved.mp4")
    before["moved.mp4"] = before.pop("portrait.mp4")
    probes.clear()
    hashed.clear()
    moved = api.scan_project(root)
    assert next(a for a in moved.assets if a.path.endswith("moved.mp4")).id == portrait.id
    assert hashed == ["moved.mp4"] and probes == []
    assert hashes(clips) == before
    (clips / "landscape.mp4").unlink()
    before.pop("landscape.mp4")
    missing = api.scan_project(root)
    assert next(a for a in missing.assets if a.id == landscape.id).state == "missing"
    assert hashes(clips) == before
    generate(clips / "square.mp4", "120x120")
    before = hashes(clips)
    added = api.scan_project(root)
    assert len(added.assets) == 3
    assert next(a for a in added.assets if a.path.endswith("square.mp4")).probe.orientation == "square"
    assert hashes(clips) == before


def test_display_rotation_is_probed(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    source = tmp_path / "landscape.mp4"
    generate(source, "160x90")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    ffmpeg("-display_rotation", "90", "-i", source, "-c", "copy", clips / "rotated.mp4")
    before = hashes(clips)
    manifest = api.init_project(str(source), clips, tmp_path / "project")
    probe = manifest.assets[0].probe
    assert abs(probe.rotation) == 90 and probe.orientation == "portrait"
    assert (probe.width, probe.height) == (160, 90)
    assert hashes(clips) == before
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash


def test_hdr_metadata_is_reported_unsupported(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    generate(clips / "hdr-tagged.mp4", "160x90", extra=(
        "-x264-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc"))
    before = hashes(clips)
    root = tmp_path / "project"
    manifest = api.init_project("uoink:hdr-tag-fixture", clips, root)
    assert manifest.assets[0].state == "unsupported"
    assert manifest.assets[0].probe.flags == ["hdr"]
    assert api.project_status(root)["counts"]["unsupported"] == 1
    assert hashes(clips) == before


def test_variable_frame_rate_metadata_is_flagged(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=2",
           "-vf", r"select=if(lt(n\,30)\,1\,not(mod(n\,2)))",
           "-fps_mode", "vfr", "-c:v", "libx264", clips / "vfr.mp4")
    before = hashes(clips)
    root = tmp_path / "project"
    manifest = api.init_project("uoink:vfr-fixture", clips, root)
    assert "vfr_suspected" in manifest.assets[0].probe.flags
    assert api.project_status(root)["counts"]["unsupported"] == 1
    assert hashes(clips) == before


@pytest.mark.parametrize("kind", ["concat", "hls", "sdp"])
def test_disguised_reference_demuxers_are_rejected(tmp_path, kind):
    clips = tmp_path / "clips"
    clips.mkdir()
    path = clips / "disguised.mp4"
    contents = {
        "concat": "ffconcat version 1.0\nfile 'referenced.mp4'\n",
        "hls": "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n../outside.ts\n#EXT-X-ENDLIST\n",
        "sdp": "v=0\no=- 0 0 IN IP4 127.0.0.1\ns=fixture\nc=IN IP4 127.0.0.1\n"
               "t=0 0\nm=video 1234 RTP/AVP 96\na=rtpmap:96 H264/90000\n",
    }
    path.write_text(contents[kind], encoding="utf-8")
    before = hashes(clips)
    # Newer FFmpeg also rejects disguised HLS during format detection. Either
    # rejection precedes attempts to open a referenced file or network socket.
    rejection = "not on whitelist|Not detecting m3u8/hls"
    with pytest.raises(MediaError, match=rejection):
        probe_file(path)
    root = tmp_path / "project"
    asset, = api.init_project("uoink:fixture", clips, root).assets
    assert asset.state == "unsupported" and asset.probe is None
    assert "not on whitelist" in asset.error or "Not detecting m3u8/hls" in asset.error
    assert api.project_status(root)["counts"]["unsupported"] == 1
    assert hashes(clips) == before


@pytest.mark.parametrize("suffix", [".webm", ".mkv", ".wav"])
def test_restricted_probe_accepts_common_media_containers(tmp_path, suffix):
    path = tmp_path / f"clip{suffix}"
    if suffix == ".wav":
        ffmpeg("-f", "lavfi", "-i", "sine=duration=0.5", path)
    else:
        codec = "libvpx-vp9" if suffix == ".webm" else "libx264"
        ffmpeg("-f", "lavfi", "-i", "color=s=32x32:r=30:d=0.5", "-c:v", codec, path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata = probe_file(path)
    assert metadata.duration == pytest.approx(0.5, abs=0.05)
    assert metadata.has_audio == (suffix == ".wav")
    if suffix != ".wav":
        assert metadata.width == metadata.height == 32
        assert metadata.flags == []
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
