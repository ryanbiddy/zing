"""V2 validation/dispatch and the pre-R9 v1 command/ASS byte snapshot."""

import hashlib
import json
import os
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from myzing.composition import (
    AssetRef, CaptionStyle, Composition, CompositionCaption, CompositionClip,
    FontAsset, LoudnessTarget, lower_to_v1, upgrade_edl,
)
from myzing.ffmpeg_capabilities import FFmpegCapabilityError
from myzing.layout.types import Box, EventLayout, OverlapCheck
from myzing.render import command, pipeline, render_composition
from myzing.render.captions import generate_ass
from myzing.render.composition import load_render_document, prepare_composition
from myzing.render.font_files import private_font
from myzing.render.graph import build_graph
from myzing.render.validation import EDLValidationError, MediaInfo, ResolvedClip, ValidatedEDL
from myzing.schemas import Clip, EDL, Word

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "src/myzing/_data/fonts"


def font_ref(name="Anton-Regular.ttf"):
    path = FONTS / name
    return FontAsset(str(path), hashlib.sha256(path.read_bytes()).hexdigest(), "OFL-1.1")


def plan(tmp_path, *, captions=()):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"generated fixture placeholder")
    return Composition(
        assets=[AssetRef("asset", source.name, hashlib.sha256(source.read_bytes()).hexdigest(), aliases=["asset-alias"])],
        clips=[CompositionClip("asset-alias", 0, 3, 0, id="clip", asset_id="asset")],
        captions=list(captions), width=640, height=360,
    )


def caption(**kwargs):
    defaults = dict(text="ONE TWO", start=0, end=2, id="caption", word_timed=False,
                    font=font_ref(), style=CaptionStyle(32),
                    layout=EventLayout("caption", 0, 2, "preferred-anchor", OverlapCheck(True), box=Box(.2, .3, .6, .3)))
    defaults.update(kwargs)
    return CompositionCaption(**defaults)


def forbid_work(monkeypatch):
    def unexpected(*a, **kw):
        pytest.fail("validation must finish before any subprocess/probe/render")
    monkeypatch.setattr(pipeline.subprocess, "run", unexpected)
    monkeypatch.setattr(pipeline, "probe_media", unexpected)


def test_pre_r9_v1_commands_graph_and_ass_are_byte_identical(tmp_path, monkeypatch):
    baseline = json.loads((ROOT / "tests/fixtures/render-v1-baseline.json").read_text(encoding="utf-8"))
    edl = load_render_document(baseline["edl"])
    assert type(edl) is EDL
    v = ValidatedEDL(edl, (ResolvedClip(edl.clips[0], Path("source.mp4"), MediaInfo(2, True, False)),), (), 2, (), "landscape")
    graph = build_graph(v, True)
    assert graph.graph.encode() == baseline["graph"].encode()
    for version in (6, 9):
        monkeypatch.setattr(pipeline, "ffmpeg_major_version", lambda _, v=version: v)
        cmd = pipeline._ffmpeg_command("ffmpeg", graph, Path("graph.txt"), Path("output.mp4"), v)
        assert json.dumps(cmd).encode() == json.dumps(baseline["commands"][str(version)]).encode()
    ass = generate_ass(edl.captions, edl.width, edl.height, tmp_path / "captions.ass")
    # The original pysubs2 save uses native newlines; pin both original byte
    # streams instead of changing v1 to make a cross-platform golden pass.
    assert hashlib.sha256(ass.read_bytes()).hexdigest() == baseline["ass_sha256"][os.name]


def test_missing_or_changed_asset_stops_before_any_work(tmp_path, monkeypatch):
    c = plan(tmp_path)
    forbid_work(monkeypatch)
    out, work = tmp_path / "output/video.mp4", tmp_path / "work"
    (tmp_path / "source.mp4").write_bytes(b"changed")
    with pytest.raises(EDLValidationError, match="asset asset: SHA-256 mismatch"):
        render_composition(c, out, base_dir=tmp_path, work_dir=work)
    (tmp_path / "source.mp4").unlink()
    with pytest.raises(EDLValidationError, match="asset asset: missing asset"):
        render_composition(c, out, base_dir=tmp_path, work_dir=work)
    assert not out.parent.exists() and not work.exists()


def test_unused_assets_and_fonts_are_verified_before_work(tmp_path, monkeypatch):
    c = plan(tmp_path, captions=[caption()])
    c.assets.append(AssetRef("unused", "missing.wav", "0" * 64))
    forbid_work(monkeypatch)
    with pytest.raises(EDLValidationError, match="unused: missing asset"):
        render_composition(c, tmp_path / "out.mp4", base_dir=tmp_path)
    c.assets.pop()
    c.captions[0].font.sha256 = "0" * 64
    with pytest.raises(EDLValidationError, match="caption caption font: SHA-256 mismatch"):
        render_composition(c, tmp_path / "out.mp4", base_dir=tmp_path)


def test_all_unsupported_features_named_before_io(tmp_path, monkeypatch):
    from test_composition_v2 import talking_head_example
    c, _ = talking_head_example()
    from myzing.composition import SpeedSegment
    c.clips[0].speed_map = [SpeedSegment(1, 4, 1)]
    c.audio[0].src_in = .1
    forbid_work(monkeypatch)
    with pytest.raises(EDLValidationError) as caught:
        render_composition(c, tmp_path / "out.mp4")
    message = str(caught.value)
    assert message.startswith("not yet supported in this renderer: ")
    for text in ("speed maps", "duck_scope=all_speech", "loudness targets"):
        assert text in message
    assert "hyperframes" not in message
    assert "dissolve" not in message
    assert "LUTs" not in message
    assert not (tmp_path / "out.mp4").exists()


@pytest.mark.parametrize("role", ["speech", "silence", "uncertain", "sfx", "ambience"])
def test_audio_roles_cannot_silently_become_music(tmp_path, role):
    from myzing.composition import CompositionAudio
    c = plan(tmp_path)
    c.audio = [CompositionAudio("asset-alias", "music", id="track", asset_id="asset", role=role)]
    with pytest.raises(EDLValidationError, match=f"track: role={role}"):
        prepare_composition(c, tmp_path)


def test_unsafe_acceptance_is_per_event_and_roundtrips(tmp_path, monkeypatch):
    event = caption()
    event.layout = replace(event.layout, overlap=OverlapCheck(False, face_ids=["face"]), reason="infeasible", warnings=["infeasible: overlap"])
    c = plan(tmp_path, captions=[event])
    forbid_work(monkeypatch)
    with pytest.raises(EDLValidationError, match="caption caption: unsafe/infeasible"):
        prepare_composition(c, tmp_path)
    c.warnings.append("unsafe layout is fine")
    with pytest.raises(EDLValidationError, match="accepted_unsafe_layouts"):
        prepare_composition(c, tmp_path)
    c.accepted_unsafe_layouts = ["caption"]
    c = Composition.from_json(c.to_json())
    prepared = prepare_composition(c, tmp_path)
    assert any("explicitly accepted" in w for w in prepared.warnings)
    with pytest.raises(ValueError, match="accepted_unsafe_layouts"):
        lower_to_v1(c)
    with pytest.raises(ValueError, match="existing caption ids"):
        replace(c, accepted_unsafe_layouts=["wrong-id"])


def test_id_resolution_does_not_guess_by_ambiguous_alias(tmp_path):
    c = plan(tmp_path)
    other = tmp_path / "other.mp4"
    other.write_bytes(b"different")
    c.assets.append(AssetRef("other", other.name, hashlib.sha256(other.read_bytes()).hexdigest(), aliases=["asset-alias"]))
    c.clips.append(CompositionClip("asset-alias", 0, 1, 3, id="second", asset_id="other"))
    prepared = prepare_composition(c, tmp_path)
    assert [c.src for c in prepared.edl.clips] == ["asset", "other"]
    assert prepared.assets["other"] == other
    assert c.clips[0].src == "asset-alias"


def test_null_legacy_hash_is_reported_without_inventing_identity(tmp_path):
    c = plan(tmp_path)
    c.assets[0].sha256 = None
    prepared = prepare_composition(c, tmp_path)
    assert any("unverified" in w for w in prepared.warnings)
    assert prepared.composition.assets[0].sha256 is None


@pytest.mark.parametrize("path", ["https://example.invalid/video.mp4", "//server/share/video.mp4", r"\\server\share\video.mp4"])
def test_v2_does_not_read_network_assets(tmp_path, path, monkeypatch):
    c = plan(tmp_path)
    c.assets[0].path = path
    monkeypatch.setattr(Path, "is_file", lambda *a: pytest.fail("network asset was inspected"))
    with pytest.raises(EDLValidationError, match="use a local file path"):
        prepare_composition(c, tmp_path)


def test_libass_preflight_precedes_probes_and_work_files(tmp_path, monkeypatch):
    c = plan(tmp_path, captions=[caption()])
    def missing(_):
        raise FFmpegCapabilityError("missing libass; install ffmpeg-full")
    monkeypatch.setattr(pipeline, "caption_filter", missing)
    monkeypatch.setattr(pipeline, "probe_media", lambda *a: pytest.fail("probe called"))
    out, work = tmp_path / "new/video.mp4", tmp_path / "work"
    with pytest.raises(pipeline.RenderError, match="libass"):
        render_composition(c, out, base_dir=tmp_path, work_dir=work)
    assert not out.parent.exists() and not work.exists()


@pytest.mark.parametrize("timing", [None, {"version": 1, "status": "measured", "method": "fixture", "original": {"start": 0, "end": 1}, "adjustments": []},
    {"version": 1, "status": "corrected", "method": "user_correction", "original": {"start": .5, "end": .5}, "adjustments": []}])
def test_word_provenance_is_not_rewritten(tmp_path, timing):
    c = plan(tmp_path, captions=[caption(word_timed=True, words=[Word("ONE", 0, .8, timing=timing), Word("TWO", 1, 2)])])
    original = c.to_json()
    prepared = prepare_composition(c, tmp_path)
    assert c.to_json() == original
    assert prepared.composition.to_json() == original


def test_pending_word_review_and_mismatched_text_fail(tmp_path):
    event = caption(word_timed=True, words=[Word("ONE", 0, .8, timing={"version": 1, "status": "pending"})])
    with pytest.raises(EDLValidationError, match="timing review"):
        prepare_composition(plan(tmp_path, captions=[event]), tmp_path)
    event.words = [Word("WRONG", 0, .8)]
    with pytest.raises(EDLValidationError, match="does not match phrase"):
        prepare_composition(plan(tmp_path, captions=[event]), tmp_path)


def test_private_font_retains_glyphs_license_and_has_valid_checksums():
    def tables(data):
        out = {}
        for i in range(struct.unpack_from(">H", data, 4)[0]):
            tag, _, offset, length = struct.unpack_from(">4sIII", data, 12 + 16 * i)
            out[tag] = data[offset:offset + length]
        return out
    for name in ("Anton-Regular.ttf", "IBMPlexSans.ttf"):
        source = (FONTS / name).read_bytes()
        alias, data = private_font(source)
        assert alias.encode("utf-16-be") in tables(data)[b"name"]
        assert sum(v[0] for v in struct.iter_unpack(">I", data)) & 0xFFFFFFFF == 0xB1B0AFBA
        for tag, contents in tables(source).items():
            if tag not in {b"name", b"head", b"DSIG"}:
                assert contents == tables(data)[tag]
        assert b"\x00O\x00F\x00L" in tables(data)[b"name"] or b"\x00l\x00i\x00c\x00e\x00n\x00s\x00e" in tables(data)[b"name"]
        assert (FONTS / name).read_bytes() == source


def test_cli_dispatches_v2_and_rejects_v1_only_options(tmp_path, monkeypatch, capsys):
    c = plan(tmp_path)
    path = tmp_path / "plan.json"
    path.write_text(c.to_json(), encoding="utf-8")
    calls = []
    def render(composition, output, **kwargs):
        calls.append((composition, output, kwargs))
        return pipeline.RenderResult(output, 3, (), (), "", None)
    monkeypatch.setattr(command, "render_composition", render)
    assert command.run([str(path)]) == 0
    assert isinstance(calls[0][0], Composition) and calls[0][2]["base_dir"] == tmp_path
    assert command.run([str(path), "--otio", "out.otio"]) == 1
    assert "not yet supported" in capsys.readouterr().err
    assert len(calls) == 1


def test_optional_controls_load_old_v2_and_v1_lowering_still_preserves_bytes():
    original = EDL(clips=[Clip("source", 0, 1, 0)])
    data = upgrade_edl(original).to_dict()
    data.pop("accepted_unsafe_layouts")
    assert lower_to_v1(Composition.from_dict(data)).to_json() == original.to_json()
