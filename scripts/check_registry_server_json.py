"""Check future MCP registry metadata against this checkout, without network.

Run with Python 3.11+: python scripts/check_registry_server_json.py [server.json]
This checks repository contracts, not remote schema validity or PyPI availability.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
NAME = "io.github.ryanbiddy/zing"
SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"


def check(server_path: Path) -> list[str]:
    root = server_path.parent
    data = json.loads(server_path.read_text(encoding="utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if not isinstance(data, dict):
        return ["expected a JSON object"]
    errors: list[str] = []
    for key, expected in (("$schema", SCHEMA), ("name", NAME), ("version", project["version"])):
        if data.get(key) != expected:
            errors.append(f"{key} must be {expected!r}")
    description = data.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 100:
        errors.append("description must be 1-100 characters, not blank")
    if project["name"] != "myzing":
        errors.append("project.name must be 'myzing'")
    if project.get("scripts", {}).get("zing") != "myzing.cli:main":
        errors.append("project.scripts must expose zing = myzing.cli:main")
    if not project.get("optional-dependencies", {}).get("mcp"):
        errors.append("project.optional-dependencies must provide the mcp extra")

    packages = data.get("packages")
    expected_package = {
        "registryType": "pypi",
        "identifier": project["name"],
        "version": project["version"],
        "transport": {"type": "stdio"},
    }
    if packages != [expected_package]:
        errors.append("packages must describe one matching PyPI package over stdio")

    # PyPI verification reads the published long description. Setuptools gets
    # that from project.readme, so check that source as well as the public README.
    readme = project.get("readme")
    readme_file = readme.get("file") if isinstance(readme, dict) else readme
    paths = {root / "README.md"}
    if isinstance(readme_file, str):
        path = (root / readme_file).resolve()
        if not path.is_relative_to(root.resolve()):
            errors.append("project.readme must stay inside the checkout")
        else:
            paths.add(path)
    else:
        errors.append("project.readme must name the file used for PyPI's long description")
    marker = f"mcp-name: {NAME}"
    for path in sorted(paths):
        if not path.is_file() or marker not in path.read_text(encoding="utf-8"):
            errors.append(f"{path.name} must contain the plain-text marker {marker!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = Path(args[0]).resolve() if args else ROOT / "server.json"
    try:
        errors = check(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors = [f"cannot read registry inputs: {exc}"]
    for error in errors:
        print(f"server.json: {error}", file=sys.stderr)
    if errors:
        return 1
    print("server.json matches pyproject.toml and the PyPI README marker (offline check only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
