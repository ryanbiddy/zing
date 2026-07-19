"""Writer shot-list import (B-S6, INTEGRATION-CONTRACT v1 §6.2).

Integration truth over parallel truth (the pack-seam lesson): the parser
is proven against Lane C's checked-in conformance fixtures, and every
receipt this module emits is run through Lane C's own contract validator
— my implementation and the suite gate can never drift apart silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myzing import mcp_server, shot_list, storage
from myzing.schemas import Breakdown, VideoMeta
from tools.eval.suite_contracts import validate_contract_payload

FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "tools" / "eval" / "fixtures" / "suite_v1" / "writer-shot-list.json"
)

VALID_DOC = (
    "---\n"
    "document_type: writer.shot-list\n"
    "schema_version: 1\n"
    "generated_at: 2026-07-19T12:00:00Z\n"
    "source_script_id: 17\n"
    "---\n"
    "# Cut of the pricing short\n"
    "## Hook\nOpen on the result.\n"
    "## Beats\nExplain the change.\n"
    "## Script\nProse.\n"
    "## CTA\nSave the draft.\n"
    "## Shots\n1. Use the measured keeper.\n"
    "## Credits\nSource: uoink://item/short-123\n"
)

SLUG = "tiktok-999"


@pytest.fixture
def studied(zing_workspace):
    b = Breakdown(
        meta=VideoMeta(
            source_url="https://www.tiktok.com/@a/video/999",
            platform="tiktok",
            duration=9.0,
        )
    )
    storage.save_breakdown(b, slug=SLUG)
    return b


def fixture_cases():
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return [c for c in data["cases"] if "payload_text" in c]


@pytest.mark.parametrize(
    "case", fixture_cases(), ids=lambda c: c["id"]
)
def test_parser_agrees_with_lane_c_fixture(case):
    front, defect = shot_list.parse_document(case["payload_text"].encode("utf-8"))
    if case["expected_valid"]:
        assert defect is None, defect
    else:
        assert defect is not None


def test_import_receipt_passes_lane_c_validator(studied, tmp_path):
    doc = tmp_path / "export.md"
    doc.write_text(VALID_DOC, encoding="utf-8")
    receipt = shot_list.import_shot_list(str(doc), SLUG)
    assert receipt["ok"] is True, receipt
    issues = validate_contract_payload("zing.shot-list.import/1", receipt)
    assert issues["issues"] == []
    assert receipt["data"]["document"]["source_ref"] == "writer://script/17"
    assert receipt["data"]["target_ref"] == f"zing://breakdown/{SLUG}"
    # Path-free: the selected input path appears nowhere in the receipt.
    assert str(doc) not in json.dumps(receipt)


def test_reimport_is_idempotent_one_copy_equal_receipts(studied, tmp_path):
    doc = tmp_path / "export.md"
    doc.write_text(VALID_DOC, encoding="utf-8")
    first = shot_list.import_shot_list(str(doc), SLUG)
    second = shot_list.import_shot_list(str(doc), SLUG)
    assert first == second
    imports = storage.breakdown_dir(SLUG) / shot_list.IMPORTS_DIRNAME
    assert len(list(imports.glob("*.md"))) == 1


def test_unsupported_version_is_distinct_and_actionable(studied, tmp_path):
    doc = tmp_path / "export.md"
    doc.write_text(VALID_DOC.replace("schema_version: 1", "schema_version: 2"),
                   encoding="utf-8")
    receipt = shot_list.import_shot_list(str(doc), SLUG)
    assert receipt["ok"] is False
    assert receipt["error"]["code"] == "unsupported_version"
    assert "update zing" in receipt["error"]["message"]
    assert validate_contract_payload("zing.shot-list.import/1", receipt)["issues"] == []


def test_missing_target_names_the_code(zing_workspace, tmp_path):
    doc = tmp_path / "export.md"
    doc.write_text(VALID_DOC, encoding="utf-8")
    receipt = shot_list.import_shot_list(str(doc), "tiktok-000")
    assert receipt["ok"] is False
    assert receipt["error"]["code"] == "target_not_found"
    assert "study_video" in receipt["error"]["message"]


def test_traversal_slug_is_target_not_found(zing_workspace, tmp_path):
    doc = tmp_path / "export.md"
    doc.write_text(VALID_DOC, encoding="utf-8")
    receipt = shot_list.import_shot_list(str(doc), "../../outside")
    assert receipt["ok"] is False
    assert receipt["error"]["code"] == "target_not_found"


def test_invalid_file_and_missing_file(studied, tmp_path):
    doc = tmp_path / "export.md"
    doc.write_text("not a shot list", encoding="utf-8")
    receipt = shot_list.import_shot_list(str(doc), SLUG)
    assert receipt["ok"] is False
    assert receipt["error"]["code"] == "invalid_file"

    receipt = shot_list.import_shot_list(str(tmp_path / "ghost.md"), SLUG)
    assert receipt["ok"] is False
    assert receipt["error"]["code"] == "invalid_file"


def test_oversized_file_is_invalid_file(studied, tmp_path):
    doc = tmp_path / "big.md"
    doc.write_bytes(b"x" * (shot_list.SIZE_LIMIT + 1))
    receipt = shot_list.import_shot_list(str(doc), SLUG)
    assert receipt["ok"] is False
    assert receipt["error"]["code"] == "invalid_file"
    assert "MiB" in receipt["error"]["message"]


def test_mcp_handler_validates_arguments(zing_workspace):
    assert mcp_server.h_import_shot_list("", SLUG)["ok"] is False
    assert mcp_server.h_import_shot_list("x.md", " ")["ok"] is False


def test_mcp_handler_returns_the_contract_receipt(studied, tmp_path):
    doc = tmp_path / "export.md"
    doc.write_text(VALID_DOC, encoding="utf-8")
    result = mcp_server.h_import_shot_list(str(doc), SLUG)
    assert result["ok"] is True
    assert result["contract"] == "zing.shot-list.import"
    assert validate_contract_payload("zing.shot-list.import/1", result)["issues"] == []
