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


def test_readme_discloses_whisper_model_download_and_peer_calls() -> None:
    from myzing.study import transcribe

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lowered = readme.lower()

    assert "a video URL only when you" in readme
    assert "Hugging Face" in readme
    assert "first `zing study`" in readme
    assert "never downloads one" in readme  # speech models only via consented setup
    assert transcribe.DEFAULT_MODEL in readme
    assert transcribe.ENV_MODEL in readme
    assert "ElevenLabs" in readme
    assert "loopback HTTP" in readme
    assert "Uoink" in readme
    assert "the only network calls it makes are" not in readme
    assert "external network calls are limited" not in lowered
