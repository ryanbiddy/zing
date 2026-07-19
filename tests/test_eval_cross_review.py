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
RECENT_REVIEW_MARKER = (
    "- **2026-07-19 (Lane C, SG-1 cross-review complete — "
    "PRs #197, #195, #193):**"
)
CURRENT_REVIEW_MARKER = (
    "- **2026-07-19 (Lane C, SG-1 cross-review complete \u2014 "
    "PRs #210, #208, #206):**"
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


def test_sg1_review_checks_fetch_install_and_status_cost_claims():
    notes = LANE_NOTES.read_text(encoding="utf-8")

    assert RECENT_REVIEW_MARKER in notes
    review = notes.split(RECENT_REVIEW_MARKER, 1)[1].split(
        "\n- **2026-07-19 (Lane C, PROCESS OBSERVATION SG-1):**", 1
    )[0]
    normalized = " ".join(review.split())

    for pr in ("#197", "#195", "#193"):
        assert pr in normalized
    assert "reviewed the actual diffs" in normalized
    assert "docs/FETCH-TROUBLESHOOTING.md:10-33" in normalized
    assert "pyproject.toml:16-18" in normalized
    assert "src/myzing/doctor.py:136-203" in normalized
    assert "`yt_dlp_ejs=False`" in normalized
    assert "`n challenge solving failed`" in normalized
    assert "`yt-dlp[default]`" in normalized
    assert "`h_zing_status()`" in normalized
    assert "0.288–0.379s" in normalized
    assert "median 0.302s" in normalized
    assert "68s" in normalized
    assert "1920×1080" in normalized
    assert "5,380,884" in normalized


def test_sg1_review_checks_readiness_side_effects_and_vacuous_provenance():
    notes = LANE_NOTES.read_text(encoding="utf-8")

    assert CURRENT_REVIEW_MARKER in notes
    review = notes.split(CURRENT_REVIEW_MARKER, 1)[1].split(
        "\n- **2026-07-19 (Lane C, PROCESS OBSERVATION SG-1):**", 1
    )[0]
    normalized = " ".join(review.split())

    for pr in ("#210", "#208", "#206"):
        assert pr in normalized
    assert "reviewed the actual diffs" in normalized
    assert "src/myzing/doctor.py:166-257,448-464" in normalized
    assert "`ok=True`" in normalized
    assert "`Verdict: fully ready`" in normalized
    assert "`WILL fail`" in normalized
    assert "src/myzing/tts_providers.py:99-129" in normalized
    assert "`.mp3`" in normalized
    assert "`network_calls=1`" in normalized
    assert "before `urlopen`" in normalized
    assert "handoff/QUEUE.md:63-84" in normalized
    assert "`zing_version`" in normalized
    assert "`measured_at`" in normalized
    assert "vacuous" in normalized
