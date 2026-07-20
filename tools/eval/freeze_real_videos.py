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
from myzing.study.ingest import detect_platform

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
    # ``read_text`` decodes with universal newlines, so text pins are
    # sha256 of the LF-normalized UTF-8 text — identical on LF (CI) and
    # CRLF (Windows core.autocrlf) checkouts. Keep in sync with
    # ``tests/test_eval_real_videos._sha256``.
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
    schema_version = manifest.get("schema_version")
    if schema_version not in {1, 2}:
        raise RegressionFreezeError(
            f"unsupported real-video manifest schema: {schema_version}"
        )
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RegressionFreezeError("real-video manifest has no cases")
    if schema_version == 2:
        for case in cases:
            fixture_id = case.get("fixture_id", "<missing fixture_id>")
            human_truth = case.get("human_truth")
            if (
                not isinstance(human_truth, dict)
                or not isinstance(human_truth.get("available"), bool)
            ):
                raise RegressionFreezeError(
                    f"{fixture_id}: schema 2 requires human_truth.available"
                )
            if not human_truth["available"] and not human_truth.get("reason"):
                raise RegressionFreezeError(
                    f"{fixture_id}: unavailable human truth requires a reason"
                )
            if human_truth["available"] and (
                not human_truth.get("path")
                or not human_truth.get("section")
            ):
                raise RegressionFreezeError(
                    f"{fixture_id}: available human truth requires path and section"
                )
            rights = case.get("rights")
            if (
                not isinstance(rights, dict)
                or not rights.get("label")
                or not rights.get("evidence_url")
                or not rights.get("attribution")
            ):
                raise RegressionFreezeError(
                    f"{fixture_id}: schema 2 requires rights evidence"
                )
            study_options = case.get("study_options", {})
            if not isinstance(study_options, dict):
                raise RegressionFreezeError(
                    f"{fixture_id}: study_options must be an object"
                )
            if (
                "raw_mode" in study_options
                and not isinstance(study_options["raw_mode"], bool)
            ):
                raise RegressionFreezeError(
                    f"{fixture_id}: study_options.raw_mode must be boolean"
                )
            if study_options.get("raw_mode"):
                regeneration = manifest.get("regeneration")
                required_commands = {
                    "fetch_command",
                    "freeze_command",
                    "frames_command",
                }
                if (
                    not isinstance(regeneration, dict)
                    or not required_commands <= regeneration.keys()
                ):
                    raise RegressionFreezeError(
                        f"{fixture_id}: raw-mode fixtures require fetch, "
                        "freeze, and frames regeneration commands"
                    )
    return manifest


def _human_truth(
    manifest: dict[str, Any],
    case: dict[str, Any],
) -> dict[str, Any]:
    if "human_truth" in case:
        return dict(case["human_truth"])
    return {
        "available": True,
        "path": manifest["human_truth"],
        "section": case["truth_section"],
        "caveat": case.get("truth_caveat"),
    }


def _manifest_display_path(path: Path) -> str:
    try:
        return path.relative_to(HERE.parents[1]).as_posix()
    except ValueError:
        return path.name


def _portable_breakdown(
    measured: Breakdown,
    case: dict[str, Any],
) -> Breakdown:
    frozen = Breakdown.from_dict(measured.to_dict())
    frozen.meta.source_url = case["source_url"]
    frozen.meta.platform = detect_platform(case["source_url"])
    frozen.meta.author = case["creator"]
    frozen.meta.title = case["title"]
    frozen.meta.media_path = ""
    for shot in frozen.shots:
        shot.keyframe = ""
    fixture_provenance = {
        "fixture_id": case["fixture_id"],
        "video_id": case["video_id"],
        "role": case["role"],
    }
    if "study_options" in case:
        fixture_provenance["study_options"] = dict(case["study_options"])
    if "human_truth" in case:
        fixture_provenance["human_truth"] = dict(case["human_truth"])
    else:
        fixture_provenance["human_truth"] = (
            "handoff/research/EXAMPLE-DATASET-TRUTH.md"
        )
        fixture_provenance["truth_section"] = case["truth_section"]
    frozen.provenance["regression_fixture"] = fixture_provenance
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
    source_document_path = None
    if manifest.get("source_document"):
        source_document_path = HERE.parents[1] / manifest["source_document"]
        if not source_document_path.is_file():
            raise RegressionFreezeError(
                f"source document not found: {source_document_path}"
            )
    for case in manifest["cases"]:
        human_truth = _human_truth(manifest, case)
        if human_truth["available"]:
            truth_path = HERE.parents[1] / human_truth["path"]
            if not truth_path.is_file():
                raise RegressionFreezeError(
                    f"human truth file not found: {truth_path}"
                )
        media_path = media_root / case["media_filename"]
        if not media_path.is_file():
            raise RegressionFreezeError(
                f"media not found for {case['fixture_id']}: {media_path}"
            )
        expected_sha256 = case.get("expected_media", {}).get("sha256")
        if expected_sha256 and _sha256(media_path) != expected_sha256:
            raise RegressionFreezeError(
                f"{case['fixture_id']}: source media SHA-256 does not "
                "match expected_media.sha256"
            )
        case_directory = output / case["fixture_id"]
        if case_directory.exists():
            raise RegressionFreezeError(
                f"refusing to replace frozen fixture: {case_directory}"
            )

    output.mkdir(parents=True, exist_ok=True)
    frozen_directories = []
    for case in manifest["cases"]:
        human_truth = _human_truth(manifest, case)
        truth_path = None
        if human_truth["available"]:
            truth_path = HERE.parents[1] / human_truth["path"]
        media_path = media_root / case["media_filename"]
        case_directory = output / case["fixture_id"]

        study_options = dict(case.get("study_options", {}))
        measured = adapter(media_path, **study_options)
        expected_media = case.get("expected_media", {})
        for field in ("width", "height"):
            expected = expected_media.get(field)
            if expected is not None and getattr(measured.meta, field) != expected:
                raise RegressionFreezeError(
                    f"{case['fixture_id']}: measured {field} "
                    f"{getattr(measured.meta, field)} does not match "
                    f"expected {expected}"
                )
        expected_duration = expected_media.get("duration_seconds")
        if (
            expected_duration is not None
            and abs(measured.meta.duration - expected_duration) > 0.02
        ):
            raise RegressionFreezeError(
                f"{case['fixture_id']}: measured duration "
                f"{measured.meta.duration} does not match expected "
                f"{expected_duration}"
            )
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
        if truth_path is None:
            truth_provenance = human_truth
        else:
            truth_provenance = {
                **human_truth,
                "sha256": _text_sha256(truth_path),
            }
            if "available" not in case.get("human_truth", {}):
                truth_provenance.pop("available", None)
        provenance = {
            "schema_version": manifest["schema_version"],
            "fixture_id": case["fixture_id"],
            "source": {
                "url": case["source_url"],
                "video_id": case["video_id"],
                "role": case["role"],
                "title": case["title"],
                "creator": case["creator"],
            },
            "human_truth": truth_provenance,
            **({"rights": case["rights"]} if "rights" in case else {}),
            **(
                {"study_options": study_options}
                if study_options
                else {}
            ),
            **(
                {"regeneration": dict(manifest["regeneration"])}
                if manifest.get("regeneration")
                else {}
            ),
            "source_media": {
                "committed": False,
                "filename": case["media_filename"],
                "byte_size": media_path.stat().st_size,
                "sha256": _sha256(media_path),
                "acquisition": {
                    **manifest["source_acquisition"],
                    **case.get("acquisition", {}),
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
                "Restored canonical title, creator, and platform metadata.",
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
                "path": _manifest_display_path(manifest_path),
                "sha256": _text_sha256(manifest_path),
            },
            **(
                {
                    "source_document": {
                        "path": manifest["source_document"],
                        "sha256": _text_sha256(source_document_path),
                    }
                }
                if source_document_path is not None
                else {}
            ),
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
