"""Build the wheel offline and inspect its public metadata and runtime files."""
import email
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
FILES = ("package.json", "package-lock.json", "shot.cjs")


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    pytest.importorskip("setuptools", minversion="77", reason="setuptools 77+ is needed to build the wheel offline")
    root = tmp_path_factory.mktemp("release-wheel")
    shutil.copytree(ROOT / "src/myzing", root / "src/myzing", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE.md", "docs/THIRD-PARTY-NOTICES.md"):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    result = subprocess.run([sys.executable, "-c",
                             "from setuptools.build_meta import build_wheel; build_wheel('dist')"],
                            cwd=root, env={**os.environ, "PIP_NO_INDEX": "1"},
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return next((root / "dist").glob("*.whl"))


def test_wheel_contains_factory_sidecar(wheel):
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for name in FILES:
            path = "myzing/_data/factory/sidecar/" + name
            assert path in names, path
            assert archive.read(path) == (ROOT / "tools/factory-sidecar" / name).read_bytes()


def test_release_metadata():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["authors"] == [{"name": "Ryan Biddy"}]
    assert project["keywords"] == ["video", "shorts", "clips", "podcast", "ffmpeg", "mcp", "captions"]
    classifiers = {
        "Development Status :: 4 - Beta", "Environment :: Console",
        "Intended Audience :: End Users/Desktop", "Operating System :: OS Independent",
        "Programming Language :: Python :: 3 :: Only", "Topic :: Multimedia :: Video",
        *(f"Programming Language :: Python :: 3.{minor}" for minor in range(11, 15)),
    }
    assert set(project["classifiers"]) == classifiers
    assert project["requires-python"] == ">=3.11"
    urls = {
        "Homepage": "https://myzing.app", "Source": "https://github.com/ryanbiddy/zing",
        "Issues": "https://github.com/ryanbiddy/zing/issues",
        "Changelog": "https://github.com/ryanbiddy/zing/blob/main/CHANGELOG.md",
        "Documentation": "https://github.com/ryanbiddy/zing/tree/main/docs",
    }
    assert project["urls"] == urls


def test_wheel_metadata(wheel):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(name))
    assert metadata["Author"] == "Ryan Biddy" and metadata["Author-email"] is None
    assert metadata["License-Expression"] == "MIT"
    assert metadata["Requires-Python"] == project["requires-python"]
    assert metadata["Keywords"].split(",") == project["keywords"]
    assert set(metadata.get_all("Classifier")) == set(project["classifiers"])
    assert set(metadata.get_all("Project-URL")) == {f"{key}, {value}" for key, value in project["urls"].items()}
