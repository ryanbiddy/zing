"""Headline effects follow beat changes and readable script mentions."""
import json

from myzing.story.audio import _mention, effect_events
from test_story_render import node_page_script


def test_headline_effects_follow_beats_badges_and_picture_entries():
    story = {"look": "headline", "cast": {"mira": {"name": "Mira Vale"}, "sol": {"name": "Sol Reed"}},
             "images": {"elephant-photo": {}, "paper-moon": {"keywords": ["moon"]}}}
    timings = {"duration": 4, "outro_start": 3, "beats": [
        {"start": .35, "lines": [
            {"start": .35, "text": "Mira saw elephants."},
            {"start": .8, "text": "Vale called Sol."},
            {"start": 1.2, "text": "The moon rose."}]},
        {"start": 2, "lines": [{"start": 2, "text": "Mira saw the moon again."}]},
    ]}
    assert effect_events(story, timings) == [
        {"kind": "pop", "at": .35}, {"kind": "pop", "at": .35},
        {"kind": "pop", "at": .8}, {"kind": "pop", "at": 1.2},
        {"kind": "whoosh", "at": 2}, {"kind": "pop", "at": 2}, {"kind": "pop", "at": 2},
        {"kind": "whoosh", "at": 3},
    ]


def test_headline_effects_ignore_say_partial_words_and_authored_panels():
    story = {"look": "headline", "cast": {"ann": {"name": "Ann Vale"}},
             "images": {"elephant": {}}, "panels": [{"from": "missing", "cards": [{"at": 0}]}]}
    timings = {"duration": 1, "outro_start": 1, "beats": [
        {"start": .35, "lines": [{"start": .35, "text": "An annual tale of elephantine scale.",
                                    "say": "Ann Vale sees elephants."}]}]}
    assert effect_events(story, timings) == []


def test_headline_audio_and_page_match_the_same_words(tmp_path):
    cases = [
        ("The glass broke", "glass", True), ("The glas broke", "glass", True),
        ("Two elephants", "elephant", True), ("One elephant", "elephants", True),
        ("ＭＩＲＡ Paper", "Mira", False), ("Éva saw it", "Éva", False),
        ("Jean-Luc saw it", "Jean Luc", False), ("Ann_Lee came", "Ann", False),
        ("annual parade", "Ann", False), ("A paper moon", "paper-moon", True),
        ("elephantine scale", "elephant", True), ("Two stars", "", True),
    ]
    result = node_page_script("const cases=" + json.dumps(cases) + ";"
                              "console.log(JSON.stringify(cases.map(args=>window.headlineMatch(...args))));", tmp_path)
    assert result == [found if (found := _mention(text, phrase, plural=plural)) is not None else -1
                      for text, phrase, plural in cases]


def test_headline_surnames_keep_apostrophes_and_hyphens():
    story = {"look": "headline", "cast": {"ada": {"name": "Ada O'Neill"}, "bea": {"name": "Bea Smith-Jones"}}}
    timings = {"duration": 3, "outro_start": 3, "beats": [{"start": 0, "lines": [
        {"start": 0, "text": "Neill and Jones stayed home."},
        {"start": 1, "text": "O'Neill and Smith-Jones left."},
    ]}]}
    assert effect_events(story, timings) == [{"kind": "pop", "at": 1}, {"kind": "pop", "at": 1}]
