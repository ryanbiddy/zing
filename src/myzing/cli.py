"""Zing CLI entry point: routes to per-command modules, each exposing
`run(argv: list[str]) -> int` and parsing its own arguments."""

from __future__ import annotations

import importlib
import importlib.metadata
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
               "print a judgment prompt (study, compare, direct, taste, meme-writer)"),
    "profile": ("myzing.profile.command",
                "build and inspect style profiles from studied videos"),
    "assemble": ("myzing.assemble.command",
                 "turn a direction into a draft edit"),
    "render": ("myzing.render.command",
               "render an EDL to video"),
    "layout": ("myzing.layout.command",
               "plan caption boxes and paths around faces and platform UI"),
    "color": ("myzing.color.command",
              "match an SDR look approximation and apply a .cube LUT"),
    "thumbs": ("myzing.thumbs",
               "generate thumbnail candidates for a video"),
    "meme": ("myzing.memes.command",
             "browse templates, draft ideas, check text, and render still memes"),
    "serve-mcp": ("myzing.mcp_server",
                  "run the MCP server (connects Claude and other AI clients)"),
}


def _version() -> str:
    """Report the installed distribution version, the same way mcp_server
    does, so `zing --version` and the version the MCP server advertises to a
    client can never disagree. Falls back to the source constant when running
    from a checkout with no installed metadata."""
    try:
        return importlib.metadata.version("myzing")
    except importlib.metadata.PackageNotFoundError:
        from myzing import __version__

        return __version__


def _usage() -> str:
    width = max(map(len, _COMMANDS)) + 3
    rows = "\n".join(
        f"  {name:<{width}}{help_line}"
        for name, (_, help_line) in _COMMANDS.items()
    )
    return (
        "zing — study short videos, build a taste profile, direct and "
        "render your own\n\n"
        "usage: zing [--version] <command> [args]\n\n"
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
    if argv == ["--version"]:
        print(_version())
        return 0
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
