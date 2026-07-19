"""Machine-checkable conformance for Sprint 3 direction judgments."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DIRECTION_VALIDATOR_VERSION = "1.1.0"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_CRITERION_INDEX = ROOT / "docs" / "taste" / "INDEX.md"
DEFAULT_JARGON_LIST = HERE / "direction-jargon.json"
DEFAULT_DIRECTION_CASES = HERE / "directions"

_INDEX_ROW_RE = re.compile(r"^\|\s*([A-Z][A-Za-z0-9-]*)\s*\|")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")

_TOP_LEVEL_TYPES = {
    "verdict": str,
    "gaps": list,
    "shot_prompts": list,
    "keepers": list,
    "assembly_notes": str,
}
_GAP_TYPES = {
    "criterion_id": str,
    "profile_evidence": str,
    "footage_evidence": str,
    "severity": str,
}
_SHOT_TYPES = {
    "n": int,
    "instruction": str,
    "closes_gap": (str, int),
    "duration_hint": (str, int, float),
}
_KEEPER_TYPES = {
    "start": (int, float),
    "end": (int, float),
    "why": str,
}
_SEVERITIES = frozenset({"blocking", "important", "polish"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def load_criterion_ids(path: Path = DEFAULT_CRITERION_INDEX) -> frozenset[str]:
    """Load every criterion ID from the first column of the master index."""
    criterion_ids = {
        match.group(1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := _INDEX_ROW_RE.match(line))
        and match.group(1) != "ID"
    }
    if not criterion_ids:
        raise ValueError(f"criterion index has no IDs: {path}")
    return frozenset(criterion_ids)


def load_jargon_terms(path: Path = DEFAULT_JARGON_LIST) -> tuple[str, ...]:
    """Load the review-maintained plain-language denylist."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    terms = payload.get("terms")
    if not isinstance(terms, list) or not terms:
        raise ValueError(f"direction jargon list has no terms: {path}")
    values = []
    for index, item in enumerate(terms):
        if not isinstance(item, Mapping) or not isinstance(item.get("term"), str):
            raise ValueError(
                f"direction jargon list term {index} has no string term"
            )
        term = item["term"].strip()
        if not term:
            raise ValueError(f"direction jargon list term {index} is empty")
        values.append(term)
    duplicates = sorted(
        term for term in set(values) if values.count(term) > 1
    )
    if duplicates:
        raise ValueError(
            "direction jargon list has duplicate terms: "
            + ", ".join(duplicates)
        )
    return tuple(values)


def _wrong_type(value: Any, expected: Any) -> bool:
    if isinstance(value, bool) and (
        expected is int
        or (
            isinstance(expected, tuple)
            and any(item in (int, float) for item in expected)
        )
    ):
        return True
    return not isinstance(value, expected)


def _expected_type_name(expected: Any) -> str:
    if isinstance(expected, tuple):
        return " or ".join(item.__name__ for item in expected)
    return expected.__name__


def _required_issues(
    value: Any,
    path: str,
    required: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return [
            {
                "path": path,
                "kind": "wrong_type",
                "expected": "object",
                "actual": type(value).__name__,
            }
        ]
    issues = []
    for key, expected in required.items():
        child_path = f"{path}.{key}"
        if key not in value:
            issues.append(
                {
                    "path": child_path,
                    "kind": "missing_key",
                }
            )
        elif _wrong_type(value[key], expected):
            issues.append(
                {
                    "path": child_path,
                    "kind": "wrong_type",
                    "expected": _expected_type_name(expected),
                    "actual": type(value[key]).__name__,
                }
            )
    return issues


def _shape_issues(direction: Any) -> list[dict[str, Any]]:
    issues = _required_issues(direction, "direct", _TOP_LEVEL_TYPES)
    if not isinstance(direction, Mapping):
        return issues

    nested_specs = (
        ("gaps", _GAP_TYPES),
        ("shot_prompts", _SHOT_TYPES),
        ("keepers", _KEEPER_TYPES),
    )
    for key, required in nested_specs:
        values = direction.get(key)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            issues.extend(
                _required_issues(
                    value,
                    f"direct.{key}[{index}]",
                    required,
                )
            )
    gaps = direction.get("gaps")
    if isinstance(gaps, list):
        for index, gap in enumerate(gaps):
            if not isinstance(gap, Mapping):
                continue
            severity = gap.get("severity")
            if isinstance(severity, str) and severity not in _SEVERITIES:
                issues.append(
                    {
                        "path": f"direct.gaps[{index}].severity",
                        "kind": "invalid_value",
                        "expected": sorted(_SEVERITIES),
                        "actual": severity,
                    }
                )
    return issues


def _criterion_issues(
    direction: Any,
    criterion_ids: frozenset[str],
) -> list[dict[str, Any]]:
    if not isinstance(direction, Mapping):
        return []
    gaps = direction.get("gaps")
    if not isinstance(gaps, list):
        return []
    issues = []
    for index, gap in enumerate(gaps):
        if not isinstance(gap, Mapping):
            continue
        criterion_id = gap.get("criterion_id")
        if isinstance(criterion_id, str) and criterion_id not in criterion_ids:
            issues.append(
                {
                    "path": f"direct.gaps[{index}].criterion_id",
                    "kind": "unknown_criterion_id",
                    "actual": criterion_id,
                }
            )
    return issues


def _sentence_count(instruction: str) -> int:
    stripped = instruction.strip()
    if not stripped:
        return 0
    return len(
        [
            fragment
            for fragment in _SENTENCE_BOUNDARY_RE.split(stripped)
            if fragment.strip()
        ]
    )


def _matched_jargon(
    instruction: str,
    jargon_terms: Sequence[str],
) -> list[str]:
    return [
        term
        for term in jargon_terms
        if re.search(
            rf"(?<!\w){re.escape(term)}(?!\w)",
            instruction,
            flags=re.IGNORECASE,
        )
    ]


def _language_issues(
    direction: Any,
    jargon_terms: Sequence[str],
) -> list[dict[str, Any]]:
    if not isinstance(direction, Mapping):
        return []
    prompts = direction.get("shot_prompts")
    if not isinstance(prompts, list):
        return []
    issues = []
    for index, prompt in enumerate(prompts):
        if not isinstance(prompt, Mapping):
            continue
        instruction = prompt.get("instruction")
        if not isinstance(instruction, str):
            continue
        path = f"direct.shot_prompts[{index}].instruction"
        sentence_count = _sentence_count(instruction)
        if sentence_count > 2:
            issues.append(
                {
                    "path": path,
                    "kind": "too_many_sentences",
                    "actual": sentence_count,
                    "maximum": 2,
                }
            )
        matches = _matched_jargon(instruction, jargon_terms)
        if matches:
            issues.append(
                {
                    "path": path,
                    "kind": "jargon",
                    "terms": matches,
                }
            )
    return issues


def validate_direction(
    direction: Any,
    *,
    criterion_ids: frozenset[str] | None = None,
    jargon_terms: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate format only; do not claim that the direction is good."""
    if criterion_ids is None:
        criterion_ids = load_criterion_ids()
    if jargon_terms is None:
        jargon_terms = load_jargon_terms()

    dimensions = {
        "shape": {
            "passed": False,
            "issues": _shape_issues(direction),
        },
        "criterion_ids": {
            "passed": False,
            "issues": _criterion_issues(direction, criterion_ids),
            "known_criterion_count": len(criterion_ids),
        },
        "shot_prompt_language": {
            "passed": False,
            "issues": _language_issues(direction, jargon_terms),
            "heuristic_only": True,
            "maximum_sentences": 2,
            "jargon_term_count": len(jargon_terms),
        },
    }
    for dimension in dimensions.values():
        dimension["passed"] = not dimension["issues"]
    failed = [
        name for name, detail in dimensions.items() if not detail["passed"]
    ]
    return {
        "direction_validator_version": DIRECTION_VALIDATOR_VERSION,
        "passed": not failed,
        "failed_dimensions": failed,
        "dimensions": dimensions,
        "not_checked": [
            "truth of verdict or evidence",
            "severity calibration",
            "whether a shot is physically filmable",
            "whether a shot closes the claimed gap",
            "creative quality",
        ],
    }


def _extract_direction(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload
    judgment = payload.get("judgment")
    if isinstance(judgment, Mapping) and "direct" in judgment:
        return judgment["direct"]
    if "direct" in payload:
        return payload["direct"]
    return payload


def evaluate_direction_paths(
    paths: Sequence[Path],
    *,
    criterion_index: Path = DEFAULT_CRITERION_INDEX,
    jargon_list: Path = DEFAULT_JARGON_LIST,
) -> dict[str, Any]:
    """Validate direction JSON files for inclusion in the eval report."""
    if not paths:
        return {
            "available": False,
            "status": "not-run",
            "passed": None,
            "direction_validator_version": DIRECTION_VALIDATOR_VERSION,
            "criterion_index": None,
            "jargon_list": None,
            "case_count": 0,
            "cases": [],
        }

    criterion_ids = load_criterion_ids(criterion_index)
    jargon_terms = load_jargon_terms(jargon_list)
    cases = []
    for path in paths:
        if not path.is_file():
            raise ValueError(f"direction output not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases.append(
            {
                "fixture_id": path.stem,
                "fixture_sha256": _sha256(path),
                "score": validate_direction(
                    _extract_direction(payload),
                    criterion_ids=criterion_ids,
                    jargon_terms=jargon_terms,
                ),
            }
        )

    return {
        "available": True,
        "status": "scored",
        "passed": all(case["score"]["passed"] for case in cases),
        "direction_validator_version": DIRECTION_VALIDATOR_VERSION,
        "criterion_index": {
            "path": _display_path(criterion_index),
            "sha256": _sha256(criterion_index),
            "criterion_count": len(criterion_ids),
        },
        "jargon_list": {
            "path": _display_path(jargon_list),
            "sha256": _sha256(jargon_list),
            "term_count": len(jargon_terms),
        },
        "case_count": len(cases),
        "cases": cases,
    }
