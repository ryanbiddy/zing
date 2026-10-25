"""Real silent clips, stills and Studio progress through the public CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.ffmpeg
@pytest.mark.parametrize("clip_count,duration", [(1, 4), (3, 3)])
def test_studio_speechless_clip_folder_completes(tmp_path, monkeypatch, zing_workspace, capsys, clip_count, duration):
    for name in ("cv2", "numpy", "PIL", "scenedetect", "pysubs2"):
        pytest.importorskip(name)
    from PIL import Image
    from myzing.studio.command import run
    from myzing.composition import Composition

    monkeypatch.setenv("UOINK_URL", "http://127.0.0.1:1")
    clips = tmp_path / "clips"
    clips.mkdir()
    for i in range(clip_count + 1):
        reference = i == clip_count
        output = tmp_path / "reference.mp4" if reference else clips / f"screen-{i}.mp4"
        # Silent screen-like graphics with one continuous shot.
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        f"color=c={'navy' if reference else ['blue', 'green', 'maroon'][i]}:s=320x180:r=30:d={4 if reference else duration}",
                        "-vf", "drawbox=x=20:y=20:w=180:h=110:color=white:t=2",
                        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(output)],
                       capture_output=True, check=True, timeout=30)
    for i in range(3):
        Image.new("RGB", (32, 32), (i * 80, 0, 0)).save(clips / f"frame-{i}.jpg")
    out = tmp_path / "project"
    # Run the real worker and speech-skip path. Any attempted network access
    # fails the run; no authored words or fabricated study replaces silence.
    worker = """
from contextlib import ExitStack
from unittest.mock import patch
from myzing.match.worker import main
def offline(*args, **kwargs):
    raise AssertionError("Unexpected network access during offline Studio regression")
with ExitStack() as stack:
    for name in ("socket.socket.connect", "socket.create_connection", "socket.getaddrinfo"):
        stack.enter_context(patch(name, offline))
    raise SystemExit(main())
"""
    monkeypatch.setattr("myzing.match.jobs.worker_command",
                        lambda: [sys.executable, "-c", worker])
    answers = {"path": "a", "project": str(out), "reference_kind": "file",
               "reference": str(tmp_path / "reference.mp4"), "reference_range": "all",
               "clips": str(clips), "footage_kind": "general", "topic": "silent screens",
               "platform": "YouTube", "aspects": ["16:9"], "length": 4, "tone": "natural",
               "captions": "none", "music": "none", "speech_model": "skip",
               "short_side": 180, "picture_crop": "off"}
    answer_file = tmp_path / "answers.json"
    answer_file.write_text(json.dumps(answers))
    code = run(["--answers", str(answer_file), "--yes", "--json"])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    result = events[-1]
    assert code == 0 and result["ok"], result
    assert "Skipped 3 still images; Studio cuts video clips." in result["warnings"]
    assert any("Studying screen-" in e.get("step", "") for e in events)
    assert result["result"]["ready"] >= 1 and not result["result"]["failures"]
    for row in result["result"]["drafts"].values():
        plan = Composition.from_json(Path(row["plan"]).read_text(encoding="utf-8"))
        assert max(c.timeline_end for c in plan.clips) == pytest.approx(4, abs=2 / 30)
        assert all(Path(c.src).suffix == ".mp4" for c in plan.clips)
        assert not plan.captions
        assert json.loads(Path(row["report"]).read_text())["render"]["full_decode"]
        if clip_count == 3:
            assert len(plan.clips) >= 2
    comparison = json.loads((out / "director/comparison.json").read_text())
    assert all(not c["words"] and c["status"] == "ready" for c in comparison["inventory"])
