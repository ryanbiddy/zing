"""Private handshake entry point; all pipeline children belong to its owner."""

import json
import sys

from .api import match


def main():
    options = json.loads(sys.stdin.readline())
    result = match(**options, progress=lambda line: print(line, flush=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
