"""Color CLI and dependency failures stay usable on a stdlib-only install."""

import builtins
import json
import os
import subprocess
import sys
from pathlib import Path

from myzing import cli, doctor
from myzing.color import command


def test_color_help_and_required_arguments(capsys):
    assert cli.main(["color", "--help"]) == 0
    assert "match" in capsys.readouterr().out
    assert command.run(["match"]) == 2
    assert "required" in capsys.readouterr().err


def test_missing_numpy_has_install_hint_and_json_error(monkeypatch, capsys):
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("absent")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", missing)
    assert command.run(["match", "--reference", "r", "--clip", "c", "--out", "o", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False and 'myzing[color]' in payload["error"]


def test_core_and_color_contracts_import_without_site_packages():
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([
        sys.executable, "-S", "-c",
        "import sys; import myzing.cli; import myzing.color.models; "
        "import myzing.color.command; assert 'numpy' not in sys.modules",
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_doctor_reports_optional_color_with_remedy(monkeypatch):
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    absent = doctor.check_color()
    assert not absent.ok and absent.tier == doctor.OPTIONAL
    assert "myzing[color]" in absent.fix
    monkeypatch.setattr(doctor, "_has_module", lambda name: name == "numpy")
    assert doctor.check_color().ok
