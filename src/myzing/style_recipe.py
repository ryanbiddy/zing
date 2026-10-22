"""StyleRecipe v1: evidence, chosen approximations, and explicit unknowns.

Construction is pure: no IO, model calls, asset fetching, current timestamps,
or claims to recover the creator's font, LUT, preset, or editor project.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re
from typing import Any, Literal

from myzing.audio.models import AudioMap
from myzing.color.models import Recipe as ColorRecipe
from myzing.composition.models import ColorTransform, FontAsset, TransitionRecipe, validate_evidence
from myzing.contracts import Record, bounded, digest, encode, json_value, nonempty
from myzing.layout.types import Box, LayoutPlan
from myzing.schemas import Breakdown
from myzing.study.transitions import TransitionEvidence, TransitionsResult


@dataclass
class CropEvidence(Record):
    timestamp: float
    box: Box
    path: str | None = None
    sha256: str | None = None
    note: str = ""
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if self.timestamp < 0:
            raise ValueError("crop timestamp must be non-negative")
        digest(self.sha256, "crop sha256")


@dataclass
class ObservationProvenance(Record):
    reference: str  # URL or file supplied by the producer; never resolved here.
    sha256: str | None = None
    sample_timestamps: list[float] = field(default_factory=list)
    detector: str | None = None
    detector_version: str | int | None = None
    model: str | None = None
    model_version: str | None = None
    timestamp_basis: str = "reported source intervals; exact sampling unavailable"
    crop_evidence: list[CropEvidence] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.reference, "observation reference URL or file")
        nonempty(self.timestamp_basis, "timestamp_basis")
        digest(self.sha256, "reference sha256")
        if any(t < 0 for t in self.sample_timestamps):
            raise ValueError("sample timestamps must be non-negative")


@dataclass
class Coverage(Record):
    samples: int
    fraction: float | None
    basis: str
    details: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if self.samples < 0:
            raise ValueError("coverage samples must be non-negative")
        if self.fraction is not None:
            bounded(self.fraction, 0, 1, "coverage fraction")
        nonempty(self.basis, "coverage basis")


@dataclass
class MeasuredFact(Record):
    name: str
    value: Any
    unit: str
    coverage: Coverage
    confidence: float | None
    provenance: ObservationProvenance
    confidence_kind: Literal["unreported", "producer-reported", "heuristic"] = "unreported"
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        for name in ("name", "unit"):
            nonempty(getattr(self, name), f"measurement {name}")
        if self.confidence is not None:
            bounded(self.confidence, 0, 1, "measurement confidence")
        if (self.confidence is None) != (self.confidence_kind == "unreported"):
            raise ValueError("measurement confidence and confidence_kind must agree")


@dataclass
class FontCandidate(Record):
    family: str
    substitution_evidence: list[str]
    asset: FontAsset | None = None
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.family, "font candidate family")
        if not self.substitution_evidence or any(not v.strip() for v in self.substitution_evidence):
            raise ValueError("font candidate needs substitution evidence; original font identity is unknown")


@dataclass
class LookApproximation(Record):
    color: ColorTransform
    evidence: list[str]
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if not self.evidence:
            raise ValueError("look approximation needs selection evidence")


@dataclass
class Approximations(Record):
    font_candidates: list[FontCandidate] = field(default_factory=list)
    looks: list[LookApproximation] = field(default_factory=list)
    transitions: list[TransitionRecipe] = field(default_factory=list)
    layout: LayoutPlan | None = None
    version: int = 1


@dataclass
class Unknown(Record):
    subject: str
    reason: str
    status: Literal["unsupported", "unmeasured", "unreported"] = "unmeasured"
    provenance: ObservationProvenance | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.subject, "unknown subject")
        nonempty(self.reason, "unknown reason")


@dataclass
class StyleRecipe(Record):
    reference: ObservationProvenance
    measured: list[MeasuredFact] = field(default_factory=list)
    approximations: Approximations = field(default_factory=Approximations)
    unknowns: list[Unknown] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    version: int = 1


def build_style_recipe(
    breakdown: Breakdown, *, reference_sha256: str | None = None,
    color: ColorRecipe | None = None, audio: AudioMap | None = None,
    layout: LayoutPlan | None = None, transitions: TransitionsResult | None = None,
    font_candidates: list[FontCandidate] | None = None,
    transition_recipes: list[TransitionRecipe] | None = None,
    provenance: dict[str, ObservationProvenance] | None = None,
) -> StyleRecipe:
    """Collect producer evidence without promoting plans to measurements.

    Optional provenance overrides are keyed by scope (meta, shots, words,
    captions, audio, color, layout, transitions). They supply missing historical
    detector/model versions or crops; they do not run a detector. Sparse
    observations never imply full recall. Breakdown.judgment is not consumed.
    """
    if type(breakdown.schema_version) is not int or breakdown.schema_version != 1:
        raise ValueError("unsupported Breakdown schema_version; recipe construction expects 1")
    json_value(breakdown.to_dict(), "breakdown")
    b = deepcopy(breakdown)
    metadata = deepcopy(b.provenance)
    source = b.meta.source_url or b.meta.media_path
    reference_hash = next((v for v in (reference_sha256, metadata.get("media_sha256"), metadata.get("sha256"))
                           if v is not None), None)
    reference = ObservationProvenance(source, reference_hash, details=metadata)
    recipe = StyleRecipe(reference, warnings=list(b.warnings))
    recipe.approximations.font_candidates = deepcopy(font_candidates or [])
    recipe.approximations.transitions = deepcopy(transition_recipes or [])
    recipe.unknowns = [Unknown(f"original_{name}", "Cannot uniquely recover this from a studied reference.", "unsupported")
                       for name in ("font", "LUT", "preset", "project")]

    def evidence(scope, timestamps=(), *, ref=None, sha=None, detector=None,
                 detector_version=None, model=None, model_version=None, details=None,
                 basis="reported source intervals; exact sampling unavailable"):
        if provenance and scope in provenance:
            return deepcopy(provenance[scope])
        known_hash = sha if sha is not None else (
            reference.sha256 if not ref or ref in (source, b.meta.media_path) else None)
        return ObservationProvenance(
            reference=ref or source, sha256=known_hash,
            sample_timestamps=list(timestamps), detector=detector,
            detector_version=detector_version, model=model, model_version=model_version,
            timestamp_basis=basis, details=deepcopy(metadata if details is None else details),
        )

    def add(name, value, unit, prov, count=1, confidence=None, fraction=None,
            basis="reported records; detector recall and sampled-time coverage unknown",
            coverage_details=None, heuristic=False):
        recipe.measured.append(MeasuredFact(
            name, deepcopy(value), unit, Coverage(count, fraction, basis, coverage_details or {}),
            confidence, prov,
            "unreported" if confidence is None else ("heuristic" if heuristic else "producer-reported"),
        ))

    def unknown(subject, reason, status="unmeasured", prov=None, value=None):
        recipe.unknowns.append(Unknown(subject, reason, status, prov, value or {}))

    def embedded_version(label):
        # Historical study stamps embed the package version in these names.
        match = re.match(r"(?:scenedetect|rapidocr)-([0-9][^ ]*)", label or "")
        return match[1] if match else None

    if b.meta.duration > 0:
        add("duration", b.meta.duration, "seconds", evidence("meta"))
    else:
        unknown("duration", "Breakdown has no positive measured duration.")
    if b.shots:
        prov = evidence("shots", [s.start for s in b.shots], detector=metadata.get("shot_detector"),
                        detector_version=metadata.get("shot_detector_version") or embedded_version(metadata.get("shot_detector")))
        add("shot_durations", [s.duration for s in b.shots], "seconds", prov, len(b.shots))
        add("average_shot_duration", b.avg_shot_duration, "seconds", prov, len(b.shots))
        add("cuts_per_10s", b.cuts_per_10s, "cuts/window (10 seconds; trailing window is raw)",
            prov, len(b.cuts_per_10s))
    else:
        unknown("pacing", "No shot observations supplied; an empty list does not prove no cuts.")
    if b.words:
        prov = evidence("words", [w.start for w in b.words], detector="faster-whisper" if metadata.get("faster_whisper") else None,
                        detector_version=metadata.get("faster_whisper"), model=metadata.get("whisper_model"),
                        model_version=metadata.get("whisper_model_revision"))
        # Retain complete words, including P2 corrections and original intervals.
        add("words", encode(b.words), "seconds; confidence unitless", prov, len(b.words))
        unknown("word_confidence_calibration", "Word.confidence=1 can mean not reported; no aggregate confidence inferred.", "unreported")
    else:
        unknown("words", "No transcript words supplied; speech presence remains unmeasured.")
    for index, caption in enumerate(b.captions):
        prov = evidence("captions", [caption.start, caption.end], detector=metadata.get("ocr_backend"),
                        detector_version=metadata.get("ocr_version") or embedded_version(metadata.get("ocr_backend")))
        add(f"captions[{index}]", encode(caption), "seconds; position category; word count; unitless confidence",
            prov, confidence=caption.confidence)
    if not b.captions:
        unknown("captions", "No OCR events supplied; missing captions are not proof of absent text.")
    unknown("caption_geometry", "Breakdown OCR positions are coarse categories; exact glyph geometry is unmeasured.")
    if not provenance or not any(p.crop_evidence for p in provenance.values()):
        unknown("crop_evidence", "No observation crop assets or normalized crop boxes were supplied.")
    if not font_candidates:
        unknown("font_candidates", "No substitution candidates with evidence were supplied.")

    if b.audio.loudness_curve:
        prov = evidence("audio", range(len(b.audio.loudness_curve)), detector=metadata.get("loudness"))
        add("audio.rms_curve", b.audio.loudness_curve, "dBFS (one-second buckets)", prov,
            len(b.audio.loudness_curve))
    # Defaults are not evidence that audio analysis ran. Require its producer stamp.
    if metadata.get("vad"):
        add("audio.speech_ratio", b.audio.speech_ratio, "fraction of duration", evidence("audio", detector=metadata["vad"]))
    if metadata.get("has_music"):
        add("audio.has_music", b.audio.has_music, "boolean", evidence("audio", detector=metadata["has_music"]),
            confidence=b.audio.music_confidence, heuristic=True)

    if color is not None:
        color = deepcopy(color)
        ref = color.reference
        prov = evidence("color", [s.timestamp for s in ref.samples], ref=ref.path, sha=ref.sha256,
                        detector="zing-color", detector_version=color.color_version,
                        details={"color_metadata": ref.color_metadata, "tool_version": color.tool_version},
                        basis="requested seek seconds; not exact decoded PTS")
        units = {
            "luma_percentiles": "encoded Rec.709 Y' [0,1] at p1/5/25/50/75/95/99",
            "lightness_percentiles": "CIELAB L* at p1/5/25/50/75/95/99",
            "contrast": "CIELAB L* p95-p5", "ab_mean": "CIELAB a*, b*",
            "ab_spread": "CIELAB a*, b*", "ab_percentiles": "CIELAB a*, b* percentiles",
            "saturation": "CIELAB chroma p5/25/50/75/95", "tone_ab": "CIELAB a*, b* per L* quartile",
            "palette": "CIELAB L*, a*, b*", "palette_weights": "fraction of sampled pixels",
            "clipping": "fraction of sampled pixels", "pixel_count": "pixels",
        }
        for name, unit in units.items():
            add("color." + name, getattr(ref.aggregate, name), unit, prov, len(ref.samples), ref.confidence,
                ref.coverage.get("sample_fraction"), "usable/requested samples; not temporal coverage",
                ref.coverage, heuristic=True)
        recipe.approximations.looks.append(LookApproximation(
            ColorTransform.from_recipe(color), list(color.match.chosen.reasons) + [color.interpretation]))
        recipe.warnings.extend(color.warnings)
        recipe.warnings.extend(ref.warnings)
    else:
        unknown("color", "No measured color recipe supplied.")

    if audio is not None:
        audio = deepcopy(audio)
        prov = evidence("audio", audio.beats, ref=audio.source,
                        detector="zing-audio", detector_version=audio.tool_versions.get("audio_algorithm"),
                        details=audio.tool_versions, basis="decoded source audio seconds")
        coverage = {"decoded_seconds": audio.duration_seconds, "truncated": audio.truncated,
                    "max_seconds": audio.max_seconds}
        add("audio.segments", [s.to_dict() for s in audio.segments], "seconds; unitless confidence", prov,
            len(audio.segments), coverage_details=coverage)
        add("audio.onsets", [o.to_dict() for o in audio.onsets], "seconds; normalized spectral flux", prov,
            len(audio.onsets), coverage_details=coverage)
        if audio.tempo.status == "steady":
            add("audio.tempo", audio.tempo.bpm, "beats/minute", prov, len(audio.beats),
                audio.tempo.confidence, coverage_details=coverage, heuristic=True)
            add("audio.beats", audio.beats, "seconds", prov, len(audio.beats),
                audio.tempo.confidence, coverage_details=coverage, heuristic=True)
        else:
            unknown("audio.tempo", audio.tempo.evidence, prov=prov, value=audio.tempo.to_dict())
        for name, unit in (("integrated_lufs", "LUFS"), ("loudness_range_lu", "LU"), ("true_peak_dbtp", "dBTP")):
            value = getattr(audio.loudness, name)
            if value is None:
                unknown("audio." + name, "AudioMap reports no measurement.", prov=prov)
            else:
                add("audio." + name, value, unit, prov, coverage_details=coverage)
        unknown("audio.downbeats", "Downbeats/meter are not established by the current audio map.", "unsupported", prov)
        recipe.warnings.extend(audio.warnings)
    else:
        unknown("audio_map", "No fine audio analysis supplied; tempo, onsets and roles remain unmeasured.")

    if layout is not None:
        layout = deepcopy(layout)
        data = layout.provenance
        prov = evidence("layout", data.get("sample_times", []), ref=data.get("video"),
                        sha=data.get("video_sha256"), detector=data.get("backend"),
                        detector_version=data.get("opencv_version"), model=data.get("model_url"),
                        model_version=data.get("model_sha256"), details=data,
                        basis="supplied layout sample times in source video seconds")
        add("layout.face_tracks", [t.to_dict() for t in layout.tracks], "normalized frame; seconds", prov,
            len(data.get("sample_times", [])))
        recipe.approximations.layout = layout
        recipe.warnings.extend(layout.warnings)
    else:
        unknown("layout", "No face tracks, placement or safety result supplied.")

    transition_data = deepcopy(transitions.provenance if transitions is not None else metadata)
    observations = transitions.transitions if transitions is not None else b.transitions
    sidecars = transition_data.get("transition_evidence", [])
    seen = set()
    for index, raw in enumerate(sidecars):
        item = TransitionEvidence.from_dict(raw)
        validate_evidence(item)
        prov = evidence("transitions", [item.evidence_start_seconds, item.evidence_end_seconds],
                        detector=transition_data.get("transition_detector"), detector_version=item.detector_version,
                        details=transition_data, basis="source seconds; detector evidence window")
        if item.observation_index is not None:
            if not 0 <= item.observation_index < len(observations):
                raise ValueError("transition evidence observation_index is outside the legacy observations")
            legacy = observations[item.observation_index]
            if (item.observation_index in seen or
                    (item.signature, item.start_seconds, item.end_seconds) != (legacy.kind, legacy.start, legacy.end)):
                raise ValueError("transition evidence must agree with its unique legacy observation")
            prov.details["legacy_observation"] = encode(legacy)
            seen.add(item.observation_index)
        if item.signature == "unknown":
            unknown(f"transitions[{index}]", item.reason, prov=prov, value=item.to_dict())
        else:
            add(f"transitions[{index}]", item.to_dict(), "seconds; unitless heuristic score", prov,
                confidence=item.confidence, heuristic=True)
    for index, item in enumerate(observations):
        if index in seen:
            continue
        add(f"legacy_transitions[{index}]", encode(item), "seconds; frame pairs", evidence(
            "transitions", [item.start, item.end], detector=transition_data.get("transition_detector"),
            detector_version=transition_data.get("transition_detector_version")))
    if not sidecars and not observations:
        unknown("transitions", "No observations supplied; no transition type is inferred.")
    if transitions is not None:
        recipe.warnings.extend(transitions.warnings)

    for fact in recipe.measured:
        missing = [name for name in ("sha256", "detector", "detector_version")
                   if getattr(fact.provenance, name) is None]
        if fact.provenance.model is not None and fact.provenance.model_version is None:
            missing.append("model_version")
        if missing:
            unknown(fact.name + ".provenance", "Producer did not report: " + ", ".join(missing),
                    "unreported", fact.provenance)
    if reference.sha256 is None:
        unknown("reference.sha256", "No content hash supplied; pure construction cannot hash a file.", "unreported", reference)
    recipe.warnings = list(dict.fromkeys(recipe.warnings))
    # Validate and detach even reused mutable records; the caller owns its inputs.
    return StyleRecipe.from_dict(recipe.to_dict())
