"""Generated credits and waving puppets share the authored layout checks."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest
from PIL import Image, ImageDraw

from myzing.story.layout import card_box, panel_overlaps
from myzing.story.outro import CREDIT_EM, prepare
from test_factory_brand_kit import browser_tools
from test_story_contract import story, timings
from test_story_render import node_page_script, story_folder


def with_photo():
    value = story()
    value["cast"]["ada"]["photos"] = [{"path": "drawing.png", "credit": "Test artist",
                                         "license": "CC0", "source_url": "https://example.org/drawing"}]
    return value


def test_default_outro_waves_first_photo_actor_and_credits_clear_head():
    value = with_photo()
    value["cast"] = {"blank": {"name": "Paper Person"}, **value["cast"]}
    original = deepcopy(value)
    result = prepare(value, timings())
    panel = result["panels"][-1]
    assert panel["actors"] == [{"who": "ada", "x": 810, "pose": "wave"}]
    assert panel["cards"][-1]["size"] == 34
    assert panel_overlaps(panel, timings(), cast=result["cast"]) == []
    assert value == original


@pytest.mark.parametrize("count,size", [(1, 34), (5, 27), (9, 27)])
def test_credits_type_steps_and_lines_fit_card(count, size):
    value = with_photo()
    value["images"] = {f"drawing-{i}": {"path": f"drawn-{i}.png", "credit": f"Test artist {i}",
                                        "license": "CC0", "source_url": "https://example.org/drawing"}
                       for i in range(count)}
    panel = prepare(value, timings())["panels"][-1]
    card = panel["cards"][-1]
    assert card["size"] == size
    assert (len(card["lines"]) <= 5) == (size == 34)
    assert all(len(line) * size * CREDIT_EM + 24 <= card["w"] for line in card["lines"])
    x, y, w, h = card_box(card)
    assert x >= 0 and x + w < 1080 and y >= 150 and y + h <= 1860
    assert panel_overlaps(panel, timings(), cast=value["cast"]) == []


def test_custom_outro_keeps_art_and_places_credits_away_from_seated_head():
    value = with_photo()
    custom = {"from": "outro", "set": {"wall": "#112233"},
              "actors": [{"who": "ada", "x": 530, "y": 1370, "pose": "table", "head_scale": 1.2}],
              "cards": [{"kind": "tag", "text": "THE END", "x": 80, "y": 200, "at": "outro"}]}
    value["panels"].append(deepcopy(custom))
    result = prepare(value, timings())
    panel = result["panels"][-1]
    assert {**panel, "cards": panel["cards"][:-1]} == custom
    assert panel_overlaps(panel, timings(), cast=result["cast"]) == []


def test_no_photo_means_no_generated_actor():
    assert not prepare(story(), timings())["panels"][-1].get("actors")


def test_credit_page_uses_chosen_type_size(tmp_path):
    result = node_page_script("console.log(JSON.stringify([27,34].map(size=>CARDS.credits({size,lines:['Test artist'],w:900}))));", tmp_path)
    assert "font-size:27px" in result[0] and "font-size:34px" in result[1]
    assert all("width:900px" in html for html in result)


def test_default_outro_renders_drawn_photo_actor(tmp_path, browser_tools):
    from myzing.story.render import render

    folder = story_folder(tmp_path)
    path = folder / "story.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["cast"]["nia"]["photos"] = [{"path": "drawing.png", "credit": "Drawn test head",
                                         "license": "CC0", "source_url": "https://example.org/drawing"}]
    drawing = Image.new("RGBA", (300, 360))
    pen = ImageDraw.Draw(drawing)
    pen.ellipse((25, 15, 275, 340), fill="#FBF4E4", outline="#17161C", width=8)
    pen.ellipse((85, 135, 105, 155), fill="#17161C")
    pen.ellipse((195, 135, 215, 155), fill="#17161C")
    drawing.save(folder / "drawing.png")
    (folder / "heads").mkdir()
    drawing.save(folder / "heads" / "nia-0.png")
    path.write_text(json.dumps(value), encoding="utf-8")
    images = render(folder, stills=[1.2])
    assert images[0].read_bytes().startswith(b"\xff\xd8")
