"""Prototype five hand-checkable transition signatures on synthetic goldens."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


SIGNATURES = (
    "hard_cut",
    "dissolve",
    "wipe",
    "zoom_punch",
    "audio_aligned_cut",
)


class TransitionProbeError(RuntimeError):
    """A transition feature could not be measured honestly."""


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
    width: int = 96,
    height: int = 96,
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
        if feature.mean_absolute_difference >= 0.8:
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
    sample_rate: int = 8000,
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
    window = sample_rate // 50
    levels = []
    for start in range(0, len(samples) - window + 1, window):
        chunk = samples[start : start + window]
        levels.append(math.sqrt(sum(value * value for value in chunk) / len(chunk)))
    onsets = []
    for index, level in enumerate(levels):
        previous = levels[index - 1] if index else 0.0
        if level >= 500 and previous < 150:
            onsets.append(index * window / sample_rate)
    return onsets


def detect_transition_signatures(
    media_path: Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, Any]:
    fps, _, _ = _probe_video(media_path, ffprobe)
    width = height = 96
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
        if len(run) <= 2 and max_difference >= 15 and max_histogram >= 0.1:
            signature = "hard_cut"
            strongest_pair = max(
                run,
                key=lambda feature: feature.mean_absolute_difference,
            )
            hard_cut_times.append(strongest_pair.time_seconds)
        elif len(run) >= 4:
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
            if radial >= 0.48 and flow >= 0.7:
                signature = "zoom_punch"
            elif centroid_span >= width * 0.3 and column_fraction <= 0.55:
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
        if abs(onset - cut) <= 0.08
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


def summarize_signature_precision(
    cases: Sequence[dict[str, Any]],
) -> dict[str, dict[str, int | float]]:
    summary = {}
    for signature in SIGNATURES:
        true_positives = sum(
            signature in case["truth"] and signature in case["predicted"]
            for case in cases
        )
        false_positives = sum(
            signature not in case["truth"] and signature in case["predicted"]
            for case in cases
        )
        predicted_count = true_positives + false_positives
        precision = true_positives / predicted_count if predicted_count else 0.0
        summary[signature] = {
            "true_positives": true_positives,
            "false_positives": false_positives,
            "predicted_count": predicted_count,
            "precision": round(precision, 6),
        }
    return summary


def evaluate_transition_goldens(
    directories: Sequence[Path],
    report_path: Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, Any]:
    if not directories:
        raise ValueError("no transition goldens found")
    cases = []
    for directory in directories:
        truth = json.loads(
            (directory / "transition-truth.json").read_text(encoding="utf-8")
        )
        measurement = detect_transition_signatures(
            directory / truth["media"],
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        cases.append(
            {
                "fixture_id": truth["fixture_id"],
                "truth": truth["transition"]["signatures"],
                "predicted": measurement["predicted"],
                "events": measurement["events"],
                "audio_onsets_seconds": measurement["audio_onsets_seconds"],
                "audio_aligned_pairs": measurement["audio_aligned_pairs"],
                "feature_summary": measurement["feature_summary"],
            }
        )
    signatures = summarize_signature_precision(cases)
    report = {
        "prototype_schema_version": 1,
        "signatures": signatures,
        "macro_precision": round(
            sum(value["precision"] for value in signatures.values())
            / len(signatures),
            6,
        ),
        "cases": cases,
        "limitations": {
            "prototype_only": True,
            "not_detected": [
                "j_cut",
                "l_cut",
                "jump_cut",
                "match_cut",
                "whip_pan",
                "speed_ramp",
                "glitch",
                "invisible_cut",
            ],
            "notes": [
                "Thresholds are calibrated only on exact synthetic 96px goldens.",
                "Precision on these goldens is not evidence of real-video recall.",
                "Audio alignment detects energy onset, not speaker or scene identity.",
                "Zoom flow uses small pure-Python block matching, not learned flow.",
            ],
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("goldens", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args(argv)
    directories = sorted(
        path
        for path in args.goldens.iterdir()
        if (path / "transition-truth.json").is_file()
    )
    try:
        report = evaluate_transition_goldens(
            directories,
            args.report,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
        )
    except (OSError, ValueError, TransitionProbeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    for signature, result in report["signatures"].items():
        print(f"{signature}: precision={result['precision']:.3f}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
