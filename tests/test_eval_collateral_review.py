from pathlib import Path


REVIEW = (
    Path(__file__).resolve().parents[1]
    / "handoff"
    / "reviews"
    / "CX-1-COLLATERAL-lane-c.md"
)


def test_cx1_collateral_review_covers_every_assigned_surface_and_routes_findings():
    review = REVIEW.read_text(encoding="utf-8")

    for surface in (
        "Uoink README",
        "Zing README",
        "Writer README",
        "SUITE-CONNECT.md",
        "Uoink site",
        "store-listing drafts",
        "v3.7.0 draft release notes",
    ):
        assert surface in review

    for section in (
        "## Verdict",
        "## P1",
        "## P2",
        "## P3",
        "## What held up",
        "## Routing",
        "## Re-review of overnight fixes",
    ):
        assert section in review

    for finding in (
        "CX1-P1-1",
        "CX1-P1-2",
        "CX1-P1-3",
        "CX1-P2-1",
        "CX1-P2-2",
        "CX1-P2-3",
    ):
        assert finding in review

    normalized = " ".join(review.split())
    assert "latest published release is v3.4.0" in normalized
    assert "Uoink-Setup-3.6.0.exe" in normalized
    assert "nothing to configure" in normalized
    assert "again automatic, no wiring" in normalized
    assert "UOINK_TOKEN" in normalized
    assert "WRITER_UOINK_TOKEN" in normalized
    assert "myzing" in normalized
    assert "PyPI" in normalized
    assert "No API keys, no cloud" in normalized
    assert "ElevenLabs" in normalized
    assert "Nothing leaves your machine" in normalized
    assert "Anthropic" in normalized
    assert "not published" in normalized
