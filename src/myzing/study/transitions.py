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
from statistics import median
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
DETECTOR_VERSION = 6
SUPPORTED_SIGNATURES = SIGNATURES
VALIDATION_STATUS = {
    "status": "experimental",
    "synthetic_recall_available": True,
    "real_video_recall_available": True,
    "real_video_precision_available": True,
    "synthetic_precision_available": True,
    "validation_scope": "P14 generated textures and T6 pinned real clips; clip-level tuning holdout, provisional labels in reviewed windows only",
    "real_video_held_out": {
        "report": "tools/eval/real/transitions-v6-results.json",
        "split": "tools/eval/real/transition-split.json",
        "clip_count": 5,
        "reviewed_seconds": 22.0,
        "event_count": 8,
        "hard_cut": {"tp": 7, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "unknown": 0},
        "dissolve": {"tp": 0, "fp": 0, "fn": 1, "precision": None, "recall": 0.0, "unknown": 1},
        "other_classes": "no labeled positives; real recall unavailable",
        "limitations": "one annotator; prior v5 failures disclosed; shared source works; not a blind or representative benchmark",
    },
    "unsupported_signatures": ["whip_pan", "flash"],
    "confidence_kind": "heuristic evidence score; not a calibrated probability",
}
EXPERIMENTAL_RECALL_WARNING = (
    "transition types are experimental: real-video recall measured on 8 held-out "
    "events in 5 clips (22 reviewed seconds): hard cuts 7/7, precision 7/7; "
    "dissolves 0/1, precision undefined (no accepted predictions). Other classes "
    "lack labeled positives. Provisional labels and shared source works limit generalization."
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
ADAPTIVE_MOTION_SECONDS = 0.20
OPTICAL_MAX_ERROR = 0.28
OPTICAL_MIN_DIFFERENCE = 10.0

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
        "adaptive_motion_seconds": ADAPTIVE_MOTION_SECONDS,
        "adaptive_min_difference": 8.0,
        "adaptive_difference_ratio": 3.0,
        "adaptive_histogram_distance": 0.08,
        "adaptive_histogram_ratio": 4.0,
        "adaptive_structure_change": 0.15,
        "adjacent_blend_suppression_frames": 2,
        "fast_translation_span_seconds": 0.10,
        "fast_translation_min_difference": 6.0,
        "fast_translation_max_residual": 0.20,
        "black_endpoint_max_luma": 20.0,
    },
    "gradual": {
        "min_frame_pairs": GRADUAL_MIN_PAIRS,
        "optical_max_normalized_error": OPTICAL_MAX_ERROR,
        "optical_min_endpoint_difference": OPTICAL_MIN_DIFFERENCE,
        "optical_window_seconds": [0.4, 0.6, 0.8, 1.0, 1.2, 1.5],
        "optical_min_structure_change": 0.18,
        "optical_min_edge_change": 0.10,
        "optical_min_each_change_polarity_fraction": 0.12,
        "optical_max_handle_drift_ratio": 0.30,
        "optical_min_translation_residual": 0.55,
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
    structure_change: float = 0.0
    edge_change: float = 0.0



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
    pooled_left: list[float] | None = None,
    pooled_right: list[float] | None = None,
) -> PairFeatures:
    differences = [abs(a - b) for a, b in zip(left, right)]
    mean_difference = sum(differences) / len(differences)
    changed = [value >= 8 for value in differences]
    a = pooled_left if pooled_left is not None else models.pool(left, width, height)
    b = pooled_right if pooled_right is not None else models.pool(right, width, height)
    return PairFeatures(
        time_seconds=round((pair_index + 1) / fps, 6),
        mean_absolute_difference=round(mean_difference, 6),
        histogram_distance=round(_histogram_distance(left, right), 6),
        changed_fraction=round(sum(changed) / len(changed), 6),
        structure_change=round(models.structure_change(a, b, width // 4), 6),
        edge_change=round(models.edge_change(a, b, width // 4), 6),
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


def _hard_cuts(features: list[PairFeatures], frames: list[list[float]], fps: float) -> list[int]:
    """Isolated scene changes, allowing a short blended boundary in noisy footage."""
    handles = max(2, math.ceil(QUIET_HANDLE_SECONDS * fps))
    radius = max(3, round(ADAPTIVE_MOTION_SECONDS * fps))
    candidates = []
    for i, feature in enumerate(features):
        if feature.mean_absolute_difference < 8:
            continue
        neighbors = features[max(0, i - radius):max(0, i - 1)] + features[i + 2:i + radius + 1]
        motion = max(1, median(f.mean_absolute_difference for f in neighbors)) if neighbors else 1
        histogram = max(0.01, median(f.histogram_distance for f in neighbors)) if neighbors else 0.01
        nearby = features[max(0, i - handles):i] + features[i + 1:i + handles + 1]
        background = max((f.mean_absolute_difference for f in nearby), default=0)
        legacy = (feature.mean_absolute_difference >= HARD_CUT_DIFFERENCE
                  and feature.mean_absolute_difference >= 5 * max(1, background))
        adaptive = (feature.mean_absolute_difference >= 3 * motion
                    and feature.histogram_distance >= max(0.08, 4 * histogram)
                    and feature.structure_change >= 0.15)
        if not (legacy or adaptive):
            continue
        a, b = frames[i:i + 2]
        # A textured scene disappearing into persistent black cannot retain
        # structure under an affine exposure fit; explicitly test that endpoint.
        black = (max(b) <= 20 and max(b) - min(b) < 2 and sum(a) / len(a) > sum(b) / len(b) + 12
                 and feature.structure_change > 0.25 and feature.edge_change > 0.8
                 and i + handles + 1 < len(frames)
                 and all(max(f) <= 20 and max(f) - min(f) < 2 for f in frames[i + 1:i + handles + 2]))
        if not black and models.exposure_residual(a, b) <= EXPOSURE_MAX_RESIDUAL:
            continue
        span = max(2, round(0.10 * fps))
        if i >= span and i + span + 1 < len(frames):
            sides = [(frames[i - span], a), (b, frames[i + span + 1])]
            if all(models.distance(x, y) > 6 and models.translation_error(x, y, FRAME_WIDTH // 4) < 0.20
                   for x, y in sides):
                # A rapid translated scene on BOTH sides is compatible with
                # an unsupported whip. A discontinuity alone cannot type it.
                continue
        returns = any(models.distance(a, frames[after]) < 3
                      for after in range(i + 2, min(len(frames), i + handles + 2)))
        returns = returns or any(models.distance(b, frames[before]) < 3
                                 for before in range(max(0, i - handles), i))
        if not returns:
            candidates.append(i)
    # An archival blend may produce two peaks. Keep one boundary, never two
    # events for the same change. Two-frame label tolerance still applies.
    selected = []
    for i in sorted(candidates, key=lambda j: features[j].mean_absolute_difference, reverse=True):
        if all(abs(i - j) > 2 for j in selected):
            selected.append(i)
    return sorted(selected)


def _optical_dissolves(frames: list[list[float]], features: list[PairFeatures],
                       fps: float, occupied: list[tuple[int, int]]) -> list[tuple[int, int, float, int, int]]:
    """Scan independent windows: grain and ongoing motion need not become quiet.

    A candidate must reconstruct throughout as a monotone optical blend, change
    structure across both brightening and darkening regions, and fit worse as a
    translated scene. Handles may move relative to the endpoint separation.
    """
    handles = max(2, math.ceil(QUIET_HANDLE_SECONDS * fps))
    step = max(1, round(fps / 15))
    candidates = []
    for length in sorted({round(t * fps) for t in (0.4, 0.6, 0.8, 1.0, 1.2, 1.5)}):
        for first in range(handles, len(frames) - length - handles, step):
            last = first + length
            if any(first < end and last > start for start, end in occupied):
                continue
            a, b = frames[first], frames[last]
            separation = models.distance(a, b)
            if separation < OPTICAL_MIN_DIFFERENCE:
                continue
            activity = [f.mean_absolute_difference for f in features[first:last]]
            if max(activity) > 0.28 * sum(activity):
                continue
            drift = max(models.distance(frames[first - handles], a),
                        models.distance(b, frames[last + handles])) / separation
            if drift > 0.30:
                continue
            delta = [y - x for x, y in zip(a, b)]
            if min(sum(d > 5 for d in delta), sum(d < -5 for d in delta)) < 0.12 * len(delta):
                continue
            # Cheap sparse fit before spatial and dense temporal checks.
            interior = [frames[first + round(length * j / 8)] for j in range(1, 8)]
            error, alpha = models.blend_fit(a, b, interior)
            if (error > OPTICAL_MAX_ERROR or any(y < x - 0.04 for x, y in zip(alpha, alpha[1:]))
                    or max(y - x for x, y in zip([0.0] + alpha, alpha + [1.0])) > 0.35):
                continue
            if (models.structure_change(a, b, FRAME_WIDTH // 4) < 0.18
                    or models.edge_change(a, b, FRAME_WIDTH // 4) < 0.10
                    or models.exposure_residual(a, b) < 0.5
                    or models.translation_error(a, b, FRAME_WIDTH // 4) < 0.55):
                continue
            error, alpha = models.blend_fit(a, b, frames[first + 1:last])
            if error > OPTICAL_MAX_ERROR or any(y < x - 0.04 for x, y in zip(alpha, alpha[1:])):
                continue
            # Exclude endpoint plateaus; retain a frame of uncertainty at each
            # end, rather than pretending optical boundaries are exact.
            progress = [0.0] + alpha + [1.0]
            start = first + max(0, next(i for i, v in enumerate(progress) if v >= 0.08) - 1)
            end = first + min(length, next(i for i, v in enumerate(progress) if v >= 0.92) + 1)
            candidates.append((error + 0.15 * drift, start, end, error, first, last))
    selected = []
    for _, first, last, error, anchor_a, anchor_b in sorted(candidates):
        if all(last < a - handles or first > b + handles for a, b, *_ in selected):
            selected.append((first, last, error, anchor_a, anchor_b))
    return sorted(selected)


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
    pooled = [models.pool(frame, width, height) for frame in frames]
    features = [
        _pair_features(left, right, index, fps, width, height, pooled[index], pooled[index + 1])
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
             error: float = 1.0, direction: str | None = None,
             anchor_first: int | None = None, anchor_last: int | None = None) -> None:
        # first/last are frame indices, including the pre-change anchor.
        start = last / fps if signature == "hard_cut" else first / fps
        end = last / fps
        radius = max(handles, round(ADAPTIVE_MOTION_SECONDS * fps)) if signature == "hard_cut" else handles
        evidence_first = first if anchor_first is None else anchor_first
        evidence_last = last if anchor_last is None else anchor_last
        evidence = TransitionEvidence(
            signature=signature, start_seconds=round(start, 6), end_seconds=round(end, 6),
            evidence_start_seconds=round(max(0, evidence_first - radius) / fps, 6),
            evidence_end_seconds=round(min(len(frames) - 1, evidence_last + radius) / fps, 6),
            confidence=round(max(CONFIDENT_EFFECT, min(0.98, 1 - error)), 4)
            if signature != "unknown" else 0.0,
            detector_version=DETECTOR_VERSION, reason=reason, direction=direction,
        )
        events.append({**evidence.to_dict(), "frame_pair_count": last - first})
        if signature != "unknown":
            predictions.add(signature)
        if signature == "hard_cut":
            hard_cut_times.append(round(start, 6))

    cut_indices = _hard_cuts(features, pooled, fps)
    for index in cut_indices:
        f = features[index]
        emit("hard_cut", index, index + 1,
             f"structural discontinuity relative to local motion; MAD={f.mean_absolute_difference:.2f}, "
             f"histogram={f.histogram_distance:.3f}, block_structure={f.structure_change:.3f}, edge_change={f.edge_change:.3f}", 0.1)

    for run in runs:
        first = feature_indices[id(run[0])]
        last = feature_indices[id(run[-1])] + 1
        if any(first <= index < last for index in cut_indices):
            emit("unknown", first, last, "motion surrounding isolated cuts; remaining edit type unknown")
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

    occupied = [(round(e["start_seconds"] * fps) - (e["signature"] == "hard_cut"),
                 round(e["end_seconds"] * fps)) for e in events if e["signature"] != "unknown"]
    optical = _optical_dissolves(pooled, features, fps, occupied)
    for first, last, error, anchor_first, anchor_last in optical:
        emit("dissolve", first, last,
             f"windowed optical blend with moving handles; normalized residual={error:.3f}; "
             "distributed structural replacement; endpoints approximate", error,
             anchor_first=anchor_first, anchor_last=anchor_last)

    # Split abstentions around accepted intervals so continuous footage keeps
    # unknown evidence without covering accepted events with contradictory runs.
    known = [e for e in events if e["signature"] != "unknown"]
    unknown = [e for e in events if e["signature"] == "unknown"]
    occupied = [(round(e["start_seconds"] * fps) - (e["signature"] == "hard_cut"),
                 round(e["end_seconds"] * fps)) for e in known]
    events = known
    for event in unknown:
        pieces = [(round(event["start_seconds"] * fps), round(event["end_seconds"] * fps))]
        for a, b in occupied:
            pieces = [(x, y) for start, end in pieces for x, y in
                      ([(start, end)] if b <= start or a >= end else [(start, min(a, end)), (max(b, start), end)])
                      if y > x]
        for first, last in pieces:
            emit("unknown", first, last, event["reason"])
    events.sort(key=lambda e: (e["start_seconds"], e["end_seconds"], e["signature"]))

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
            "optical_dissolve_count": len(optical),
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
