"""New directed looks share local story inputs and select the right cast assets."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import threading

import pytest
from PIL import Image

from myzing import mcp_server
from myzing.story import command, contract, heads, jobs, render
from myzing.story.layout import panel_overlaps, picture_box
from myzing.story.outro import prepare
from test_factory_brand_kit import browser_tools
from test_story_command import line_files, story_file
from test_story_contract import story, timings
from test_story_heads import draw_photo
from test_story_render import story_folder


@pytest.fixture
def drawn_photo(tmp_path):
    draw_photo(tmp_path / "shape.ppm")
    return {"path": "shape.ppm", "credit": "Test drawing", "license": "CC0 1.0",
            "source_url": "https://example.org/test-drawing", "face": [90, 70, 120, 140]}


def test_scrapbook_heads_writes_portraits_without_calling_the_cutter(tmp_path, drawn_photo, monkeypatch):
    monkeypatch.setattr(heads, "cut_head", lambda *args, **kwargs: pytest.fail("scrapbook cut a head"))
    value = {"look": "scrapbook", "cast": {"mira": {"name": "Mira Paper", "photos": [drawn_photo]}}}
    records = heads.generate(tmp_path, value)
    assert len(records) == 1 and records[0]["portrait"] == "heads/mira-0-portrait.jpg"
    assert "head" not in records[0]
    assert not list((tmp_path / "heads").glob("*.png"))
    with Image.open(tmp_path / records[0]["portrait"]) as portrait:
        assert (portrait.format, portrait.size, portrait.mode) == ("JPEG", (600, 600), "RGB")


def test_comic_heads_writes_real_cut_heads_and_portraits(tmp_path, drawn_photo):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    value = {"look": "comic", "cast": {"mira": {"name": "Mira Paper", "photos": [drawn_photo]}}}
    records = heads.generate(tmp_path, value)
    assert records[0]["head"] == "heads/mira-0.png"
    assert (tmp_path / "heads/mira-0-portrait.jpg").is_file()
    with Image.open(tmp_path / records[0]["head"]) as head:
        assert head.mode == "RGBA" and head.getpixel((0, 0))[3] == 0
        assert head.getchannel("A").getextrema() == (0, 255)


def test_heads_override_prepares_comic_from_scrapbook_and_renders(tmp_path, drawn_photo, browser_tools, capsys):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    story_folder(tmp_path)
    path = tmp_path / "story.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["look"] = "scrapbook"
    value["cast"]["nia"]["photos"] = [drawn_photo]
    path.write_text(json.dumps(value), encoding="utf-8")
    before = path.read_bytes()

    assert command.run(["heads", str(tmp_path)]) == 0
    portraits = json.loads(capsys.readouterr().out)["heads"]
    assert portraits[0]["portrait"] == "heads/nia-0-portrait.jpg"
    assert (tmp_path / portraits[0]["portrait"]).is_file()
    assert not (tmp_path / "heads/nia-0.png").exists()

    assert command.run(["heads", str(tmp_path), "--look", "comic"]) == 0
    cuts = json.loads(capsys.readouterr().out)["heads"]
    assert cuts[0]["head"] == "heads/nia-0.png"
    with Image.open(tmp_path / cuts[0]["head"]) as head:
        assert head.mode == "RGBA" and head.getchannel("A").getextrema() == (0, 255)
    assert path.read_bytes() == before

    assert command.run(["render", str(tmp_path), "--look", "comic", "--stills", "0.2"]) == 0
    outputs = json.loads(capsys.readouterr().out)["stills"]
    assert len(outputs) == 1
    with Image.open(outputs[0]) as still:
        assert (still.format, still.size) == ("JPEG", (1080, 1920))
    assert path.read_bytes() == before


def test_leak_warning_names_both_photo_looks(tmp_path, drawn_photo, monkeypatch, capsys):
    pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")

    def keep_everything(image, mask, *args, **kwargs):
        mask[:] = cv2.GC_PR_FGD

    monkeypatch.setattr(cv2, "grabCut", keep_everything)
    heads.generate(tmp_path, {"look": "comic", "cast": {"mira": {"photos": [drawn_photo]}}})
    warning = capsys.readouterr().err
    assert "background may have leaked" in warning
    assert "render with --look scrapbook or --look headline" in warning
    assert "use the photo as it is" in warning


@pytest.mark.parametrize("look", ["scrapbook", "comic"])
def test_cutout_story_passes_new_look_override_without_rewriting(tmp_path, capsys, look):
    value = story()
    path = tmp_path / "story.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    before = path.read_bytes()
    assert contract.check(value) == []
    assert command.run(["check", str(tmp_path), "--look", look, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["look"] == look and result["problems"] == []
    assert contract.load(tmp_path, look=look)["look"] == look
    assert path.read_bytes() == before


@pytest.mark.parametrize("look", ["scrapbook", "comic"])
def test_new_starter_keeps_directed_panels(tmp_path, capsys, look):
    assert command.run(["new", str(tmp_path), "--topic", "a paper moon", "--look", look]) == 0
    capsys.readouterr()
    value = json.loads((tmp_path / "story.json").read_text(encoding="utf-8"))
    assert value["look"] == look and value["panels"][0]["actors"]
    problems = contract.check(value)
    assert len(problems) == 1 and "replace this source" in problems[0]
    value["sources"] = story()["sources"]
    assert contract.check(value) == []


@pytest.mark.parametrize("look", ["scrapbook", "comic"])
def test_build_override_reaches_assets_render_and_receipt(tmp_path, monkeypatch, capsys, look):
    from myzing.story import images

    value = story_file(tmp_path)
    lines = line_files(tmp_path, value)
    before = (tmp_path / "story.json").read_bytes()
    observed = []
    monkeypatch.setattr(heads, "generate", lambda directory, value: observed.append(("heads", value["look"])))
    monkeypatch.setattr(images, "generate", lambda directory, value: observed.append(("images", value["look"])))

    def capture(directory, **options):
        observed.append(("render", options["look"]))
        output = directory / "story.mp4"
        output.write_bytes(b"test video")
        return output

    monkeypatch.setattr(render, "render", capture)
    assert command.run(["build", str(tmp_path), "--look", look, "--lines-dir", str(lines)]) == 0
    capsys.readouterr()
    assert observed == [("heads", look), ("images", look), ("render", look)]
    assert json.loads((tmp_path / "story-receipt.json").read_text(encoding="utf-8"))["look"] == look
    assert (tmp_path / "story.json").read_bytes() == before


@pytest.mark.parametrize("look", ["scrapbook", "comic"])
def test_mcp_new_check_and_build_accept_new_looks(tmp_path, monkeypatch, look):
    assert mcp_server.h_story_new(str(tmp_path), "a paper moon", look=look)["ok"]
    value = story_file(tmp_path)
    value["look"] = look
    (tmp_path / "story.json").write_text(json.dumps(value), encoding="utf-8")
    result = mcp_server.h_story_check(str(tmp_path))
    assert result["valid"] and result["look"] == look
    observed, release = {}, threading.Event()

    def build(directory, **options):
        observed.update(options)
        assert release.wait(5)
        return {"rendered": "story.mp4"}

    monkeypatch.setattr(command, "build", build)
    try:
        result = mcp_server.h_story_build(str(tmp_path), look=look)
        assert result["ok"] and result["status"] == "started"
        thread = jobs._JOBS[str(tmp_path.resolve())]
    finally:
        release.set()
        if "thread" in locals():
            thread.join(5)
    assert not thread.is_alive() and observed["look"] == look


def test_mcp_look_schemas_list_all_four_choices():
    pytest.importorskip("mcp", reason='mcp SDK not installed (pip install "myzing[mcp]")')
    registered = {tool.name: tool for tool in asyncio.run(mcp_server.build_server().list_tools())}
    for name in ("story_new", "story_build"):
        schema = registered[name].model_dump(by_alias=True)["inputSchema"]["properties"]["look"]
        enums = [schema] if "enum" in schema else schema["anyOf"]
        assert next(item["enum"] for item in enums if "enum" in item) == list(contract.LOOKS)


def test_scrapbook_check_uses_picture_geometry_and_ignores_head_scale():
    value = story()
    value["look"] = "scrapbook"
    panel = value["panels"][0]
    panel["actors"] = [{"who": "ada", "x": 540, "head_scale": .1, "flip": True}]
    panel["cards"] = [{"kind": "tag", "text": "Paper", "x": 460, "y": 810, "at": "hook"}]
    assert any("covers ada's picture" in problem for problem in contract.check(value))
    actor = panel["actors"][0]
    assert picture_box(actor, 1) == picture_box({**actor, "flip": False, "head_scale": 3}, 1)
    panel["cards"][0]["y"] = 300
    assert contract.check(value) == []


def test_scrapbook_generated_outro_uses_picture_clearance():
    value = story()
    value["look"] = "scrapbook"
    value["cast"]["ada"]["photos"] = [{"path": "drawing.png", "credit": "Test drawing", "license": "CC0",
                                         "source_url": "https://example.org/drawing"}]
    value["panels"].append({"from": "outro", "actors": [{"who": "ada", "x": 540, "scale": 1.2}]})
    before = deepcopy(value)
    result = prepare(value, timings())
    outro = result["panels"][-1]
    assert outro["cards"][-1]["kind"] == "credits"
    assert panel_overlaps(outro, timings(), cast=result["cast"], look="scrapbook") == []
    assert value == before
