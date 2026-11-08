"""Meme review regressions on generated images and offline inputs."""
from __future__ import annotations

import io
import json
import subprocess

import pytest

try:
    from PIL import Image, ImageChops
except ImportError:
    Image = ImageChops = None

from myzing import cli, mcp_server
from myzing.memes import MemeError
from myzing.memes.ideas import generate_ideas
from myzing.memes.render import caption_geometry, draw_composition, render_meme
from myzing.memes.video import render_meme_video


@pytest.mark.skipif(Image is None, reason="install myzing[memes] for render tests")
def test_caption_stack_must_fit_at_font_floor():
    with pytest.raises(MemeError, match="Text does not fit its box at a readable size"):
        caption_geometry(["one\ntwo", "three\nfour", "five\nsix"], (160, 160), "sans")


@pytest.mark.skipif(Image is None, reason="install myzing[memes] for render tests")
def test_caption_stack_stays_inside_bar_when_it_fits():
    bar, boxes, font = caption_geometry(["one\ntwo", "three\nfour", "five\nsix"], (160, 640), "sans")
    assert font >= 10
    assert all(0 <= box.y < box.y + box.height <= bar for box in boxes)


@pytest.mark.ffmpeg
@pytest.mark.skipif(Image is None, reason="install myzing[memes] for render tests")
def test_transparent_still_video_matches_canvas_background(tmp_path):
    source = tmp_path / "transparent.png"
    image = Image.new("RGBA", (160, 160), (255, 255, 255, 0))
    image.save(source)
    expected, _ = draw_composition(image, size=image.size, layers=[])
    assert expected.getextrema() == ((24, 24),) * 3
    result = render_meme_video(["ready"], image=str(source), width=160, duration=.4, fps=10,
                               at=[.2], out=str(tmp_path / "transparent.mp4"))
    frame = subprocess.run(["ffmpeg", "-v", "error", "-i", result["path"], "-frames:v", "1",
                            "-f", "image2pipe", "-c:v", "png", "-"],
                           capture_output=True, timeout=90)
    assert frame.returncode == 0, frame.stderr.decode(errors="replace")
    with Image.open(io.BytesIO(frame.stdout)) as actual:
        difference = ImageChops.difference(actual.convert("RGB"), expected)
        assert all(high <= 3 for low, high in difference.getextrema())


@pytest.mark.parametrize("regions", [1, True, "x", {}, ((0, 0, 1, 1),)])
def test_render_rejects_non_list_regions(regions):
    with pytest.raises(MemeError, match="regions must contain"):
        render_meme(["hello"], image="missing.png", layout="labels", regions=regions)
    result = mcp_server.h_meme_render(["hello"], image="missing.png", layout="labels", regions=regions)
    assert not result["ok"] and "regions must contain" in result["error"]


@pytest.mark.parametrize("regions", ["1", '"x"', "{}"])
def test_cli_regions_error_is_json(regions, capsys):
    assert cli.main(["meme", "render", "--image", "missing.png", "--text", "hello",
                     "--layout", "labels", "--regions", regions, "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert not result["ok"] and "regions must contain" in result["error"]


@pytest.mark.parametrize("topic", ["my :", "our ;", "their ,"])
def test_ideas_accept_punctuation_only_noun(topic):
    ideas = generate_ideas(topic)
    assert len(ideas) == 6
    assert all(idea["validation"]["valid"] for idea in ideas)
