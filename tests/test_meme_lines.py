"""POLISH1 item 4: offline lines use the topic's words and measured photo facts."""

from __future__ import annotations

import json
import re

import pytest

from myzing.memes.ideas import HONESTY, color_name, generate_ideas, photo_facts

# Payoffs the pre-POLISH1 formulas reused for every topic.
OLD_FIXED = {"nobody move", "we are so back", "day 47", "six hours later", "(i have no idea)",
             '"define going"', "me, building a system first", "and nobody knows why", "(i changed nothing)",
             "me, acting like i planned this", "great question. next slide.", "the junior dev nodding",
             "one sentence", "and at this point i'm afraid to ask", "the plan"}
PAIRS = [("monday standup", "my cat knocking things off the desk"),
         ("when the build finally passes", "when the printer jams again"),
         ("how it works", "why the deploy failed"),
         ("fix the flaky test", "release day")]


def lines(topic, **kwargs):
    return [line for idea in generate_ideas(topic, n=8, **kwargs) for line in idea["texts"]]


def topic_tokens(topic):
    return {w for w in re.findall(r"[a-z0-9']+", topic.casefold()) if len(w) > 2} | {
        # gerund forms the topic parser writes for tasks
        "fixing"}


@pytest.mark.parametrize("first,second", PAIRS)
def test_two_topics_share_no_line_and_every_line_uses_the_topic(first, second):
    a, b = lines(first), lines(second)
    assert not set(a) & set(b), set(a) & set(b)
    for topic, produced in ((first, a), (second, b)):
        tokens = topic_tokens(topic)
        for line in produced:
            words = set(re.findall(r"[a-z0-9']+", line.casefold()))
            assert words & tokens, (topic, line)
            assert line not in OLD_FIXED and line.strip('"') not in OLD_FIXED, line


@pytest.mark.parametrize("topic", [t for pair in PAIRS for t in pair])
def test_lines_stay_grammatical_and_budgeted(topic):
    ideas = generate_ideas(topic, n=8)
    assert len({tuple(i["texts"]) for i in ideas}) == 8
    for idea in ideas:
        assert idea["validation"]["valid"], idea
        assert idea["note"] == HONESTY and idea["provider"] == "offline_formulas"
        for line in idea["texts"]:
            low = line.casefold()
            assert not re.search(r"\b(the|a) (the|a)\b", low), line
            assert not re.search(r"\b(the|of|about|touch) *[,)]", low), line
            assert not re.search(r"\bthe tests deserves\b|\bthe \w+s deserves\b", low), line
            assert "nobody:" not in low  # the banned filler stays banned
    assert ["when the build finally passes"] in [i["texts"] for i in generate_ideas("when the build finally passes", n=8)]


def test_situation_subjects_and_agreement():
    texts = " | ".join(lines("the tests pass"))
    assert "the tests deserve a raise" in texts and "don't touch the tests" in texts
    texts = " | ".join(lines("you open the legacy code"))
    assert "don't touch the legacy code" in texts
    texts = " | ".join(lines("when the build finally passes"))
    assert "(i never touched the build)" in texts and "the build deserves a raise" in texts
    assert "my cat can sense fear" in " | ".join(lines("my cat knocking things off the desk"))


def photo(**overrides):
    record = {"face_method": "yunet", "faces": [], "colors": ["#2a6fdb"], "subject_estimate": None,
              "brightness": .5, "text": None}
    record.update(overrides)
    return record


def test_photo_facts_change_the_lines_and_are_named_as_evidence():
    group = photo(faces=[{"x": i / 4, "y": .2, "width": .15, "height": .2} for i in range(3)])
    dark = photo(brightness=.12, colors=["#101010"])
    sign = photo(text="EMERGENCY EXIT ONLY", face_method="center_heuristic")
    pet = photo(subject_estimate={"box": [.3, .05, .4, .45], "confidence": .9,
                                  "evidence": {"position": "top-center", "photo_brightness": .6}})
    assert photo_facts(group)["faces"] == 3 and photo_facts(dark)["light"] == "dark"
    assert photo_facts(sign)["faces"] is None and photo_facts(sign)["text"] == "EMERGENCY EXIT ONLY"
    assert photo_facts(photo())["color"] == "blue" and photo_facts(dark)["color"] is None
    first = {name: generate_ideas("monday standup", n=8, seed="s", photo=record)[0]
             for name, record in (("group", group), ("dark", dark), ("sign", sign), ("pet", pet))}
    assert first["group"]["texts"] == ["all 3 of us after monday standup"]
    assert first["group"]["evidence"] == ["topic words", "faces=3"]
    assert first["dark"]["texts"] == ["monday standup at 2am", "the standup never sleeps"]
    assert first["sign"]["texts"] == ['the sign said "EMERGENCY EXIT ONLY"', "monday standup anyway"]
    assert first["pet"]["formula"] == "subject_label" and len(first["pet"]["regions"]) == 2
    label, other = first["pet"]["regions"]
    subject = pet["subject_estimate"]["box"]
    for x, y, w, h in (label, other):  # labels sit beside the subject, never on it
        assert x + w <= subject[0] or x >= subject[0] + subject[2] or y + h <= subject[1] or y >= subject[1] + subject[3]
    assert "not what it is" in first["pet"]["why"]
    for name in ("cat", "dog", "pet"):
        assert name not in first["pet"]["why"].split()
    # Without evidence the same topic and seed fall back to topic formulas.
    plain = generate_ideas("monday standup", n=8, seed="s", photo=photo(colors=["#808080"]))
    assert all(i["evidence"] == ["topic words"] for i in plain)


def test_color_names_only_saturated_colors():
    assert color_name("#d93025") == "red" and color_name("#1e8e3e") == "green"
    assert color_name("#7a4a1f") == "brown" and color_name("#e8710a") == "orange"
    assert color_name("#777777") is None and color_name("#ffffff") is None and color_name("bad") is None


def test_still_concepts_use_measured_photo_facts(tmp_path, zing_workspace):
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    from myzing.still.api import create_stills

    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (900, 700), (14, 16, 22)).save(folder / "night.png")
    result = create_stills(folder, "monday standup", tmp_path / "out", n=3)
    index = json.loads((tmp_path / "out" / "index.json").read_text(encoding="utf-8"))
    record = index["photos"][0]
    assert record["brightness"] < .1
    assert record["text"] in (None, "")  # None only when local OCR is unavailable
    assert index["concepts"][0]["texts"] == ["monday standup at 2am", "the standup never sleeps"]
    assert HONESTY in result["warnings"]
    prompt = (tmp_path / "out" / "meme-writer.md").read_text(encoding="utf-8")
    assert '"light": "dark"' in prompt


def test_local_ocr_text_becomes_line_evidence_when_available(tmp_path, zing_workspace):
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw, ImageFont
    from myzing.memes.render import resolve_font
    from myzing.still.inventory import _ocr_engine, describe_photo

    if _ocr_engine() is None:
        pytest.skip("local OCR runtime/models are not installed; text evidence stays unknown")
    image = Image.new("RGB", (1200, 800), (235, 235, 230))
    ImageDraw.Draw(image).text((300, 300), "EXIT", font=ImageFont.truetype(resolve_font("sans"), 160), fill="black")
    image.save(tmp_path / "sign.png")
    record = describe_photo(tmp_path / "sign.png")
    assert record.text == "EXIT" and 'Text read locally: "EXIT"' in record.description
    idea = generate_ideas("monday standup", n=8, seed="x", photo=record)
    assert any(i["texts"] == ['the sign said "EXIT"', "monday standup anyway"] for i in idea)
