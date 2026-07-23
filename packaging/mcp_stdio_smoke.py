"""Exercise the installed Zing MCP server from a neutral directory.

This script is run by ``clean_host_check.py`` with the new virtual
environment's interpreter. It uses only the standard library in the client
process and launches the real installed ``myzing.cli serve-mcp`` entry point.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading


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
TIMEOUT_SECONDS = 60


class StdioClient:
    def __init__(self, env: dict[str, str]):
        self.proc = subprocess.Popen(
            [sys.executable, "-P", "-m", "myzing.cli", "serve-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        self._stdout: queue.Queue[str] = queue.Queue()
        self._stderr: list[str] = []
        self._next_id = 0
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._stdout.put(line)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())

    def send(
        self,
        method: str,
        params: dict | None = None,
        *,
        notify: bool = False,
    ) -> dict | None:
        message: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notify:
            self._next_id += 1
            message["id"] = self._next_id
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        return self._wait_for(self._next_id)

    def _wait_for(self, request_id: int) -> dict:
        while True:
            try:
                line = self._stdout.get(timeout=TIMEOUT_SECONDS)
            except queue.Empty:
                stderr = "\n".join(self._stderr[-20:])
                raise RuntimeError(
                    f"MCP response {request_id} timed out; stderr:\n{stderr}"
                ) from None
            message = json.loads(line)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(
                    f"MCP response {request_id} failed: {message['error']}"
                )
            return message["result"]

    def close(self) -> None:
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            self.proc.kill()
            self.proc.wait(timeout=10)


def run_smoke() -> dict:
    from myzing import __version__

    env = dict(os.environ)
    client = StdioClient(env)
    try:
        initialized = client.send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "zing-clean-host",
                    "version": "0",
                },
            },
        )
        assert initialized is not None
        server = initialized["serverInfo"]
        if server != {"name": "zing", "version": __version__}:
            raise RuntimeError(
                f"unexpected product identity: {server}; "
                f"installed version={__version__}"
            )
        client.send("notifications/initialized", {}, notify=True)

        listed = client.send("tools/list", {})
        assert listed is not None
        tools = {tool["name"] for tool in listed["tools"]}
        if tools != EXPECTED_TOOLS:
            raise RuntimeError(
                "installed MCP tool surface drift: "
                f"missing={sorted(EXPECTED_TOOLS - tools)}, "
                f"extra={sorted(tools - EXPECTED_TOOLS)}"
            )

        called = client.send(
            "tools/call",
            {"name": "zing_status", "arguments": {}},
        )
        assert called is not None
        if called.get("isError") is True:
            raise RuntimeError(f"zing_status returned an MCP error: {called}")
        text = next(
            (
                block["text"]
                for block in called.get("content", [])
                if block.get("type") == "text"
            ),
            None,
        )
        payload = json.loads(text) if text else {}
        if payload.get("ok") is not True:
            raise RuntimeError(f"zing_status returned invalid data: {payload}")

        return {
            "ok": True,
            "server": server,
            "tool_count": len(tools),
            "called": "zing_status",
        }
    finally:
        client.close()


def main() -> int:
    try:
        payload = run_smoke()
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
