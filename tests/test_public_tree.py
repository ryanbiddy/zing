from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.eval import public_tree
from tools.eval.content_policy import text_measurements


CALIB = ROOT / "handoff/research/ocr-calibration"


def test_public_tree_has_only_reviewed_assets_and_no_detected_secrets_or_home_paths():
    report = public_tree.scan(ROOT)
    assert report["scanned_files"] > 700
    assert report["issues"] == []


def test_scanner_reports_locations_without_echoing_sensitive_values():
    value = "gh" + "p_" + "a" * 36
    assert public_tree.text_issues(value) == [(1, "credential-shaped value")]
    home = "C:/Users/" + "private-person" + "/data"
    assert public_tree.text_issues(home) == [(1, "personal home path")]
    assert public_tree.text_issues("C:/Users/ExampleUser/data") == []


def test_ocr_records_keep_anchored_geometry_labels_and_no_text():
    files = sorted(CALIB.glob("*/*.jsonl"))
    assert len(files) == 14
    total = 0
    for path in files:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert rows[0]["publication"]["text_permitted"] is False
        count = 0
        for row in rows[1:]:
            if "lines" in row:
                assert len(row["frame_sha256"]) == 64
                assert row["step"] > 0
                items = row["lines"]
            else:
                assert row["label"] in {"likely_caption", "incidental_text", "unsupported_script", "unreadable"}
                items = [row]
            for item in items:
                assert "text" not in item
                assert len(item["text_sha256"]) == len(item["normalized_text_sha256"]) == 64
                assert isinstance(item["token_count"], int) and item["token_count"] >= 0
                assert 0 <= item["score"] <= 1 and 0 <= item["y_center"] <= 1
                count += 1
        assert count == rows[0]["publication"]["text_values_removed"]
        total += count
    assert total == 31998


def test_ocr_freezer_emits_hashes_without_original_text(tmp_path, monkeypatch):
    from myzing.schemas import Breakdown, VideoMeta
    from myzing.study.captions import Line
    spec = importlib.util.spec_from_file_location("ocr_freeze", CALIB / "freeze.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.storage, "load_breakdown", lambda _: Breakdown(
        meta=VideoMeta(source_url="synthetic.mp4", platform="file", duration=1.0)
    ))
    monkeypatch.setattr(module.storage, "find_media", lambda _: tmp_path / "synthetic.mp4")
    monkeypatch.setattr(module.captions, "_engine", lambda: (object(), "test"))
    class Frame:
        def tobytes(self):
            return b"generated-frame"
    monkeypatch.setattr(module.captions, "_iter_frames", lambda *_: [(0.0, 0.25, Frame())])
    monkeypatch.setattr(module.captions, "_ocr", lambda *_: [Line("Generated kite", 0.99, 0.6, 0.5)])
    output = module.freeze(tmp_path / "workspace", "synthetic", tmp_path / "out")
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["publication"]["text_permitted"] is False
    line = rows[1]["lines"][0]
    assert "text" not in line
    assert line.items() >= text_measurements("Generated kite").items()


def test_v1_corpus_keeps_metadata_and_source_licenses():
    folder = ROOT / "tools/eval/real"
    assert {p.suffix for p in folder.iterdir() if p.is_file()} <= {".py", ".json", ".md"}
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["sources"]) == 4
    for item in manifest["sources"] + manifest["clips"]:
        for field in ("license", "attribution", "license_url", "sha256"):
            assert item[field]
        assert len(item["sha256"]) == 64


def test_calibration_scores_remain_reproducible_without_text():
    from handoff.research import pc2_baseline as baseline
    rows = baseline.load()
    baseline.annotate_persistence(rows)
    assert len(rows) == 15999
    assert sum(row["label"] == baseline.CAPTION for row in rows) == 577
    assert baseline.score(rows, baseline.rule) == pytest.approx((0.710, 0.700, 0.705), abs=0.0005)
    assert baseline.score(rows, baseline.persistence_rule) == pytest.approx((0.477, 0.882, 0.619), abs=0.0005)
