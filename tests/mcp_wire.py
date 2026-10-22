"""SDK-independent stdio client and explicit wire normalization."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/mcp_wire"
LEGACY_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MODERN_VERSION = "2026-07-28"


def isolated_env(directory: Path) -> dict[str, str]:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # An explicitly invalid peer URL stops discovery before any lease or socket.
    env.pop("UOINK_TOKEN", None)
    env.update(
        ZING_HOME=str(directory / "home"),
        ZING_PROMPTS_DIR=str(ROOT / "prompts"),
        UOINK_URL="disabled://mcp-wire",
        HOME=str(directory), USERPROFILE=str(directory),
        LOCALAPPDATA=str(directory / "appdata"),
        XDG_STATE_HOME=str(directory / "state"),
        HF_HOME=str(directory / "models"),
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
    )
    return env


class StdioClient:
    """Strict JSON lines; bounded waits and complete child cleanup."""

    def __init__(self, directory: Path, *, fixture_inputs=True, command=None, env=None):
        self.env = isolated_env(directory) if env is None else env
        if command is None:
            command = [sys.executable, "-P"] + (
                [str(ROOT / "tests/mcp_wire_child.py")] if fixture_inputs else
                ["-m", "myzing.cli", "serve-mcp"]
            )
        self.proc = subprocess.Popen(
            command, cwd=directory, env=self.env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        self.lines = queue.Queue()
        self.stderr = []
        self.transcript = []
        self.threads = [threading.Thread(target=self._stdout, daemon=True),
                        threading.Thread(target=self._stderr, daemon=True)]
        for thread in self.threads:
            thread.start()

    def _stdout(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _stderr(self):
        for line in self.proc.stderr:
            self.stderr.append(line)

    def exchange(self, request):
        self.proc.stdin.write(json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n")
        self.proc.stdin.flush()
        if "id" not in request:
            return None
        deadline = time.monotonic() + 60
        while True:
            try:
                line = self.lines.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise AssertionError("MCP timeout: " + "".join(self.stderr[-20:])) from None
            assert line is not None, "MCP exited: " + "".join(self.stderr[-20:])
            message = json.loads(line)  # Never discard polluted stdout.
            assert message.get("jsonrpc") == "2.0", message
            if "id" not in message:
                self.transcript.append({"notification": message})
                continue
            assert message["id"] == request["id"], message
            self.transcript.append({"request": request, "response": message})
            return message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
            raise AssertionError("MCP did not exit after stdin EOF") from None
        finally:
            for thread in self.threads:
                thread.join(timeout=2)
            self.proc.stdout.close()
            self.proc.stderr.close()
        if exc[0] is None:
            assert self.proc.returncode == 0, "".join(self.stderr[-20:])


def rpc(request_id, method, params=None):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def modern_params(**params):
    return dict(params, _meta={
        "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
    })


def canonical(value) -> str:
    """Only object-key order and outer JSON whitespace are canonicalized."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def normalize(request, response, env):
    """No blanket text/path/version removal: these are the only volatile fields."""
    response = copy.deepcopy(response)
    result = response.get("result", {})
    if request["method"] == "initialize":
        result["serverInfo"]["version"] = "<ZING_VERSION>"
    if request["method"] == "tools/call" and request["params"]["name"] == "zing_status":
        def status(payload):
            assert payload["workspace"]["root"] == env["ZING_HOME"]
            payload["workspace"]["root"] = "<ZING_HOME>"
            payload["version"] = "<ZING_VERSION>"
            return payload

        # SDK 1 emits indented JSON in text as well as structuredContent.
        block = result["content"][0]
        block["text"] = json.dumps(status(json.loads(block["text"])), indent=2, ensure_ascii=False)
        if "structuredContent" in result:
            result["structuredContent"] = status(result["structuredContent"])
    return response


def capture(directory):
    requests = [rpc(1, "initialize", {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "zing-wire", "version": "1"},
    }), {"jsonrpc": "2.0", "method": "notifications/initialized"},
        rpc(2, "tools/list", {}), rpc(3, "prompts/list", {}),
        rpc(4, "resources/list", {}), rpc(5, "resources/templates/list", {})]
    from myzing.prompt_pack import available_prompts

    for name, arguments in [
        ("zing_status", {}), ("list_presets", {}),
        ("meme_templates", {"search": "drake"}),
        ("get_prompt", {"name": "study"}),
        ("get_breakdown", {"slug": "missing-wire-fixture"}),
    ]:
        requests.append(rpc(len(requests), "tools/call", {"name": name, "arguments": arguments}))
    for name in available_prompts():
        requests.append(rpc(len(requests), "prompts/get", {"name": name, "arguments": {}}))
    with StdioClient(directory) as client:
        exchanges = [{"request": request, "response": normalize(request, response, client.env)
                      if response is not None else None}
                     for request in requests for response in [client.exchange(request)]]
    return exchanges
