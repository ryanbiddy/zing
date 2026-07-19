"""Zing CLI entry point: routes to per-command modules, each exposing
`run(argv: list[str]) -> int` and parsing its own arguments."""

from __future__ import annotations

import importlib
import sys

# User-facing top-level help (final review P2-6: the module docstring —
# internal routing notes — used to print here).
_USAGE = """\
zing — study short videos, build a taste profile, direct and render your own

usage: zing <command> [args]

commands:
  doctor      check your environment and print the exact fix for each gap
  setup       guided first run: study a preset pack or your own links
  study       measure a video (URL or local file) into a breakdown
  prompt      print a judgment prompt (study, compare, direct, taste)
  profile     build and inspect style profiles from studied videos
  assemble    turn a direction into a draft edit
  render      render an EDL to video
  thumbs      generate thumbnail candidates for a video
  serve-mcp   run the MCP server (connects Claude and other AI clients)

Most commands accept --help. To connect an AI client, start with:
  zing serve-mcp --print-config
"""

_COMMANDS = {
    "doctor": "myzing.doctor",
    "study": "myzing.study.command",
    "profile": "myzing.profile.command",
    "assemble": "myzing.assemble.command",
    "serve-mcp": "myzing.mcp_server",
    "prompt": "myzing.prompt_pack",
    "setup": "myzing.setup_flow",
    "render": "myzing.render.command",
    "thumbs": "myzing.thumbs",
}


def main(argv: list[str] | None = None) -> int:
    # Windows text-encoding honesty, two layers (final review P2-8):
    # - Redirected/piped output (scripts, agents, `> config.json`) gets
    #   the legacy console codepage (cp1252) and turns em dashes into
    #   mojibake — reconfigure non-tty streams to UTF-8, the encoding
    #   every consumer of piped output actually expects.
    # - Interactive consoles that still can't encode a character replace
    #   it instead of crashing print() (the original cp1252 fix).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                if not stream.isatty():
                    stream.reconfigure(encoding="utf-8", errors="replace")
                else:
                    stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    command, rest = argv[0], argv[1:]
    module_name = _COMMANDS.get(command)
    if module_name is None:
        print(f"zing: unknown command '{command}' (try: {', '.join(_COMMANDS)})")
        return 2
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        print(
            f"zing {command}: this install is missing {module_name} — "
            "reinstall zing (pip install --force-reinstall)"
        )
        return 2
    return int(module.run(rest))


if __name__ == "__main__":
    sys.exit(main())
