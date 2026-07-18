"""Opt-in transition measurements promoted from the C-Q9 prototype."""

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


SIGNATURES = (
    "hard_cut",
    "dissolve",
    "wipe",
    "zoom_punch",
    "audio_aligned_cut",
)
DETECTOR_NAME = "zing-transition-signatures"
DETECTOR_VERSION = 2
FRAME_WIDTH = 96
FRAME_HEIGHT = 96
ACTIVE_DIFFERENCE = 0.8
HARD_CUT_MAX_PAIRS = 2
HARD_CUT_DIFFERENCE = 15.0
HARD_CUT_HISTOGRAM_DISTANCE = 0.1
GRADUAL_MIN_PAIRS = 4
ZOOM_RADIAL_COHERENCE = 0.48
ZOOM_FLOW_MAGNITUDE = 0.7
WIPE_CENTROID_WIDTH_FRACTION = 0.3
WIPE_MAX_CHANGED_COLUMN_FRACTION = 0.55
AUDIO_SAMPLE_RATE = 8000
AUDIO_WINDOWS_PER_SECOND = 50
AUDIO_ONSET_LEVEL = 500.0
AUDIO_PREVIOUS_MAX = 150.0
AUDIO_ALIGNMENT_SECONDS = 0.08

DETECTOR_THRESHOLDS = {
    "analysis_frame": {
        "width": FRAME_WIDTH,
        "height": FRAME_HEIGHT,
    },
    "active_run": {
        "mean_absolute_difference": ACTIVE_DIFFERENCE,
    },
    "hard_cut": {
        "max_frame_pairs": HARD_CUT_MAX_PAIRS,
        "mean_absolute_difference": HARD_CUT_DIFFERENCE,
        "histogram_distance": HARD_CUT_HISTOGRAM_DISTANCE,
    },
    "gradual": {
        "min_frame_pairs": GRADUAL_MIN_PAIRS,
    },
    "zoom_punch": {
        "radial_flow_coherence": ZOOM_RADIAL_COHERENCE,
        "mean_flow_magnitude": ZOOM_FLOW_MAGNITUDE,
    },
    "wipe": {
        "centroid_span_width_fraction": WIPE_CENTROID_WIDTH_FRACTION,
        "max_changed_column_fraction": WIPE_MAX_CHANGED_COLUMN_FRACTION,
    },
    "audio_alignment": {
        "sample_rate": AUDIO_SAMPLE_RATE,
        "windows_per_second": AUDIO_WINDOWS_PER_SECOND,
        "onset_level": AUDIO_ONSET_LEVEL,
        "previous_max": AUDIO_PREVIOUS_MAX,
        "max_delta_seconds": AUDIO_ALIGNMENT_SECONDS,
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
class PairFeatures:
    time_seconds: float
    mean_absolute_difference: float
    histogram_distance: float
    changed_fraction: float
    changed_column_fraction: float
    changed_column_centroid: float | None
    radial_flow_coherence: float
    mean_flow_magnitude: float


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


def _block_flow(
    left: bytes,
    right: bytes,
    width: int,
    height: int,
) -> tuple[float, float]:
    block = 12
    radius = 3
    vectors: list[tuple[float, float, float, float]] = []
    for y in range(block, height - block, block):
        for x in range(block, width - block, block):
            samples = [
                left[row * width + column]
                for row in range(y - block // 2, y + block // 2, 2)
                for column in range(x - block // 2, x + block // 2, 2)
            ]
            if max(samples) - min(samples) < 20:
                continue
            best: tuple[int, int, int] | None = None
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    error = 0
                    for row in range(y - block // 2, y + block // 2, 2):
                        left_offset = row * width
                        right_offset = (row + dy) * width
                        for column in range(x - block // 2, x + block // 2, 2):
                            error += abs(
                                left[left_offset + column]
                                - right[right_offset + column + dx]
                            )
                    candidate = (error, dx, dy)
                    if best is None or candidate < best:
                        best = candidate
            if best is not None:
                _, dx, dy = best
                magnitude = math.hypot(dx, dy)
                vectors.append((x - width / 2, y - height / 2, dx, dy))

    moving = [
        vector
        for vector in vectors
        if math.hypot(vector[2], vector[3]) >= 0.5
    ]
    if not moving:
        return 0.0, 0.0
    radial_scores = []
    magnitudes = []
    for radial_x, radial_y, dx, dy in moving:
        radial_length = math.hypot(radial_x, radial_y)
        magnitude = math.hypot(dx, dy)
        if radial_length:
            radial_scores.append(
                (radial_x * dx + radial_y * dy) / (radial_length * magnitude)
            )
        magnitudes.append(magnitude)
    positive_coherence = sum(max(0.0, score) for score in radial_scores) / max(
        1, len(radial_scores)
    )
    return positive_coherence, sum(magnitudes) / len(magnitudes)


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
    column_weights = [
        sum(differences[row * width + column] for row in range(height))
        for column in range(width)
    ]
    active_columns = [
        index for index, value in enumerate(column_weights) if value / height >= 3
    ]
    total_column_weight = sum(column_weights)
    centroid = (
        sum(index * value for index, value in enumerate(column_weights))
        / total_column_weight
        if total_column_weight
        else None
    )
    radial_coherence, flow_magnitude = _block_flow(
        left,
        right,
        width,
        height,
    )
    return PairFeatures(
        time_seconds=round((pair_index + 1) / fps, 6),
        mean_absolute_difference=round(mean_difference, 6),
        histogram_distance=round(_histogram_distance(left, right), 6),
        changed_fraction=round(sum(changed) / len(changed), 6),
        changed_column_fraction=round(len(active_columns) / width, 6),
        changed_column_centroid=(
            round(centroid, 6) if centroid is not None else None
        ),
        radial_flow_coherence=round(radial_coherence, 6),
        mean_flow_magnitude=round(flow_magnitude, 6),
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
) -> list[float]:
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
        return []
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
    return onsets


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
    predictions: set[str] = set()
    events = []
    hard_cut_times = []
    for run in runs:
        max_difference = max(
            feature.mean_absolute_difference for feature in run
        )
        max_histogram = max(feature.histogram_distance for feature in run)
        start = run[0].time_seconds
        end = run[-1].time_seconds
        signature: str | None = None
        if (
            len(run) <= HARD_CUT_MAX_PAIRS
            and max_difference >= HARD_CUT_DIFFERENCE
            and max_histogram >= HARD_CUT_HISTOGRAM_DISTANCE
        ):
            signature = "hard_cut"
            strongest_pair = max(
                run,
                key=lambda feature: feature.mean_absolute_difference,
            )
            hard_cut_times.append(strongest_pair.time_seconds)
            start = strongest_pair.time_seconds
            end = strongest_pair.time_seconds
        elif len(run) >= GRADUAL_MIN_PAIRS:
            radial = sum(feature.radial_flow_coherence for feature in run) / len(run)
            flow = sum(feature.mean_flow_magnitude for feature in run) / len(run)
            centroids = [
                feature.changed_column_centroid
                for feature in run
                if feature.changed_column_centroid is not None
            ]
            centroid_span = max(centroids) - min(centroids) if centroids else 0.0
            column_fraction = sum(
                feature.changed_column_fraction for feature in run
            ) / len(run)
            if (
                radial >= ZOOM_RADIAL_COHERENCE
                and flow >= ZOOM_FLOW_MAGNITUDE
            ):
                signature = "zoom_punch"
            elif (
                centroid_span >= width * WIPE_CENTROID_WIDTH_FRACTION
                and column_fraction <= WIPE_MAX_CHANGED_COLUMN_FRACTION
            ):
                signature = "wipe"
            else:
                signature = "dissolve"
        if signature is not None:
            predictions.add(signature)
            events.append(
                {
                    "signature": signature,
                    "start_seconds": start,
                    "end_seconds": end,
                    "frame_pair_count": len(run),
                }
            )

    audio_onsets = _audio_onsets(media_path, ffmpeg)
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
        "audio_aligned_pairs": aligned,
        "feature_summary": {
            "frame_count": len(frames),
            "active_run_count": len(runs),
            "max_frame_difference": max(
                feature.mean_absolute_difference for feature in features
            ),
            "max_radial_flow_coherence": max(
                feature.radial_flow_coherence for feature in features
            ),
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
    """Return typed observations without claiming calibrated confidence."""
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
    for event in measurement["events"]:
        kind = event["signature"]
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
    return TransitionsResult(
        transitions=observations,
        warnings=[],
        provenance=detector_provenance(measurement["feature_summary"]),
    )
