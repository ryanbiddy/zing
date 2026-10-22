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
        env = dict(env, UOINK_URL="disabled://mcp-stdio-test")
        env.pop("UOINK_TOKEN", None)
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
        # Final review P3-1: serverInfo.version used to be the SDK's own
        # version — meaningless in client logs. It must be OUR version.
        from myzing.mcp_server import _version

        assert result["serverInfo"]["version"] == _version()
        c.send("notifications/initialized", {}, notify=True)
        yield c
    finally:
        c.close()


EXPECTED_TOOLS = {
    "plan_drafts",
    "match_start",
    "match_status",
    "still_concepts",
    "still_render",
    "inspect_timeline",
    "meme_templates",
    "meme_ideas",
    "meme_check",
    "meme_render",
    "brief_questions",
    "brief_save",
    "meme_render_video",
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


def test_brief_tools_roundtrip(client, tmp_path):
    from myzing.project.api import init_project

    root = tmp_path / "brief-project"
    root.mkdir()
    init_project("uoink:example", root, root)

    def call(name, arguments):
        response = client.send("tools/call", {"name": name, "arguments": arguments})
        assert not response.get("isError"), response
        return json.loads(next(block["text"] for block in response["content"] if block["type"] == "text"))

    questions = call("brief_questions", {})
    assert questions["ok"] and len(questions["questions"]) == 6
    saved = call("brief_save", {"project": str(root), "answers": {"exact_spellings": ["Zoë"]}})
    assert saved["ok"] and saved["brief"]["exact_spellings"] == ["Zoë"]
    assert json.loads((root / "brief.json").read_text(encoding="utf-8")) == saved["brief"]
    bad = call("brief_save", {"project": str(root), "answers": {"aspect": "wrong"}})
    assert bad["ok"] is False and "aspect" in bad["error"]


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
        19: "nineteen", 20: "twenty", 23: "twenty-three", 24: "twenty-four", 26: "twenty-six", 27: "twenty-seven", 28: "twenty-eight", 30: "thirty", 32: "thirty-two",
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


def test_meme_tools_roundtrip_without_network(client):
    def call(name, arguments):
        result = client.send("tools/call", {"name": name, "arguments": arguments})
        assert result.get("isError") in (False, None)
        assert all(c["type"] == "text" for c in result["content"])
        return json.loads(result["content"][0]["text"])

    assert call("meme_templates", {"search": "drake"})["templates"][0]["id"] == "drake"
    idea = call("meme_ideas", {"topic": "builds", "template": "db", "n": 1})["ideas"][0]
    assert len(idea["texts"]) == 3
    assert call("meme_check", {"texts": idea["texts"], "template": "db"})["valid"]
    invalid = call("meme_check", {"texts": ["a" * 71]})
    assert invalid["ok"] and invalid["problems"][0]["code"] == "line_too_long"
    assert not call("meme_render", {"texts": ["hello"]})["ok"]
    assert not call("meme_render_video", {"texts": ["hello"]})["ok"]


def test_meme_render_stdio_returns_a_path(client, tmp_path):
    image_module = pytest.importorskip("PIL.Image")
    source = tmp_path / "photo.png"
    target = tmp_path / "meme.png"
    image_module.new("RGB", (200, 200), "#729168").save(source)
    result = client.send("tools/call", {"name": "meme_render", "arguments": {
        "texts": ["setup", "payoff"], "image": str(source), "out": str(target),
    }})
    assert result.get("isError") in (False, None)
    assert all(c["type"] == "text" for c in result["content"])
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] and Path(payload["path"]) == target
    assert target.is_file()


def test_tool_error_is_data_not_protocol_error(client):
    result = client.send(
        "tools/call",
        {"name": "get_breakdown", "arguments": {"slug": "nothing-here"}},
    )
    text = [c["text"] for c in result["content"] if c["type"] == "text"][0]
    payload = json.loads(text)
    assert payload["ok"] is False
    assert "list_breakdowns" in payload["error"]


# -- protocol-version negotiation (SG-4, 2026-07-19) -------------------------

@pytest.mark.parametrize("asked,expect", [
    # An old client still gets its own version back (backward compat) —
    # this is what the rest of this file's smoke tests exercise.
    ("2024-11-05", "2024-11-05"),
    ("2025-03-26", "2025-03-26"),
    ("2025-06-18", "2025-06-18"),
    ("2025-11-25", "2025-11-25"),
    # initialize selects the legacy era. Modern clients use server/discover
    # or inline metadata, tested in test_mcp_wire.py.
    ("2026-07-28", "2025-11-25"),
    ("2099-01-01", "2025-11-25"),
])
def test_protocol_version_negotiation(tmp_path, asked, expect):
    env = dict(os.environ)
    env["ZING_HOME"] = str(tmp_path / "zing-home")
    c = StdioClient(env)
    try:
        result = c.send(
            "initialize",
            {
                "protocolVersion": asked,
                "capabilities": {},
                "clientInfo": {"name": "zing-proto-test", "version": "0"},
            },
        )
        assert result["protocolVersion"] == expect
        assert result["serverInfo"]["name"] == "zing"
    finally:
        c.close()
