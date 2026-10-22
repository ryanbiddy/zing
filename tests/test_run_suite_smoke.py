"""Unit gates for the three-product family-smoke launcher."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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
    assert smoke._git_revision(repo, allow_dirty=True) == revision
    changed_hash = smoke._working_tree_sha256(repo)

    tracked.write_text("VERSION = 1\n", encoding="utf-8")
    assert smoke._working_tree_sha256(repo) != changed_hash
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


def test_fixture_seed_uses_uoink_platform_data_root(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "uoink"
    repo.mkdir()
    observed = tmp_path / "observed-root.txt"
    product_data = tmp_path / "product-data"
    (repo / "uoink_install_isolation.py").write_text(
        "def apply_from_process(): pass\n"
        "def data_root(path): return path\n", encoding="utf-8",
    )
    (repo / "_platform.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "def user_data_dir():\n"
        "    return Path(os.environ['UOINK_TEST_DATA_ROOT'])\n",
        encoding="utf-8",
    )
    (repo / "index.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "class Index:\n"
        "    @classmethod\n"
        "    def open(cls, path):\n"
        "        Path(os.environ['SUITE_SMOKE_OBSERVED_ROOT']).write_text(\n"
        "            str(path), encoding='utf-8')\n"
        "        return cls()\n"
        "    def upsert_yoink(self, record, content):\n"
        "        pass\n"
        "    def close(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "fixture.mp4"
    fixture.write_bytes(b"fixture")
    env = smoke._safe_base_env(tmp_path / "isolated")
    env.update({
        "UOINK_TEST_DATA_ROOT": str(product_data),
        "SUITE_SMOKE_OBSERVED_ROOT": str(observed),
    })

    smoke._seed_uoink_fixture(
        python=sys.executable,
        uoink_repo=repo,
        env=env,
        output_root=tmp_path / "output",
        fixture_media=fixture,
    )

    assert observed.read_text(encoding="utf-8") == str(
        product_data / "index.db"
    )


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


def test_mcp_initialize_preserves_product_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        "initialize": {
            "serverInfo": {"name": "zing", "version": "0.1.0"},
        },
        "tools/list": {"tools": [{"name": "zing_status"}]},
    }

    def request(
        _client,
        method: str,
        _params: dict | None = None,
        *,
        notification: bool = False,
        timeout: float = smoke.MCP_TIMEOUT,
    ) -> dict | None:
        del timeout
        if notification:
            assert method == "notifications/initialized"
            return None
        return responses[method]

    client = object.__new__(smoke.StdioMCPClient)
    monkeypatch.setattr(smoke.StdioMCPClient, "request", request)

    assert client.initialize() == ("zing", "0.1.0", ["zing_status"])


def test_mcp_initialize_rejects_sdk_version_drift() -> None:
    with pytest.raises(smoke.SmokeError) as failure:
        smoke._validate_mcp_initialize(
            "writer",
            expected_version="0.1.0",
            identity="writer",
            version="1.28.1",
            tool_names=["writer_status"],
        )

    assert failure.value.code == "mcp_version_drift"


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
    for name in ("UOINK_URL", "UOINK_TOKEN", "UOINK_ISOLATED_PROFILE", "WRITER_UOINK_URL"):
        monkeypatch.setenv(name, "must-not-cross")

    env = smoke._safe_base_env(tmp_path)

    assert not set(smoke.FORBIDDEN_PROVIDER_ENV) & set(env)
    assert not any(name.startswith(("UOINK_", "WRITER_")) for name in env)
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
    ("value", "expected"),
    [
        ("C:\\Users\\ExampleUser\\clip.mp4", True),
        ("D:/suite/private.json", True),
        ("/home/example/clip.mp4", True),
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


@pytest.mark.parametrize("isolated_ports", [False, True])
@pytest.mark.parametrize("separate_runtimes", [False, True])
def test_peer_launch_seed_and_doctor_use_selected_runtime_and_ports(
    tmp_path, monkeypatch, isolated_ports, separate_runtimes,
):
    """Drive through discovery to seeding with no sockets or real processes."""
    repos = {name: tmp_path / name for name in ("uoink", "writer", "zing")}
    for product, marker in (("uoink", "server.py"), ("writer", "src/writer/cli.py"),
                            ("zing", "src/myzing/cli.py"), ("uoink", "uoink_install_isolation.py")):
        path = repos[product] / marker
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    work = tmp_path / "work"
    media = tmp_path / "fixture.mp4"
    media.write_bytes(b"fake-media")
    starts, mcps, doctors, ports, urls, seeds = {}, {}, [], [], [], []
    expected = {name: name + "-python" if separate_runtimes else "zing-python" for name in repos}

    class FakeProcess:
        process = SimpleNamespace(pid=12345, poll=lambda: 0)

        def stop(self):
            pass

    def start(name, command, *, cwd, env):
        starts[name] = (command, env)
        if name == "uoink":
            root = Path(env["UOINK_ISOLATED_PROFILE"]) if isolated_ports else cwd
            (root / "token.txt").write_text("fake-token", encoding="utf-8")
        return FakeProcess()

    class FakeClient(FakeProcess):
        def __init__(self, name, command, **kwargs):
            self.name = name
            mcps[name] = command

        def initialize(self):
            return self.name, "1.0", []

        def call(self, *args):
            return {"ok": True}

        def close(self):
            pass

    def seed(**kwargs):
        seeds.append(kwargs)
        raise smoke.SmokeError("test_stop", "stop after recording seed interpreter")

    monkeypatch.setattr(smoke.ManagedProcess, "start", start)
    monkeypatch.setattr(smoke, "StdioMCPClient", FakeClient)
    monkeypatch.setattr(smoke, "_port_available", lambda port: ports.append(port) or True)
    monkeypatch.setattr(smoke, "_wait_http", lambda url, process: urls.append(url))
    monkeypatch.setattr(smoke, "_git_revision", lambda *a, **k: "a" * 40)
    monkeypatch.setattr(smoke, "_product_versions", lambda *a: dict.fromkeys(repos, "1.0"))
    monkeypatch.setattr(smoke, "_read_json_file", lambda *a, **k: {})
    monkeypatch.setattr(smoke, "_json_request", lambda *a, **k: (200, {"ok": True}))
    monkeypatch.setattr(smoke, "_validate_contract", lambda *a, **k: None)
    monkeypatch.setattr(smoke, "_validate_mcp_initialize", lambda *a, **k: None)
    monkeypatch.setattr(smoke, "_require_initial_peer", lambda *a: None)
    monkeypatch.setattr(smoke, "_run_writer_doctor", lambda executable, *a: doctors.append(executable) or {})
    monkeypatch.setattr(smoke, "_seed_uoink_fixture", seed)
    kwargs = {"uoink_python": expected["uoink"], "writer_python": expected["writer"]} if separate_runtimes else {}
    with pytest.raises(smoke.SmokeError, match="stop after recording"):
        smoke.run_suite_smoke(mode="deterministic_ci", uoink_repo=repos["uoink"],
                              writer_repo=repos["writer"], zing_repo=repos["zing"],
                              work_root=work, fixture_video=media, python="zing-python",
                              isolated_ports=isolated_ports, **kwargs)
    assert ports == ([15179, 15181] if isolated_ports else [5179, 5181])
    assert urls == [f"http://127.0.0.1:{port}/ping" for port in ports]
    for name in ("uoink", "writer"):
        assert starts[name][0][0] == expected[name]
    for name in repos:
        assert mcps[name][0] == expected[name]
    assert doctors == [expected["writer"]]
    assert seeds[0]["python"] == expected["uoink"]
    assert ("UOINK_ISOLATED_PROFILE" in starts["uoink"][1]) is isolated_ports
    assert starts["writer"][1]["WRITER_UOINK_URL"] == urls[0].removesuffix("/ping")


def test_cli_forwards_peer_runtimes_and_local_port_opt_in(tmp_path, monkeypatch):
    observed = {}

    def run(**kwargs):
        observed.update(kwargs)
        return {"record_contract": "zing.suite-smoke", "version": 1, "mode": "deterministic_ci"}

    monkeypatch.setattr(smoke, "run_suite_smoke", run)
    args = ["--uoink-repo", str(tmp_path), "--writer-repo", str(tmp_path),
            "--zing-repo", str(tmp_path), "--output", str(tmp_path / "record.json"),
            "--work-dir", str(tmp_path / "work"), "--python", "zing-python"]
    assert smoke.main(args) == 0
    assert observed["isolated_ports"] is False
    assert observed["uoink_python"] is None and observed["writer_python"] is None
    assert smoke.main(args + ["--isolated-ports", "--uoink-python", "uoink-python",
                             "--writer-python", "writer-python"]) == 0
    assert observed["isolated_ports"] is True
    assert observed["uoink_python"] == "uoink-python"
    assert observed["writer_python"] == "writer-python"


def test_windows_venv_redirector_is_refused_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(smoke, "sys", SimpleNamespace(prefix="venv", base_prefix="base", executable="venv-python"))
    with pytest.raises(smoke.SmokeError) as failure:
        smoke.run_suite_smoke(mode="deterministic_ci", uoink_repo=tmp_path,
                              writer_repo=tmp_path, zing_repo=tmp_path, work_root=tmp_path,
                              python="venv-python")
    assert failure.value.code == "windows_venv_launcher"
