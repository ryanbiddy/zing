"""Look selection and headline validation stay local and keep authored files intact."""
from __future__ import annotations

from copy import deepcopy
import json
import threading

import pytest

from myzing import mcp_server
from myzing.story import StoryError, command, contract, jobs, receipt, render
from myzing.story.outro import prepare
from test_story_command import line_files, story_file
from test_story_contract import story, timings
from test_story_render import node_page_script, story_folder


def headline():
    value = story()
    value["look"] = "headline"
    value.pop("panels")
    return value


def save(directory, value):
    path = directory / "story.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_default_look_and_page_vocabulary(tmp_path):
    value = story_file(tmp_path)
    assert prepare(value, timings())["look"] == "cutout"
    assert contract.load(tmp_path) == value
    assert command.check_report(tmp_path)["look"] == "cutout"
    result = node_page_script("console.log(JSON.stringify(window.storyVocabulary));", tmp_path)
    assert result["looks"] == list(contract.LOOKS) == ["cutout", "headline", "scrapbook", "comic"]
    assert result["headline_colors"] == contract.VOCABULARY["headline_colors"]


@pytest.mark.parametrize("look", ["unknown", None, 3, []])
def test_unknown_look_lists_valid_names(look):
    value = story()
    value["look"] = look
    assert any("look:" in error and "cutout, headline" in error for error in contract.check(value))


def test_headline_needs_no_panels_and_ignores_supplied_panels():
    value = headline()
    assert contract.check(value) == []
    value["panels"] = [{"from": "outro", "cards": [{"nonsense": True}]}]
    assert contract.check(value) == []
    warnings, notes = contract.messages(value)
    assert not warnings
    assert len(notes) == 2
    assert all("ignores" in note["message"] for note in notes)
    value["panels"] = "also ignored"
    assert contract.check(value) == []


def test_headline_keeps_script_sources_and_rights_checks():
    value = headline()
    value["beats"][0]["lines"][0]["text"] = "word " * 23
    value["sources"] = []
    value["cast"]["ada"]["photos"] = [{"path": "missing.jpg", "credit": "Test artist",
                                          "license": "CC BY-NC", "source_url": "https://example.org/drawing"}]
    problems = contract.check(value)
    assert any("22 words" in problem for problem in problems)
    assert any("sources:" in problem for problem in problems)
    assert any("NC" in problem for problem in problems)


def test_headline_long_line_warns_without_failing(tmp_path, capsys):
    value = headline()
    value["beats"][0]["lines"][0]["text"] = " ".join(["word"] * 17)
    save(tmp_path, value)
    assert command.run(["check", str(tmp_path), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["look"] == "headline" and result["problems"] == []
    assert result["warnings"] == [{"path": "beats[0].lines[0].text",
                                    "message": "more than 16 words makes headline type small; use a shorter line"}]
    assert command.run(["check", str(tmp_path)]) == 0
    assert "warning:" in capsys.readouterr().err


def test_check_notes_do_not_fail(tmp_path, capsys):
    value = story_file(tmp_path)
    value["look"] = "headline"
    save(tmp_path, value)
    assert command.run(["check", str(tmp_path)]) == 0
    assert "note: panels: headline ignores panels" in capsys.readouterr().err


def test_check_override_does_not_rewrite_and_can_replace_unknown_look(tmp_path, capsys):
    value = headline()
    value["look"] = "old-look"
    path = save(tmp_path, value)
    before = path.read_bytes()
    assert command.run(["check", str(tmp_path), "--look", "headline", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["look"] == "headline"
    assert contract.load(tmp_path, look="headline")["look"] == "headline"
    assert path.read_bytes() == before
    assert command.run(["check", str(tmp_path), "--look", "bogus", "--json"]) == 1
    assert "cutout, headline" in json.loads(capsys.readouterr().out)["problems"][0]["message"]


def test_render_override_reaches_page_without_rewriting(tmp_path, monkeypatch):
    folder = story_folder(tmp_path)
    before = (folder / "story.json").read_bytes()
    observed = {}

    def capture(data, scratch, frames):
        observed.update(data)
        frames.mkdir()
        (frames / "00001.jpg").write_bytes(b"test frame")

    monkeypatch.setattr(render, "capture", capture)
    assert render.render(folder, stills=[.2], look="headline")[0].read_bytes() == b"test frame"
    assert observed["story"]["look"] == "headline" and observed["story"]["panels"] == []
    assert (folder / "story.json").read_bytes() == before


def test_build_override_reaches_each_step_and_receipt(tmp_path, monkeypatch, capsys):
    from myzing.story import heads, images

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
    assert command.run(["build", str(tmp_path), "--look", "headline", "--lines-dir", str(lines)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert json.loads((tmp_path / "story-receipt.json").read_text(encoding="utf-8"))["look"] == "headline"
    assert result["receipt"].endswith("story-receipt.json")
    assert observed == [("heads", "headline"), ("images", "headline"), ("render", "headline")]
    assert (tmp_path / "story.json").read_bytes() == before


def test_headline_starter_passes_check_and_has_no_panels(tmp_path, capsys):
    assert command.run(["new", str(tmp_path), "--topic", "paper stars", "--look", "headline"]) == 0
    capsys.readouterr()
    value = contract.load(tmp_path)
    assert value["look"] == "headline" and "panels" not in value
    assert all(not member.get("photos") for member in value["cast"].values())
    assert command.run(["check", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["problems"] == []


def test_headline_prepared_outro_credits_and_portraits():
    value = headline()
    value["cast"]["ada"]["photos"] = [{"path": "drawn.jpg", "credit": "Test artist",
                                          "license": "CC0", "source_url": "https://example.org/drawing"}]
    value["panels"] = [{"from": "outro", "cards": [{"text": "ignored"}]}]
    before = deepcopy(value)
    result = prepare(value, {**timings(), "provider": "kokoro"})
    assert result["cast"]["ada"]["portraits"] == ["ada-0-portrait.jpg"]
    assert result["cast"]["ada"]["heads"] == ["ada-0.png"]
    assert result["headline_outro_cast"] == "ada" and result["panels"] == []
    assert "narration is an AI voice" in result["headline_credits"]
    assert "photo: Test artist · CC0" in result["headline_credits"]
    assert result["headline_credit_size"] == 34
    assert value == before


@pytest.mark.parametrize("color", contract.VOCABULARY["headline_colors"])
def test_headline_beat_colors_are_validated(color):
    value = headline()
    value["beats"][0]["color"] = color
    assert contract.check(value) == []
    value["beats"][0]["color"] = "purple"
    assert any("beats[0].color:" in problem for problem in contract.check(value))


def test_image_keywords_are_checked():
    value = headline()
    value["images"] = {"paper-star": {"path": "drawn.jpg", "credit": "Test artist", "license": "CC0",
                                       "source_url": "https://example.org/drawing", "keywords": ["star", "stars"]}}
    assert contract.check(value) == []
    value["images"]["paper-star"]["keywords"] = [""]
    assert any("keywords[0]" in problem for problem in contract.check(value))


def test_mcp_starter_and_check_report_look(tmp_path):
    assert mcp_server.h_story_new(str(tmp_path), "paper stars", look="headline")["ok"]
    result = mcp_server.h_story_check(str(tmp_path))
    assert result == {"ok": True, "valid": True, "look": "headline", "problems": [], "warnings": [], "notes": []}


def test_mcp_build_override_validates_selected_look(tmp_path, monkeypatch):
    value = headline()
    value.pop("look")  # Missing panels is valid only when the requested override is applied.
    before = save(tmp_path, value).read_bytes()
    observed, release = {}, threading.Event()

    def build(directory, **options):
        observed.update(options)
        assert release.wait(5)
        return {"rendered": "story.mp4"}

    monkeypatch.setattr(command, "build", build)
    result = mcp_server.h_story_build(str(tmp_path), look="headline")
    assert result["ok"] and result["status"] == "started"
    thread = jobs._JOBS[str(tmp_path.resolve())]
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert observed["look"] == "headline"
    assert (tmp_path / "story.json").read_bytes() == before


def test_receipt_records_default_look(tmp_path):
    story_folder(tmp_path)
    output = tmp_path / "story.mp4"
    output.write_bytes(b"test output")
    assert json.loads(receipt.write(tmp_path, output).read_text(encoding="utf-8"))["look"] == "cutout"
