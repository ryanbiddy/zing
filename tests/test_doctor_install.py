"""Doctor repairs the environment that owns the installed Zing command."""
import sys

import pytest

from myzing import __version__, doctor


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    monkeypatch.setattr(doctor, "_which", lambda name: None)


@pytest.mark.parametrize("prefix,command", [
    ("/home/user/.local/share/pipx/venvs/myzing", "pipx install --force"),
    (r"C:\Users\user\pipx\venvs\myzing", "pipx install --force"),
    ("/home/user/.local/share/uv/tools/myzing", "uv tool install --force"),
    (r"C:\Users\user\AppData\Roaming\uv\tools\myzing", "uv tool install --force"),
    ("/opt/venvs/myzing", "python -m pip install"),
])
@pytest.mark.parametrize("check,extra", [
    ("check_ytdlp", "study"), ("check_scenedetect", "study"),
    ("check_whisper", "study"), ("check_ocr", "study"), ("check_caption_geometry", "study"),
    ("check_fonts", "fonts"), ("check_pillow", "memes"), ("check_layout", "layout"),
    ("check_screen", "screen"), ("check_color", "color"),
    ("check_audio", "audio"), ("check_audio_ml", "audio-ml"),
])
def test_missing_extra_uses_installer(monkeypatch, prefix, command, check, extra):
    monkeypatch.setattr(sys, "prefix", prefix)
    if check == "check_screen":
        monkeypatch.setattr(sys, "platform", "darwin")
    result = getattr(doctor, check)()
    assert f'{command} "myzing[{extra}]=={__version__}"' in result.fix
    assert "or: pip install" not in result.fix


@pytest.mark.parametrize("prefix,expected", [
    ("/opt/pipx/venvs/myzing", 'pipx runpip myzing install -U "yt-dlp[default]"'),
    ("/opt/uv/tools/myzing", 'uv pip install --python "{python}" -U "yt-dlp[default]"'),
    ("/opt/venvs/myzing", 'python -m pip install -U "yt-dlp[default]"'),
])
def test_dependency_update_uses_installer(monkeypatch, prefix, expected):
    from datetime import date
    monkeypatch.setattr(sys, "prefix", prefix)
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(doctor, "_run_version_cached", lambda cmd: "2020.01.01")
    assert expected.format(python=sys.executable) in doctor.check_ytdlp(date(2026, 11, 9)).fix
