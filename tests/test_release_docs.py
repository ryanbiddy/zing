"""Published install examples and README links must work outside GitHub."""
import re
import shlex
import tomllib
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_install_examples_pin_release():
    docs = [ROOT / "README.md", *sorted(ROOT.glob("llms*.md")),
            *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "skills").rglob("*.md")),
            *sorted((ROOT / "plugins").rglob("README.md"))]
    found, stale = [], []
    for doc in docs:
        text = doc.read_text(encoding="utf-8").replace("\\\n", " ")
        for command in re.findall(r"\b(?:pipx install|uv tool install|pip install)\b[^`\n]*", text):
            for word in shlex.split(command):
                if re.match(r"myzing(?:\[|[=<>!~]|$)", word):
                    found.append((doc, word))
                    if not re.fullmatch(r"myzing(?:\[[\w,-]+\])?==" + re.escape(VERSION), word):
                        stale.append((str(doc.relative_to(ROOT)), command))
                elif re.search(r"(?:^|/)myzing-.*\.whl", word):
                    found.append((doc, word))
                    if not re.search(r"myzing-" + re.escape(VERSION) + r"-", word):
                        stale.append((str(doc.relative_to(ROOT)), command))
    assert found
    assert not stale, stale


def test_readme_links_are_absolute():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(<?([^\s)>]+)", text)
    targets += re.findall(r"^\s*\[[^\]]+\]:\s*<?([^\s>]+)", text, re.M)
    targets += re.findall(r'''(?:href|src)=["']([^"']+)["']''', text)
    assert targets
    assert not [target for target in targets if not urlsplit(target).scheme]


def test_readme_describes_the_release_candidate():
    text = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "release candidate" in text and VERSION in text
    assert "pre-alpha" not in text and "not on pypi" not in text
