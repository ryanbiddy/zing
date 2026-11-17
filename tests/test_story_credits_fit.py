"""End cards keep readable type, whole credits and full receipts in every look."""
from __future__ import annotations

from copy import deepcopy
import json
import wave

import pytest
from PIL import Image, ImageDraw

from myzing.story import receipt
from myzing.story.outro import prepare
from test_factory_brand_kit import browser_tools
from test_story_scrapbook import page_story, run_story_page


LOOKS = ("cutout", "headline", "scrapbook", "comic")


def credit_story(tmp_path, look, *, long=False):
    data = page_story(tmp_path, look)
    data["story"]["cast"] = {
        "ada": {"name": "Ada Paper", "photos": [{
            "path": "drawing.png", "credit": "Drawn test face", "license": "CC0",
            "source_url": "https://example.test/drawing"}]},
        "bea": {"name": "Bea Fold"},
    }
    with Image.open(tmp_path / "heads" / "ada-0-portrait.jpg") as portrait:
        portrait.save(tmp_path / "drawing.png")
    data["timings"]["synthetic"] = True
    if long:
        data["story"]["sources"] = [
            {"title": f"Source{i:02d} records the paper town folding boats and houses from its last sheet of blue paper",
             "url": f"https://example.test/source-{i}"}
            for i in range(1, 31)
        ]
        pictures = tmp_path / "images"
        pictures.mkdir()
        drawing = Image.new("RGB", (120, 120), "#FBF4E4")
        ImageDraw.Draw(drawing).polygon([(15, 90), (60, 20), (105, 90)], fill="#2B50D8")
        drawing.save(pictures / "paper-photo.png")
        data["story"]["images"] = {"paper": {
            "path": "images/paper-photo.png", "credit": "Drawn test triangle", "license": "CC0",
            "source_url": "https://example.test/triangle"}}
        with wave.open(str(tmp_path / "silence.wav"), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 800)
        data["story"]["music"] = {
            "path": "silence.wav", "credit": "Test silence", "license": "CC0",
            "source_url": "https://example.test/silence"}
    return data


def inspect_credits(tmp_path, data):
    return run_story_page(tmp_path, data, """
      await window.build(d.story,d.timings,d.base,d.vocabulary);window.seek(14);
      const credits=[...document.querySelectorAll('.credits')].at(-1);
      const style=getComputedStyle(credits),matrix=new DOMMatrix(style.transform);
      const card=credits.closest('.card')||credits;
      const lines=[...credits.querySelectorAll('span')].map(span=>({
        text:span.textContent,visibility:getComputedStyle(span).visibility,
        boxes:[...span.getClientRects()].map(b=>({left:b.left,top:b.top,right:b.right,bottom:b.bottom}))}));
      return {box:rect(credits),card:rect(card),size:parseFloat(style.fontSize),lines,
        columns:Number(credits.dataset.columns),omitted:Number(credits.dataset.omitted),
        matrix:{a:matrix.a,b:matrix.b,c:matrix.c,d:matrix.d,e:matrix.e,f:matrix.f}};
    """)


def assert_inside(inner, outer):
    assert outer["left"] - .05 <= inner["left"] < inner["right"] <= outer["right"] + .05
    assert outer["top"] - .05 <= inner["top"] < inner["bottom"] <= outer["bottom"] + .05


@pytest.mark.parametrize("look", LOOKS)
def test_long_credits_fit_without_scaling_and_keep_full_receipt(tmp_path, browser_tools, look):
    data = credit_story(tmp_path, look, long=True)
    authored = deepcopy(data["story"])
    data["story"] = prepare(data["story"], data["timings"])
    got = inspect_credits(tmp_path, data)
    assert got["size"] == 22
    assert got["columns"] == 2
    assert got["matrix"] == {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}
    viewport = {"left": 0, "top": 0, "right": 1080, "bottom": 1920}
    assert_inside(got["box"], viewport)
    assert_inside(got["card"], viewport)
    for line in got["lines"]:
        assert line["visibility"] == "visible" and line["boxes"]
        for box in line["boxes"]:
            assert_inside(box, got["box"])
            assert_inside(box, got["card"])
            assert_inside(box, viewport)
    text = " ".join(" ".join(line["text"] for line in got["lines"]).split())
    for credit in ("narration is an AI voice", "photo: Drawn test face · CC0",
                   "image: Drawn test triangle · CC0", "music: Test silence · CC0"):
        assert credit in text
    shown = [i for i in range(1, 31) if f"Source{i:02d}" in text]
    assert shown == list(range(1, len(shown) + 1))
    assert 0 < len(shown) < 30
    for source in authored["sources"][:len(shown)]:
        assert source["title"] in text
    marker = f"+ {30 - len(shown)} more in the receipt"
    assert got["omitted"] == 30 - len(shown)
    assert got["lines"][-1]["text"] == marker and len(got["lines"][-1]["boxes"]) == 1
    if look == "headline":
        assert data["story"]["headline_credit_columns"] == 2
    else:
        assert data["story"]["panels"][-1]["cards"][-1]["columns"] == 2

    (tmp_path / "story.json").write_text(json.dumps(authored), encoding="utf-8")
    (tmp_path / "timings.json").write_text(json.dumps(data["timings"]), encoding="utf-8")
    output = tmp_path / "story.mp4"
    output.write_bytes(b"test render output")
    saved = json.loads(receipt.write(tmp_path, output).read_text(encoding="utf-8"))
    assert saved["sources"] == authored["sources"] and len(saved["sources"]) == 30
    assert saved["voice"]["synthetic"] is True
    assert saved["photos"] == [{"cast": "ada", "name": "Ada Paper", **authored["cast"]["ada"]["photos"][0]}]
    assert saved["images"][0]["credit"] == "Drawn test triangle"
    assert saved["music"] == authored["music"]


@pytest.mark.parametrize("look", LOOKS)
def test_two_columns_keep_all_short_media_credits(tmp_path, browser_tools, look):
    data = credit_story(tmp_path, look)
    data["story"]["sources"][0]["title"] = "Paper"
    photo = data["story"]["cast"]["ada"]["photos"][0]
    data["story"]["cast"]["ada"]["photos"] = [{**photo, "credit": f"A{i:02d}"} for i in range(34)]
    heads = tmp_path / "heads"
    for index in range(1, 34):
        for suffix in (".png", "-portrait.jpg"):
            (heads / f"ada-{index}{suffix}").write_bytes((heads / f"ada-0{suffix}").read_bytes())
    data["story"] = prepare(data["story"], data["timings"])
    got = inspect_credits(tmp_path, data)
    assert got["size"] == 22 and got["columns"] == 2 and got["omitted"] == 0
    text = " ".join(line["text"] for line in got["lines"])
    assert "source: Paper" in text and "more in the receipt" not in text
    for index in range(34):
        assert f"photo: A{index:02d} · CC0" in text
    for line in got["lines"]:
        for box in line["boxes"]:
            assert_inside(box, got["box"])
            assert_inside(box, got["card"])


@pytest.mark.parametrize("look", LOOKS)
def test_short_credits_keep_their_font_and_position(tmp_path, browser_tools, look):
    data = credit_story(tmp_path, look)
    data["story"] = prepare(data["story"], data["timings"])
    got = inspect_credits(tmp_path, data)
    assert got["size"] == 34
    expected = {
        "cutout": (70.111717, 500.462341, 560.932861, 156.450317),
        "scrapbook": (70.111717, 500.462341, 560.932861, 156.450317),
        "headline": (90, 500, 900, 153),
        "comic": (109.380791, 547.898010, 505.979736, 145.132568),
    }[look]
    # Measured from the original page at the same settled end-card time.
    assert tuple(got["box"][key] for key in ("x", "y", "width", "height")) == pytest.approx(expected, abs=.05)
    assert [line["text"] for line in got["lines"]] == [
        "narration is an AI voice", "source: Invented fixture", "photo: Drawn test face · CC0"]
