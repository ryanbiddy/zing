from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, which the base package supports.
    import tomli as tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_license_uses_spdx_expression() -> None:
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["license"] == "MIT"
