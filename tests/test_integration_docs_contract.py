from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONNECT = ROOT / "docs" / "CONNECT.md"
AUDIT = ROOT / "handoff" / "reviews" / "CX-4-INTEGRATION-DOCS-QA.md"


def test_zing_connect_uses_ratified_credential_and_peer_language() -> None:
    text = CONNECT.read_text(encoding="utf-8")

    for stale_claim in (
        "next to its server.py",
        'installed but no token → "unconfig"',
        "if the file is gone, zing refetches",
    ):
        assert stale_claim not in text

    for required_claim in (
        "`unconfigured`",
        r"%LOCALAPPDATA%\Uoink\token.txt",
        "~/Library/Application Support/Uoink/token.txt",
        "Zing never reads Uoink's token file",
        "HTTP(S) source URL",
    ):
        assert required_claim in text


def test_cx4_audit_covers_every_ratified_integration_boundary() -> None:
    text = AUDIT.read_text(encoding="utf-8")

    for required_claim in (
        "Direct MCP registration",
        "Discovery and runtime leases",
        "Credential custody",
        "Peer states",
        "Stable references",
        "Kept-media handoff",
        "Writer shot-list handoff",
        "Engagement accounting",
        "SUITE-CONNECT.md",
        "S6-INTEGRATION.md",
        "Routed code gaps",
    ):
        assert required_claim in text
