"""Measure the shipped page with the installed, offline factory browser."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from myzing import mcp_server
from myzing.cover import CoverError, data_path, render
from myzing.cover.frame import dimensions
from myzing.cover.geometry import SIZES
from test_cover_command import invoke
from test_cover_contract import spec_at
from test_factory_brand_kit import browser_tools


def test_real_all_styles_sizes_receipt_and_layout(tmp_path, browser_tools, capsys):
    data = spec_at(tmp_path)
    payload = "<img src=x onerror=alert(1)>"
    data["clipping"]["headline"] = payload
    data["quote"]["by"] = [payload]
    data["quote"].update(text=payload, highlight="src=x")
    data.pop("said")
    (tmp_path / "cover.json").write_text(json.dumps(data))
    result = invoke(capsys, "render", tmp_path)
    receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
    assert dimensions(Path(result["sheet"])) == (1152, 1040)
    assert len(receipt["files"]) == len(result["files"]) == 16
    assert receipt["frame"]["sha256"] == hashlib.sha256((tmp_path / "frame.png").read_bytes()).hexdigest()
    assert receipt["frame"]["rights"] == "own" and receipt["frame"]["timestamp"] == 2
    assert all(f["license"] == "OFL-1.1" for f in receipt["fonts"]) and len(receipt["fonts"]) == 4
    assert receipt["checks"]["local_requests_only"] == receipt["checks"]["text_fit"] == "passed"
    first = None
    for row in receipt["files"]:
        w, h = SIZES[row["size"]]
        path = tmp_path / "out" / row["file"]
        assert dimensions(path) == (row["width"], row["height"]) == (w, h)
        assert path.stat().st_size == row["bytes"]
        boxes = {b["field"]: b for b in row["layout"]["boxes"]}
        assert all(b["x"] >= -1 and b["y"] >= -1 and b["x"] + b["width"] <= w + 1 and
                   b["y"] + b["height"] <= h + 1 for b in boxes.values())
        if row["style"] == "quote":
            assert boxes["text"]["text"] == "“" + payload + "”"
            assert boxes["by"]["text"] == payload.upper() and row["layout"]["highlight"] == "src=x"
        if row["size"] == "wide":
            assert row["bytes"] < 2_000_000 and 0 < row["quality"] <= 92
        if row["style"] == "clipping" and row["size"] != "wide":
            assert boxes["headline"]["text"] == payload
        if row["file"] == "clipping-wide.jpg":
            mast = boxes["masthead"]
            assert .35 < mast["width"] / w < .92
            assert (mast["x"] + mast["width"] / 2) / w == pytest.approx(.5, abs=.001)
            assert .37 < row["layout"]["tear"]["y"] / h < .42
            first = (row["layout"], path.read_bytes())
    again = mcp_server.h_cover_render(str(tmp_path), "clipping", "wide")
    assert again["ok"] and len(again["files"]) == 1
    again_row = json.loads(Path(again["receipt"]).read_text(encoding="utf-8"))["files"][0]
    assert (again_row["layout"], Path(again["files"][0]).read_bytes()) == first


def test_missing_blocks_png_and_double_size(tmp_path, browser_tools):
    data = spec_at(tmp_path)
    for key in ("number", "quote", "clipping"):
        del data[key]
    (tmp_path / "cover.json").write_text(json.dumps(data))
    result = render.render(tmp_path, size="wide", format="png", scale=2)
    assert len(result["files"]) == 1
    assert dimensions(Path(result["files"][0])) == (3840, 2160)
    assert Path(result["sheet"]).suffix == ".jpg"
    assert json.loads(Path(result["receipt"]).read_text())["checks"]["wide_jpeg_bytes"] == "skipped"


@pytest.mark.parametrize("key,value", [("bottom", "W" * 32), ("tag", "W" * 64)])
def test_unreadable_type_preserves_previous_set(tmp_path, browser_tools, key, value):
    data = spec_at(tmp_path)
    result = render.render(tmp_path, style="plate", size="wide")
    receipt = Path(result["receipt"]).read_bytes()
    data["plate"][key] = value
    (tmp_path / "cover.json").write_text(json.dumps(data))
    with pytest.raises(CoverError, match=r"plate\." + key):
        render.render(tmp_path, style="plate", size="square")
    assert Path(result["receipt"]).read_bytes() == receipt
    assert not (tmp_path / "out/plate-square.jpg").exists()


def test_offline_request_fails_even_if_scene_can_continue(tmp_path, browser_tools, monkeypatch):
    spec_at(tmp_path)
    scene = tmp_path / "cover" / "cover.html"
    scene.parent.mkdir()
    shutil.copytree(data_path().parent / "fonts", tmp_path / "fonts")
    markup = data_path("cover.html").read_text(encoding="utf-8")
    scene.write_text(markup.replace("<body>", '<body><img src="https://example.invalid/unwanted">'), encoding="utf-8")
    original = render.data_path
    monkeypatch.setattr(render, "data_path", lambda name: scene if name == "cover.html" else original(name))
    with pytest.raises(CoverError, match="Blocked resource"):
        render.render(tmp_path, style="plate", size="square")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("style,fields", [
    ("number", {"figure": "4", "label": "MINUTES WAITING OUTSIDE", "tag": "CITY DESK"}),
    ("clipping", {"masthead": "CNN", "kicker": "WWWW " * 18}),
])
def test_long_wide_text_fits(tmp_path, browser_tools, style, fields):
    data = spec_at(tmp_path)
    data[style].update(fields)
    data["source"]["name"] = "CNN" if style == "clipping" else "City Desk"
    (tmp_path / "cover.json").write_text(json.dumps(data))
    result = render.render(tmp_path, style=style, size="wide")
    boxes = json.loads(Path(result["receipt"]).read_text())["files"][0]["layout"]["boxes"]
    key = "label" if style == "number" else "kicker"
    box = next(box for box in boxes if box["field"] == key)
    assert box["text"].strip() == fields[key].strip() and box["fontSize"] >= (40 if style == "number" else 24)


def test_body_whitespace_cannot_fill_a_column(tmp_path, browser_tools):
    data = spec_at(tmp_path)
    data["clipping"]["body"] = " " + "W" * 250 + " "
    data.pop("said")
    (tmp_path / "cover.json").write_text(json.dumps(data))
    with pytest.raises(CoverError, match="clipping.body"):
        render.render(tmp_path, style="clipping", size="wide")


def test_quote_highlight_preserves_display_punctuation(tmp_path, browser_tools):
    data = spec_at(tmp_path)
    data["quote"]["highlight"] = "It’s"
    (tmp_path / "cover.json").write_text(json.dumps(data))
    result = render.render(tmp_path, style="quote", size="wide")
    layout = json.loads(Path(result["receipt"]).read_text(encoding="utf8"))["files"][0]["layout"]
    assert layout["highlight"] == "It's"
    assert next(b["text"] for b in layout["boxes"] if b["field"] == "text") == "“It's time.”"
