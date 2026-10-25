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
    answers = {"path": "a", "project": str(out), "reference_kind": "file", "reference": str(reference), "reference_range": "all",
               "clips": str(clips), "topic": "a generated style test", "platform": "YouTube", "aspects": ["16:9"],
               "length": 6, "tone": "natural", "captions": "none", "music": "original", "draft": "B", "speech_model": "skip"}
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
    monkeypatch.setattr("myzing.studio.flow.default_project", lambda: str(out))
    monkeypatch.setattr("sys.stdin", io.StringIO(f"c\n{photos}\none quick fix\nsquare\nyes\n"))
    assert run([]) == 0
    text = capsys.readouterr().out
    assert "What are we making?" in text and "Downloads: none" in text
    state = load_session(out)
    selected = state.result["result"]["stills"]["1:1"]["selected"]
    with Image.open(selected["path"]) as image:
        assert image.size == (1080, 1080)
    assert selected["alt_text"] and state.result["warnings"]
    assert Path(state.result["result"]["stills"]["1:1"]["concepts"]["contact_sheet"]).is_file()


@pytest.mark.ffmpeg
def test_square_redelivery_coalesces_near_identical_track_times(tmp_path):
    """V1 failure: two independently sampled tracks differ by one source ulp."""
    import math
    from myzing.composition import AssetRef, Composition, CompositionClip
    from myzing.layout.types import Box, FaceTrack, Keyframe
    from myzing.render.deliveries import delivery_plans
    from myzing.render.composition import render_composition
    from myzing.match.evidence import decode
    source = tmp_path / "moving.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x360:rate=30:duration=16", "-c:v", "libx264", "-preset", "ultrafast", str(source)],
                   check=True, capture_output=True, timeout=60)
    clip = CompositionClip(str(source), 14.43335, 15.43335, 0, id="clip", asset_id="s")
    plan = Composition(assets=[AssetRef("s", str(source), None)], clips=[clip], width=640, height=360)
    tracks = [FaceTrack(name, [Keyframe(14.43335, Box(.70, .2, .10, .2)),
                               Keyframe(t, Box(.50, .2, .10, .2)),
                               Keyframe(15.43335, Box(.30, .2, .10, .2))])
              for name, t in [("left", 14.5), ("right", math.nextafter(14.5, math.inf))]]
    import os
    measured = {os.path.normcase(str(source.resolve())): {"display_dimensions": (640, 360), "tracks": tracks,
                "cuts": [], "ranges": [(clip.src_in, clip.src_out)], "warnings": []}}
    deliveries, _ = delivery_plans(plan, ["1:1"], tmp_path / "plans", measured=measured, framing="reframe", short_side=360)
    square = deliveries["1:1"]
    framing = square.clips[0].framing
    assert framing.mode == "reframe"  # no studio fallback, no blanket blurfill
    assert len(framing.keyframes) == 3
    for a, b in zip(framing.keyframes, framing.keyframes[1:]):
        assert b.time - a.time >= 1e-6
        assert 1.5 * math.hypot(b.center_x - a.center_x, b.center_y - a.center_y) / (b.time - a.time) <= framing.max_velocity + 1e-6
    output = tmp_path / "square.mp4"
    render_composition(square, output)
    assert decode(output, square)["full_decode"]
