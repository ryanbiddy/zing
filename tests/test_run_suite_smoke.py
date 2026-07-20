"""Unit gates for the three-product family-smoke launcher."""

from __future__ import annotations

import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.eval import run_suite_smoke as smoke
from tools.eval.suite_contracts import load_fixture_case


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def test_port_probe_refuses_a_reusable_bound_listener() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()

        assert smoke._port_available(listener.getsockname()[1]) is False
    finally:
        listener.close()


def test_recorded_revision_refuses_uncommitted_runtime_source(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Suite Smoke")
    _git(repo, "config", "user.email", "suite-smoke@example.test")
    tracked = repo / "service.py"
    tracked.write_text("VERSION = 1\n", encoding="utf-8")
    _git(repo, "add", "service.py")
    _git(repo, "commit", "-q", "-m", "fixture")

    revision = smoke._git_revision(repo)
    assert len(revision) == 40

    tracked.write_text("VERSION = 2\n", encoding="utf-8")
    with pytest.raises(smoke.SmokeError) as tracked_failure:
        smoke._git_revision(repo)
    assert tracked_failure.value.code == "source_worktree_dirty"

    tracked.write_text("VERSION = 1\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "untracked.py").write_text(
        "RUNTIME = True\n", encoding="utf-8")
    with pytest.raises(smoke.SmokeError) as untracked_failure:
        smoke._git_revision(repo)
    assert untracked_failure.value.code == "source_worktree_dirty"


@pytest.mark.ffmpeg
def test_generated_fixture_uses_an_exact_render_preset(
    tmp_path: Path,
) -> None:
    from myzing.render.validation import output_preset

    video = tmp_path / "fixture.mp4"
    smoke._generate_fixture_video(video)
    probed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(probed.stdout)["streams"][0]

    assert (stream["width"], stream["height"]) == (360, 640)
    assert output_preset(stream["width"], stream["height"]) == "vertical"


def test_step_ledger_duration_matches_serialized_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter((
        datetime(2026, 7, 19, 12, 0, 0, 900, tzinfo=timezone.utc),
        datetime(2026, 7, 19, 12, 0, 0, 1100, tzinfo=timezone.utc),
    ))
    monkeypatch.setattr(smoke, "_utc_now", lambda: next(moments))
    ledger = smoke.StepLedger()

    with ledger.step("probe"):
        pass

    assert ledger.steps == [{
        "id": "probe",
        "started_at": "2026-07-19T12:00:00.000Z",
        "ended_at": "2026-07-19T12:00:00.001Z",
        "duration_seconds": 0.001,
        "passed": True,
    }]


def test_zing_engagement_requires_a_product_owned_receipt() -> None:
    with pytest.raises(
        smoke.SmokeError,
        match="required opened-event receipt",
    ) as failure:
        smoke._zing_engagement(
            {"ok": True, "slug": "suite-smoke"},
            {"provenance": {"source_handoff": {"refetch": False}}},
        )

    assert failure.value.code == "zing_opened_event_missing"


@pytest.mark.parametrize("state", ["accepted", "spooled", "rejected"])
def test_zing_engagement_accepts_contract_terminal_states(
    state: str,
) -> None:
    assert smoke._zing_engagement(
        {
            "engagement": {
                "event_id": "zing-opened-suite-smoke",
                "state": state,
            },
        },
        {},
    ) == ("zing-opened-suite-smoke", state)


def test_peer_contract_is_found_and_validated_after_stop() -> None:
    peer = load_fixture_case("peer_absent")["payload"]
    nested = {"status": {"peers": [{"uoink": peer}]}}

    found = smoke._find_peer_contract(nested)

    assert found == peer
    assert smoke._validate_peer_after_stop(found, "zing") == "absent"


def test_zing_peer_stop_waits_through_cached_available_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter((
        load_fixture_case("peer_available")["payload"],
        load_fixture_case("peer_absent")["payload"],
    ))

    class FakeClient:
        def call(self, tool: str) -> dict:
            assert tool == "zing_status"
            return {"ok": True, "environment": {"peer": next(responses)}}

    monkeypatch.setattr(smoke, "POLL_INTERVAL", 0)

    assert smoke._wait_zing_peer_after_stop(FakeClient()) == "absent"


def test_initial_peer_must_be_formal_and_available() -> None:
    peer = load_fixture_case("peer_available")["payload"]
    smoke._require_initial_peer({"suite": {"peer": peer}}, "zing")

    with pytest.raises(smoke.SmokeError) as failure:
        smoke._require_initial_peer(
            {"suite": {"uoink": {"reachable": True}}},
            "zing",
        )

    assert failure.value.code == "zing_peer_probe_missing"


def test_safe_environment_removes_provider_credentials_and_forces_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in smoke.FORBIDDEN_PROVIDER_ENV:
        monkeypatch.setenv(name, "must-not-cross")

    env = smoke._safe_base_env(tmp_path)

    assert not set(smoke.FORBIDDEN_PROVIDER_ENV) & set(env)
    assert env["LOCALAPPDATA"] == str(tmp_path)
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"


@pytest.mark.parametrize(
    ("platform_name", "expected"),
    [
        ("win32", Path("RyanSuite/services.d")),
        (
            "darwin",
            Path("home/Library/Application Support/RyanSuite/services.d"),
        ),
        ("linux", Path("xdg-state/ryan-suite/services.d")),
    ],
)
def test_runtime_registry_path_matches_the_product_contract(
    tmp_path: Path,
    platform_name: str,
    expected: Path,
) -> None:
    env = smoke._safe_base_env(tmp_path)

    assert smoke._runtime_registry_dir(
        env,
        platform_name=platform_name,
    ) == tmp_path / expected


@pytest.mark.parametrize(
    ("platform_name", "expected"),
    [
        ("win32", Path("Uoink")),
        (
            "darwin",
            Path("home/Library/Application Support/Uoink"),
        ),
        ("linux", Path("xdg-data/Uoink")),
    ],
)
def test_uoink_data_path_matches_the_product_contract(
    tmp_path: Path,
    platform_name: str,
    expected: Path,
) -> None:
    env = smoke._safe_base_env(tmp_path)

    assert smoke._uoink_data_dir(
        env,
        platform_name=platform_name,
    ) == tmp_path / expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("C:\\Users\\Ryan\\clip.mp4", True),
        ("D:/suite/private.json", True),
        ("/home/ryan/clip.mp4", True),
        ("writer://script/17", False),
        ("uoink://item/source-1", False),
        ("A relative/path.md", False),
    ],
)
def test_absolute_path_detection(value: str, expected: bool) -> None:
    assert smoke._has_absolute_path(value) is expected


def test_real_capture_cli_fails_before_start_without_source_url(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "record.json"

    exit_code = smoke.main([
        "--mode",
        "real_capture",
        "--uoink-repo",
        str(tmp_path / "uoink"),
        "--writer-repo",
        str(tmp_path / "writer"),
        "--zing-repo",
        str(tmp_path / "zing"),
        "--output",
        str(output),
    ])

    assert exit_code == 1
    assert not output.exists()
    failure = json.loads(capsys.readouterr().err)
    assert failure == {
        "ok": False,
        "failure_code": "source_url_required",
        "error": (
            "real_capture requires an explicit supported short-video URL"
        ),
    }


def test_atomic_record_write_round_trips(
    tmp_path: Path,
) -> None:
    output = tmp_path / "nested" / "record.json"
    record = {"record_contract": "zing.suite-smoke", "version": 1}

    smoke._write_record(output, record)

    assert json.loads(output.read_text(encoding="utf-8")) == record
    assert list(output.parent.glob("*.tmp")) == []


def test_launcher_assertion_set_matches_independent_evaluator() -> None:
    record = load_fixture_case("suite_smoke_pass")["payload"]

    assert list(smoke.RECORDED_ASSERTIONS) == [
        assertion["id"] for assertion in record["assertions"]
    ]
