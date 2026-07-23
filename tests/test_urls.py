"""One source-URL rule for every Zing ingestion boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myzing import urls

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "eval"
    / "fixtures"
    / "suite_v1"
    / "source-url.json"
)
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_cases() -> list[dict[str, object]]:
    return FIXTURE["cases"]


def test_source_url_fixture_identity_is_pinned() -> None:
    assert FIXTURE["fixture"] == "ryan.suite.source-url-conformance"
    assert FIXTURE["version"] == 1
    assert len(FIXTURE["cases"]) == 16


@pytest.mark.parametrize("case", _fixture_cases(), ids=lambda case: case["id"])
def test_source_urls_match_the_shared_conformance_fixture(
        case: dict[str, object]) -> None:
    assert urls.is_http_url(case["value"]) is case["expected_valid"]
