from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "handoff" / "reviews" / "CX-5-LAUNCH-DRY-RUN-INDEX.md"


def test_cx5_indexes_one_bounded_launch_rehearsal_packet() -> None:
    text = INDEX.read_text(encoding="utf-8")

    for required in (
        "LAUNCH-DRY-RUN.md",
        "Uoink-Setup-3.7.0.exe",
        "uoink-3.7.0.mcpb",
        "myzing-0.1.0",
        "ryan_writer-0.1.0.dev0",
        "clean-host",
        "MCP surface",
        "Official MCP Registry",
        "Anthropic Connectors Directory",
        "Smithery",
        "Ryan-only actions",
        "SHA-256",
    ):
        assert required in text

    for forbidden in (
        "READY TO PUBLISH",
        "submitted successfully",
        "published successfully",
        "release is live",
    ):
        assert forbidden not in text


def test_cx5_keeps_every_external_action_unauthorized() -> None:
    text = INDEX.read_text(encoding="utf-8")

    for action in (
        "publish",
        "release",
        "submit",
        "post",
        "deliver",
        "purchase",
        "spend",
    ):
        assert f"`{action}`: **not performed**" in text
