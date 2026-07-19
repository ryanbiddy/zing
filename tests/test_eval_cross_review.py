from pathlib import Path


LANE_NOTES = (
    Path(__file__).resolve().parents[1] / "handoff" / "NOTES-lane-c.md"
)
REVIEW_MARKER = (
    "- **2026-07-19 (Lane C, SG-1 cross-review complete — "
    "PRs #170, #168, #167):**"
)
LATEST_REVIEW_MARKER = (
    "- **2026-07-19 (Lane C, SG-1 cross-review complete — "
    "PRs #185, #183, #182):**"
)


def test_sg1_review_pins_prs_reproduction_and_evidence_gaps():
    notes = LANE_NOTES.read_text(encoding="utf-8")

    assert REVIEW_MARKER in notes
    review = notes.split(REVIEW_MARKER, 1)[1].split(
        "\n- **2026-07-19 (Lane C, PROCESS OBSERVATION SG-1):**", 1
    )[0]
    normalized = " ".join(review.split())

    assert "src/myzing/doctor.py:170-181,204-209,402-418" in normalized
    assert "`ok=True`" in normalized
    assert "`Verdict: fully ready`" in normalized
    assert "1080x2044" in normalized
    assert "1080x2042" in normalized
    assert "stable media paths" in normalized
    assert "elapsed wall clocks" in normalized
    assert "178s" in normalized
    assert "138s" in normalized


def test_sg1_review_records_latest_unreviewed_diffs_and_verdicts():
    notes = LANE_NOTES.read_text(encoding="utf-8")

    assert LATEST_REVIEW_MARKER in notes
    review = notes.split(LATEST_REVIEW_MARKER, 1)[1].split(
        "\n- **2026-07-19 (Lane C, PROCESS OBSERVATION SG-1):**", 1
    )[0]
    normalized = " ".join(review.split())

    assert "#185" in normalized
    assert "#183" in normalized
    assert "#182" in normalized
    assert "src/myzing/setup_flow.py" in normalized
    assert "src/myzing/study/transcribe.py" in normalized
    assert "handoff/research/ocr-calibration/" in normalized
    assert "reviewed the actual diffs" in normalized
    assert "regression" in normalized
    assert "13,313" in normalized
    assert "1,041 timestamps" in normalized
    assert "`verified_frames_t: [30.0]`" in normalized
    assert '`basis="layout-rule"`' in normalized
    assert "`New York`" in normalized
    assert "`York New`" in normalized
    assert "`START_DENIED`" in normalized
    assert "`[not-started] tiktok-111`" in normalized
