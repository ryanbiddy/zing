"""Generated labels use file fonts without system font discovery."""

import subprocess
import sys
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from conftest import drawtext_fontfile
from tools import plan_examples
from tools.eval.fonts import BUNDLED_FONT
from tools.eval.make_goldens import CASES, _graph_for
from tools.eval.real.run_real_eval import review_evidence


@pytest.mark.parametrize("path,expected", [
    (PureWindowsPath(r"C:\repo space\font.ttf"), r"C\:/repo space/font.ttf"),
    (PureWindowsPath(r"C:\O'Brien\font.ttf"), r"C\:/O'\\\''Brien/font.ttf"),
    ("/repo space/O'Brien/font.ttf", r"/repo space/O'\\\''Brien/font.ttf"),
    (Path("/fonts/[a],b;c.ttf"), "/fonts/[a],b;c.ttf"),
])
def test_drawtext_fontfile_escapes_filtergraph_path(path, expected):
    assert drawtext_fontfile(path) == expected


def test_goldens_use_bundled_font_from_any_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert BUNDLED_FONT.is_absolute() and BUNDLED_FONT.is_file()
    assert BUNDLED_FONT.name == "IBMPlexSans.ttf"
    for case in CASES:
        assert f"drawtext=fontfile='{drawtext_fontfile()}':" in _graph_for(case)


def test_plan_examples_use_bundled_font(tmp_path, monkeypatch):
    graphs = []

    def run(command, **kwargs):
        graphs.append(command[command.index("-filter_complex") + 1])
        Path(command[-1]).write_bytes(b"generated media")

    monkeypatch.setattr(plan_examples.subprocess, "run", run)
    plan_examples.example_project(tmp_path, media=True)
    assert len(graphs) == 3
    assert all(f"drawtext=fontfile='{drawtext_fontfile()}':" in graph for graph in graphs)


def test_real_eval_review_uses_bundled_font(tmp_path):
    commands = []
    runner = SimpleNamespace(command=lambda name, args: commands.append(args))
    manifest = {"clips": [{"id": "clip", "file": "clip.mp4", "fps": 30}]}
    labels = {"clips": {"clip": {"transition_windows": [[0, 1]]}}}
    review_evidence(manifest, labels, tmp_path, runner)
    assert len(commands) == 1
    graph = commands[0][commands[0].index("-vf") + 1]
    assert f"drawtext=fontfile='{drawtext_fontfile()}':" in graph


@pytest.mark.parametrize("script", [
    "tools/eval/make_goldens.py", "tools/eval/real/run_real_eval.py", "tools/plan_examples.py",
])
def test_media_generators_still_run_as_scripts(script, tmp_path):
    path = Path(__file__).resolve().parents[1] / script
    result = subprocess.run([sys.executable, str(path), "--help"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
