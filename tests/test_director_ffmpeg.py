"""Generated clips -> three plans -> one existing-renderer v1 output; no models."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from myzing.director import plan_drafts
from myzing.render.pipeline import render_edl
from myzing.schemas import EDL

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.plan_examples import example_project


@pytest.mark.ffmpeg
def test_lowered_plan_renders_with_real_media(tmp_path, zing_workspace):
    project, _, _ = example_project(tmp_path / "project", media=True)
    result = plan_drafts(project, project / "recipe.json", tmp_path / "plans", seed=17)
    assert result["status"] == "ready", result
    edl = EDL.from_dict(json.loads(Path(result["v1_edls"]["A"]).read_text(encoding="utf-8")))
    # Use the exact exported dimensions, captions and source trims.
    output = tmp_path / "plan-A.mp4"
    render_edl(edl, output, work_dir=tmp_path / "render-work")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output)],
                           capture_output=True, text=True, check=True, timeout=30)
    data = json.loads(probe.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1920, 1080)
    assert video["codec_name"] == "h264" and video["r_frame_rate"] == "30/1"
    assert abs(float(data["format"]["duration"]) - 6) <= 2 / 30
    assert any(s["codec_type"] == "audio" for s in data["streams"])
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"],
                   check=True, capture_output=True, timeout=60)
    # Verify planned source choices at a caption-free upper-right pixel. Each
    # known source shot is a distinct color, so this catches mapping/order bugs.
    palette = [(255, 0, 0), (0, 0, 255), (0, 128, 0), (255, 255, 0)]
    for clip in edl.clips:
        relative = min(.1, (clip.src_out - clip.src_in) / 2)
        sample = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(clip.timeline_start + relative),
                                 "-i", str(output), "-frames:v", "1", "-vf", "crop=2:2:1800:100,format=rgb24",
                                 "-f", "rawvideo", "-"], capture_output=True, check=True, timeout=30).stdout
        expected = palette[min(3, int((clip.src_in + relative) / 2))]
        assert len(sample) == 12
        assert max(abs(sample[i] - expected[i]) for i in range(3)) < 30
