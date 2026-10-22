"""Reference facts must never become invented fonts, grades, or presets."""

import copy
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from myzing.audio.models import AudioMap, Loudness, Onset, Segment, Tempo
from myzing.color.models import Candidate, LookParameters, MatchResult, Measurement, Recipe, Sample, Statistics, Transform
from myzing.composition import ColorTransform, FontAsset, TransitionRecipe
from myzing.contracts import Record
from myzing.layout.types import Box, FaceTrack, Keyframe, LayoutPlan
from myzing.schemas import Breakdown, TransitionObservation, Word
from myzing.study.transitions import TransitionEvidence, TransitionsResult
from myzing.style_recipe import (
    Approximations, Coverage, CropEvidence, FontCandidate, MeasuredFact,
    ObservationProvenance, StyleRecipe, Unknown, build_style_recipe,
)

ROOT = Path(__file__).resolve().parents[1]
BREAKDOWNS = sorted((ROOT / "tools/eval").rglob("breakdown.json"))


@pytest.mark.parametrize("path", BREAKDOWNS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_recipe_construction_from_every_existing_fixture_breakdown(path, monkeypatch):
    breakdown = Breakdown.from_json(path.read_text(encoding="utf-8"))
    before = breakdown.to_json()
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("recipe construction performed IO"))
    recipe = build_style_recipe(breakdown)
    assert recipe.to_json() == build_style_recipe(breakdown).to_json()
    assert StyleRecipe.from_json(recipe.to_json()).to_json() == recipe.to_json()
    assert breakdown.to_json() == before
    assert {"original_font", "original_LUT", "original_preset", "original_project"} <= {u.subject for u in recipe.unknowns}
    assert recipe.approximations == Approximations()
    assert all(fact.unit and fact.coverage.basis and fact.provenance.reference for fact in recipe.measured)
    assert all(w in recipe.warnings for w in breakdown.warnings)


def sample_breakdown():
    b = Breakdown.from_json((ROOT / "tools/eval/sample/breakdown.json").read_text(encoding="utf-8"))
    b.words = [Word("hello", .25, .75), Word("zing", .75, 1.75)]
    return b


def color_recipe():
    stats = Statistics([0.1] * 7, [50] * 7, 20, [0, 0], [1, 1], [[0, 1], [0, 1]],
                       [1] * 5, [[0, 0]] * 4, [[50, 0, 0]], [1], {"black": 0, "white": 0}, 100)
    measured = Measurement("reference.mp4", "a" * 64, 3, [Sample(1, 0, stats)], stats,
                           {"sample_fraction": 0.5, "requested_samples": 2, "usable_samples": 1},
                           0.2, {"color_space": "bt709"}, ["sparse color coverage"])
    transform = Transform("teal-orange", LookParameters(shadows=[-0.07, 0.035, 0.055]), strength=0.6)
    candidate = Candidate(transform, 0.1, {"palette": 0.1}, ["closest of supplied look bank"])
    match = MatchResult([candidate], candidate, 0.4, 0.2, [])
    return Recipe(measured, copy.deepcopy(measured), match, stats, "look.cube", "b" * 64,
                  "preview.png", "SDR Rec.709", ["approximation only"], "0.1.0", "1")


def test_optional_outputs_keep_measurements_choices_and_abstentions_separate():
    from jsonschema import Draft202012Validator
    from myzing.schema_export import schemas

    b = sample_breakdown()
    b.judgment = {"study": {"claim": "not a measurement"}}
    color = color_recipe()
    audio = AudioMap("reference.mp4", 3, 22050, 3, True,
                     Tempo("none", None, 0.1, "no stable beat grid"), [], [Onset(1, 0.8)],
                     [Segment(0, 3, "uncertain", 0.2, "ambiguous energy")], Loudness(-18, None, -2),
                     warnings=["truncated"], tool_versions={"audio_algorithm": "1"})
    layout = LayoutPlan([], [FaceTrack("face", [Keyframe(1, Box(0.2, 0.1, 0.3, 0.3))])], [],
                        provenance={"video": "reference.mp4", "video_sha256": "a" * 64,
                                    "sample_times": [1], "backend": "OpenCV DNN CPU", "opencv_version": "4.13",
                                    "model_url": "local-test-model.onnx", "model_sha256": "c" * 64})
    known = TransitionEvidence("wipe", 1, 1.5, 0.8, 1.7, 0.85, 5, "moving spatial boundary", 0, "left")
    abstained = TransitionEvidence("unknown", 2, 2.2, 1.8, 2.4, 0, 5, "motion lacks quiet handles")
    transitions = TransitionsResult([TransitionObservation("wipe", 1, 1.5, 15, True, -0.02)],
                                    {"transition_detector": "zing-transition-signatures",
                                     "transition_evidence": [known.to_dict(), abstained.to_dict()]}, ["experimental"])
    crop = CropEvidence(0.25, Box(0.1, 0.4, 0.8, 0.2), "crop.png", "d" * 64)
    provenance = ObservationProvenance("reference.mp4", "a" * 64, [0.25], "OCR", "1", "glyph-model", "rev1",
                                       crop_evidence=[crop])
    chosen = TransitionRecipe("wipe", 0.5, "chosen stand-in", "left", known)
    font = FontCandidate("Anton", ["supplied licensed substitute; no exact font identification"],
                         FontAsset("Anton.ttf", "e" * 64, "OFL-1.1"))
    before = [copy.deepcopy(obj.to_dict()) for obj in (b, color, audio, layout)]
    recipe = build_style_recipe(b, color=color, audio=audio, layout=layout, transitions=transitions,
                                font_candidates=[font], transition_recipes=[chosen], provenance={"captions": provenance})
    facts = {f.name: f for f in recipe.measured}
    assert facts["color.palette"].value == color.reference.aggregate.palette
    assert facts["color.palette"].coverage.fraction == 0.5
    assert facts["color.palette"].confidence == 0.2
    assert facts["color.palette"].confidence_kind == "heuristic"
    assert facts["captions[0]"].provenance.crop_evidence == [crop]
    assert facts["transitions[0]"].value == known.to_dict()
    assert facts["transitions[0]"].provenance.detector_version == 5
    assert facts["transitions[0]"].provenance.details["legacy_observation"]["audio_onset_delta"] == -0.02
    assert any(u.evidence == abstained.to_dict() for u in recipe.unknowns)
    assert any(u.subject == "audio.tempo" and u.evidence["status"] == "none" for u in recipe.unknowns)
    assert "audio.tempo" not in facts and "audio.beats" not in facts
    assert recipe.approximations.font_candidates == [font]
    assert recipe.approximations.transitions == [chosen]
    assert recipe.approximations.layout == layout
    lut = recipe.approximations.looks[0].color
    assert lut.strength == 1  # PC cube already baked the 0.6 strength.
    assert lut.baked_transform.strength == 0.6
    assert {"sparse color coverage", "approximation only", "truncated", "experimental"} <= set(recipe.warnings)
    assert "not a measurement" not in recipe.to_json()
    assert [obj.to_dict() for obj in (b, color, audio, layout)] == before

    def walk(value):
        if is_dataclass(value):
            if isinstance(value, Record):
                assert value.version == 1
                assert type(value).from_json(value.to_json()).to_json() == value.to_json()
            for f in fields(value):
                walk(getattr(value, f.name))
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(recipe)
    Draft202012Validator(schemas()["style-recipe-v1.schema.json"]).validate(recipe.to_dict())


def test_word_timing_is_evidence_not_an_inferred_measurement():
    from myzing.schemas import Word

    b = sample_breakdown()
    b.words = [Word("Hi", 0.1, 0.4, timing={"status": "corrected", "method": "user_correction",
                                         "original": {"start": 0.1, "end": 0.1}, "version": 1})]
    recipe = build_style_recipe(b)
    words = next(f for f in recipe.measured if f.name == "words")
    assert words.value[0]["timing"] == b.words[0].timing
    assert words.confidence is None
    assert any(u.subject == "word_confidence_calibration" for u in recipe.unknowns)


def test_unmeasured_defaults_do_not_become_zero_music_or_beat_claims():
    b = sample_breakdown()
    b.words, b.shots, b.captions = [], [], []
    b.audio.loudness_curve = []
    b.provenance = {}
    recipe = build_style_recipe(b)
    assert [f.name for f in recipe.measured] == ["duration"]
    assert recipe.measured[0].provenance.detector_version is None
    assert recipe.reference.sha256 is None
    assert any(u.subject == "reference.sha256" for u in recipe.unknowns)


def test_audio_provenance_uses_known_hash_only_for_the_same_source():
    b = sample_breakdown()
    b.meta.media_path = "reference.mp4"
    audio = AudioMap("reference.mp4", 3, 22050, 600, False, Tempo(), [], [], [], Loudness(-18, None, -1))
    recipe = build_style_recipe(b, reference_sha256="a" * 64, audio=audio)
    fact = next(f for f in recipe.measured if f.name == "audio.integrated_lufs")
    assert fact.provenance.sha256 == "a" * 64
    audio.source = "another.mp4"
    recipe = build_style_recipe(b, reference_sha256="a" * 64, audio=audio)
    fact = next(f for f in recipe.measured if f.name == "audio.integrated_lufs")
    assert fact.provenance.sha256 is None
    with pytest.raises(ValueError, match="SHA-256"):
        build_style_recipe(b, reference_sha256="")


def test_embedded_historical_detector_versions_are_retained():
    b = sample_breakdown()
    b.provenance = {"shot_detector": "scenedetect-0.7 AdaptiveDetector", "ocr_backend": "rapidocr-3.9.1"}
    facts = {f.name: f for f in build_style_recipe(b).measured}
    assert facts["shot_durations"].provenance.detector_version == "0.7"
    assert facts["captions[0]"].provenance.detector_version == "3.9.1"


@pytest.mark.parametrize("mutate,match", [
    (lambda b: b.provenance.update({"bad": float("nan")}), "finite"),
    (lambda b: setattr(b.meta, "duration", float("inf")), "finite"),
    (lambda b: setattr(b, "schema_version", 2), "unsupported"),
])
def test_invalid_recipe_input(mutate, match):
    b = sample_breakdown()
    mutate(b)
    with pytest.raises(ValueError, match=match):
        build_style_recipe(b)


@pytest.mark.parametrize("construct,match", [
    (lambda: FontCandidate("Arial", []), "substitution evidence"),
    (lambda: Coverage(1, 2, "sample fraction"), "coverage fraction"),
    (lambda: Coverage(-1, None, "unknown"), "non-negative"),
    (lambda: ObservationProvenance("ref.mp4", "wrong"), "SHA-256"),
    (lambda: StyleRecipe(ObservationProvenance("ref.mp4"), version=2), "unsupported"),
    (lambda: CropEvidence(-1, Box(0, 0, 1, 1)), "non-negative"),
    (lambda: MeasuredFact("test", 1, "count", Coverage(1, None, "unknown"), 0.5,
                          ObservationProvenance("ref.mp4")), "must agree"),
])
def test_recipe_validation(construct, match):
    with pytest.raises(ValueError, match=match):
        construct()


@pytest.mark.parametrize("field,value,match", [
    ("confidence", 2, "confidence"), ("evidence_start_seconds", 1.1, "evidence window"),
    ("direction", "diagonal", "direction"), ("observation_index", 10, "outside"),
    ("signature", "dissolve", "only wipe|must agree"),
])
def test_transition_sidecar_validation(field, value, match):
    b = sample_breakdown()
    known = TransitionEvidence("wipe", 1, 1.5, 0.8, 1.7, 0.85, 5, "boundary", 0, "left").to_dict()
    known[field] = value
    result = TransitionsResult([TransitionObservation("wipe", 1, 1.5)], {"transition_evidence": [known]}, [])
    with pytest.raises(ValueError, match=match):
        build_style_recipe(b, transitions=result)
