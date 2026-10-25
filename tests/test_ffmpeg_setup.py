"""Setup must stay useful on CI's lean machine with no FFmpeg installed."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from myzing import doctor, ffmpeg_setup as setup, setup_flow


@pytest.fixture
def build(monkeypatch):
    state = {"version": "8.1.2", "filters": setup.REQUIRED_FILTERS | {"ass"},
             "encoders": {"libx264"}}
    def probe(argv):
        if argv[-1] == "-version":
            return "ffmpeg version " + state["version"]
        if argv[-1] == "-filters":
            return "\n".join(f" T.. {name} V->V description" for name in state["filters"])
        return "\n".join(f" V....D {name} description" for name in state["encoders"])
    monkeypatch.setattr(setup, "_probe", probe)
    return state


@pytest.mark.parametrize("platform,manager,command", [
    ("win32", "winget", "winget install --id Gyan.FFmpeg -e"),
    ("darwin", "brew", "brew install ffmpeg-full"),
    ("linux", "apt", "sudo apt install ffmpeg"),
    ("linux", "dnf", "sudo dnf install ffmpeg"),
])
def test_os_command_and_doctor_failures(monkeypatch, build, platform, manager, command):
    monkeypatch.setattr(setup.sys, "platform", platform)
    monkeypatch.setattr(setup.shutil, "which", lambda n: n if n == manager else None)
    assert setup.install_plan()["command"] == command
    monkeypatch.setattr(doctor, "_which", lambda n: n)
    assert doctor.check_ffmpeg().ok
    build.update(filters=set(), encoders=set(), version="5.1.6")
    check = doctor.check_ffmpeg()
    assert not check.ok and command in check.fix
    for missing in ("libx264", "libass", "drawtext", "xfade", ">= 6.0"):
        assert missing in check.detail
    monkeypatch.setattr(doctor, "_which", lambda n: None)
    check = doctor.check_ffmpeg()
    assert not check.ok and "ffmpeg not found" in check.detail and "ffprobe not found" in check.detail


@pytest.mark.parametrize("version,ok", [("6.0", True), ("6.1.1", True), ("9.0", True),
                                        ("n8.1.2", True), ("N-unknown", False), ("4.4", False)])
def test_version_floor(build, version, ok):
    build["version"] = version
    assert setup.inspect_build("ffmpeg", "ffprobe")["ok"] is ok


@pytest.mark.parametrize("name", sorted(setup.REQUIRED_FILTERS))
def test_each_required_filter(build, name):
    build["filters"] -= {name}
    assert name + " filter" in setup.inspect_build("ffmpeg", "ffprobe")["missing"]


def test_subtitles_also_proves_libass(build):
    build["filters"] = setup.REQUIRED_FILTERS | {"subtitles"}
    assert setup.inspect_build("ffmpeg", "ffprobe")["ok"]


@pytest.mark.parametrize("failure", [OSError("denied"), subprocess.TimeoutExpired("ffmpeg", 30), RuntimeError("probe failed")])
def test_probe_failure_is_actionable(monkeypatch, failure):
    def fail(argv):
        raise failure
    monkeypatch.setattr(setup, "_probe", fail)
    result = setup.inspect_build("ffmpeg", "ffprobe")
    assert not result["ok"] and result["errors"]


@pytest.fixture
def terminal(monkeypatch, build, capsys):
    monkeypatch.setattr(setup.sys, "platform", "win32")
    monkeypatch.setattr(setup, "_interactive", lambda: True)
    monkeypatch.setattr(setup.shutil, "which", lambda n: n)
    calls = []
    def run(argv, **kwargs):
        assert not kwargs.get("shell")
        calls.append(argv)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(setup.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("answer", ["", "no", "y", "sure"])
def test_decline_even_with_yes_flag(terminal, monkeypatch, answer):
    monkeypatch.setattr("builtins.input", lambda _: answer)
    assert setup_flow.run(["--ffmpeg", "--yes"]) == 0
    assert terminal == []


@pytest.mark.parametrize("flags", [["--json"], ["--non-interactive"], []])
def test_noninteractive_never_installs(terminal, monkeypatch, capsys, flags):
    monkeypatch.setattr(setup, "_interactive", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("prompted"))
    assert setup_flow.run(["--ffmpeg", "--yes", *flags]) == 0
    out = capsys.readouterr().out
    if "--json" in flags:
        assert json.loads(out)["executed"] is False
    assert "winget install --id Gyan.FFmpeg -e" in out
    assert terminal == []


def test_explicit_print_flags_on_tty(terminal, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("prompted"))
    for flag in ("--json", "--non-interactive"):
        assert setup_flow.run(["--ffmpeg", flag]) == 0
    assert terminal == []


def test_yes_without_ffmpeg_never_installs(terminal):
    assert setup_flow.run(["--yes"]) == 2
    assert terminal == []


def test_consented_install_rechecks_capabilities(terminal, monkeypatch, build, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert setup_flow.run(["--ffmpeg"]) == 0
    assert terminal == [["winget", "install", "--id", "Gyan.FFmpeg", "-e"]]
    assert "libx264, libass, drawtext" in capsys.readouterr().out
    build["filters"] -= {"ass"}
    assert setup_flow.run(["--ffmpeg"]) == 1
    assert "libass" in capsys.readouterr().out


def test_package_manager_failure_is_not_success(terminal, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=7))
    assert setup_flow.run(["--ffmpeg"]) == 1
    assert "exit: 7" in capsys.readouterr().out


def test_missing_package_manager_and_eof(terminal, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    monkeypatch.setattr(setup.shutil, "which", lambda n: None)
    assert setup_flow.run(["--ffmpeg"]) == 1
    assert terminal == []
    def eof(_):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert setup_flow.run(["--ffmpeg"]) == 0
    assert terminal == []


def test_reject_mixed_actions(terminal):
    with pytest.raises(SystemExit):
        setup_flow.run(["--ffmpeg", "--speech-model", "small.en", "--yes"])
    assert terminal == []
