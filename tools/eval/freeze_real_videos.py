"""Freeze measured example-video Breakdowns and reproducibility provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Sequence

from myzing.schemas import Breakdown

from .performance import StudyBenchmarkAdapter


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "real_videos"
DEFAULT_MANIFEST = DEFAULT_OUTPUT / "manifest.json"


class RegressionFreezeError(RuntimeError):
    """A real-video fixture could not be frozen without losing provenance."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _artifact_sha256(path: Path) -> str:
    if path.suffix.lower() in {".json", ".md", ".txt"}:
        return _text_sha256(path)
    return _sha256(path)


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _tool_version(command: str) -> str | None:
    resolved = shutil.which(command)
    if resolved is None:
        return None
    result = subprocess.run(
        [resolved, "-version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return None
    return result.stdout.splitlines()[0]


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise RegressionFreezeError(
            f"unsupported real-video manifest schema: {manifest.get('schema_version')}"
        )
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RegressionFreezeError("real-video manifest has no cases")
    return manifest


def _portable_breakdown(
    measured: Breakdown,
    case: dict[str, Any],
) -> Breakdown:
    frozen = Breakdown.from_dict(measured.to_dict())
    frozen.meta.source_url = case["source_url"]
    frozen.meta.platform = "youtube"
    frozen.meta.author = case["creator"]
    frozen.meta.title = case["title"]
    frozen.meta.media_path = ""
    for shot in frozen.shots:
        shot.keyframe = ""
    frozen.provenance["regression_fixture"] = {
        "fixture_id": case["fixture_id"],
        "video_id": case["video_id"],
        "role": case["role"],
        "human_truth": "handoff/research/EXAMPLE-DATASET-TRUTH.md",
        "truth_section": case["truth_section"],
    }
    return frozen


def _freeze_with_adapter(
    media_root: Path,
    output: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    adapter: Any,
    *,
    ffmpeg: str,
) -> list[Path]:
    truth_path = HERE.parents[1] / manifest["human_truth"]
    if not truth_path.is_file():
        raise RegressionFreezeError(f"human truth file not found: {truth_path}")
    output.mkdir(parents=True, exist_ok=True)
    frozen_directories = []
    for case in manifest["cases"]:
        media_path = media_root / case["media_filename"]
        if not media_path.is_file():
            raise RegressionFreezeError(
                f"media not found for {case['fixture_id']}: {media_path}"
            )
        case_directory = output / case["fixture_id"]
        if case_directory.exists():
            raise RegressionFreezeError(
                f"refusing to replace frozen fixture: {case_directory}"
            )

        measured = adapter(media_path)
        artifact_directory = adapter.artifact_directory_for(media_path)
        if artifact_directory is None or not artifact_directory.is_dir():
            raise RegressionFreezeError(
                f"study artifacts were not preserved for {case['fixture_id']}"
            )
        measured_media = artifact_directory / measured.meta.media_path
        if not measured_media.is_file():
            raise RegressionFreezeError(
                f"measured media is missing for {case['fixture_id']}"
            )

        case_directory.mkdir(parents=True)
        frozen = _portable_breakdown(measured, case)
        breakdown_path = case_directory / "breakdown.json"
        breakdown_path.write_text(
            frozen.to_json(indent=2) + "\n",
            encoding="utf-8",
        )

        artifacts = [breakdown_path]
        provenance = {
            "schema_version": 1,
            "fixture_id": case["fixture_id"],
            "source": {
                "url": case["source_url"],
                "video_id": case["video_id"],
                "role": case["role"],
                "title": case["title"],
                "creator": case["creator"],
            },
            "human_truth": {
                "path": manifest["human_truth"],
                "section": case["truth_section"],
                "sha256": _text_sha256(truth_path),
                "caveat": case.get("truth_caveat"),
            },
            "source_media": {
                "committed": False,
                "filename": case["media_filename"],
                "byte_size": media_path.stat().st_size,
                "sha256": _sha256(media_path),
                "acquisition": {
                    **manifest["source_acquisition"],
                    "selected_format_ids": case["selected_format_ids"],
                },
            },
            "measured_media": {
                "committed": False,
                "byte_size": measured_media.stat().st_size,
                "sha256": _sha256(measured_media),
            },
            "normalizations": [
                "Replaced the temporary local source path with the canonical URL.",
                "Restored canonical YouTube title, creator, and platform metadata.",
                "Cleared meta.media_path because source media is not committed.",
                (
                    "Cleared shot keyframe paths because derived source frames "
                    "are not committed without documented redistribution terms."
                ),
            ],
            "measurement": dict(frozen.provenance),
            "performance": adapter.performance_for(media_path),
            "environment": {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "python": platform.python_version(),
                "ffmpeg": _tool_version(ffmpeg),
                "myzing": _package_version("myzing"),
                "scenedetect": _package_version("scenedetect-headless"),
                "faster_whisper": _package_version("faster-whisper"),
                "rapidocr": _package_version("rapidocr"),
                "onnxruntime": _package_version("onnxruntime"),
                "yt_dlp": _package_version("yt-dlp"),
            },
            "manifest": {
                "path": manifest_path.relative_to(HERE.parents[1]).as_posix(),
                "sha256": _text_sha256(manifest_path),
            },
            "artifacts": {
                path.relative_to(case_directory).as_posix(): _artifact_sha256(path)
                for path in artifacts
            },
        }
        (case_directory / "provenance.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        frozen_directories.append(case_directory)
    return frozen_directories


def freeze_real_videos(
    media_root: Path,
    output: Path = DEFAULT_OUTPUT,
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    adapter: Any | None = None,
) -> list[Path]:
    """Measure every manifest case and freeze portable artifacts."""
    media_root = media_root.resolve()
    output = output.resolve()
    manifest_path = manifest_path.resolve()
    manifest = _load_manifest(manifest_path)
    if adapter is not None:
        return _freeze_with_adapter(
            media_root,
            output,
            manifest_path,
            manifest,
            adapter,
            ffmpeg=ffmpeg,
        )
    with tempfile.TemporaryDirectory(prefix="zing-real-video-freeze-") as workspace:
        benchmark = StudyBenchmarkAdapter(
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            workspace=Path(workspace),
        )
        return _freeze_with_adapter(
            media_root,
            output,
            manifest_path,
            manifest,
            benchmark,
            ffmpeg=ffmpeg,
        )


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args(argv)
    try:
        directories = freeze_real_videos(
            args.media_root,
            args.output,
            args.manifest,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
        )
    except (OSError, ValueError, RegressionFreezeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    for directory in directories:
        print(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
