from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
PYTHON_SCRIPT_COMMAND = re.compile(
    r"\bpython(?:3)?\s+([A-Za-z0-9_./\\-]+\.py)\b"
)


def test_documented_python_script_commands_point_to_shipped_files() -> None:
    missing: list[str] = []
    for doc in PRODUCT_DOCS:
        text = doc.read_text(encoding="utf-8")
        for match in PYTHON_SCRIPT_COMMAND.finditer(text):
            script = match.group(1).replace("\\", "/")
            if not (ROOT / script).is_file():
                missing.append(f"{doc.relative_to(ROOT)} -> {script}")

    assert not missing, "documented Python commands reference missing files: " + ", ".join(
        missing
    )


def test_readme_names_optional_loopback_network_calls() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()

    assert "the only network calls it makes are" not in readme
    assert "external network calls" in readme
    assert "loopback http" in readme
    assert "uoink" in readme
