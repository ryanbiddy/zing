"""Zing CLI entry point.

Conflict-free by design: this file routes to lane-owned command modules and
should almost never change. Each command module exposes
`run(argv: list[str]) -> int` and parses its own arguments.

  zing doctor            -> myzing.doctor            (Lane B)
  zing study <url|file>  -> myzing.study.command     (Lane A)
  zing serve-mcp         -> myzing.mcp_server        (Lane B)
  zing render <edl.json> -> myzing.render.command    (Lane C)
"""

from __future__ import annotations

import importlib
import sys

_COMMANDS = {
    "doctor": "myzing.doctor",
    "study": "myzing.study.command",
    "serve-mcp": "myzing.mcp_server",
    "render": "myzing.render.command",
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command, rest = argv[0], argv[1:]
    module_name = _COMMANDS.get(command)
    if module_name is None:
        print(f"zing: unknown command '{command}' (try: {', '.join(_COMMANDS)})")
        return 2
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        print(f"zing {command}: not implemented yet (see handoff/SPRINT-1-D1.md)")
        return 2
    return int(module.run(rest))


if __name__ == "__main__":
    sys.exit(main())
