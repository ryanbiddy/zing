"""Opt-in, experimental transition observations with explicit abstention."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from array import array
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from myzing.schemas import TransitionObservation
from . import transition_models as models


SIGNATURES = (
    "hard_cut",
    "dissolve",
    "wipe",
    "zoom_punch",
    "audio_aligned_cut",
)
DETECTOR_NAME = "zing-transition-signatures"
DETECTOR_VERSION = 5
SUPPORTED_SIGNATURES = SIGNATURES
VALIDATION_STATUS = {
    "status": "experimental",
    "synthetic_recall_available": True,
    "real_video_recall_available": False,
    "synthetic_precision_available": True,
    "validation_scope": "P14 generated textures; disjoint calibration/held-out parameters",
    "unsupported_signatures": ["whip_pan", "flash"],
    "confidence_kind": "heuristic evidence score; not a calibrated probability",
}
EXPERIMENTAL_RECALL_WARNING = (
    "transition types are experimental: real-video recall is unavailable "
    "because the audited corpora have no exhaustive frame-level transition "
    "labels"
)
FRAME_WIDTH = 96
FRAME_HEIGHT = 96
ACTIVE_DIFFERENCE = 0.8
HARD_CUT_DIFFERENCE = 15.0
GRADUAL_MIN_PAIRS = 4
# Frozen v4 sub-gate constants, used only by the historical eval audit.
DISSOLVE_TEMPORAL_MONOTONICITY = 0.75
DISSOLVE_MEAN_FRAME_DIFFERENCE = 1.0
AUDIO_SAMPLE_RATE = 8000
AUDIO_WINDOWS_PER_SECOND = 50
AUDIO_ONSET_LEVEL = 500.0
AUDIO_PREVIOUS_MAX = 150.0
AUDIO_ALIGNMENT_SECONDS = 0.08
CONFIDENT_EFFECT = 0.8
MODEL_MAX_ERROR = 0.16
EXPOSURE_MAX_RESIDUAL = 0.18
MAX_GRADUAL_SECONDS = 1.5
MAX_ZOOM_SECONDS = 0.6
QUIET_HANDLE_SECONDS = 0.12

DETECTOR_THRESHOLDS = {
    "analysis_frame": {
        "width": FRAME_WIDTH,
        "height": FRAME_HEIGHT,
    },
    "active_run": {
        "mean_absolute_difference": ACTIVE_DIFFERENCE,
    },
    "hard_cut": {
        "mean_absolute_difference": HARD_CUT_DIFFERENCE,
        "local_difference_ratio": 5.0,
        "return_to_scene_max_difference": 3.0,
    },
    "gradual": {
        "min_frame_pairs": GRADUAL_MIN_PAIRS,
    },
    "audio_alignment": {
        "sample_rate": AUDIO_SAMPLE_RATE,
        "windows_per_second": AUDIO_WINDOWS_PER_SECOND,
        "onset_level": AUDIO_ONSET_LEVEL,
        "previous_max": AUDIO_PREVIOUS_MAX,
        "max_delta_seconds": AUDIO_ALIGNMENT_SECONDS,
    },
    "evidence_gate": {
        "confidence_min": CONFIDENT_EFFECT,
        "model_max_normalized_error": MODEL_MAX_ERROR,
        "exposure_max_normalized_residual": EXPOSURE_MAX_RESIDUAL,
        "max_gradual_seconds": MAX_GRADUAL_SECONDS,
        "max_zoom_seconds": MAX_ZOOM_SECONDS,
        "quiet_handle_seconds": QUIET_HANDLE_SECONDS,
        "endpoint_min_mean_difference": 12.0,
        "zoom_min_scale": 1.15,
    },
}


class TransitionProbeError(RuntimeError):
    """A transition feature could not be measured honestly."""


@dataclass
class TransitionsResult:
    transitions: list[TransitionObservation]
    provenance: dict[str, Any]
    warnings: list[str]


@dataclass(frozen=True)
class TransitionEvidence:
    """Versioned sidecar until pass 4 can extend TransitionObservation.

    observation_index links a supported candidate to the legacy list. Unknowns
    have no legacy observation; confidence scores support the proposed label,
    not the probability that an edit happened.
    """

    signature: str
    start_seconds: float
    end_seconds: float
    evidence_start_seconds: float
    evidence_end_seconds: float
    confidence: float
    detector_version: int
    reason: str
    observation_index: int | None = None
    direction: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TransitionEvidence:
        if value.get("version") != 1:
            raise ValueError("unsupported transition evidence version")
        return cls(**value)


@dataclass(frozen=True)
class PairFeatures:
    time_seconds: float
    mean_absolute_difference: float
    histogram_distance: float
    changed_fraction: float



def _run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TransitionProbeError(f"could not run {command[0]}: {exc}") from exc


def _probe_video(media_path: Path, ffprobe: str) -> tuple[float, int, int]:
    if shutil.which(ffprobe) is None:
        raise TransitionProbeError(f"ffprobe executable not found: {ffprobe}")
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "json",
            str(media_path),
        ]
    )
    if result.returncode:
        raise TransitionProbeError(
            result.stderr.decode(errors="replace").strip()
            or "ffprobe could not read video stream"
        )
    try:
        stream = json.loads(result.stdout)["streams"][0]
        numerator, denominator = stream["r_frame_rate"].split("/", 1)
        fps = float(numerator) / float(denominator)
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TransitionProbeError("ffprobe returned malformed video metadata") from exc
    if fps <= 0 or width <= 0 or height <= 0:
        raise TransitionProbeError("ffprobe returned invalid video metadata")
    return fps, width, height


def _read_gray_frames(
    media_path: Path,
    ffmpeg: str,
    width: int = FRAME_WIDTH,
    height: int = FRAME_HEIGHT,
) -> list[bytes]:
    if shutil.which(ffmpeg) is None:
        raise TransitionProbeError(f"ffmpeg executable not found: {ffmpeg}")
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(media_path),
            "-an",
            "-vf",
            f"scale={width}:{height}:flags=bilinear,format=gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ]
    )
    if result.returncode:
        raise TransitionProbeError(
            result.stderr.decode(errors="replace").strip()
            or "ffmpeg could not decode video frames"
        )
    frame_size = width * height
    if len(result.stdout) % frame_size:
        raise TransitionProbeError("ffmpeg returned a partial grayscale frame")
    return [
        result.stdout[offset : offset + frame_size]
        for offset in range(0, len(result.stdout), frame_size)
    ]


def _histogram_distance(left: bytes, right: bytes) -> float:
    left_histogram = [0] * 16
    right_histogram = [0] * 16
    for value in left:
        left_histogram[value // 16] += 1
    for value in right:
        right_histogram[value // 16] += 1
    return sum(
        abs(left_count - right_count)
        for left_count, right_count in zip(left_histogram, right_histogram)
    ) / (2 * len(left))


def _pair_features(
    left: bytes,
    right: bytes,
    pair_index: int,
    fps: float,
    width: int,
    height: int,
) -> PairFeatures:
    differences = [abs(a - b) for a, b in zip(left, right)]
    mean_difference = sum(differences) / len(differences)
    changed = [value >= 8 for value in differences]
    return PairFeatures(
        time_seconds=round((pair_index + 1) / fps, 6),
        mean_absolute_difference=round(mean_difference, 6),
        histogram_distance=round(_histogram_distance(left, right), 6),
        changed_fraction=round(sum(changed) / len(changed), 6),
    )


def _active_runs(features: list[PairFeatures]) -> list[list[PairFeatures]]:
    runs: list[list[PairFeatures]] = []
    current: list[PairFeatures] = []
    for feature in features:
        if feature.mean_absolute_difference >= ACTIVE_DIFFERENCE:
            current.append(feature)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _audio_onsets(
    media_path: Path,
    ffmpeg: str,
    sample_rate: int = AUDIO_SAMPLE_RATE,
) -> tuple[list[float], bool]:
    """Onset times plus a probed-ok flag: a FAILED audio decode must stay
    distinguishable from measured-no-onsets, or audio_aligned_cut silently
    can never fire and the report reads as measured-empty (A-Q10 finding,
    same contract rule as Breakdown warnings)."""
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(media_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]
    )
    if result.returncode:
        return [], False
    samples = array("h")
    samples.frombytes(result.stdout)
    window = sample_rate // AUDIO_WINDOWS_PER_SECOND
    levels = []
    for start in range(0, len(samples) - window + 1, window):
        chunk = samples[start : start + window]
        levels.append(math.sqrt(sum(value * value for value in chunk) / len(chunk)))
    onsets = []
    for index, level in enumerate(levels):
        previous = levels[index - 1] if index else 0.0
        if level >= AUDIO_ONSET_LEVEL and previous < AUDIO_PREVIOUS_MAX:
            onsets.append(index * window / sample_rate)
    return onsets, True


def detect_transition_signatures(
    media_path: Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, Any]:
    fps, _, _ = _probe_video(media_path, ffprobe)
    width = FRAME_WIDTH
    height = FRAME_HEIGHT
    frames = _read_gray_frames(media_path, ffmpeg, width, height)
    if len(frames) < 2:
        raise TransitionProbeError("transition probe needs at least two frames")
    features = [
        _pair_features(left, right, index, fps, width, height)
        for index, (left, right) in enumerate(zip(frames, frames[1:]))
    ]
    runs = _active_runs(features)
    feature_indices = {id(feature): index for index, feature in enumerate(features)}
    predictions: set[str] = set()
    events = []
    hard_cut_times = []
    dissolve_candidate_count = 0
    suppressed_dissolve_candidates = 0
    handles = max(2, math.ceil(QUIET_HANDLE_SECONDS * fps))
    sampled = [models.sample(frame, width, height) for frame in frames]

    def emit(signature: str, first: int, last: int, reason: str,
             error: float = 1.0, direction: str | None = None) -> None:
        # first/last are frame indices, including the pre-change anchor.
        start = last / fps if signature == "hard_cut" else first / fps
        end = last / fps
        evidence = TransitionEvidence(
            signature=signature, start_seconds=round(start, 6), end_seconds=round(end, 6),
            evidence_start_seconds=round(max(0, first - handles) / fps, 6),
            evidence_end_seconds=round(min(len(frames) - 1, last + handles) / fps, 6),
            confidence=round(max(CONFIDENT_EFFECT, min(0.98, 1 - error)), 4)
            if signature != "unknown" else 0.0,
            detector_version=DETECTOR_VERSION, reason=reason, direction=direction,
        )
        events.append({**evidence.to_dict(), "frame_pair_count": last - first})
        if signature != "unknown":
            predictions.add(signature)
        if signature == "hard_cut":
            hard_cut_times.append(round(start, 6))

    for run in runs:
        first = feature_indices[id(run[0])]
        last = feature_indices[id(run[-1])] + 1
        abrupt = []
        for index in range(first, last):
            feature = features[index]
            neighbors = features[max(0, index - handles):index] + features[index + 1:index + 1 + handles]
            background = max((item.mean_absolute_difference for item in neighbors), default=0)
            if (feature.mean_absolute_difference >= HARD_CUT_DIFFERENCE
                    and feature.mean_absolute_difference >= 5 * max(1, background)
                    and models.exposure_residual(sampled[index], sampled[index + 1]) > EXPOSURE_MAX_RESIDUAL):
                # Reject isolated flashes returning to the same scene in the handles.
                returns = any(models.distance(sampled[index], sampled[after]) < 3
                              for after in range(index + 2, min(len(frames), index + handles + 2)))
                if not returns:
                    abrupt.append(index)
        if abrupt:
            for index in abrupt:
                emit("hard_cut", index, index + 1, "isolated structural discontinuity", 0.1)
            continue

        dissolve_candidate_count += 1
        a, b = sampled[first], sampled[last]
        duration = (last - first) / fps
        quiet = (first >= handles and last + handles < len(frames)
                 and all(item.mean_absolute_difference < ACTIVE_DIFFERENCE
                         for item in features[first - handles:first] + features[last:last + handles]))
        reason = "motion or unsupported effect; insufficient reconstruction evidence"
        signature = "unknown"
        direction = None
        error = 1.0
        if (quiet and GRADUAL_MIN_PAIRS <= len(run) and duration <= MAX_GRADUAL_SECONDS
                and models.distance(a, b) >= 12
                and models.exposure_residual(a, b) > EXPOSURE_MAX_RESIDUAL):
            interior = sampled[first + 1:last]
            wipe_error, wipe_direction = models.wipe_error(a, b, interior, width // 2, height // 2)
            candidates = [
                (wipe_error, "wipe", "monotone spatial boundary between endpoint scenes", wipe_direction),
                (models.dissolve_error(a, b, interior), "dissolve",
                 "interior frames reconstruct from both endpoint scenes", None),
            ]
            if duration <= MAX_ZOOM_SECONDS:
                zoom_error, zoom = models.zoom_error(list(frames[first]), list(frames[last]), width, height)
                if zoom >= 1.15:
                    candidates.append((zoom_error, "zoom_punch", "short centered magnification with quiet handles", None))
            fitted_error, fitted_signature, fitted_reason, fitted_direction = min(candidates, key=lambda item: item[0])
            # A wipe is also an endpoint pixel selection. Its moving boundary
            # is the more specific evidence and takes precedence over dissolve.
            if wipe_error <= MODEL_MAX_ERROR:
                fitted_error, fitted_signature, fitted_reason, fitted_direction = candidates[0]
            if fitted_error <= MODEL_MAX_ERROR:
                error, signature, reason, direction = fitted_error, fitted_signature, fitted_reason, fitted_direction
        elif not quiet or duration > MAX_GRADUAL_SECONDS:
            reason = "continuous motion or missing quiet handles; edit type unknown"
        elif models.exposure_residual(a, b) <= EXPOSURE_MAX_RESIDUAL:
            reason = "luminance change preserves scene structure; edit type unknown"
        if signature != "dissolve":
            suppressed_dissolve_candidates += 1
        emit(signature, first, last, reason, error, direction)

    audio_onsets, audio_probe_ok = _audio_onsets(media_path, ffmpeg)
    aligned = [
        {
            "cut_seconds": cut,
            "onset_seconds": onset,
            "delta_seconds": round(onset - cut, 6),
        }
        for cut in hard_cut_times
        for onset in audio_onsets
        if abs(onset - cut) <= AUDIO_ALIGNMENT_SECONDS
    ]
    if aligned:
        predictions.add("audio_aligned_cut")
    return {
        "predicted": sorted(predictions),
        "events": events,
        "audio_onsets_seconds": [round(value, 6) for value in audio_onsets],
        "audio_probe_ok": audio_probe_ok,
        "audio_aligned_pairs": aligned,
        "feature_summary": {
            "frame_count": len(frames),
            "active_run_count": len(runs),
            "dissolve_candidate_count": dissolve_candidate_count,
            "suppressed_dissolve_candidates": suppressed_dissolve_candidates,
            "max_frame_difference": max(
                feature.mean_absolute_difference for feature in features
            ),
            "flow_measured": False,
            "unknown_count": sum(event["signature"] == "unknown" for event in events),
        },
        "pair_features": [asdict(feature) for feature in features],
    }


def detector_provenance(
    feature_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = {
        "transition_detector": DETECTOR_NAME,
        "transition_detector_version": DETECTOR_VERSION,
        "transition_thresholds": deepcopy(DETECTOR_THRESHOLDS),
        "transition_validation": deepcopy(VALIDATION_STATUS),
    }
    if feature_summary is not None:
        provenance["transition_feature_summary"] = feature_summary
    return provenance


def detect_transitions(
    media_path: Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> TransitionsResult:
    """Return legacy observations and complete, versioned evidence sidecars."""
    measurement = detect_transition_signatures(
        media_path,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    aligned_by_cut = {}
    for pair in measurement["audio_aligned_pairs"]:
        cut = pair["cut_seconds"]
        delta = pair["delta_seconds"]
        prior = aligned_by_cut.get(cut)
        if prior is None or abs(delta) < abs(prior):
            aligned_by_cut[cut] = delta
    observations = []
    evidence_records = []
    for event in measurement["events"]:
        kind = event["signature"]
        # Never promote an abstention to the legacy effect vocabulary.
        evidence = TransitionEvidence(
            signature=kind,
            start_seconds=event["start_seconds"], end_seconds=event["end_seconds"],
            evidence_start_seconds=event["evidence_start_seconds"],
            evidence_end_seconds=event["evidence_end_seconds"],
            confidence=event["confidence"], detector_version=event["detector_version"],
            reason=event["reason"], direction=event.get("direction"),
            observation_index=len(observations) if kind != "unknown" else None,
        )
        evidence_records.append(evidence.to_dict())
        if kind == "unknown":
            continue
        start = event["start_seconds"]
        audio_delta = aligned_by_cut.get(start) if kind == "hard_cut" else None
        observations.append(
            TransitionObservation(
                kind=kind,
                start=start,
                end=event["end_seconds"],
                frame_pair_count=event["frame_pair_count"],
                audio_aligned=audio_delta is not None,
                audio_onset_delta=audio_delta,
            )
        )
    warnings = [EXPERIMENTAL_RECALL_WARNING]
    if not measurement["audio_probe_ok"]:
        warnings.append(
            "transition audio alignment skipped: ffmpeg could not decode "
            "the audio stream"
        )
    provenance = detector_provenance(measurement["feature_summary"])
    provenance["transition_evidence"] = evidence_records
    provenance["transition_audio_probe_ok"] = measurement["audio_probe_ok"]
    return TransitionsResult(
        transitions=observations,
        warnings=warnings,
        provenance=provenance,
    )
