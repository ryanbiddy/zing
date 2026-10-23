"""Private studio handshake; never accepts executable code."""

import json
import sys

from .execute import run_confirmed
from .models import write_json


def main():
    payload = json.loads(sys.stdin.readline())
    try:
        result = run_confirmed(payload["answers"], progress=lambda line: print(line, flush=True))
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        result = {"ok": False, "status": "failed", "error": str(exc), "outputs": []}
    write_json(payload["result_path"], result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
