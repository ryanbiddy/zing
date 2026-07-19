"""Run Zing's versioned evaluation scorer and write a JSON report."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from myzing.schemas import Breakdown, StyleProfile

from .audio_delivery import (
    measure_audio_delivery,
    summarize_audio_delivery,
)
from .direction_format import (
    DEFAULT_DIRECTION_CASES,
    evaluate_direction_paths,
)
from .make_goldens import DEFAULT_OUTPUT as DEFAULT_GOLDENS
from .performance import (
    StudyBenchmarkAdapter,
    summarize_performance,
    unavailable_performance,
)
from .profile_scoring import (
    ProfileBuilder,
    evaluate_profile_cases,
)
from .scoring import MANIFEST, MANIFEST_PATH, score


HERE = Path(__file__).resolve().parent
DEFAULT_REPORT = HERE / "eval-report.json"
SAMPLE_DIRECTORY = HERE / "sample"
DEFAULT_PROFILE_CASES = HERE / "profiles"


def study_adapter(media_path: Path) -> Breakdown:
    """Adapt Lane A's stable media-path API to the pure scorer."""
    try:
        from myzing.study.api import study
    except ImportError as exc:
        raise RuntimeError(
            "Lane A study API is unavailable; run with --sample until it lands"
        ) from exc
    return study(str(media_path))


def profile_builder_adapter(
    name: str,
    slugs: list[str],
    workspace: Path,
) -> StyleProfile:
    """Adapt Lane A's stable workspace API to the profile scorer."""
    try:
        from myzing.profile.api import build_profile
    except ImportError as exc:
        raise RuntimeError(
            "Lane A profile builder is unavailable; omit --profiles until "
            "it lands"
        ) from exc
    return build_profile(name, slugs, workspace=workspace)


def _adapter_performance(
    adapter: Callable[[Path], Breakdown] | None,
    media_path: Path,
) -> dict[str, Any]:
    if adapter is None:
        return unavailable_performance(
            "checked-in Breakdown: no live study or render was timed"
        )
    getter = getattr(adapter, "performance_for", None)
    if not callable(getter):
        return unavailable_performance(
            "adapter does not expose per-stage performance"
        )
    return getter(media_path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ffmpeg_version(ffmpeg: str) -> str | None:
    if shutil.which(ffmpeg) is None:
        return None
    result = subprocess.run(
        [ffmpeg, "-version"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()[0] if result.returncode == 0 else None


def _load_breakdown(path: Path) -> Breakdown:
    return Breakdown.from_json(path.read_text(encoding="utf-8"))


def _print_table(cases: list[dict[str, Any]]) -> None:
    headings = ("case", "cuts", "captions", "audio", "speech", "overall")
    rows = []
    for case in cases:
        result = case["score"]
        speech = result["audio"]["speech_ratio"]
        rows.append(
            (
                result["fixture_id"],
                "PASS" if result["cuts"]["passed"] else "FAIL",
                "PASS" if result["captions"]["passed"] else "FAIL",
                "PASS" if result["audio"]["window_pattern"]["passed"] else "FAIL",
                (
                    "PASS"
                    if speech["passed"]
                    else "FAIL" if speech["passed"] is False else "N/A"
                ),
                "PASS" if result["passed"] else "FAIL",
            )
        )
    widths = [
        max(len(str(value)) for value in (heading,) + tuple(row[index] for row in rows))
        for index, heading in enumerate(headings)
    ]
    print("  ".join(heading.ljust(widths[index]) for index, heading in enumerate(headings)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


def evaluate(
    case_directories: Sequence[Path],
    report_path: Path,
    *,
    adapter: Callable[[Path], Breakdown] | None = None,
    ffmpeg: str = "ffmpeg",
    profile_case_directories: Sequence[Path] = (),
    profile_builder: ProfileBuilder | None = None,
    direction_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    """Evaluate a non-empty case set and write a machine-readable report."""
    if not case_directories:
        raise ValueError("no evaluation cases found")
    started = time.perf_counter()
    cases = []
    for case_directory in case_directories:
        truth_path = case_directory / "truth.json"
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        media_path = case_directory / truth.get("media", "")
        if adapter is None:
            breakdown_path = case_directory / "breakdown.json"
            breakdown = _load_breakdown(breakdown_path)
        else:
            breakdown_path = None
            breakdown = adapter(media_path)

        hashes = {"truth.json": _sha256(truth_path)}
        if media_path.is_file():
            hashes[media_path.name] = _sha256(media_path)
        if breakdown_path is not None:
            hashes["breakdown.json"] = _sha256(breakdown_path)
        cases.append(
            {
                "directory": case_directory.name,
                "fixture_hashes": hashes,
                "score": score(truth, breakdown),
                "audio_delivery": measure_audio_delivery(media_path, ffmpeg),
                "performance": _adapter_performance(adapter, media_path),
            }
        )

    profile_eval = evaluate_profile_cases(
        profile_case_directories,
        builder=profile_builder,
    )
    direction_eval = evaluate_direction_paths(direction_paths)
    report = {
        "report_schema_version": 5,
        "scorer_version": MANIFEST["scorer_version"],
        "manifest_sha256": _sha256(MANIFEST_PATH),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "ffmpeg": _ffmpeg_version(ffmpeg),
        "wall_clock_seconds": round(time.perf_counter() - started, 6),
        "passed": (
            all(case["score"]["passed"] for case in cases)
            and profile_eval["passed"] is not False
            and direction_eval["passed"] is not False
        ),
        "audio_delivery": summarize_audio_delivery(cases),
        "performance": summarize_performance(cases),
        "profile_eval": profile_eval,
        "direction_eval": direction_eval,
        "cases": cases,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _print_table(cases)
    print(f"\nreport: {report_path}")
    return report


def _write_error_report(report_path: Path, ffmpeg: str, exc: Exception) -> None:
    report = {
        "report_schema_version": 5,
        "scorer_version": MANIFEST["scorer_version"],
        "manifest_sha256": _sha256(MANIFEST_PATH),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "ffmpeg": _ffmpeg_version(ffmpeg),
        "wall_clock_seconds": None,
        "passed": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
        "audio_delivery": summarize_audio_delivery([]),
        "performance": summarize_performance([]),
        "profile_eval": evaluate_profile_cases([], builder=None),
        "direction_eval": evaluate_direction_paths([]),
        "cases": [],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Default mode: score the checked-in sample. Pass --study to "
            "measure generated goldens through the live study adapter."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--sample",
        action="store_true",
        help="score the checked-in sample without live performance timings",
    )
    mode.add_argument(
        "--study",
        action="store_true",
        help="run Lane A's study(media_path) adapter on generated goldens",
    )
    parser.add_argument("--goldens", type=Path, default=DEFAULT_GOLDENS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument(
        "--profiles",
        action="store_true",
        help="also build and score the checked-in Sprint 2 profile cases",
    )
    parser.add_argument(
        "--directions",
        action="store_true",
        help="also validate the checked-in Sprint 3 direction outputs",
    )
    args = parser.parse_args(argv)

    if args.study:
        if not args.goldens.is_dir():
            parser.error(
                f"goldens directory not found: {args.goldens}; run make_goldens first"
            )
        case_directories = sorted(
            path for path in args.goldens.iterdir() if (path / "truth.json").is_file()
        )
        adapter = StudyBenchmarkAdapter(
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
        )
    else:
        if not args.sample:
            print("mode: checked-in sample (default; pass --study for live study)")
        case_directories = [SAMPLE_DIRECTORY]
        adapter = None

    if args.profiles:
        if not DEFAULT_PROFILE_CASES.is_dir():
            parser.error(
                f"profile cases directory not found: {DEFAULT_PROFILE_CASES}"
            )
        profile_case_directories = sorted(
            path
            for path in DEFAULT_PROFILE_CASES.iterdir()
            if (path / "expected-profile.json").is_file()
        )
        if not profile_case_directories:
            parser.error(
                f"no profile cases found in: {DEFAULT_PROFILE_CASES}"
            )
        profile_builder = profile_builder_adapter
    else:
        profile_case_directories = []
        profile_builder = None

    if args.directions:
        if not DEFAULT_DIRECTION_CASES.is_dir():
            parser.error(
                f"direction cases directory not found: {DEFAULT_DIRECTION_CASES}"
            )
        direction_paths = sorted(DEFAULT_DIRECTION_CASES.glob("*.json"))
        if not direction_paths:
            parser.error(
                f"no direction outputs found in: {DEFAULT_DIRECTION_CASES}"
            )
    else:
        direction_paths = []

    try:
        report = evaluate(
            case_directories,
            args.report,
            adapter=adapter,
            ffmpeg=args.ffmpeg,
            profile_case_directories=profile_case_directories,
            profile_builder=profile_builder,
            direction_paths=direction_paths,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        _write_error_report(args.report, args.ffmpeg, exc)
        parser.exit(2, f"error: {exc}\nreport: {args.report}\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
