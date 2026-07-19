from pathlib import Path


QUEUE = Path(__file__).resolve().parents[1] / "handoff" / "QUEUE.md"
PROPOSAL_HEADING = (
    "- **P-C2 (Lane C, SG-5, 2026-07-19) · "
    "warning-only caption-evidence calibration.**"
)


def test_p_c2_keeps_ocr_quality_work_calibration_first_and_warning_only():
    queue = QUEUE.read_text(encoding="utf-8")

    assert PROPOSAL_HEADING in queue
    proposal = queue.split(PROPOSAL_HEADING, 1)[1].split("\n- **", 1)[0]
    normalized = " ".join(proposal.split())

    assert "**Proposal:**" in proposal
    assert "**Refutation:**" in proposal
    assert "**Survives as:**" in proposal
    assert "S5-SWEEP-LANE-A.md" in normalized
    assert "60 events" in normalized
    assert "median confidence 0.88" in normalized
    assert "0.77–0.93" in normalized
    assert "1,882 events" in normalized
    assert "no production filter" in normalized
    assert "no schema request" in normalized
    assert "warning-only" in normalized
