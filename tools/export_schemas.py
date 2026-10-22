"""Regenerate package schemas, or fail if checked-in copies are stale."""

import argparse
import json
from pathlib import Path

from myzing.schema_export import schemas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "src/myzing/_data/schemas")
    args = parser.parse_args()
    for name, schema in schemas().items():
        payload = (json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        path = args.out / name
        if args.check:
            if not path.is_file() or path.read_bytes() != payload:
                parser.exit(1, f"Stale schema: {path}. Run uv run python tools/export_schemas.py\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        print(path)


if __name__ == "__main__":
    main()
