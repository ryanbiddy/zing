"""P4 contract boundary: no renderer or optional media runtime is involved."""

import copy
import json
import sys
from dataclasses import fields, is_dataclass, replace
from fractions import Fraction
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from myzing.audio.models import AudioMap, Loudness, Segment, Tempo
from myzing.composition import *
from myzing.contracts import Record
from myzing.layout.types import Box, EventLayout, Keyframe, OverlapCheck
from myzing.project.models import Asset, ProjectManifest, Rational, Reference, SourceRecord
from myzing.render.validation import EDLValidationError, validate_edl
from myzing.schema_export import schemas
from myzing.schemas import AudioTrack, CaptionSpec, Clip, EDL, Word
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.composition_examples import example_documents, talking_head_example


def legacy(fps=30.0):
    return EDL(
        clips=[Clip("take's clip.mp4", 1, 3.5, 0)], fps=fps,
        captions=[CaptionSpec("café zing", 0.1, 1, words=[
            Word("café", 0.1, 0.4, 0.8, {"version": 1, "status": "corrected", "method": "user_correction",
                                       "original": {"start": 1.1, "end": 1.1}, "adjustments": []}),
            Word("zing", 0.4, 1),
        ])],
        audio=[AudioTrack("music.wav", "music", 0, -12, True)],
    )


@pytest.mark.parametrize("fps", [30, 30.0, 29.97, 23.976, 30000 / 1001])
def test_upgrade_lowering_preserve_v1_bytes_and_numeric_spelling(fps):
    source = legacy(fps)
    original = source.to_json(indent=2).encode("utf-8")
    v2 = upgrade_edl(source)
    again = Composition.from_json(v2.to_json())
    assert lower_to_v1(again).to_json(indent=2).encode("utf-8") == original
    assert rate(again.fps) == Fraction(str(fps))
    assert again.captions[0].words[0].timing == source.captions[0].words[0].timing
    assert "timing" not in again.to_dict()["captions"][0]["words"][1]
    again.captions[0].words[0].timing["adjustments"].append({"note": "different"})
    assert source.to_json(indent=2).encode("utf-8") == original


def rate(fps):
    return Fraction(fps.numerator, fps.denominator)


def test_upgrade_uses_inventory_identity_hash_and_aliases_without_io(monkeypatch):
    source = legacy()
    origin = SourceRecord("media/take.mp4")
    asset = Asset("stable-42", "media/take.mp4", source.clips[0].src, "a" * 64, 100, 1, origin, None)
    manifest = ProjectManifest(Reference("reference.mp4", "file", origin), "media", origin, [asset])
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("upgrade performed IO"))
    upgraded = upgrade_edl(source, manifest=manifest)
    assert upgraded.assets[0].id == "stable-42"
    assert upgraded.assets[0].sha256 == "a" * 64
    assert upgraded.assets[0].aliases == [source.clips[0].src]
    assert lower_to_v1(upgraded).to_json() == source.to_json()
    assert upgraded.assets[1].sha256 is None
    assert upgraded.assets[1].id == upgrade_edl(source).assets[1].id


def test_multiple_legacy_spellings_retain_one_manifest_identity():
    origin = SourceRecord("canonical.mp4")
    asset = Asset("same", "canonical.mp4", "old.mp4", "a" * 64, 1, 1, origin, None)
    manifest = ProjectManifest(Reference("ref.mp4", "file", origin), ".", origin, [asset])
    edl = EDL(clips=[Clip("old.mp4", 0, 1, 0), Clip("canonical.mp4", 1, 2, 1)])
    v2 = upgrade_edl(edl, manifest=manifest)
    assert len(v2.assets) == 1
    assert lower_to_v1(v2).to_json() == edl.to_json()


def test_worked_composition_roundtrip_determinism_and_typed_reuse():
    c, layout = talking_head_example()
    assert all(e.overlap.safe for e in layout.events)
    assert layout.events[0].reason != "preferred-anchor"  # Face blocks the requested center.
    assert c.captions[1].layout.path
    encoded = c.to_json()

    def reversed_keys(value):
        if isinstance(value, dict):
            return {k: reversed_keys(v) for k, v in reversed(list(value.items()))}
        return [reversed_keys(v) for v in value] if isinstance(value, list) else value

    rebuilt = Composition.from_dict(reversed_keys(c.to_dict()))
    assert rebuilt.to_json() == encoded
    assert isinstance(rebuilt.clips[0], Clip)
    assert isinstance(rebuilt.captions[0], CaptionSpec)
    assert isinstance(rebuilt.captions[0].layout, EventLayout)
    assert isinstance(rebuilt.captions[0].words[0], Word)
    assert isinstance(rebuilt.fps, Rational)
    assert rebuilt.clips[0].color.stage == "before_captions"


def test_upgrade_preserves_v1_caption_end_tolerance():
    source = legacy()
    source.captions[0].words[-1].end += 0.0000005
    from myzing.render.validation import _validate_caption
    _validate_caption(source.captions[0], 0, 2.5, [])
    assert lower_to_v1(upgrade_edl(source)).to_json() == source.to_json()


def test_all_new_composition_records_have_version_and_deterministic_codec():
    c, _ = talking_head_example()

    def walk(value):
        if is_dataclass(value):
            if isinstance(value, Record):
                assert hasattr(value, "version") or hasattr(value, "schema_version")
                assert type(value).from_json(value.to_json()).to_json() == value.to_json()
            for f in fields(value):
                walk(getattr(value, f.name))
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(c)
    for obj in [SpeedSegment(0, 1, 0.5), SourceRange(0, 1)]:
        assert type(obj).from_dict(obj.to_dict()).to_json() == obj.to_json()


def test_rational_output_frame_helpers_are_exact_and_do_not_guess_ntsc():
    fps = Rational(30000, 1001)
    assert frame_time(30000, fps) == 1001
    assert frame_index(frame_time(123456, fps), fps) == 123456
    assert frame_index(Fraction(1001, 60000), fps) == 0
    assert frame_index(Fraction(1001, 60000), fps, rounding="nearest") == 1
    assert frame_index(Fraction(1001, 60000), fps, rounding="ceil") == 1
    assert upgrade_edl(legacy(29.97)).fps == Rational(2997, 100)


@pytest.mark.parametrize("call,match", [
    (lambda: frame_time(True, Rational(30, 1)), "frame index"),
    (lambda: frame_index(float("nan"), Rational(30, 1)), "finite"),
    (lambda: frame_index(-1, Rational(30, 1)), "non-negative"),
    (lambda: frame_index(1, Rational(30, 1), rounding="bankers"), "rounding"),
    (lambda: Composition(fps=Rational(1.5, 1)), "integer|int"),
])
def test_frame_helper_validation(call, match):
    with pytest.raises(ValueError, match=match):
        call()


def test_speed_map_source_handles_follow_source_seconds():
    a = CompositionClip("a.mp4", 0, 4, 0, id="a", asset_id="a",
                        speed_map=[SpeedSegment(0, 2, 2), SpeedSegment(2, 4, 1)])
    b = CompositionClip("b.mp4", 1, 4, 2.5, id="b", asset_id="b")
    assert a.duration == 3
    assert a.source_at(0.5) == 1
    assert a.source_at(2.5) == 3.5
    assert a.source_at(3) == 4
    t = Transition("t", "a", "b", 2.5, 3, TransitionRecipe("dissolve", 0.5, "chosen"),
                   SourceRange(3.5, 4), SourceRange(1, 1.5))
    c = Composition(assets=[AssetRef("a", "a.mp4", None), AssetRef("b", "b.mp4", None)],
                    clips=[a, b], transitions=[t])
    assert Composition.from_dict(c.to_dict()).clips[0].source_at(2.5) == 3.5


def set_value(data, path, value):
    for key in path[:-1]:
        data = data[key]
    data[path[-1]] = value


@pytest.mark.parametrize("path,value,match", [
    (("schema_version",), 3, "unsupported"),
    (("schema_version",), True, "unsupported"),
    (("fps", "version"), 2, "unsupported"),
    (("fps", "denominator"), 0, "positive"),
    (("width",), True, "int"),
    (("assets", 0, "sha256"), "bad", "SHA-256"),
    (("assets", 0, "id"), "asset-take-2", "duplicate"),
    (("clips", 0, "asset_id"), "missing", "unknown asset"),
    (("clips", 0, "src"), "elsewhere.mp4", "asset path"),
    (("clips", 0, "src_out"), 20, "asset duration"),
    (("clips", 0, "src_in"), -1, "trim"),
    (("clips", 0, "timeline_start"), -1, "non-negative"),
    (("clips", 0, "color", "stage"), "after_captions", "before_captions"),
    (("clips", 0, "color", "strength"), 2, "strength"),
    (("transitions", 0, "outgoing_handle"), None, "missing required source handles"),
    (("transitions", 0, "incoming_handle", "src_out"), 2.4, "entire overlap"),
    (("transitions", 0, "incoming_clip"), "clip-3", "adjacent"),
    (("transitions", 0, "start"), 1, "match recipe duration"),
    (("transitions",), [], "explicit transition"),
    (("captions", 0, "layout", "box", "x"), -0.1, "between"),
    (("captions", 0, "layout", "box", "width"), 1.1, "between"),
    (("captions", 0, "layout", "box", "x"), 0.9, "normalized frame"),
    (("captions", 0, "layout", "overlap", "safe"), False, "agree"),
    (("captions", 0, "layout", "id"), "wrong", "match"),
    (("captions", 1, "layout", "path", 1, "time"), 3.1, "increasing"),
    (("captions", 1, "layout", "path", 0, "time"), 3.3, "cover"),
    (("captions", 0, "backend"), "both", "one of"),
    (("captions", 1, "font"), None, "needs layout, font"),
    (("captions", 0, "font", "sha256"), "ABC", "SHA-256"),
    (("captions", 0, "style", "color"), "yellow", "#RRGGBB"),
    (("captions", 0, "words", 0, "end"), 0.3, "zero duration"),
    (("captions", 0, "words", 0, "start"), 0.1, "outside caption"),
    (("audio", 0, "role"), "speech", "only music"),
    (("audio", 0, "duck_scope"), "detected_sfx", "one of"),
    (("loudness_target", "true_peak_dbtp"), 2, "target true peak"),
    (("unknown_field",), 2, "unsupported fields"),
])
def test_invalid_composition(path, value, match):
    data = talking_head_example()[0].to_dict()
    set_value(data, path, value)
    with pytest.raises(ValueError, match=match):
        Composition.from_dict(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("path", [
    ("clips", 0, "src_in"), ("clips", 0, "color", "strength"),
    ("captions", 0, "layout", "box", "x"), ("audio", 0, "gain_db"),
    ("captions", 0, "words", 0, "timing", "original", "end"),
])
def test_nonfinite_values_fail_even_inside_timing_evidence(path, value):
    data = talking_head_example()[0].to_dict()
    set_value(data, path, value)
    with pytest.raises(ValueError, match="finite"):
        Composition.from_dict(data)


def test_overlap_longer_than_either_clip():
    data = talking_head_example()[0].to_dict()
    data["transitions"][0].update(start=0, end=4)
    data["transitions"][0]["recipe"]["duration_seconds"] = 4
    with pytest.raises(ValueError, match="longer than either clip"):
        Composition.from_dict(data)


@pytest.mark.parametrize("segments", [[SpeedSegment(1, 2, 1)], [SpeedSegment(0, 1, 1), SpeedSegment(1.1, 2, 1)]])
def test_speed_map_gaps_and_incomplete_trim(segments):
    with pytest.raises(ValueError, match="speed map"):
        CompositionClip("x.mp4", 0, 2, 0, id="x", asset_id="x", speed_map=segments)


def test_mutation_is_validated_before_serialization():
    c = upgrade_edl(legacy())
    c.clips[0].src_out = float("inf")
    with pytest.raises(ValueError, match="finite"):
        c.to_json()


@pytest.mark.parametrize("version", [0, 2, 3, "1", True, 1.0, None])
def test_v1_loader_refuses_other_versions(version):
    with pytest.raises(ValueError, match="unsupported EDL schema_version"):
        EDL.from_dict({"schema_version": version})


def test_explicit_dispatch_and_renderer_stays_v1(tmp_path):
    assert load_composition(legacy().to_dict()).schema_version == 2
    composition, _ = talking_head_example()
    assert load_composition(composition.to_dict()).to_dict() == composition.to_dict()
    with pytest.raises(ValueError, match="unsupported EDL schema_version"):
        load_composition({"schema_version": 99})
    with pytest.raises(EDLValidationError, match="unsupported EDL schema_version 2"):
        validate_edl(composition, tmp_path, lambda _: pytest.fail("v2 reached media probe"))


def test_lowering_reports_every_v2_feature_in_worked_example():
    c, _ = talking_head_example()
    expected = example_documents()["lowering-failure.json"]["error"]
    with pytest.raises(ValueError) as caught:
        lower_to_v1(c)
    assert str(caught.value) == expected
    assert expected in (ROOT / "docs/COMPOSITION-V2.md").read_text(encoding="utf-8")
    for text in ["clips[0].color", "clips[1].color", "transitions", "captions[1].layout",
                 "captions[1].backend=hyperframes", "audio[0].duck_scope=all_speech", "loudness_target", "warnings"]:
        assert text in expected


def test_individual_lowering_blockers_cover_other_optional_fields():
    from myzing.brief import Brief

    c = upgrade_edl(legacy())
    c.clips[0].speed_map = [SpeedSegment(1, 3.5, 1)]
    c.audio[0].src_out = 2
    c.audio[0].role_evidence = Segment(0, 2, "music", 0.8, "given")
    c.brief = Brief()
    assert lowering_blockers(c) == ["clips[0].speed_map", "audio[0].role_evidence", "audio[0].source_trim", "brief"]
    c.fps = Rational(24, 1)
    assert "fps differs from legacy_fps" in lowering_blockers(c)
    c.legacy_fps = None
    c.fps = Rational(30000, 1001)
    assert "rational fps cannot be represented exactly by v1" in lowering_blockers(c)


def test_audio_map_roles_are_kept_without_inference():
    audio = AudioMap("source.wav", 2, 22050, 600, False, Tempo(), [], [],
                     [Segment(0, 1, "uncertain", 0.2, "unresolved")], Loudness(None, None, None))
    track = audio_from_map(audio, 0, id="audio-1", asset=AssetRef("a", "source.wav", "a" * 64))
    assert track.role == "uncertain" and track.role_evidence == audio.segments[0]
    assert (track.src_in, track.src_out) == (0, 1)
    assert CompositionAudio.from_json(track.to_json()).to_json() == track.to_json()
    with pytest.raises(ValueError, match="must agree"):
        replace(track, role="sfx")


def test_generated_schemas_and_worked_documents_validate_and_are_current():
    examples = example_documents()
    for filename, schema in schemas().items():
        assert "oneOf" not in schema and schema["type"] == "object"
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        document = examples["talking-head.json" if filename.startswith("composition") else "style-recipe.json"]
        validator.validate(document)
        packaged = files("myzing").joinpath("_data/schemas", filename).read_bytes()
        expected = (json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        assert packaged == expected
        bad = copy.deepcopy(document)
        bad["schema_version" if filename.startswith("composition") else "version"] = 99
        assert not validator.is_valid(bad)
    for name, data in examples.items():
        expected = (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        assert (ROOT / "docs/examples/composition-v2" / name).read_bytes() == expected


def test_json_schema_rejects_missing_overlap_handles():
    data = talking_head_example()[0].to_dict()
    del data["transitions"][0]["incoming_handle"]
    assert not Draft202012Validator(schemas()["composition-v2.schema.json"]).is_valid(data)


@pytest.mark.parametrize("kind", ["dip_to_black", "dip_to_white"])
def test_json_schema_requires_handles_for_dips(kind):
    data = talking_head_example()[0].to_dict()
    data["transitions"][0]["recipe"]["kind"] = kind
    data["transitions"][0]["recipe"].pop("direction", None)
    validator = Draft202012Validator(schemas()["composition-v2.schema.json"])
    assert validator.is_valid(data)
    del data["transitions"][0]["outgoing_handle"]
    assert not validator.is_valid(data)


def test_caption_fields_project_to_the_existing_hyperframes_plan():
    from myzing.render.hyperframes_adapter import validate_plan

    c, _ = talking_head_example()
    caption = c.captions[1]
    style = caption.style.to_dict()
    del style["version"]
    del style["box_color"]
    style["font"] = caption.font.path
    path = [{"time": k.time, "box": {n: getattr(k.box, n) for n in ("x", "y", "width", "height")}}
            for k in caption.layout.path]
    p = {"version": 1, "width": c.width, "height": c.height, "fps": 30, "duration": 8,
         "background": {"color": "#000000"}, "captions": [{
             "start": caption.start, "end": caption.end, "template": caption.template,
             "path": path, "style": style,
             "words": [{"text": w.text, "start": w.start, "end": w.end} for w in caption.words],
         }]}
    assert validate_plan(p) == p
    assert all(w.timing is not None for w in caption.words)
