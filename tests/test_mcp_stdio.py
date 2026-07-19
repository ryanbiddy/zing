"""The Lane B gate: the MCP server boots and speaks the protocol over stdio.

uoink's C-01 pattern: launch the real entry point as a subprocess with
``python -P`` (PYTHONSAFEPATH — recreates the embeddable-Python condition
that crashed every Claude Desktop launch of uoink before its sys.path fix)
and drive the actual client handshake:

    initialize -> notifications/initialized -> tools/list
    -> tools/call zing_status -> prompts/list

The subprocess gets an isolated ZING_HOME so the test never touches a real
workspace. Skips loudly when the mcp SDK is missing so a local run without
it can't report false confidence.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

try:
    import mcp  # noqa: F401

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False

pytestmark = pytest.mark.skipif(
    not HAVE_SDK, reason='mcp SDK not installed (pip install "myzing[mcp]")'
)

TIMEOUT = 60  # generous: Windows CI process spawn + pydantic import is slow


class StdioClient:
    """Minimal MCP stdio client: one request in flight, honest timeouts."""

    def __init__(self, env: dict[str, str]):
        self.proc = subprocess.Popen(
            [sys.executable, "-P", "-m", "myzing.cli", "serve-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        self._lines: queue.Queue[str] = queue.Queue()
        self._stderr: list[str] = []
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        self._next_id = 0

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._lines.put(line)

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr.append(line)

    def send(self, method: str, params: dict | None = None, *, notify: bool = False):
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._next_id += 1
            msg["id"] = self._next_id
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        return self._read_response(self._next_id)

    def _read_response(self, want_id: int) -> dict:
        while True:
            try:
                line = self._lines.get(timeout=TIMEOUT)
            except queue.Empty:
                stderr = "".join(self._stderr[-20:])
                raise AssertionError(
                    f"no response for id={want_id} within {TIMEOUT}s; "
                    f"server stderr:\n{stderr}"
                ) from None
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("id") == want_id:
                assert "error" not in msg, f"protocol error: {msg['error']}"
                return msg["result"]
            # notifications and unrelated ids are skipped

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def client(tmp_path):
    env = dict(os.environ)
    env["ZING_HOME"] = str(tmp_path / "zing-home")
    env["ZING_PROMPTS_DIR"] = str(tmp_path / "no-prompts")
    c = StdioClient(env)
    try:
        result = c.send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "zing-smoke-test", "version": "0"},
            },
        )
        assert result["serverInfo"]["name"] == "zing"
        c.send("notifications/initialized", {}, notify=True)
        yield c
    finally:
        c.close()


EXPECTED_TOOLS = {
    "study_video",
    "study_uoink_item",
    "import_shot_list",
    "get_breakdown",
    "list_breakdowns",
    "save_judgment",
    "zing_status",
    "get_prompt",
    "push_to_uoink",
    "generate_thumbnails",
    "get_frames",
    "build_profile",
    "get_profile",
    "list_profiles",
    "render_edl",
    "get_render",
    "export_otio",
    "list_presets",
    "setup_taste",
}


def test_connect_doc_names_every_tool():
    """B-S6 doc-drift gate: CONNECT.md promised "twelve tools" while the
    server served nineteen — the count and enumeration now live under
    the same pin as the registry itself. Adding a tool without
    documenting it (or documenting a tool that no longer exists) fails
    here, not in a launch review."""
    doc = (
        Path(__file__).resolve().parents[1] / "docs" / "CONNECT.md"
    ).read_text(encoding="utf-8")
    undocumented = {t for t in EXPECTED_TOOLS if f"`{t}`" not in doc}
    assert not undocumented, f"CONNECT.md is missing: {sorted(undocumented)}"
    spelled = {
        3: "three", 12: "twelve", 17: "seventeen", 18: "eighteen",
        19: "nineteen", 20: "twenty",
    }.get(len(EXPECTED_TOOLS))
    assert spelled and spelled in doc, (
        f"CONNECT.md's tool count is stale — the server serves "
        f"{len(EXPECTED_TOOLS)} tools"
    )
    # Final review P2-7's second half: the doc also claimed "both
    # prompt-pack prompts" against a four-prompt pack. Pin that count too.
    from myzing.prompt_pack import available_prompts

    n_prompts = len(available_prompts())
    word = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}[n_prompts]
    assert f"all {word} prompt-pack prompts" in doc, (
        f"CONNECT.md's prompt count is stale — the pack has {n_prompts}"
    )


def test_tools_list_and_zing_status_roundtrip(client):
    tools = client.send("tools/list", {})["tools"]
    names = {t["name"] for t in tools}
    assert names == EXPECTED_TOOLS
    for t in tools:
        assert t.get("description"), f"tool {t['name']} has no description"

    result = client.send("tools/call", {"name": "zing_status", "arguments": {}})
    assert result.get("isError") in (False, None)
    text_blocks = [c["text"] for c in result["content"] if c["type"] == "text"]
    assert text_blocks, "zing_status returned no text content"
    payload = json.loads(text_blocks[0])
    assert payload["ok"] is True
    assert "environment" in payload and "workspace" in payload
    assert payload["workspace"]["breakdowns"] == 0


def test_prompts_list_answers_even_with_no_pack(client):
    result = client.send("prompts/list", {})
    assert result["prompts"] == []  # empty pack dir: honest empty, no crash


def test_tool_error_is_data_not_protocol_error(client):
    result = client.send(
        "tools/call",
        {"name": "get_breakdown", "arguments": {"slug": "nothing-here"}},
    )
    text = [c["text"] for c in result["content"] if c["type"] == "text"][0]
    payload = json.loads(text)
    assert payload["ok"] is False
    assert "list_breakdowns" in payload["error"]
