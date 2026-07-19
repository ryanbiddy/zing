"""Zing CLI entry point: routes to per-command modules, each exposing
`run(argv: list[str]) -> int` and parsing its own arguments."""

from __future__ import annotations

import importlib
import sys

# One registry drives routing AND the help text (final review P2-6
# replaced docstring-help with a hand-written synopsis; this removes
# the remaining drift class — a command added here appears in help by
# construction, ordered as listed).
_COMMANDS: dict[str, tuple[str, str]] = {
    "doctor": ("myzing.doctor",
               "check your environment and print the exact fix for each gap"),
    "setup": ("myzing.setup_flow",
              "guided first run: study a preset pack or your own links"),
    "study": ("myzing.study.command",
              "measure a video (URL or local file) into a breakdown"),
    "prompt": ("myzing.prompt_pack",
               "print a judgment prompt (study, compare, direct, taste)"),
    "profile": ("myzing.profile.command",
                "build and inspect style profiles from studied videos"),
    "assemble": ("myzing.assemble.command",
                 "turn a direction into a draft edit"),
    "render": ("myzing.render.command",
               "render an EDL to video"),
    "thumbs": ("myzing.thumbs",
               "generate thumbnail candidates for a video"),
    "serve-mcp": ("myzing.mcp_server",
                  "run the MCP server (connects Claude and other AI clients)"),
}


def _usage() -> str:
    width = max(map(len, _COMMANDS)) + 3
    rows = "\n".join(
        f"  {name:<{width}}{help_line}"
        for name, (_, help_line) in _COMMANDS.items()
    )
    return (
        "zing — study short videos, build a taste profile, direct and "
        "render your own\n\n"
        "usage: zing <command> [args]\n\n"
        f"commands:\n{rows}\n\n"
        "Most commands accept --help. To connect an AI client, start with:\n"
        "  zing serve-mcp --print-config\n"
    )


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
        print(_usage())
        return 0
    command, rest = argv[0], argv[1:]
    module_name = _COMMANDS.get(command, (None, ""))[0]
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
