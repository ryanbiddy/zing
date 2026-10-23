"""Generated media through the actual studio front door; no live peer/model IO."""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from myzing.studio.command import run
from myzing.studio.models import load_session, read_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.match_examples import generate


@pytest.mark.ffmpeg
def test_studio_match_answers_json_generated_media(tmp_path, monkeypatch, zing_workspace, capsys):
    for name in ("cv2", "numpy", "PIL", "scenedetect", "pysubs2"):
        pytest.importorskip(name)
    reference, clips = generate(tmp_path / "inputs")
    out, trace = tmp_path / "project", tmp_path / "trace.json"
    monkeypatch.setattr("myzing.match.jobs.worker_command", lambda: [sys.executable, "-m", "tools.match_examples", "--worker", str(trace)])
    answers = {"path": "a", "project": str(out), "reference_kind": "file", "reference": str(reference),
               "clips": str(clips), "topic": "a generated style test", "platform": "YouTube", "aspects": ["16:9"],
               "length": 6, "tone": "natural", "captions": "none", "music": "original", "draft": "B"}
    file = tmp_path / "answers.json"
    file.write_text(json.dumps(answers))
    assert run(["--answers", str(file), "--yes", "--json"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    result = events[-1]
    assert events[0]["event"] == "plan" and any(e["event"] == "progress" for e in events)
    assert result["ok"] and result["result"]["ready"] == 3
    for row in result["result"]["drafts"].values():
        assert read_json(row["plan"])["captions"] == []
        assert read_json(row["report"])["render"]["full_decode"]
    assert result["result"]["choice"]["receipt"]["draft"] == "B"
    assert not read_json(trace)["network_attempts"]
    assert load_session(out).status == "ready"


@pytest.mark.ffmpeg
def test_studio_meme_stdin_generated_photo(tmp_path, monkeypatch, zing_workspace, capsys):
    Image = pytest.importorskip("PIL.Image")
    photos = tmp_path / "photos"
    photos.mkdir()
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x360:rate=30:duration=1", "-frames:v", "1", str(photos / "frame.png")],
                   check=True, capture_output=True, timeout=30)
    out = tmp_path / "studio"
    monkeypatch.setattr("sys.stdin", io.StringIO(f"c\n{out}\n{photos}\none quick fix\nsquare\n\nyes\n"))
    assert run([]) == 0
    text = capsys.readouterr().out
    assert "What are we making?" in text and "Downloads: none" in text
    state = load_session(out)
    selected = state.result["result"]["stills"]["1:1"]["selected"]
    with Image.open(selected["path"]) as image:
        assert image.size == (1080, 1080)
    assert selected["alt_text"] and state.result["warnings"]
    assert Path(state.result["result"]["stills"]["1:1"]["concepts"]["contact_sheet"]).is_file()
