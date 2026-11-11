"""Word pieces are joined before captions, quotes and transcript matching."""
import json
from types import SimpleNamespace

import pytest

from myzing.factory import source
from myzing.schemas import Word
from myzing.study.transcribe import _collect_words


def segment(*texts, start=0.0):
    return SimpleNamespace(words=[
        SimpleNamespace(word=text, start=start + i * .4, end=start + i * .4 + .3, probability=.9)
        for i, text in enumerate(texts)
    ])


@pytest.mark.parametrize("raw,expected", [
    ([" that", " 20", "%", " were"], ["that", "20%", "were"]),
    ([" using", " salesforce", ".com.", " Another"], ["using", "salesforce.com.", "Another"]),
    ([" my", " co", "-founder", " and"], ["my", "co-founder", "and"]),
    ([" weirdly", " simple", "-minded.", " It's"], ["weirdly", "simple-minded.", "It's"]),
])
@pytest.mark.parametrize("probabilities", [(.8314, .6234), (.6234, .8314)])
def test_collect_words_joins_real_pieces(raw, expected, probabilities):
    seg = segment(*raw)
    seg.words[1].probability, seg.words[2].probability = probabilities
    assert _collect_words(iter([seg])) == [
        Word(expected[0], 0, .3, .9), Word(expected[1], .4, 1.1, .623), Word(expected[2], 1.2, 1.5, .9),
    ]


@pytest.mark.parametrize("raw", [["新", "世界"], ["co", "founder"], ["version", "2"]])
def test_collect_words_keeps_unspaced_letters_and_digits(raw):
    assert _collect_words([segment(*raw)]) == [Word(raw[0], 0, .3, .9), Word(raw[1], .4, .7, .9)]


@pytest.mark.parametrize("piece", [" -", " --", " —", " –", " ...", " …", "\t%", "\u00a0.com."])
def test_collect_words_keeps_spaced_punctuation(piece):
    assert _collect_words([segment(" word", piece, " next")]) == [
        Word("word", 0, .3, .9), Word(piece.strip(), .4, .7, .9), Word("next", .8, 1.1, .9),
    ]


@pytest.mark.parametrize("piece", ["-", "--", "—", "–", "...", "…", "™", "°C", "，"])
def test_collect_words_joins_unspaced_punctuation_and_symbols(piece):
    assert _collect_words([segment(" word", piece)]) == [Word("word" + piece, 0, .7, .9)]


def test_collect_words_keeps_segment_boundaries():
    segments = [segment(" salesforce"), SimpleNamespace(words=None), segment(" ", ".com.", start=2)]
    assert _collect_words(iter(segments)) == [Word("salesforce", 0, .3, .9), Word(".com.", 2.4, 2.7, .9)]


def test_collect_words_joins_multiple_pieces():
    seg = segment(" 18", ",000", "%", " returned")
    seg.words[0].probability = .6
    assert _collect_words([seg]) == [Word("18,000%", 0, 1.1, .6), Word("returned", 1.2, 1.5, .9)]


@pytest.mark.parametrize("shape", ["factory", "zing"])
def test_load_transcript_joins_real_pieces(tmp_path, shape):
    raw = ["that", "20", "%", "were", "using", "salesforce", ".com.", "Another",
           "my", "co", "-founder", "and", "weirdly", "simple", "-minded.", "It's"]
    data = [{"w": text, "s": i, "e": i + .5} for i, text in enumerate(raw)]
    if shape == "zing":
        data = {"words": [{"text": w["w"], "start": w["s"], "end": w["e"]} for w in data]}
    path = tmp_path / "words.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    segments, words = source.load_transcript(path, offset=2)
    assert words == [
        {"w": "that", "s": 2, "e": 2.5}, {"w": "20%", "s": 3, "e": 4.5},
        {"w": "were", "s": 5, "e": 5.5}, {"w": "using", "s": 6, "e": 6.5},
        {"w": "salesforce.com.", "s": 7, "e": 8.5}, {"w": "Another", "s": 9, "e": 9.5},
        {"w": "my", "s": 10, "e": 10.5}, {"w": "co-founder", "s": 11, "e": 12.5},
        {"w": "and", "s": 13, "e": 13.5}, {"w": "weirdly", "s": 14, "e": 14.5},
        {"w": "simple-minded.", "s": 15, "e": 16.5}, {"w": "It's", "s": 17, "e": 17.5},
    ]
    assert segments == [
        {"s": 2, "e": 8.5, "text": "that 20% were using salesforce.com."},
        {"s": 9, "e": 16.5, "text": "Another my co-founder and weirdly simple-minded."},
        {"s": 17, "e": 17.5, "text": "It's"},
    ]


@pytest.mark.parametrize("piece", [".com", ",000", "%", "'s", "’s", "-founder", ":30", ";", "!", "?", ")", "]"])
def test_load_transcript_joins_suffixes(tmp_path, piece):
    path = tmp_path / "words.json"
    path.write_text(json.dumps([{"w": "word", "s": 1, "e": 2}, {"w": piece, "s": 2, "e": 3}]), encoding="utf-8")
    assert source.load_transcript(path)[1] == [{"w": "word" + piece, "s": 1, "e": 3}]


def test_load_transcript_keeps_standalone_marks_and_other_words(tmp_path):
    raw = ["%", "新", "世界", "co", "founder", "2", "-", "--", "—", "–", "...", "…", "°C", "/year", "(word", "[word"]
    data = [{"w": text, "s": i, "e": i + .5} for i, text in enumerate(raw)]
    path = tmp_path / "words.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert source.load_transcript(path)[1] == data
