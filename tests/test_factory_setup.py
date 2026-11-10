"""Factory setup works in a checkout and from an installed wheel."""
import builtins
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from myzing import storage
from myzing.factory import command, tools
from myzing.render import hyperframes_adapter as hf


ROOT = Path(__file__).resolve().parents[1]
FILES = ("package.json", "package-lock.json", "shot.cjs")
RUN = subprocess.run


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    monkeypatch.delenv("ZING_FACTORY_SIDECAR", raising=False)

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(tools.subprocess, "run", refuse)


@pytest.mark.parametrize("layout", ["override", "checkout", "installed"])
def test_sidecar_directory(tmp_path, monkeypatch, layout):
    checkout = tmp_path / "checkout"
    monkeypatch.setattr(tools, "__file__", str(checkout / "src/myzing/factory/tools.py"))
    expected = storage.resolve_workspace() / "factory-sidecar"
    if layout in {"override", "checkout"}:
        expected = checkout / "tools/factory-sidecar"
        expected.mkdir(parents=True)
    if layout == "override":
        expected = tmp_path / "custom sidecar"
        monkeypatch.setenv("ZING_FACTORY_SIDECAR", str(expected))
    assert tools.sidecar_directory() == expected


def test_sidecar_uses_default_home(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "__file__", str(tmp_path / "lib/site-packages/myzing/factory/tools.py"))
    monkeypatch.delenv("ZING_HOME")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert tools.sidecar_directory() == tmp_path / ".zing/factory-sidecar"


@pytest.mark.parametrize("name", FILES)
def test_packaged_sidecar_matches_checkout(name):
    assert tools.data_path("sidecar", name).read_bytes() == (ROOT / "tools/factory-sidecar" / name).read_bytes()


@pytest.fixture
def npm(tmp_path, monkeypatch):
    directory = tmp_path / "sidecar"
    monkeypatch.setenv("ZING_FACTORY_SIDECAR", str(directory))
    monkeypatch.setattr(tools.shutil, "which", lambda name: name if name in {"node", "npm"} else None)
    return directory


@pytest.mark.parametrize("existing", ["absent", "ready", "old-lock", "missing-module"])
def test_factory_setup_copies_and_installs(npm, monkeypatch, capsys, existing):
    if existing != "absent":
        npm.mkdir()
        for name in FILES:
            shutil.copyfile(ROOT / "tools/factory-sidecar" / name, npm / name)
        (npm / "shot.cjs").write_text("old script", encoding="utf-8")
    if existing in {"ready", "old-lock"}:
        package = npm / "node_modules/playwright-core/package.json"
        package.parent.mkdir(parents=True)
        package.write_text("{}", encoding="utf-8")
    if existing == "old-lock":
        (npm / "package-lock.json").write_text("{}", encoding="utf-8")
    calls = []

    def run(argv, **kwargs):
        if argv == ["node", "--version"]:
            return subprocess.CompletedProcess(argv, 0, "v20.19.0", "")
        calls.append((argv, kwargs))
        out = capsys.readouterr().out
        assert str(npm) in out and "npm ci" in out
        assert argv == ["npm", "ci"] and Path(kwargs["cwd"]) == npm
        for name in FILES:
            assert (npm / name).read_bytes() == (ROOT / "tools/factory-sidecar" / name).read_bytes()
        package = npm / "node_modules/playwright-core/package.json"
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(tools.subprocess, "run", run)
    assert command.run(["setup"]) == 0
    assert "ready" in capsys.readouterr().out.lower()
    assert len(calls) == int(existing != "ready")
    for name in FILES:
        assert (npm / name).read_bytes() == (ROOT / "tools/factory-sidecar" / name).read_bytes()
    calls.clear()
    assert command.run(["setup"]) == 0
    assert "ready" in capsys.readouterr().out.lower() and calls == []


@pytest.mark.parametrize("failure", ["node", "npm", "old-node", "npm-failed"])
def test_factory_setup_errors(npm, monkeypatch, capsys, failure):
    monkeypatch.setattr(tools.shutil, "which", lambda name: None if name == failure else name)

    def run(argv, **kwargs):
        if argv == ["node", "--version"]:
            return subprocess.CompletedProcess(argv, 0, "v18.20.0" if failure == "old-node" else "v24.0.0", "")
        raise subprocess.CalledProcessError(1, argv, stderr="npm failed")
    monkeypatch.setattr(tools.subprocess, "run", run)
    assert command.run(["setup"]) == 2
    text = capsys.readouterr().err
    assert ("Node.js 20" if failure in {"node", "old-node"} else "npm") in text
    assert "Traceback" not in text


def test_factory_doctor_names_setup(npm, monkeypatch):
    with pytest.raises(tools.FactoryError, match="zing factory setup"):
        tools.node_sidecar()
    assert "zing factory setup" in tools.check()["sidecar"]["fix"]


def test_factory_doctor_needs_no_render_extras(npm, monkeypatch, capsys):
    original = builtins.__import__

    def load(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 1 and ("pipeline" in fromlist or name == "visuals"):
            raise ModuleNotFoundError("No module named 'PIL'")
        return original(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, "__import__", load)
    assert command.run(["doctor"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["sidecar"]["fix"] == "The factory sidecar is not installed. Run 'zing factory setup'."
    assert not result["stock_keys"]["ok"] and "myzing[factory]==" in result["stock_keys"]["fix"]


def test_hyperframes_names_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(hf.shutil, "which", lambda name: name)
    monkeypatch.setattr(hf.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "v24.0.0", ""))
    with pytest.raises(hf.HyperframesError, match="source checkout"):
        hf.check_install(sidecar=tmp_path)


@pytest.mark.parametrize("script", ["render", "shot"])
def test_javascript_loads_playwright_from_selected_sidecar(tmp_path, monkeypatch, script):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    directory = tmp_path / "selected sidecar"
    directory.mkdir()
    shutil.copyfile(ROOT / "tools/factory-sidecar/shot.cjs", directory / "shot.cjs")
    module = directory / "node_modules/playwright-core"
    module.mkdir(parents=True)
    (module / "index.js").write_text("exports.chromium = {launch: async () => {throw Error('selected playwright')}};", encoding="utf-8")
    scene = tmp_path / "scene.html"
    scene.write_text("", encoding="utf-8")
    data = tmp_path / "data.json"
    data.write_text("{}", encoding="utf-8")
    args = [str(tools.data_path("render.cjs")), str(scene), str(data), str(tmp_path / "frames")] if script == "render" else [
        str(directory / "shot.cjs"), "https://example.com", str(tmp_path / "shot.png")]
    result = RUN([node, *args], cwd=directory, capture_output=True, text=True, timeout=30)
    assert "selected playwright" in result.stdout + result.stderr
    assert "Cannot find module" not in result.stdout + result.stderr
