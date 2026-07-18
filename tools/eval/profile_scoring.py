"""Pure scoring for Sprint 2 StyleProfile aggregate fixtures."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from myzing.schemas import StyleProfile


PROFILE_SCORER_VERSION = "1.0.0"
PROFILE_DIMENSIONS = (
    "duration",
    "shot_duration",
    "cuts_per_10s_curve",
    "time_to_first_cut",
    "time_to_first_word",
    "time_to_first_caption",
    "caption_all_caps_rate",
    "caption_words_visible_mode",
    "speech_ratio",
    "music_present_rate",
    "transition_kind_counts",
)
NOT_SCORED = [
    "name",
    "source_slugs",
    "genre",
    "platform",
    "judged",
    "unjudged_source_slugs",
    "warnings",
    "provenance",
    "schema_version",
]

ProfileBuilder = Callable[[str, list[str], Path], StyleProfile]
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def _differences(
    expected: Any,
    actual: Any,
    path: str,
) -> list[dict[str, Any]]:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(expected) | set(actual)):
            child_path = f"{path}.{key}"
            if key not in expected:
                differences.append(
                    {
                        "path": child_path,
                        "expected": None,
                        "actual": actual[key],
                        "kind": "unexpected",
                    }
                )
            elif key not in actual:
                differences.append(
                    {
                        "path": child_path,
                        "expected": expected[key],
                        "actual": None,
                        "kind": "missing",
                    }
                )
            else:
                differences.extend(
                    _differences(expected[key], actual[key], child_path)
                )
        return differences
    if (
        isinstance(expected, Sequence)
        and not isinstance(expected, (str, bytes))
        and isinstance(actual, Sequence)
        and not isinstance(actual, (str, bytes))
    ):
        differences = []
        for index in range(max(len(expected), len(actual))):
            child_path = f"{path}[{index}]"
            if index >= len(expected):
                differences.append(
                    {
                        "path": child_path,
                        "expected": None,
                        "actual": actual[index],
                        "kind": "unexpected",
                    }
                )
            elif index >= len(actual):
                differences.append(
                    {
                        "path": child_path,
                        "expected": expected[index],
                        "actual": None,
                        "kind": "missing",
                    }
                )
            else:
                differences.extend(
                    _differences(expected[index], actual[index], child_path)
                )
        return differences
    if expected != actual:
        return [
            {
                "path": path,
                "expected": expected,
                "actual": actual,
                "kind": "value",
            }
        ]
    return []


def score_profile(
    expected: StyleProfile,
    actual: StyleProfile,
    *,
    fixture_id: str = "unknown",
) -> dict[str, Any]:
    """Compare every measured aggregate exactly, with no side effects."""
    expected_dict = expected.to_dict()
    actual_dict = actual.to_dict()
    dimensions = {}
    for name in PROFILE_DIMENSIONS:
        differences = _differences(
            expected_dict[name],
            actual_dict[name],
            name,
        )
        dimensions[name] = {
            "passed": not differences,
            "expected": expected_dict[name],
            "actual": actual_dict[name],
            "differences": differences,
        }
    failed = [
        name for name, detail in dimensions.items() if not detail["passed"]
    ]
    return {
        "profile_scorer_version": PROFILE_SCORER_VERSION,
        "fixture_id": fixture_id,
        "passed": not failed,
        "failed_dimensions": failed,
        "dimensions": dimensions,
        "not_scored": list(NOT_SCORED),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate_profile_cases(
    case_directories: Sequence[Path],
    *,
    builder: ProfileBuilder | None,
) -> dict[str, Any]:
    """Build and score profile workspaces for inclusion in the eval report."""
    if not case_directories:
        return {
            "available": False,
            "status": "not-run",
            "passed": None,
            "profile_scorer_version": PROFILE_SCORER_VERSION,
            "case_count": 0,
            "cases": [],
        }
    if builder is None:
        raise ValueError("profile cases require a profile builder")

    cases = []
    for case_directory in case_directories:
        expected_path = case_directory / "expected-profile.json"
        if not expected_path.is_file():
            raise ValueError(
                f"profile case has no expected-profile.json: {case_directory}"
            )
        expected = StyleProfile.from_json(
            expected_path.read_text(encoding="utf-8")
        )
        invalid_slugs = [
            slug
            for slug in expected.source_slugs
            if not _SLUG_RE.fullmatch(slug)
        ]
        if invalid_slugs:
            raise ValueError(
                f"profile case {case_directory.name} has invalid source "
                f"slugs: {', '.join(invalid_slugs)}"
            )
        source_manifest_path = case_directory / "sources.json"
        if source_manifest_path.is_file():
            source_manifest = json.loads(
                source_manifest_path.read_text(encoding="utf-8")
            )
            source_paths = {
                source["slug"]: (
                    case_directory / source["breakdown"]
                ).resolve()
                for source in source_manifest["sources"]
            }
        else:
            source_paths = {
                slug: (
                    case_directory
                    / "breakdowns"
                    / slug
                    / "breakdown.json"
                )
                for slug in expected.source_slugs
            }
        missing = [
            slug
            for slug in expected.source_slugs
            if slug not in source_paths or not source_paths[slug].is_file()
        ]
        if missing:
            raise ValueError(
                f"profile case {case_directory.name} is missing breakdowns "
                f"for: {', '.join(missing)}"
            )
        extra = sorted(set(source_paths) - set(expected.source_slugs))
        if extra:
            raise ValueError(
                f"profile case {case_directory.name} has undeclared "
                f"breakdowns for: {', '.join(extra)}"
            )

        fixture_hashes = {
            "expected-profile.json": _sha256(expected_path),
            **{
                f"breakdowns/{slug}/breakdown.json": _sha256(path)
                for slug, path in source_paths.items()
            },
        }
        if source_manifest_path.is_file():
            fixture_hashes["sources.json"] = _sha256(source_manifest_path)

        with tempfile.TemporaryDirectory(
            prefix=f"zing-profile-eval-{case_directory.name}-"
        ) as workspace_text:
            workspace = Path(workspace_text)
            for slug, source_path in source_paths.items():
                target = workspace / "breakdowns" / slug / "breakdown.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target)
            actual = builder(
                expected.name,
                list(expected.source_slugs),
                workspace,
            )
        cases.append(
            {
                "fixture_id": case_directory.name,
                "directory": case_directory.name,
                "fixture_hashes": fixture_hashes,
                "score": score_profile(
                    expected,
                    actual,
                    fixture_id=case_directory.name,
                ),
            }
        )

    return {
        "available": True,
        "status": "scored",
        "passed": all(case["score"]["passed"] for case in cases),
        "profile_scorer_version": PROFILE_SCORER_VERSION,
        "case_count": len(cases),
        "cases": cases,
    }
