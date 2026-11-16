"""A short offline headline starter exercises frames, effects and the audio mux."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from myzing.factory import tools
from myzing.story import command, starter
from test_factory_brand_kit import browser_tools
from test_story_audio import tone


def test_real_headline_starter_build_has_frames_and_audio(tmp_path, browser_tools):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg not installed")
    starter.new(tmp_path, topic="paper stars", look="headline")
    path = tmp_path / "story.json"
    story = json.loads(path.read_text(encoding="utf-8"))
    assert "panels" not in story and command.check(tmp_path) == []
    # Keep this real build under three seconds, with generated local line audio.
    story["outro"] = 1
    lines = tmp_path / "lines"
    lines.mkdir()
    for beat in story["beats"]:
        beat["tail"] = 0
        for index, line in enumerate(beat["lines"]):
            line["gap"] = 0
            tone(lines / f"{beat['id']}-{index}.wav", duration=.15)
    path.write_text(json.dumps(story), encoding="utf-8")
    before = path.read_bytes()
    result = command.build(tmp_path, lines_dir=lines)
    assert path.read_bytes() == before
    receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
    assert receipt["look"] == "headline"
    probe = json.loads(tools.run(tools.ffprobe(), "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                 result["rendered"], capture_output=True, text=True).stdout)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1080, 1920, "30/1")
    assert audio["codec_name"] == "aac" and int(audio["nb_frames"]) > 0
    assert float(probe["format"]["duration"]) == pytest.approx(1.95, abs=1 / 30)
    # Effects should make the silent lead into the outro audible, beyond the line tones.
    decoded = tmp_path / "audio.f32"
    tools.run(tools.ffmpeg(), "-v", "error", "-y", "-i", result["rendered"], "-vn", "-ac", 1,
              "-ar", 8000, "-f", "f32le", decoded, capture_output=True)
    from array import array

    samples = array("f")
    samples.frombytes(decoded.read_bytes())
    assert max(abs(value) for value in samples[8000:12000]) > .001
