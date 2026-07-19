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
RUNTIME_SCAN_HEADING = (
    "## SG-4 render-runtime scan \u00b7 2026-07-19 \u00b7 Lane C"
)
RUNTIME_REPOSITORIES = (
    "https://github.com/Hao0321/video-autopilot-kit",
    "https://github.com/slhck/ffmpeg-progress-yield",
    "https://github.com/imageio/imageio-ffmpeg",
    "https://github.com/abus-aikorea/voice-pro",
)
EDIT_STATE_SCAN_HEADING = (
    "## SG-4 edit-state and reframing scan \u00b7 2026-07-19 \u00b7 Lane C"
)
EDIT_STATE_REPOSITORIES = (
    "https://github.com/khubaib-ctrl/TurnAround",
    "https://github.com/panoramix360/edity",
    "https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator",
    "https://github.com/Robelob/Ambar-AI-Video-Editor-Plugin-For-Premiere-Pro",
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


def test_lane_c_sg4_render_runtime_scan_has_current_unique_records():
    prior_art = PRIOR_ART.read_text(encoding="utf-8")

    assert RUNTIME_SCAN_HEADING in prior_art
    scan = prior_art.split(RUNTIME_SCAN_HEADING, 1)[1].split("\n---", 1)[0]

    for repository in RUNTIME_REPOSITORIES:
        assert prior_art.count(repository) == 1

    expected = len(RUNTIME_REPOSITORIES)
    assert scan.count("- **License:**") == expected
    assert scan.count("**Health:**") == expected
    assert scan.count("- **Verdict:") == expected
    assert scan.lower().count("pushed") >= expected
    assert scan.lower().count("release") >= expected
    assert scan.lower().count("contributor") >= expected


def test_lane_c_sg4_edit_state_scan_has_current_unique_records():
    prior_art = PRIOR_ART.read_text(encoding="utf-8")

    assert EDIT_STATE_SCAN_HEADING in prior_art
    scan = prior_art.split(EDIT_STATE_SCAN_HEADING, 1)[1].split("\n---", 1)[0]

    for repository in EDIT_STATE_REPOSITORIES:
        assert prior_art.count(repository) == 1

    expected = len(EDIT_STATE_REPOSITORIES)
    assert scan.count("- **License:**") == expected
    assert scan.count("**Health:**") == expected
    assert scan.count("- **Verdict:") == expected
    assert scan.lower().count("pushed") >= expected
    assert scan.lower().count("release") >= expected
    assert scan.lower().count("contributor") >= expected
