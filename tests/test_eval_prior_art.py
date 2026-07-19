from pathlib import Path


PRIOR_ART = (
    Path(__file__).resolve().parents[1] / "handoff" / "research" / "PRIOR-ART-OSS.md"
)
SCAN_HEADING = "## SG-4 creator-pipeline scan · 2026-07-19 · Lane C"
EXPECTED_REPOSITORIES = (
    "https://github.com/remyxai/FFMPerative",
    "https://github.com/YaoFANGUK/video-subtitle-extractor",
    "https://github.com/zhouxiaoka/autoclip",
    "https://github.com/walterlow/freecut",
)
WORKFLOW_SCAN_HEADING = "## SG-4 editorial-workflow scan · 2026-07-19 · Lane C"
WORKFLOW_REPOSITORIES = (
    "https://github.com/GuanYixuan/pyJianYingDraft",
    "https://github.com/ThioJoe/Auto-Synced-Translated-Dubs",
    "https://github.com/abhiTronix/vidgear",
    "https://github.com/EmiGross/ClaudeCut",
    "https://github.com/qwertyboy0325/vox-proof",
)


def test_lane_c_sg4_scan_records_license_health_and_verdict_per_repository():
    prior_art = PRIOR_ART.read_text(encoding="utf-8")

    assert SCAN_HEADING in prior_art
    scan = prior_art.split(SCAN_HEADING, 1)[1].split("\n---", 1)[0]

    for repository in EXPECTED_REPOSITORIES:
        assert repository in scan

    assert scan.count("- **License:**") == len(EXPECTED_REPOSITORIES)
    assert scan.count("**Health:**") == len(EXPECTED_REPOSITORIES)
    assert scan.count("- **Verdict:") == len(EXPECTED_REPOSITORIES)


def test_lane_c_sg4_editorial_workflow_scan_has_complete_repo_records():
    prior_art = PRIOR_ART.read_text(encoding="utf-8")

    assert WORKFLOW_SCAN_HEADING in prior_art
    scan = prior_art.split(WORKFLOW_SCAN_HEADING, 1)[1].split("\n---", 1)[0]

    for repository in WORKFLOW_REPOSITORIES:
        assert repository in scan

    assert scan.count("- **License:**") == len(WORKFLOW_REPOSITORIES)
    assert scan.count("**Health:**") == len(WORKFLOW_REPOSITORIES)
    assert scan.count("- **Verdict:") == len(WORKFLOW_REPOSITORIES)
