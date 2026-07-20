from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "handoff" / "reviews" / "CX-6-AG-RESEARCH-AUDIT-INDEX.md"


def test_cx6_indexes_every_assigned_dossier_with_an_exact_verdict() -> None:
    text = INDEX.read_text(encoding="utf-8")

    expected = {
        "dr-1-competitive-design.md": "THIN-REDO",
        "dr-2-umbrella-brand.md": "FABRICATED",
        "dr-3-local-first-ux.md": "FABRICATED",
        "dr-4-growth-strategy.md": "FABRICATED",
        "dr-5-brand-audit.md": "THIN-REDO",
        "dr-6-mac-dossier.md": "THIN-REDO",
        "dr-7-pmf-dossier.md": "FABRICATED",
        "BR-1-branding-canon.md": "THIN-REDO",
    }
    for dossier, verdict in expected.items():
        assert f"`{dossier}` | **{verdict}**" in text

    assert "BR-3" in text
    assert "BR-4" in text
    assert "excluded" in text.lower()


def test_cx6_preserves_fetch_evidence_and_routes_every_gap() -> None:
    text = INDEX.read_text(encoding="utf-8")

    for required in (
        "26",
        "primary",
        "ag-research-audit.md",
        "32BFA6D8F791A1073788B4FD83F26E1E0D44C1145E3F366B90FC969E8C75D65B",
        "Ryan-visible gaps",
        "DECISION-WEEK-PACKET.md",
        "7756DF34F8E8D1B27B0DF9A4507EBADD39E951E286308DE81FB0EF5B31C1CAAD",
    ):
        assert required in text

    for action in (
        "publish",
        "post",
        "submit",
        "purchase",
        "spend",
    ):
        assert f"`{action}`: **not performed**" in text
