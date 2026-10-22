"""Capture only with the original SDK 1 source; never bless SDK 2 as baseline."""
import argparse
from importlib.metadata import version
from pathlib import Path
import tempfile

from mcp_wire import FIXTURES, canonical, capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=FIXTURES / "sdk1.json")
    args = parser.parse_args()
    assert version("mcp") == "1.28.1", "Capture requires the original MCP 1.28.1"
    from myzing import mcp_server

    assert "mcp.server.fastmcp" in Path(mcp_server.__file__).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="zing-wire-sdk1-") as directory:
        exchanges = capture(Path(directory))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical({"sdk": version("mcp"), "exchanges": exchanges}),
                           encoding="utf-8", newline="\n")
    print(f"Recorded {len(exchanges)} exchanges from MCP {version('mcp')}: {args.output}")


if __name__ == "__main__":
    main()
