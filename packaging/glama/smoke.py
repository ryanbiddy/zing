"""Probe the installed console command without FFmpeg, models, or network.

Run with the Python in a fresh .[mcp] venv:
  python packaging/glama/smoke.py --workspace zing-workspace/glama-proof
The workspace must be new. This is a host fallback, not a Docker build test.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import runpy
import shutil
import sys


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TOOLS = runpy.run_path(str(ROOT / "packaging/mcp_stdio_smoke.py"))["EXPECTED_TOOLS"]


async def probe(workspace: Path) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    workspace.mkdir(parents=True, exist_ok=False)
    guard = workspace / "guard"
    guard.mkdir()
    # Python loads this before the console entry point. Record and reject any
    # attempted DNS lookup or socket connection during startup and discovery.
    (guard / "sitecustomize.py").write_text(
        "import os, pathlib, socket, sys\n"
        "root = pathlib.Path(os.environ['ZING_HOME']).parent\n"
        "(root / 'guard-loaded').touch()\n"
        "def guard(event, args):\n"
        "    if event in {'socket.connect', 'socket.getaddrinfo'}:\n"
        # Windows implements asyncio's self-pipe with socket.socketpair's
        # loopback fallback. Allow only that stdlib function, not peer traffic.
        "        fallback = getattr(socket, '_fallback_socketpair', None)\n"
        "        if event == 'socket.connect' and fallback is not None and sys._getframe(1).f_code is fallback.__code__:\n"
        "            return\n"
        "        with (root / 'network-attempts').open('a') as stream:\n"
        "            stream.write(event + '\\n')\n"
        "        raise RuntimeError('Network forbidden during MCP startup proof')\n"
        "sys.addaudithook(guard)\n",
        encoding="utf-8",
    )
    executable = Path(sys.executable).parent / ("zing.exe" if os.name == "nt" else "zing")
    if not executable.is_file():
        raise RuntimeError("Install .[mcp] into this interpreter's venv first")
    env = dict(os.environ)
    for key in ("UOINK_TOKEN", "ZING_PROMPTS_DIR", "ZING_PRESETS_DIR"):
        env.pop(key, None)
    env.update(
        PATH=str(executable.parent),
        PYTHONPATH=str(guard),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
        ZING_HOME=str(workspace / "home"),
        HF_HOME=str(workspace / "models"),
        UOINK_URL="http://127.0.0.1:1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    params = StdioServerParameters(
        command=str(executable), args=["serve-mcp"], env=env, cwd=workspace,
    )
    if any(shutil.which(name, path=env["PATH"]) for name in ("ffmpeg", "ffprobe")):
        raise RuntimeError("The proof requires a venv without FFmpeg or ffprobe")
    metadata = importlib.metadata.metadata("myzing")
    if "mcp-name: io.github.ryanbiddy/zing" not in metadata.get_payload():
        raise RuntimeError("Installed package long description lacks the PyPI verification marker")
    with (workspace / "stderr.log").open("w", encoding="utf-8") as stderr:
        async with stdio_client(params, errlog=stderr) as streams:
            async with ClientSession(*streams) as client:
                initialized = await client.initialize()
                listing = await client.list_tools()
                names = {tool.name for tool in listing.tools}
                if names != EXPECTED_TOOLS:
                    raise RuntimeError(
                        f"Tool drift: missing={sorted(EXPECTED_TOOLS - names)}, "
                        f"extra={sorted(names - EXPECTED_TOOLS)}"
                    )
                identity = initialized.server_info.model_dump(by_alias=True, exclude_none=True)
                if identity.get("name") != "zing" or identity.get("version") != importlib.metadata.version("myzing"):
                    raise RuntimeError(f"Unexpected server identity: {identity}")
    if not (workspace / "guard-loaded").is_file():
        raise RuntimeError("The child process did not load the network guard")
    if (workspace / "network-attempts").exists():
        raise RuntimeError("Startup or discovery attempted network access")
    if (workspace / "models").exists():
        raise RuntimeError("Startup or discovery created a model cache")
    return {
        "ok": True,
        "command": ["zing", "serve-mcp"],
        "server": identity,
        "tool_count": len(names),
        "tools": sorted(names),
        "matches_expected_tools": True,
        "installed_pypi_marker": True,
        "network_attempts": 0,
        "model_cache_created": False,
        "ffmpeg_on_child_path": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    result = asyncio.run(asyncio.wait_for(probe(workspace), timeout=60))
    payload = json.dumps(result, indent=2) + "\n"
    (workspace / "result.json").write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
