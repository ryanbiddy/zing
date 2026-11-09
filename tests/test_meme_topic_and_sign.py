"""Whole topics and readable sign text in offline meme and still ideas."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from myzing import cli, mcp_server
from myzing.memes import MemeError
from myzing.memes.ideas import generate_ideas
from myzing.still import inventory
from myzing.still.api import _offline, create_stills
from myzing.still.inventory import SIGN_CONFIDENCE
from myzing.study.captions import CONF_THRESHOLD, Line, _ocr

TOPIC = "NASA calls and you missed it by four minutes"
LONG = "the mission control team finally calls the astronaut waiting patiently beside the telephone for hours"


@pytest.mark.parametrize("photo", [None, {"colors": ["#2a6fdb"], "brightness": .8},
                                    {"text": "OPEN 24 HOURS"}])
def test_topic_keeps_its_last_word_in_every_fitting_formula(photo):
    ideas = generate_ideas("when " + TOPIC, n=8, photo=photo)
    assert len(ideas) == 8
    for idea in ideas:
        assert idea["validation"]["valid"]
        assert not idea.get("warnings")
        assert any(TOPIC in line for line in idea["texts"])
        assert all(TOPIC in line for line in idea["texts"] if "missed it" in line)
        assert all(len(line) <= 70 for line in idea["texts"])
    assert ["when " + TOPIC] in [idea["texts"] for idea in generate_ideas("when " + TOPIC, n=8)]


def test_seven_photo_still_pool_keeps_the_punchline():
    photos = [SimpleNamespace(sha256=str(i), colors=["#2a6fdb"], brightness=.1 + i / 10)
              for i in range(7)]
    concepts = _offline("when " + TOPIC, photos, 6)
    assert len({tuple(idea["texts"]) for _, idea in concepts}) == 6
    assert all(any(TOPIC in line for line in idea["texts"]) for _, idea in concepts)


@pytest.mark.parametrize("topic", ["when " + LONG, "a photograph of " + LONG, "why " + LONG])
def test_overlong_topic_is_shortened_at_a_word_with_a_warning(topic):
    ideas = generate_ideas(topic, n=8)
    for idea in ideas:
        assert idea["validation"]["valid"]
        warning, = idea["warnings"]
        assert warning.startswith("Your topic was shortened to fit: ")
        kept = warning.removeprefix("Your topic was shortened to fit: ")
        assert kept and kept + " " in topic
        assert any(kept in line for line in idea["texts"])
        assert "..." not in warning and "\u2026" not in warning


def test_overlong_topic_keeps_enough_distinct_formulas_for_stills():
    concepts = _offline("when " + LONG, [SimpleNamespace(sha256="photo")], 8)
    assert len({tuple(idea["texts"]) for _, idea in concepts}) == 8
    assert all(idea.get("warnings") for _, idea in concepts)


def test_overflowing_formula_is_dropped_without_shortening_a_fitting_topic():
    topic = TOPIC + " on Monday"
    ideas = generate_ideas("when " + topic, n=8, photo={"colors": ["#2a6fdb"]})
    assert all(idea["validation"]["valid"] and not idea.get("warnings") for idea in ideas)
    assert all(any(topic in line for line in idea["texts"]) for idea in ideas)
    assert not {"deadpan", "dominant_color"} & {idea["formula"] for idea in ideas}


@pytest.mark.parametrize("template", ["drake", "db", "gb", "astronaut"])
def test_templates_report_their_shared_topic_budget(template):
    for idea in generate_ideas("when " + TOPIC, template, n=8):
        assert idea["validation"]["valid"]
        assert idea["warnings"] == ["Your topic was shortened to fit: NASA calls and you missed it"]
    assert all(not idea.get("warnings") for idea in generate_ideas("builds", template, n=8))


def test_one_long_word_is_never_split():
    with pytest.raises(MemeError, match="whole topic word"):
        generate_ideas("x" * 71)


def test_shortening_warning_reaches_cli_and_mcp(capsys):
    assert cli.main(["meme", "ideas", "--topic", "when " + LONG, "--n", "1"]) == 0
    assert "Your topic was shortened to fit: " in capsys.readouterr().out
    assert cli.main(["meme", "ideas", "--topic", "when " + LONG, "--n", "1", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    result = mcp_server.h_meme_ideas("when " + LONG, n=1)
    assert result["ok"] and output["ideas"][0]["warnings"] == result["ideas"][0]["warnings"]


@pytest.fixture
def sign(monkeypatch):
    image = pytest.importorskip("PIL.Image").new("RGB", (1200, 800), "gray")
    pytest.importorskip("numpy")

    def read(text="OPEN 24 HOURS", score=.99, box=(.2, .3, .4, .1)):
        def engine(frame):
            height, width = frame.shape[:2]
            x, y, w, h = box
            points = [[a * width, b * height] for a, b in
                      ((x, y), (x + w, y), (x + w, y + h), (x, y + h))]
            return SimpleNamespace(boxes=[points], txts=[text], scores=[score])

        monkeypatch.setattr(inventory, "_ocr_engine", lambda: engine)
        return inventory.read_text(image)

    yield read
    image.close()


@pytest.mark.parametrize("text,score,box", [
    ("TATES AN", .99, (0, .3, .4, .1)),
    ("TATES AN", CONF_THRESHOLD - .01, (.2, .3, .4, .1)),
    ("TATES AN", .779, (.098, .378, .052, .072)),  # the real NASA banner read: inside the frame, partly hidden
    ("OPEN 24 HOURS", .99, (.005, .3, .4, .1)),
    ("OPEN 24 HOURS", .99, (.6, .3, .4, .1)),
    ("OPEN 24 HOURS", .99, (.2, 0, .4, .1)),
    ("OPEN 24 HOURS", .99, (.2, .9, .4, .1)),
    ("A LONG SIGN", .99, (.2, .3, .4, .1)),
    ("ABC", .99, (.2, .3, .4, .1)),
    ("OPEN 24 HOURS", float("nan"), (.2, .3, .4, .1)),
])
def test_ocr_fragments_do_not_become_sign_concepts(sign, text, score, box):
    photo = {"text": sign(text, score, box), "brightness": .1}
    ideas = generate_ideas("when " + TOPIC, n=8, photo=photo)
    assert photo["text"] == ""
    assert "photo_text" not in {idea["formula"] for idea in ideas}
    assert ideas[0]["formula"] == "dark_scene"


@pytest.mark.parametrize("score", [SIGN_CONFIDENCE, .99])
@pytest.mark.parametrize("box", [(.2, .3, .4, .1), (.01, .01, .98, .98)])
def test_clean_sign_still_becomes_a_concept(sign, score, box):
    text = sign(score=score, box=box)
    assert text == "OPEN 24 HOURS"
    idea = generate_ideas("when " + TOPIC, n=1, photo={"text": text})[0]
    assert idea["formula"] == "photo_text"
    assert idea["texts"] == ['the sign said "OPEN 24 HOURS"', TOPIC + " anyway"]
    assert idea["validation"]["valid"] and not idea.get("warnings")


def test_ocr_reader_keeps_the_normalized_box():
    output = SimpleNamespace(boxes=[[[20, 30], [60, 30], [60, 40], [20, 40]]],
                             txts=["OPEN 24 HOURS"], scores=[.99])
    line, = _ocr(lambda frame: output, SimpleNamespace(shape=(100, 100, 3)))
    assert line.box == pytest.approx((.2, .3, .4, .1))
    assert line.score == .99


@pytest.mark.parametrize("text", ["ABC", "A NASA SIGN", "24 24 24 24 24 24 24 24 24 OPEN"])
def test_sign_quote_still_needs_four_letters_and_whole_words(text):
    ideas = generate_ideas("when " + TOPIC, n=8, photo={"text": text})
    assert "photo_text" not in {idea["formula"] for idea in ideas}


def test_ocr_without_a_box_is_not_sign_evidence(monkeypatch):
    image = pytest.importorskip("PIL.Image").new("RGB", (100, 100))
    pytest.importorskip("numpy")
    monkeypatch.setattr(inventory, "_ocr_engine", lambda: object())
    monkeypatch.setattr("myzing.study.captions._ocr", lambda *args: [Line("TATES AN", .99, .5)])
    with image:
        assert inventory.read_text(image) == ""


def test_sign_can_span_ocr_lines(monkeypatch):
    image = pytest.importorskip("PIL.Image").new("RGB", (100, 100))
    pytest.importorskip("numpy")
    lines = [Line(word, .99, y + .05, .4, (.2, y, .4, .1))
             for word, y in (("OPEN", .1), ("24", .3), ("HOURS", .5))]
    monkeypatch.setattr(inventory, "_ocr_engine", lambda: object())
    monkeypatch.setattr("myzing.study.captions._ocr", lambda *args: lines)
    with image:
        assert inventory.read_text(image) == "OPEN 24 HOURS"


def test_still_result_and_saved_concept_keep_shortening_warning(tmp_path, monkeypatch, zing_workspace):
    image = pytest.importorskip("PIL.Image")
    folder = tmp_path / "photos"
    folder.mkdir()
    with image.new("RGB", (320, 240), "gray") as source:
        source.save(folder / "photo.png")
    monkeypatch.setattr(inventory, "_ocr_engine", lambda: None)
    result = create_stills(folder, "when " + LONG, tmp_path / "out")
    index = json.loads((tmp_path / "out" / "index.json").read_text(encoding="utf-8"))
    warning, = [w for w in result["warnings"] if w.startswith("Your topic was shortened")]
    assert result["count"] == 6
    assert all(warning in idea["warnings"] for idea in result["summary"])
    assert all(warning in idea["warnings"] for idea in index["concepts"])


@pytest.mark.parametrize("text,score,box,kept", [
    ("TATES AN", .99, (0, .3, .4, .1), ""),
    ("TATES AN", CONF_THRESHOLD - .01, (.2, .3, .4, .1), ""),
    ("TATES AN", .779, (.098, .378, .052, .072), ""),
    ("OPEN 24 HOURS", .99, (.2, .3, .4, .1), "OPEN 24 HOURS"),
])
def test_still_inventory_passes_only_clean_signs_to_concepts(tmp_path, zing_workspace, sign, text, score, box, kept):
    image = pytest.importorskip("PIL.Image")
    folder = tmp_path / "photos"
    folder.mkdir()
    with image.new("RGB", (320, 240), "gray") as source:
        source.save(folder / "photo.png")
    assert sign(text, score, box) == kept
    result = create_stills(folder, "when " + TOPIC, tmp_path / "out", n=1)
    index = json.loads((tmp_path / "out" / "index.json").read_text(encoding="utf-8"))
    assert index["photos"][0]["text"] == kept
    assert any(line.startswith('the sign said "') for line in result["summary"][0]["texts"]) == bool(kept)
    assert any(TOPIC in line for line in result["summary"][0]["texts"])
