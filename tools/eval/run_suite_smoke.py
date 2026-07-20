"""Run the Sprint 6 family scenario against three real product processes.

This is a developer gate, not a suite daemon. It starts Uoink and Writer on
their shipped loopback ports, connects directly to the Uoink, Writer, and
Zing stdio MCP servers, drives the ratified handoffs, writes one path-free
record, and stops every process it started.

Two modes share the same clients and assertions:

* ``deterministic_ci`` generates or accepts a local fixture video and seeds
  one isolated Uoink corpus item through Uoink's own index module.
* ``real_capture`` calls Uoink's real capture endpoint for a user-supplied
  supported short-video URL.

The runner never posts, publishes, invokes a delivery surface, calls an AI
provider, or permits a model download. It fails if ports 5179 or 5181 are
already occupied; it never kills a process it did not start.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from tools.eval.suite_contracts import validate_contract_payload
from tools.eval.suite_smoke import evaluate_suite_record


UOINK_URL = "http://127.0.0.1:5179"
WRITER_URL = "http://127.0.0.1:5181"
MCP_PROTOCOL_VERSION = "2024-11-05"
PROCESS_START_TIMEOUT = 45.0
MCP_TIMEOUT = 90.0
STUDY_TIMEOUT = 20 * 60.0
RENDER_TIMEOUT = 10 * 60.0
POLL_INTERVAL = 1.0
PEER_STOP_TIMEOUT = 75.0
FORBIDDEN_PROVIDER_ENV = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "ELEVENLABS_API_KEY",
    "GROQ_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
)
REQUIRED_MCP_TOOLS = {
    "uoink": set(),
    "writer": {
        "prepare_script",
        "save_script",
        "critique_script",
        "derive_shot_list",
        "export_shot_list",
        "scan_voice",
        "writer_status",
    },
    "zing": {
        "study_uoink_item",
        "get_breakdown",
        "build_profile",
        "save_judgment",
        "import_shot_list",
        "render_edl",
        "get_render",
        "zing_status",
        "list_breakdowns",
    },
}
CONTRACTS = {
    "runtime_lease": "ryan.suite.runtime-lease/1",
    "service_manifest": "ryan.suite.service/1",
    "health": "ryan.suite.health/1",
    "peer": "ryan.suite.peer/1",
    "media_handoff": "uoink.media.handoff/1",
    "corpus_read": "uoink.corpus.read/1",
    "shot_list": "writer.shot-list/1",
    "shot_list_import": "zing.shot-list.import/1",
    "engagement": "uoink.engagement.ingest/1",
}
RECORDED_ASSERTIONS = (
    "leases_exact",
    "manifests_exact",
    "health_exact",
    "mcp_direct",
    "kept_media_verified",
    "zero_refetch",
    "same_uoink_source",
    "writer_file_only",
    "import_path_free",
    "measured_spans_only",
    "engagement_visible",
    "peer_stop_fail_calm",
)


class SmokeError(RuntimeError):
    """A named family-gate failure safe to print without local paths."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc3339(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    revision = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SmokeError(
            "source_revision_unavailable",
            f"could not read a Git revision for {repo.name}",
        )
    for command in (
        ["git", "diff", "--quiet", "HEAD", "--"],
        ["git", "diff", "--cached", "--quiet", "HEAD", "--"],
    ):
        clean = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            check=False,
        )
        if clean.returncode == 1:
            raise SmokeError(
                "source_worktree_dirty",
                f"{repo.name} has tracked changes outside revision "
                f"{revision[:12]}",
            )
        if clean.returncode != 0:
            raise SmokeError(
                "source_revision_unavailable",
                f"could not verify the Git tree for {repo.name}",
            )
    untracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if untracked.returncode:
        raise SmokeError(
            "source_revision_unavailable",
            f"could not inspect untracked files for {repo.name}",
        )
    runtime_untracked = [
        path
        for path in untracked.stdout.splitlines()
        if (
            path.endswith(".py")
            or path.startswith(("src/", "tools/", "migrations/"))
            or path in {"pyproject.toml", "VERSION"}
        )
    ]
    if runtime_untracked:
        raise SmokeError(
            "source_worktree_dirty",
            f"{repo.name} has untracked runtime source outside revision "
            f"{revision[:12]}",
        )
    return revision


def _read_version(path: Path, pattern: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise SmokeError(
            "source_version_unavailable",
            f"could not read the version from {path.name}",
        )
    return match.group(1)


def _product_versions(
    uoink_repo: Path,
    writer_repo: Path,
    zing_repo: Path,
) -> dict[str, str]:
    return {
        "uoink": (uoink_repo / "VERSION").read_text(
            encoding="utf-8").strip(),
        "writer": _read_version(
            writer_repo / "src" / "writer" / "__init__.py",
            r'^__version__\s*=\s*"([^"]+)"',
        ),
        "zing": _read_version(
            zing_repo / "src" / "myzing" / "__init__.py",
            r'^__version__\s*=\s*"([^"]+)"',
        ),
    }


@dataclass
class StepLedger:
    steps: list[dict[str, Any]] = field(default_factory=list)

    @contextlib.contextmanager
    def step(self, step_id: str) -> Iterator[None]:
        started = _utc_now()
        passed = False
        try:
            yield
            passed = True
        finally:
            ended = _utc_now()
            started_at = _rfc3339(started)
            ended_at = _rfc3339(ended)
            serialized_started = datetime.fromisoformat(
                started_at.replace("Z", "+00:00"))
            serialized_ended = datetime.fromisoformat(
                ended_at.replace("Z", "+00:00"))
            self.steps.append({
                "id": step_id,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_seconds": round(
                    (
                        serialized_ended - serialized_started
                    ).total_seconds(),
                    3,
                ),
                "passed": passed,
            })


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    stderr_lines: list[str] = field(default_factory=list)
    stdout_lines: list[str] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        name: str,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> "ManagedProcess":
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt" else 0
            ),
        )
        managed = cls(name=name, process=process)
        assert process.stdout is not None
        assert process.stderr is not None
        threading.Thread(
            target=managed._pump,
            args=(process.stdout, managed.stdout_lines),
            daemon=True,
        ).start()
        threading.Thread(
            target=managed._pump,
            args=(process.stderr, managed.stderr_lines),
            daemon=True,
        ).start()
        return managed

    @staticmethod
    def _pump(stream, destination: list[str]) -> None:
        for line in stream:
            destination.append(line)
            del destination[:-200]

    def stop(self, timeout: float = 15.0) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=timeout)


class StdioMCPClient:
    """Small one-request-at-a-time JSON-RPC client for direct stdio MCP."""

    def __init__(
        self,
        name: str,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ):
        self.name = name
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt" else 0
            ),
        )
        self._next_id = 0
        self._lines: queue.Queue[str] = queue.Queue()
        self._stderr: list[str] = []
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        threading.Thread(
            target=self._pump_stdout, daemon=True).start()
        threading.Thread(
            target=self._pump_stderr, daemon=True).start()

    def _pump_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._lines.put(line)

    def _pump_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self._stderr.append(line)
            del self._stderr[:-100]

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        notification: bool = False,
        timeout: float = MCP_TIMEOUT,
    ) -> dict[str, Any] | None:
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params
        wanted = None
        if not notification:
            self._next_id += 1
            wanted = self._next_id
            message["id"] = wanted
        if self.process.poll() is not None:
            raise SmokeError(
                "mcp_process_exited",
                f"{self.name} MCP exited before {method}",
            )
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        if notification:
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self._lines.get(timeout=0.25)
            except queue.Empty:
                if self.process.poll() is not None:
                    break
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                raise SmokeError(
                    "mcp_non_json",
                    f"{self.name} MCP wrote non-JSON protocol output",
                ) from None
            if response.get("id") != wanted:
                continue
            if "error" in response:
                error = response["error"]
                raise SmokeError(
                    "mcp_protocol_error",
                    f"{self.name} MCP rejected {method}: "
                    f"{error.get('message', 'unknown error')}",
                )
            result = response.get("result")
            if not isinstance(result, dict):
                raise SmokeError(
                    "mcp_result_invalid",
                    f"{self.name} MCP returned a non-object result",
                )
            return result
        raise SmokeError(
            "mcp_timeout",
            f"{self.name} MCP did not answer {method} in time",
        )

    def initialize(self) -> tuple[str, list[str]]:
        result = self.request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "ryan-suite-smoke",
                "version": "1",
            },
        })
        assert result is not None
        info = result.get("serverInfo")
        identity = str(info.get("name") if isinstance(info, dict) else "")
        self.request(
            "notifications/initialized",
            {},
            notification=True,
        )
        listed = self.request("tools/list", {})
        assert listed is not None
        tools = listed.get("tools")
        names = [
            str(tool.get("name"))
            for tool in tools or []
            if isinstance(tool, dict)
        ]
        return identity, names

    def call(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float = MCP_TIMEOUT,
    ) -> dict[str, Any]:
        result = self.request(
            "tools/call",
            {"name": tool, "arguments": arguments or {}},
            timeout=timeout,
        )
        assert result is not None
        if result.get("isError") is True:
            raise SmokeError(
                "mcp_tool_error",
                f"{self.name}.{tool} returned an MCP error",
            )
        blocks = result.get("content") or []
        text = next(
            (
                str(block.get("text"))
                for block in blocks
                if isinstance(block, dict)
                and block.get("type") == "text"
            ),
            "",
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            structured = result.get("structuredContent")
            payload = structured if isinstance(structured, dict) else None
        if not isinstance(payload, dict):
            raise SmokeError(
                "mcp_tool_result_invalid",
                f"{self.name}.{tool} returned no JSON object",
            )
        return payload

    def close(self) -> None:
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)


def _json_request(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    encoded = (
        json.dumps(body).encode("utf-8")
        if body is not None else None
    )
    request_headers = {
        "Accept": "application/json",
        **dict(headers or {}),
    }
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=encoded,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout) as response:
            return response.status, json.loads(
                response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"ok": False, "error": {"code": "http_error"}}
        return error.code, payload


def _wait_http(url: str, process: ManagedProcess) -> None:
    deadline = time.monotonic() + PROCESS_START_TIMEOUT
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise SmokeError(
                "resident_start_failed",
                f"{process.name} exited before its loopback service was ready",
            )
        try:
            status, _payload = _json_request(
                "GET", url, timeout=0.5)
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.2)
            continue
        if 200 <= status < 500:
            return
        time.sleep(0.2)
    raise SmokeError(
        "resident_start_timeout",
        f"{process.name} did not become ready in time",
    )


def _port_available(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _source_env(base: dict[str, str], source: Path) -> dict[str, str]:
    env = dict(base)
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(source)
        if not current else str(source) + os.pathsep + current
    )
    return env


def _safe_base_env(local_data: Path) -> dict[str, str]:
    env = dict(os.environ)
    for name in FORBIDDEN_PROVIDER_ENV:
        env.pop(name, None)
    env.update({
        "HOME": str(local_data / "home"),
        "LOCALAPPDATA": str(local_data),
        "XDG_DATA_HOME": str(local_data / "xdg-data"),
        "XDG_STATE_HOME": str(local_data / "xdg-state"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "PYTHONUTF8": "1",
    })
    return env


def _runtime_registry_dir(
    env: Mapping[str, str],
    *,
    platform_name: str | None = None,
) -> Path:
    """Resolve the isolated registry exactly as the products do."""
    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        return Path(env["LOCALAPPDATA"]) / "RyanSuite" / "services.d"
    if platform_name == "darwin":
        return (
            Path(env["HOME"])
            / "Library"
            / "Application Support"
            / "RyanSuite"
            / "services.d"
        )
    return Path(env["XDG_STATE_HOME"]) / "ryan-suite" / "services.d"


def _uoink_data_dir(
    env: Mapping[str, str],
    *,
    platform_name: str | None = None,
) -> Path:
    """Resolve Uoink's isolated data directory exactly as Uoink does."""
    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        return Path(env["LOCALAPPDATA"]) / "Uoink"
    if platform_name == "darwin":
        return (
            Path(env["HOME"])
            / "Library"
            / "Application Support"
            / "Uoink"
        )
    return Path(env["XDG_DATA_HOME"]) / "Uoink"


def _validate_contract(
    contract: str,
    payload: dict[str, Any],
    **context: Any,
) -> None:
    result = validate_contract_payload(contract, payload, **context)
    if result["passed"] is not True:
        first = result["issues"][0] if result["issues"] else {}
        raise SmokeError(
            "contract_nonconformant",
            f"{contract} failed exact validation at "
            f"{first.get('path', '$')}: {first.get('kind', 'invalid')}",
        )


def _unwrap_writer(payload: dict[str, Any]) -> dict[str, Any]:
    if (
        payload.get("ok") is True
        and payload.get("contract") == "writer.api"
        and payload.get("version") == 1
        and isinstance(payload.get("data"), dict)
    ):
        return payload["data"]
    error = payload.get("error")
    message = (
        error.get("message")
        if isinstance(error, dict)
        else str(error or "Writer request failed")
    )
    raise SmokeError("writer_api_failed", str(message))


def _mcp_ok(
    product: str,
    tool: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if payload.get("ok") is True:
        return payload
    error = payload.get("error")
    message = (
        error.get("message")
        if isinstance(error, dict)
        else str(error or "operation failed")
    )
    raise SmokeError(
        f"{product}_{tool}_failed",
        f"{product}.{tool} failed: {message}",
    )


def _generate_fixture_video(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SmokeError(
            "ffmpeg_missing",
            "deterministic_ci needs ffmpeg to generate fixture media",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=360x640:rate=30:duration=4",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=4",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode or not path.is_file():
        raise SmokeError(
            "fixture_media_failed",
            "ffmpeg could not generate deterministic fixture media",
        )


def _seed_uoink_fixture(
    *,
    python: str,
    uoink_repo: Path,
    env: dict[str, str],
    output_root: Path,
    fixture_media: Path,
) -> str:
    """Seed one isolated item using Uoink's migrations and Index API."""
    item_id = "suite-smoke-fixture"
    folder = output_root / "suite-smoke" / item_id
    folder.mkdir(parents=True, exist_ok=True)
    media = folder / "media.mp4"
    shutil.copyfile(fixture_media, media)
    corpus = folder / "yoink.md"
    corpus.write_text(
        "# Suite smoke fixture\n\n"
        "A deterministic local fixture used only by the family gate.\n",
        encoding="utf-8",
    )
    sidecar = folder / f"{item_id}.json"
    sidecar.write_text(
        json.dumps({
            "schema_version": 2,
            "title": "Suite smoke fixture",
            "url": "https://example.test/suite-smoke/fixture",
            "source_url": "https://example.test/suite-smoke/fixture",
            "video_id": item_id,
            "channel": "Suite Smoke",
            "source_type": "short_video",
            "platform": "youtube",
            "duration": 4,
            "media_file": media.name,
            "transcript": [],
            "screenshots": [],
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    seed = (
        "import json, os;"
        "from pathlib import Path;"
        "import index;"
        "root=Path(os.environ['SUITE_SMOKE_UOINK_DATA']);"
        "idx=index.Index.open(root/'index.db');"
        "record=json.loads(os.environ['SUITE_SMOKE_ROW']);"
        "idx.upsert_yoink(record, content='deterministic suite smoke fixture');"
        "idx.close()"
    )
    record = {
        "video_id": item_id,
        "slug": item_id,
        "channel": "Suite Smoke",
        "title": "Suite smoke fixture",
        "topic": "suite-smoke",
        "hook_type": None,
        "yoinked_at": _rfc3339(_utc_now()),
        "corpus_path": str(corpus),
        "sidecar_path": str(sidecar),
        "health_score_json": "{}",
        "metadata_json": json.dumps({
            "url": "https://example.test/suite-smoke/fixture",
            "source_url": "https://example.test/suite-smoke/fixture",
            "source_type": "short_video",
            "platform": "youtube",
            "author": "Suite Smoke",
            "duration_seconds": 4,
        }),
        "schema_version": 2,
        "source_type": "short_video",
        "platform": "youtube",
        "author": "Suite Smoke",
    }
    seed_env = dict(env)
    seed_env["SUITE_SMOKE_ROW"] = json.dumps(record)
    seed_env["SUITE_SMOKE_UOINK_DATA"] = str(_uoink_data_dir(env))
    result = subprocess.run(
        [python, "-c", seed],
        cwd=uoink_repo,
        env=seed_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        raise SmokeError(
            "fixture_seed_failed",
            "Uoink's index API could not seed the deterministic fixture",
        )
    return item_id


def _capture_real(
    *,
    source_url: str,
    token: str,
) -> tuple[str, Path]:
    status, settings = _json_request(
        "POST",
        UOINK_URL + "/settings",
        body={
            "keep_media": True,
            "asr_fallback_enabled": False,
            "comment_intelligence_enabled": False,
            "hook_type_enabled": False,
            "transcript_reliability_auto_check": False,
        },
        headers={"X-Uoink-Token": token},
    )
    if status != 200 or settings.get("ok") is not True:
        raise SmokeError(
            "keep_media_enable_failed",
            "Uoink did not enable isolated keep_media settings",
        )
    status, captured = _json_request(
        "POST",
        UOINK_URL + "/extract",
        body={
            "url": source_url,
            "interval": 5,
            "long_video_mode": "lite",
        },
        headers={"X-Uoink-Token": token},
        timeout=15 * 60,
    )
    if status != 200 or captured.get("ok") is not True:
        raise SmokeError(
            "real_capture_failed",
            "Uoink could not capture the supplied supported short video",
        )
    folder_value = captured.get("folder")
    if not isinstance(folder_value, str):
        raise SmokeError(
            "real_capture_nonconformant",
            "Uoink capture returned no corpus folder",
        )
    folder = Path(folder_value)
    sidecar = folder / f"{folder.name}.json"
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SmokeError(
            "real_capture_sidecar_missing",
            "Uoink captured the short but its sidecar is unavailable",
        ) from None
    item_id = str(metadata.get("video_id") or "").strip()
    media_name = metadata.get("media_file")
    if not item_id or not isinstance(media_name, str):
        raise SmokeError(
            "real_capture_not_kept",
            "Uoink capture did not retain a stable item ID and kept media",
        )
    media = folder / media_name
    if not media.is_file():
        raise SmokeError(
            "real_capture_media_missing",
            "Uoink's kept-media sidecar points to a missing file",
        )
    return item_id, media


def _wait_for_breakdown(
    zing: StdioMCPClient,
    slug: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + STUDY_TIMEOUT
    while time.monotonic() < deadline:
        payload = zing.call("get_breakdown", {"slug": slug})
        if payload.get("ok") is True and payload.get("ready") is True:
            if payload.get("state") != "done":
                raise SmokeError(
                    "zing_study_not_current",
                    "Zing served a breakdown whose current study did not pass",
                )
            breakdown = payload.get("breakdown")
            if isinstance(breakdown, dict):
                return breakdown
        if payload.get("state") == "failed":
            raise SmokeError(
                "zing_study_failed",
                "Zing's kept-media study failed",
            )
        time.sleep(POLL_INTERVAL)
    raise SmokeError(
        "zing_study_timeout",
        "Zing's kept-media study did not finish in time",
    )


def _keeper_spans(
    breakdown: dict[str, Any],
) -> list[dict[str, Any]]:
    provenance = breakdown.get("provenance")
    raw_mode = (
        provenance.get("raw_mode")
        if isinstance(provenance, dict) else None
    )
    measured = (
        raw_mode.get("keepers")
        if isinstance(raw_mode, dict) else None
    )
    if isinstance(measured, list):
        for keeper in measured:
            if not isinstance(keeper, dict):
                continue
            try:
                start = float(keeper["start"])
                end = float(keeper["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if start >= 0 and end - start >= 0.2:
                return [{
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "why": "Zing raw-mode measurement marked this span usable.",
                }]
    shots = breakdown.get("shots")
    if isinstance(shots, list):
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            try:
                start = float(shot["start"])
                end = float(shot["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if start >= 0 and end - start >= 0.2:
                return [{
                    "start": round(start, 3),
                    "end": round(min(end, start + 4.0), 3),
                    "why": "Zing measured this shot boundary in the breakdown.",
                }]
    meta = breakdown.get("meta")
    duration = (
        meta.get("duration")
        if isinstance(meta, dict) else None
    )
    try:
        end = min(float(duration), 2.0)
    except (TypeError, ValueError):
        end = 0.0
    if end >= 0.2:
        return [{
            "start": 0.0,
            "end": round(end, 3),
            "why": "Zing measured this bounded source timeline.",
        }]
    raise SmokeError(
        "keeper_measurement_missing",
        "Zing produced no measurable span suitable for an honest draft",
    )


def _source_handoff(
    breakdown: dict[str, Any],
    item_ref: str,
    expected_sha256: str,
) -> dict[str, Any]:
    provenance = breakdown.get("provenance")
    handoff = (
        provenance.get("source_handoff")
        if isinstance(provenance, dict) else None
    )
    if not isinstance(handoff, dict):
        raise SmokeError(
            "handoff_provenance_missing",
            "Zing persisted no source_handoff provenance",
        )
    if (
        handoff.get("source_ref") != item_ref
        or handoff.get("acquisition") != "kept_media"
        or handoff.get("refetch") is not False
        or handoff.get("sha256") != expected_sha256
    ):
        raise SmokeError(
            "handoff_provenance_invalid",
            "Zing did not prove kept-media acquisition with zero refetch",
        )
    return handoff


def _wait_for_render(
    zing: StdioMCPClient,
    render_id: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + RENDER_TIMEOUT
    while time.monotonic() < deadline:
        payload = _mcp_ok(
            "zing",
            "get_render",
            zing.call("get_render", {"render_id": render_id}),
        )
        state = payload.get("state")
        if state == "done":
            return payload
        if state == "failed":
            raise SmokeError(
                "zing_render_failed",
                "Zing's draft render failed",
            )
        time.sleep(POLL_INTERVAL)
    raise SmokeError(
        "zing_render_timeout",
        "Zing's draft render did not finish in time",
    )


def _writer_event_id(
    entity_id: int,
    item_ref: str,
    *,
    version: int = 1,
) -> str:
    identity = f"writer:script:{entity_id}:v{version}:{item_ref}"
    return "writer-" + str(uuid.uuid5(uuid.NAMESPACE_URL, identity))


def _receipt_state(
    receipt: Mapping[str, Any],
) -> str:
    if int(receipt.get("accepted") or 0) > 0:
        return "accepted"
    if int(receipt.get("duplicates") or 0) > 0:
        return "duplicate"
    if int(receipt.get("spooled") or 0) > 0:
        return "spooled"
    if int(receipt.get("rejected") or 0) > 0:
        return "rejected"
    raise SmokeError(
        "engagement_unaccounted",
        "a product did not account for its submitted engagement event",
    )


def _find_peer_contract(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if (
            value.get("contract") == "ryan.suite.peer"
            and value.get("version") == 1
            and value.get("peer") == "uoink"
        ):
            return value
        for child in value.values():
            found = _find_peer_contract(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_peer_contract(child)
            if found is not None:
                return found
    return None


def _writer_peer_from_doctor(payload: dict[str, Any]) -> dict[str, Any]:
    for check in payload.get("checks") or []:
        if isinstance(check, dict) and check.get("name") == "uoink":
            result = check.get("result")
            if isinstance(result, dict):
                return result
    raise SmokeError(
        "writer_peer_probe_missing",
        "Writer doctor returned no versioned Uoink peer result",
    )


def _validate_peer_after_stop(
    peer: dict[str, Any],
    product: str,
) -> str:
    _validate_contract(
        "ryan.suite.peer/1", peer, expected_peer="uoink")
    state = str(peer.get("state") or "")
    if state not in {"absent", "unhealthy"}:
        raise SmokeError(
            "peer_stop_not_observed",
            f"{product} did not report Uoink absent or unhealthy after stop",
        )
    return state


def _wait_zing_peer_after_stop(
    client: StdioMCPClient,
) -> str:
    """Wait through Zing's contract-mandated 60-second peer-probe cache."""
    deadline = time.monotonic() + PEER_STOP_TIMEOUT
    while time.monotonic() < deadline:
        status = _mcp_ok(
            "zing",
            "zing_status",
            client.call("zing_status"),
        )
        peer = _find_peer_contract(status)
        if peer is None:
            raise SmokeError(
                "zing_peer_probe_missing",
                "Zing status returned no versioned peer result after stop",
            )
        _validate_contract(
            "ryan.suite.peer/1",
            peer,
            expected_peer="uoink",
        )
        if peer.get("state") in {"absent", "unhealthy"}:
            return str(peer["state"])
        time.sleep(POLL_INTERVAL)
    raise SmokeError(
        "peer_stop_not_observed",
        "Zing's cached Uoink peer state did not expire after stop",
    )


def _read_json_file(path: Path, *, code: str) -> dict[str, Any]:
    deadline = time.monotonic() + PROCESS_START_TIMEOUT
    while time.monotonic() < deadline:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            time.sleep(0.1)
            continue
        if isinstance(payload, dict):
            return payload
        break
    raise SmokeError(code, f"{path.stem} did not produce valid JSON")


def _run_writer_doctor(
    python: str,
    writer_repo: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    result = subprocess.run(
        [python, "-m", "writer.cli", "doctor", "--json"],
        cwd=writer_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise SmokeError(
            "writer_doctor_invalid",
            "Writer doctor did not return its JSON state",
        ) from None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise SmokeError(
            "writer_standalone_failed",
            "Writer doctor reported a required local failure",
        )
    return payload


def _require_initial_peer(
    payload: dict[str, Any],
    product: str,
) -> None:
    peer = (
        _writer_peer_from_doctor(payload)
        if product == "writer"
        else _find_peer_contract(payload)
    )
    if peer is None:
        raise SmokeError(
            f"{product}_peer_probe_missing",
            f"{product} exposes no contract-aware Uoink peer probe",
        )
    _validate_contract(
        "ryan.suite.peer/1",
        peer,
        expected_peer="uoink",
    )
    if peer.get("state") != "available":
        raise SmokeError(
            f"{product}_peer_unavailable",
            f"{product} did not report Uoink available before the scenario",
        )


def _zing_engagement(
    started: dict[str, Any],
    breakdown: dict[str, Any],
) -> tuple[str, str]:
    """Find the product-owned opened-event receipt; never emit it here."""
    candidates: list[dict[str, Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            if (
                value.get("state")
                in {"accepted", "spooled", "rejected"}
                and isinstance(value.get("event_id"), str)
            ):
                candidates.append(value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(started.get("engagement"))
    provenance = breakdown.get("provenance")
    if isinstance(provenance, dict):
        collect(provenance.get("engagement"))
    if not candidates:
        raise SmokeError(
            "zing_opened_event_missing",
            "Zing did not expose its required opened-event receipt",
        )
    receipt = candidates[0]
    event_id = str(receipt["event_id"])
    if not event_id or len(event_id) > 200:
        raise SmokeError(
            "zing_opened_event_invalid",
            "Zing's opened-event receipt has no stable event ID",
        )
    return event_id, str(receipt["state"])


def _stop_uoink(
    process: ManagedProcess,
    token: str,
) -> None:
    try:
        _json_request(
            "POST",
            UOINK_URL + "/helper/quit",
            body={},
            headers={"X-Uoink-Token": token},
            timeout=5,
        )
    except (OSError, urllib.error.URLError):
        pass
    try:
        process.process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.stop()


def _has_absolute_path(text: str) -> bool:
    return bool(
        re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]", text)
        or re.search(r"(?<![:A-Za-z0-9])/(?:home|Users|tmp|var|opt)/", text)
    )


def run_suite_smoke(
    *,
    mode: str,
    uoink_repo: Path,
    writer_repo: Path,
    zing_repo: Path,
    work_root: Path,
    source_url: str = "",
    fixture_video: Path | None = None,
    python: str = sys.executable,
) -> dict[str, Any]:
    """Drive the family scenario and return its evaluated path-free record."""
    if mode not in {"deterministic_ci", "real_capture"}:
        raise SmokeError("invalid_mode", f"unsupported smoke mode: {mode}")
    if mode == "real_capture" and not source_url.strip():
        raise SmokeError(
            "source_url_required",
            "real_capture requires an explicit supported short-video URL",
        )
    for name, repo, marker in (
        ("uoink", uoink_repo, "server.py"),
        ("writer", writer_repo, "src/writer/cli.py"),
        ("zing", zing_repo, "src/myzing/cli.py"),
    ):
        if not (repo / marker).is_file():
            raise SmokeError(
                "repo_layout_invalid",
                f"{name} repository does not contain {marker}",
            )
    occupied = [
        port for port in (5179, 5181) if not _port_available(port)
    ]
    if occupied:
        raise SmokeError(
            "port_in_use",
            "suite smoke refuses to replace an existing process on port "
            + ", ".join(str(port) for port in occupied),
        )

    work_root.mkdir(parents=True, exist_ok=True)
    local_data = work_root / "local-data"
    uoink_output = work_root / "uoink-output"
    writer_data = work_root / "writer-data"
    zing_home = work_root / "zing-home"
    artifacts_dir = work_root / "artifacts"
    for directory in (
        local_data,
        uoink_output,
        writer_data,
        zing_home,
        artifacts_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    base_env = _safe_base_env(local_data)
    uoink_env = dict(base_env)
    uoink_env["UOINK_OUTPUT_DIR"] = str(uoink_output)
    writer_env = _source_env(base_env, writer_repo / "src")
    writer_env["WRITER_DATA_DIR"] = str(writer_data)
    writer_env["WRITER_TOKEN"] = secrets.token_urlsafe(32)
    writer_env["WRITER_UOINK_URL"] = UOINK_URL
    zing_env = _source_env(base_env, zing_repo / "src")
    zing_env["ZING_HOME"] = str(zing_home)
    zing_env["UOINK_URL"] = UOINK_URL

    ledger = StepLedger()
    residents: list[ManagedProcess] = []
    clients: dict[str, StdioMCPClient] = {}
    uoink_process: ManagedProcess | None = None
    writer_process: ManagedProcess | None = None
    uoink_token = ""
    cleanup = {"passed": False, "residual_processes": 0}

    source_revisions = {
        "uoink": _git_revision(uoink_repo),
        "writer": _git_revision(writer_repo),
        "zing": _git_revision(zing_repo),
    }
    versions = _product_versions(uoink_repo, writer_repo, zing_repo)

    handoff_payload: dict[str, Any] = {}
    item_ref = ""
    kept_hash = ""
    writer_script_ref = ""
    zing_ref = ""
    shot_hash = ""
    render_hash = ""
    source_snapshot: dict[str, Any] = {}
    writer_receipts: list[tuple[str, str]] = []
    zing_receipt: tuple[str, str] | None = None
    import_receipt: dict[str, Any] = {}
    keeper_spans: list[dict[str, Any]] = []
    writer_peer_after = ""
    zing_peer_after = ""

    try:
        with ledger.step("launch_products"):
            uoink_command = [
                python,
                "-c",
                (
                    "import server;"
                    "server.maybe_toast=lambda *a, **k: None;"
                    "server._platform.open_in_os=lambda *a, **k: None;"
                    "server.main()"
                ),
            ]
            uoink_process = ManagedProcess.start(
                "uoink",
                uoink_command,
                cwd=uoink_repo,
                env=uoink_env,
            )
            residents.append(uoink_process)
            _wait_http(UOINK_URL + "/ping", uoink_process)
            token_path = uoink_repo / "token.txt"
            deadline = time.monotonic() + PROCESS_START_TIMEOUT
            while time.monotonic() < deadline and not token_path.is_file():
                time.sleep(0.1)
            try:
                uoink_token = token_path.read_text(
                    encoding="utf-8").strip()
            except OSError:
                uoink_token = ""
            if not uoink_token:
                raise SmokeError(
                    "uoink_token_unavailable",
                    "Uoink did not create its local credential",
                )
            writer_env["WRITER_UOINK_TOKEN"] = uoink_token
            zing_env["UOINK_TOKEN"] = uoink_token

            writer_process = ManagedProcess.start(
                "writer",
                [
                    python,
                    "-m",
                    "writer.cli",
                    "serve",
                    "--port",
                    "5181",
                    "--database",
                    str(writer_data / "writer.db"),
                ],
                cwd=writer_repo,
                env=writer_env,
            )
            residents.append(writer_process)
            _wait_http(WRITER_URL + "/ping", writer_process)

            clients = {
                "uoink": StdioMCPClient(
                    "uoink",
                    [python, "-P", str(uoink_repo / "uoink_mcp.py")],
                    cwd=uoink_repo,
                    env=uoink_env,
                ),
                "writer": StdioMCPClient(
                    "writer",
                    [python, "-m", "writer.cli", "serve-mcp"],
                    cwd=writer_repo,
                    env=writer_env,
                ),
                "zing": StdioMCPClient(
                    "zing",
                    [python, "-m", "myzing.cli", "serve-mcp"],
                    cwd=zing_repo,
                    env=zing_env,
                ),
            }

        with ledger.step("validate_discovery"):
            registry = _runtime_registry_dir(base_env)
            leases = {
                product: _read_json_file(
                    registry / f"{product}.json",
                    code=f"{product}_lease_missing",
                )
                for product in ("uoink", "writer")
            }
            assert uoink_process is not None
            assert writer_process is not None
            live_pids = [
                uoink_process.process.pid,
                writer_process.process.pid,
            ]
            for product, lease in leases.items():
                _validate_contract(
                    "ryan.suite.runtime-lease/1",
                    lease,
                    expected_service=product,
                    live_pids=live_pids,
                )
            for product, base in (
                ("uoink", UOINK_URL),
                ("writer", WRITER_URL),
            ):
                manifest_status, manifest = _json_request(
                    "GET",
                    base + "/.well-known/suite-service.json",
                )
                health_status, health = _json_request(
                    "GET",
                    base + "/api/suite/v1/health",
                )
                if manifest_status != 200 or health_status != 200:
                    raise SmokeError(
                        "resident_contract_unavailable",
                        f"{product} did not serve suite manifest and health",
                    )
                _validate_contract(
                    "ryan.suite.service/1",
                    manifest,
                    expected_service=product,
                )
                _validate_contract(
                    "ryan.suite.health/1",
                    health,
                    expected_service=product,
                )
            identities: list[str] = []
            for product in ("uoink", "writer", "zing"):
                identity, names = clients[product].initialize()
                if identity != product:
                    raise SmokeError(
                        "mcp_identity_drift",
                        f"{product} MCP identified itself as {identity!r}",
                    )
                missing = REQUIRED_MCP_TOOLS[product] - set(names)
                if missing or not names:
                    raise SmokeError(
                        "mcp_surface_drift",
                        f"{product} MCP is missing required direct tools",
                    )
                identities.append(identity)
            if identities != ["uoink", "writer", "zing"]:
                raise SmokeError(
                    "mcp_not_direct",
                    "the client did not connect to three direct product MCPs",
                )
            initial_writer_doctor = _run_writer_doctor(
                python, writer_repo, writer_env)
            _require_initial_peer(initial_writer_doctor, "writer")
            initial_zing_status = _mcp_ok(
                "zing",
                "zing_status",
                clients["zing"].call("zing_status"),
            )
            _require_initial_peer(initial_zing_status, "zing")

        with ledger.step("capture_kept_media"):
            if mode == "deterministic_ci":
                media = fixture_video
                if media is None:
                    media = artifacts_dir / "fixture-input.mp4"
                    _generate_fixture_video(media)
                elif not media.is_file():
                    raise SmokeError(
                        "fixture_media_missing",
                        "the deterministic fixture video does not exist",
                    )
                status, settings = _json_request(
                    "POST",
                    UOINK_URL + "/settings",
                    body={
                        "keep_media": True,
                        "asr_fallback_enabled": False,
                        "comment_intelligence_enabled": False,
                        "hook_type_enabled": False,
                        "transcript_reliability_auto_check": False,
                    },
                    headers={"X-Uoink-Token": uoink_token},
                )
                if status != 200 or settings.get("ok") is not True:
                    raise SmokeError(
                        "keep_media_enable_failed",
                        "Uoink did not enable isolated keep_media settings",
                    )
                item_id = _seed_uoink_fixture(
                    python=python,
                    uoink_repo=uoink_repo,
                    env=uoink_env,
                    output_root=uoink_output,
                    fixture_media=media,
                )
            else:
                item_id, _media = _capture_real(
                    source_url=source_url.strip(),
                    token=uoink_token,
                )
            item_ref = "uoink://item/" + urllib.parse.quote(
                item_id, safe="")
            status, handoff_payload = _json_request(
                "GET",
                UOINK_URL
                + "/api/corpus/v1/items/"
                + urllib.parse.quote(item_id, safe="")
                + "/kept-media",
                headers={"X-Uoink-Token": uoink_token},
            )
            if status != 200:
                raise SmokeError(
                    "media_handoff_failed",
                    "Uoink did not resolve the kept-media handoff",
                )
            _validate_contract(
                "uoink.media.handoff/1", handoff_payload)
            handoff_data = handoff_payload.get("data")
            media_data = (
                handoff_data.get("media")
                if isinstance(handoff_data, dict) else None
            )
            if (
                not isinstance(handoff_data, dict)
                or handoff_data.get("state") != "available"
                or not isinstance(media_data, dict)
            ):
                raise SmokeError(
                    "media_handoff_not_available",
                    "Uoink did not return an available kept file",
                )
            kept_path = Path(str(media_data["path"]))
            kept_hash = str(media_data["sha256"])
            if (
                not kept_path.is_file()
                or _sha256(kept_path) != kept_hash
                or kept_path.stat().st_size
                != int(media_data["byte_length"])
            ):
                raise SmokeError(
                    "kept_media_integrity_failed",
                    "kept media did not match Uoink's hash and size",
                )

        with ledger.step("study_kept_media"):
            study_started = _mcp_ok(
                "zing",
                "study_uoink_item",
                clients["zing"].call(
                    "study_uoink_item",
                    {"item_ref": item_ref},
                ),
            )
            slug = str(study_started.get("slug") or "")
            if not slug:
                raise SmokeError(
                    "zing_slug_missing",
                    "Zing started no stable breakdown identity",
                )
            breakdown = _wait_for_breakdown(clients["zing"], slug)
            _source_handoff(breakdown, item_ref, kept_hash)
            zing_receipt = _zing_engagement(
                study_started, breakdown)
            zing_ref = f"zing://breakdown/{slug}"

        with ledger.step("create_zing_direction"):
            profile = _mcp_ok(
                "zing",
                "build_profile",
                clients["zing"].call("build_profile", {
                    "name": "suite-smoke-profile",
                    "slugs": [slug],
                    "genre": "talking-head",
                }),
            )
            if int(profile.get("sources") or 0) != 1:
                raise SmokeError(
                    "zing_profile_failed",
                    "Zing did not create the one-source suite profile",
                )
            keeper_spans = _keeper_spans(breakdown)
            direction = {
                "verdict": (
                    "One measured source span is usable for the isolated "
                    "family-gate draft."
                ),
                "gaps": [],
                "shot_prompts": [],
                "keepers": keeper_spans,
                "assembly_notes": (
                    "The smoke keeps only a measured span and adds no "
                    "invented footage."
                ),
            }
            directed = _mcp_ok(
                "zing",
                "save_judgment",
                clients["zing"].call("save_judgment", {
                    "slug": slug,
                    "judgment": direction,
                    "section": "direct",
                    "model": "deterministic-suite-smoke",
                }),
            )
            if directed.get("section_written") != "direct":
                raise SmokeError(
                    "zing_direction_failed",
                    "Zing did not persist the direction judgment",
                )
            direction_path = artifacts_dir / "direction.json"
            direction_path.write_text(
                json.dumps(direction, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        with ledger.step("writer_create"):
            status, attached = _json_request(
                "POST",
                WRITER_URL + "/api/writer/v1/sources/uoink",
                body={"item_id": item_id},
                headers={"X-Writer-Token": writer_env["WRITER_TOKEN"]},
            )
            if status != 200:
                raise SmokeError(
                    "writer_source_failed",
                    "Writer could not retrieve the Uoink corpus item",
                )
            source_snapshot = _unwrap_writer(attached).get("source")
            if (
                not isinstance(source_snapshot, dict)
                or source_snapshot.get("provider_ref") != item_ref
                or _has_absolute_path(json.dumps(source_snapshot))
            ):
                raise SmokeError(
                    "writer_source_nonconformant",
                    "Writer's Uoink source snapshot is missing or path-bearing",
                )
            _mcp_ok(
                "writer",
                "prepare_script",
                clients["writer"].call("prepare_script", {
                    "brief": (
                        "Write a short local script grounded in the attached "
                        "Uoink source."
                    ),
                    "sources": [source_snapshot],
                }),
            )
            saved = _mcp_ok(
                "writer",
                "save_script",
                clients["writer"].call("save_script", {
                    "script": {
                        "hook": "One local source moved through three tools.",
                        "format": "tutorial",
                        "target_length_sec": 20,
                        "beats": [{
                            "label": "proof",
                            "content": (
                                "Show the measured kept-media result."
                            ),
                            "timecode": "0:00-0:04",
                        }],
                        "body": (
                            "Uoink kept the source, Zing measured it, and "
                            "Writer retained its credit."
                        ),
                        "cta": "Keep the next draft local.",
                        "sources": [source_snapshot],
                    },
                }),
            )
            script = saved.get("script")
            if not isinstance(script, dict):
                raise SmokeError(
                    "writer_script_missing",
                    "Writer did not persist the script",
                )
            script_id = int(script["id"])
            base_engagement = saved.get("engagement")
            if not isinstance(base_engagement, dict):
                raise SmokeError(
                    "writer_engagement_missing",
                    "Writer did not report script engagement delivery",
                )
            writer_receipts.append((
                _writer_event_id(script_id, item_ref),
                _receipt_state(base_engagement),
            ))
            critique = _mcp_ok(
                "writer",
                "critique_script",
                clients["writer"].call("critique_script", {
                    "script_id": script_id,
                    "findings": {
                        "grounding": "The script retains one bounded source.",
                        "voice": "The claim is specific and local.",
                    },
                    "draft_text": str(script.get("body") or ""),
                }),
            )
            if critique.get("mode") != "persisted":
                raise SmokeError(
                    "writer_critique_missing",
                    "Writer did not persist the script critique",
                )
            scan = _mcp_ok(
                "writer",
                "scan_voice",
                clients["writer"].call("scan_voice", {
                    "text": str(script.get("body") or ""),
                }),
            )
            if not isinstance(scan.get("warnings"), list):
                raise SmokeError(
                    "writer_voice_scan_missing",
                    "Writer did not complete its local Voice DNA scan",
                )
            derived = _mcp_ok(
                "writer",
                "derive_shot_list",
                clients["writer"].call("derive_shot_list", {
                    "script_id": script_id,
                }),
            )
            derived_script = derived.get("script")
            if not isinstance(derived_script, dict):
                raise SmokeError(
                    "writer_shot_derivation_failed",
                    "Writer did not persist the derived shot-list script",
                )
            final_script_id = int(derived_script["id"])
            derived_engagement = derived.get("engagement")
            if not isinstance(derived_engagement, dict):
                raise SmokeError(
                    "writer_engagement_missing",
                    "Writer did not report derived-script engagement",
                )
            writer_receipts.append((
                _writer_event_id(final_script_id, item_ref),
                _receipt_state(derived_engagement),
            ))
            writer_script_ref = f"writer://script/{final_script_id}"

        with ledger.step("export_shot_list"):
            shot_path = artifacts_dir / "writer-shot-list.md"
            exported = _mcp_ok(
                "writer",
                "export_shot_list",
                clients["writer"].call("export_shot_list", {
                    "script_id": final_script_id,
                    "output": str(shot_path),
                    "title": "Suite family-gate draft",
                }),
            )
            if not shot_path.is_file():
                raise SmokeError(
                    "writer_shot_list_missing",
                    "Writer reported an export but wrote no file",
                )
            markdown = shot_path.read_text(encoding="utf-8")
            credit = str(source_snapshot.get("credit_line") or "")
            if (
                f"source_script_id: {final_script_id}" not in markdown
                or not credit
                or credit not in markdown
                or "zing://" in markdown
                or _has_absolute_path(markdown)
            ):
                raise SmokeError(
                    "writer_file_boundary_failed",
                    "Writer's export lost its ID/credit or crossed into Zing",
                )
            document = exported.get("document")
            if (
                not isinstance(document, dict)
                or document.get("document_type") != "writer.shot-list"
                or document.get("schema_version") != 1
            ):
                raise SmokeError(
                    "writer_shot_list_nonconformant",
                    "Writer exported the wrong shot-list contract",
                )
            shot_hash = _sha256(shot_path)

        with ledger.step("import_shot_list"):
            import_receipt = clients["zing"].call(
                "import_shot_list",
                {"path": str(shot_path), "slug": slug},
            )
            _validate_contract(
                "zing.shot-list.import/1", import_receipt)
            if import_receipt.get("ok") is not True:
                raise SmokeError(
                    "zing_shot_list_import_failed",
                    "Zing rejected Writer's shot-list file",
                )
            serialized_receipt = json.dumps(import_receipt)
            document = import_receipt["data"]["document"]
            if (
                document.get("source_ref") != writer_script_ref
                or document.get("sha256") != shot_hash
                or import_receipt["data"].get("target_ref") != zing_ref
                or _has_absolute_path(serialized_receipt)
            ):
                raise SmokeError(
                    "zing_import_identity_failed",
                    "Zing's import receipt lost a stable identity or hash",
                )

        with ledger.step("assemble_render"):
            assemble = subprocess.run(
                [
                    python,
                    "-m",
                    "myzing.cli",
                    "assemble",
                    slug,
                    "--direction",
                    str(direction_path),
                    "--workspace",
                    str(zing_home),
                ],
                cwd=zing_repo,
                env=zing_env,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            edl_path = (
                zing_home / "breakdowns" / slug / "draft-edl.json")
            if assemble.returncode or not edl_path.is_file():
                raise SmokeError(
                    "zing_assemble_failed",
                    "Zing could not assemble the measured direction",
                )
            render_path = artifacts_dir / "suite-draft.mp4"
            render_started = _mcp_ok(
                "zing",
                "render_edl",
                clients["zing"].call("render_edl", {
                    "edl_path": str(edl_path),
                    "output_path": str(render_path),
                }),
            )
            render_id = str(render_started.get("render_id") or "")
            if not render_id:
                raise SmokeError(
                    "zing_render_id_missing",
                    "Zing started no stable render identity",
                )
            _wait_for_render(clients["zing"], render_id)
            if not render_path.is_file():
                raise SmokeError(
                    "zing_render_missing",
                    "Zing reported a completed render without an artifact",
                )
            render_hash = _sha256(render_path)

        with ledger.step("account_engagement"):
            if zing_receipt is None:
                raise SmokeError(
                    "zing_opened_event_missing",
                    "Zing did not account for its opened event",
                )
            all_states = [
                state for _event_id, state
                in [*writer_receipts, zing_receipt]
            ]
            if any(
                state not in {
                    "accepted",
                    "duplicate",
                    "spooled",
                    "rejected",
                }
                for state in all_states
            ):
                raise SmokeError(
                    "engagement_unaccounted",
                    "an engagement event has no visible terminal/spool state",
                )
            writer_status = _mcp_ok(
                "writer",
                "writer_status",
                clients["writer"].call("writer_status"),
            )
            engagement_status = writer_status.get("engagement")
            if not isinstance(engagement_status, dict):
                raise SmokeError(
                    "writer_engagement_status_missing",
                    "Writer exposes no durable engagement status",
                )

        with ledger.step("stop_optional_peer"):
            assert uoink_process is not None
            _stop_uoink(uoink_process, uoink_token)
            post_writer_doctor = _run_writer_doctor(
                python, writer_repo, writer_env)
            writer_peer_after = _validate_peer_after_stop(
                _writer_peer_from_doctor(post_writer_doctor),
                "writer",
            )
            zing_peer_after = _wait_zing_peer_after_stop(
                clients["zing"])
            _mcp_ok(
                "writer",
                "scan_voice",
                clients["writer"].call(
                    "scan_voice",
                    {"text": "Standalone Writer remains local."},
                ),
            )
            _mcp_ok(
                "zing",
                "list_breakdowns",
                clients["zing"].call("list_breakdowns"),
            )
    finally:
        for client in clients.values():
            client.close()
        for resident in residents:
            resident.stop()
        residual = sum(
            resident.process.poll() is None for resident in residents
        ) + sum(
            client.process.poll() is None for client in clients.values()
        )
        cleanup = {
            "passed": residual == 0,
            "residual_processes": residual,
        }

    if not cleanup["passed"]:
        raise SmokeError(
            "cleanup_failed",
            "suite smoke left a process it started running",
        )

    assert zing_receipt is not None
    submitted = [
        event_id
        for event_id, _state in [*writer_receipts, zing_receipt]
    ]
    engagement_receipts = [
        {"event_id": event_id, "state": state}
        for event_id, state in [*writer_receipts, zing_receipt]
    ]
    record = {
        "record_contract": "zing.suite-smoke",
        "version": 1,
        "mode": mode,
        "sources": {
            product: {
                "revision": source_revisions[product],
                "installed_version": versions[product],
            }
            for product in ("uoink", "writer", "zing")
        },
        "environment": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
        "steps": ledger.steps,
        "contracts": dict(CONTRACTS),
        "peer_states": {
            "uoink": "available",
            "writer": "available",
        },
        "mcp_identities": ["uoink", "writer", "zing"],
        "references": {
            "uoink_item": item_ref,
            "writer_script": writer_script_ref,
            "zing_breakdown": zing_ref,
        },
        "artifacts": [
            {"id": "kept_media", "sha256": kept_hash},
            {"id": "shot_list", "sha256": shot_hash},
            {"id": "render", "sha256": render_hash},
        ],
        "handoff": {
            "contract": "uoink.media.handoff",
            "version": 1,
            "source_ref": item_ref,
            "acquisition": "kept_media",
            "refetch": False,
            "sha256": kept_hash,
        },
        "writer_flow": {
            "corpus_item_ref": item_ref,
            "corpus_contract": "uoink.corpus.read/1",
            "source_snapshot_path_free": True,
            "script_id": int(writer_script_ref.rsplit("/", 1)[-1]),
            "script_saved": True,
            "critique_saved": True,
            "voice_dna_scanned": True,
            "shot_list": {
                "sha256": shot_hash,
                "source_ref": writer_script_ref,
                "source_credit_ref": item_ref,
                "zing_call_count": 0,
                "absolute_paths": [],
            },
        },
        "zing_flow": {
            "breakdown_ref": zing_ref,
            "breakdown_created": True,
            "profile_created": True,
            "direction_created": True,
            "keeper_spans": [
                {"start": span["start"], "end": span["end"]}
                for span in keeper_spans
            ],
            "import_receipt": import_receipt,
            "draft_provenance": {
                "breakdown_ref": zing_ref,
                "writer_source_ref": writer_script_ref,
                "shot_list_sha256": shot_hash,
                "keeper_span_source": "zing_direction",
                "keeper_spans": [
                    {"start": span["start"], "end": span["end"]}
                    for span in keeper_spans
                ],
            },
            "rendered": True,
            "render_sha256": render_hash,
        },
        "engagement": {
            "submitted_event_ids": submitted,
            "receipts": engagement_receipts,
            "visible_spool": [
                event_id
                for event_id, state
                in [*writer_receipts, zing_receipt]
                if state == "spooled"
            ],
            "durable_rejections": [
                event_id
                for event_id, state
                in [*writer_receipts, zing_receipt]
                if state == "rejected"
            ],
        },
        "optional_peer_stop": {
            "stopped_peer": "uoink",
            "remaining_products": [
                {
                    "product": "writer",
                    "peer_state": writer_peer_after,
                    "standalone_ok": True,
                },
                {
                    "product": "zing",
                    "peer_state": zing_peer_after,
                    "standalone_ok": True,
                },
            ],
        },
        "assertions": [
            {"id": assertion_id, "passed": True}
            for assertion_id in RECORDED_ASSERTIONS
        ],
        "failure_code": None,
        "cleanup": cleanup,
    }
    evaluation = evaluate_suite_record(record)
    if evaluation["passed"] is not True:
        failed = ", ".join(evaluation["failed_assertions"])
        raise SmokeError(
            "suite_record_failed",
            "independent suite-smoke evaluation failed: " + failed,
        )
    return record


def _write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local Uoink -> Zing/Writer -> Zing family gate. "
            "The runner never replaces an occupied suite port."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("deterministic_ci", "real_capture"),
        default="deterministic_ci",
    )
    parser.add_argument("--uoink-repo", type=Path, required=True)
    parser.add_argument("--writer-repo", type=Path, required=True)
    parser.add_argument("--zing-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--work-dir",
        type=Path,
        help=(
            "Keep isolated product data here. If omitted, a temporary "
            "directory is removed after the gate."
        ),
    )
    parser.add_argument(
        "--source-url",
        default="",
        help="Required only for real_capture; never written to the record.",
    )
    parser.add_argument(
        "--fixture-video",
        type=Path,
        help="Optional local video for deterministic_ci.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for all three product processes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    temporary: tempfile.TemporaryDirectory[str] | None = None
    work_root = args.work_dir
    if work_root is None:
        temporary = tempfile.TemporaryDirectory(
            prefix="ryan-suite-smoke-")
        work_root = Path(temporary.name)
    try:
        record = run_suite_smoke(
            mode=args.mode,
            uoink_repo=args.uoink_repo.resolve(),
            writer_repo=args.writer_repo.resolve(),
            zing_repo=args.zing_repo.resolve(),
            work_root=work_root.resolve(),
            source_url=args.source_url,
            fixture_video=(
                args.fixture_video.resolve()
                if args.fixture_video is not None else None
            ),
            python=args.python,
        )
        _write_record(args.output.resolve(), record)
    except SmokeError as error:
        print(
            json.dumps({
                "ok": False,
                "failure_code": error.code,
                "error": error.message,
            }),
            file=sys.stderr,
        )
        return 1
    finally:
        if temporary is not None:
            temporary.cleanup()
    print(json.dumps({
        "ok": True,
        "record_contract": record["record_contract"],
        "version": record["version"],
        "mode": record["mode"],
        "sha256": _sha256(args.output.resolve()),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
