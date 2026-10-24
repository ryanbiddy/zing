"""Release gates must fail on drift and on missing distributable assets."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_versions_match_every_surface():
    version = load("release_notes").release_version()
    from myzing import __version__
    assert version == __version__
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert load("release_notes").notes(version, text)


@pytest.mark.parametrize("surface", ["runtime", "registry", "package", "mcpb", "prompt", "lock", "pin"])
def test_version_parity_rejects_drift(tmp_path, surface):
    for name in ("pyproject.toml", "src/myzing/__init__.py", "server.json", "packaging/mcpb/manifest.json",
                 "uv.lock", "docs/DIRECTORY-SUBMISSIONS.md", "docs/RELEASING.md", "docs/CONNECT.md"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    shutil.copytree(ROOT / "src/myzing/_data/prompts", tmp_path / "src/myzing/_data/prompts")
    if surface in {"registry", "package", "mcpb"}:
        path = tmp_path / ("packaging/mcpb/manifest.json" if surface == "mcpb" else "server.json")
        data = json.loads(path.read_text())
        (data["packages"][0] if surface == "package" else data)["version"] = "999.0.0"
        path.write_text(json.dumps(data))
    else:
        path = tmp_path / {"runtime": "src/myzing/__init__.py", "prompt": "prompts/study.md",
                           "lock": "uv.lock", "pin": "docs/RELEASING.md"}[surface]
        path.write_text(path.read_text(encoding="utf-8").replace("1.0.0rc1", "999.0.0"), encoding="utf-8")
    with pytest.raises(ValueError):
        load("release_notes").release_version(tmp_path)


def test_changelog_extracts_only_requested_release():
    module = load("release_notes")
    assert module.notes("1.0.0rc1", "# Log\n## 1.0.0rc1\nNew.\n## 0.1.0\nOld.\n") == "New.\n"
    with pytest.raises(ValueError):
        module.notes("2.0", "## 1.0\nOld\n")


def test_wheel_audit_rejects_missing_data_and_private_files(tmp_path):
    audit = load("audit_dist").audit
    wheel = tmp_path / "test.whl"
    files = {p.relative_to(ROOT / "src").as_posix(): p.read_bytes()
             for p in (ROOT / "src/myzing/_data").rglob("*") if p.is_file()}
    for name in ("LICENSE", "NOTICE.md", "docs/THIRD-PARTY-NOTICES.md"):
        files["myzing-1.dist-info/licenses/" + name] = (ROOT / name).read_bytes()

    def write():
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)

    write()
    assert audit(wheel)["ok"]
    license_name = "myzing/_data/fonts/Anton-OFL.txt"
    data = files.pop(license_name)
    write()
    with pytest.raises(AssertionError, match="Missing runtime file"):
        audit(wheel)
    files[license_name] = data
    files["zing-workspace/private.json"] = b"{}"
    write()
    with pytest.raises(AssertionError):
        audit(wheel)


def test_release_workflow_is_manual_gated_and_tokenless():
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    triggers = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.findall(r"^  (\w+):", triggers, re.M) == ["workflow_dispatch"]
    assert "options: [testpypi, pypi]" in triggers
    publish = text.split("\n  publish:", 1)[1].split("\n  draft-release:", 1)[0]
    assert "needs: [build, fresh-install]" in publish
    assert "name: ${{ inputs.target }}" in publish
    assert "id-token: write" in publish and "secrets." not in publish
    assert "checkout@" not in publish and "run:" not in publish
    assert "--draft --prerelease" in text
    assert "os: [ubuntu-latest, windows-latest, macos-latest]" in text
    for action in re.findall(r"uses: ([^\s]+)", text):
        assert re.fullmatch(r"[\w/-]+@(?:[a-f0-9]{40}|v\d+\.\d+\.\d+)", action), action


def test_fresh_install_guard_blocks_sockets_and_runs_both_extras():
    module = load("fresh_install_check")
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c", module.BLOCK_NETWORK +
                             "\nimport socket\nsocket.create_connection(('127.0.0.1', 1))"],
                            capture_output=True, text=True)
    assert result.returncode != 0 and "fresh-install: network disabled" in result.stderr
    result = subprocess.run([sys.executable, "-c", module.BLOCK_NETWORK +
                             "\nimport asyncio\nasync def main(): pass\nasyncio.run(main())"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
