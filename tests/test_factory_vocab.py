"""Supplied factory spellings reach speech, planning and caption words."""
from __future__ import annotations

import asyncio
import json

import pytest

from myzing import mcp_server
from myzing.factory import command, judge, pipeline, plan, render, source
from myzing.factory.tools import FactoryError
from myzing.schemas import Word
from myzing.study import transcribe
from myzing.study.asr_hygiene import vocabulary_context


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    moments = source.transcribe_moments
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces, **kwargs: [])
    return moments


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "ep.mp4"
    path.write_bytes(b"\0")
    return path


def test_cli_saves_repeated_and_comma_separated_vocab(tmp_path, media, capsys):
    root = tmp_path / "proj"
    assert command.run(["new", str(root), "--media", str(media), "--vocab", " Pompliano, Starbase",
                        "--vocab", "Vermilion   Parish, pompliano, , Cafe\u0301"]) == 0
    expected = ["Pompliano", "Starbase", "Vermilion Parish", "Caf\u00e9"]
    assert json.loads(capsys.readouterr().out)["settings"]["vocab"] == expected
    assert json.loads((root / "factory.json").read_text(encoding="utf-8"))["vocab"] == expected


@pytest.mark.parametrize("vocab", [[], ["Pompliano"]])
def test_only_supplied_terms_are_saved(tmp_path, media, vocab):
    result = pipeline.init(tmp_path / "proj", media, name="Ana", tag="Ryan", show="Ana and Ryan",
                           brand={"name": "Fold"}, **({"vocab": vocab} if vocab else {}))
    assert result["settings"]["vocab"] == vocab


@pytest.mark.parametrize("vocab", [["x" * 81], [f"t{i}" for i in range(65)],
                                   ["\u00e9" * 70 + str(i) for i in range(4)]], ids=["term", "count", "bytes"])
def test_cli_and_settings_reject_study_limits(tmp_path, media, capsys, vocab):
    reason = vocabulary_context(vocab)["omitted"][0]["reason"]
    root = tmp_path / "proj"
    with pytest.raises(FactoryError) as caught:
        pipeline.init(root, media, vocab=vocab)
    assert str(caught.value) == reason
    assert command.run(["new", str(root), "--media", str(media), "--vocab", ",".join(vocab)]) == 2
    assert capsys.readouterr().err == f"zing factory: {reason}\n"
    assert not root.exists()


@pytest.mark.parametrize("vocab", [1, [22]])
def test_settings_reuse_study_type_errors(tmp_path, media, vocab):
    with pytest.raises(ValueError) as study:
        vocabulary_context(vocab)
    with pytest.raises(ValueError) as factory:
        pipeline.init(tmp_path / "proj", media, vocab=vocab)
    assert str(factory.value) == str(study.value)


@pytest.mark.parametrize("quick", ["small", None])
@pytest.mark.parametrize("vocab", [[], ["Pompliano", "Starbase", "Vermilion Parish"]])
def test_vocab_reaches_episode_moments_and_language_retry(tmp_path, media, monkeypatch, offline, quick, vocab):
    root = tmp_path / "proj"
    cfg = pipeline.init(root, media, moments=2, vocab=vocab)["settings"]
    if not vocab:
        cfg.pop("vocab")                          # older projects have no vocabulary setting
        pipeline._write(root / "factory.json", cfg)
    calls = []

    def speech(wav, **kwargs):
        calls.append(kwargs)
        assert wav.name == "speech.wav"
        if len(calls) == 1:
            words = [Word("Pompliano.", 10, 11), Word("Starbase.", 400, 401), Word("End.", 500, 501)]
            language = "en"
        else:
            language = kwargs["language"] or ("cy" if kwargs["duration"] < 50 else "en")
            words = [Word("Pompliano." if language == "en" else "Welsh.", 6, 7)]
        return transcribe.TranscribeResult(words, {"language": language, "language_probability": .9})

    class Scout:
        def ask(self, task, text):
            assert task == "scout"
            return {"moments": [{"start": 10, "end": 200, "hook": "First"},
                                 {"start": 400, "end": 410, "hook": "Second"}]}

    monkeypatch.setattr(source, "scout_model", lambda: quick)
    monkeypatch.setattr(source, "transcribe_moments", offline)
    monkeypatch.setattr(source, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(source, "run", lambda *args: None)
    monkeypatch.setattr(transcribe, "transcribe", speech)
    moments = pipeline._moments(root, Scout(), media, cfg, say=lambda m: None)
    assert all(m["snapped"] for m in moments)
    assert len(calls) == 4                         # the episode, two moment spans, and one language redo
    assert all(c.get("vocabulary", []) == vocab for c in calls)
    assert all(("vocabulary" in c) == bool(vocab) for c in calls)
    assert calls[0]["model_name"] == quick and calls[0]["local_files_only"] == bool(quick)
    if quick:
        assert [c["language"] for c in calls] == [None, None, None, "en"]
        assert [c["duration"] for c in calls[1:]] == [202, 22, 22]
        assert [w["w"] for w in pipeline._read(root / "words.json")] == ["Pompliano.", "Pompliano."]


def test_plan_adds_only_the_supplied_spellings():
    moment = {"hook": "A visit"}
    words = {"duration": 2, "words": [{"w": "Pompiano.", "os": 0, "oe": 1}]}
    plain = plan.prompt(moment, words)
    assert "SPELLINGS" not in plain and plan.prompt(moment, words, vocab=[]) == plain
    spellings = ("SPELLINGS: Pompliano, Starbase\n"
                 "Names and terms in SPELLINGS are spelled exactly so; a near-miss in WORDS is a fix.\n")
    given = plan.prompt(moment, words, vocab=["Pompliano", "Starbase"])
    assert spellings in given and given.replace(spellings, "") == plain


def test_planner_fixes_reach_caption_words(tmp_path, media, monkeypatch):
    root = tmp_path / "proj"
    cfg = pipeline.init(root, media, vocab=["Pompliano", "Starbase"], shapes=["9x16"])["settings"]
    d = root / "clip01"
    heard = [{"w": w, "os": i, "oe": i + .8} for i, w in enumerate("Pompiano visits Star Base.".split())]
    pipeline._write(d / "words.json", {"words": heard, "duration": 4})
    pipeline._write(d / "cams.json", {"frames": 120, "size": [1920, 1080], "cams": []})
    pipeline._write(d / "post.json", {})

    class Planner:
        def ask(self, task, text):
            if task == "clip01-context":
                return {"flags": []}
            assert task == "clip01-plan" and "SPELLINGS: Pompliano, Starbase\n" in text
            return {"hook": "A visit", "shots": [{"from": 0, "layout": "solo"}],
                    "fixes": [{"heard": "Pompiano", "meant": "Pompliano"},
                              {"heard": "Star Base", "meant": "Starbase"}]}

    captions = []

    def rendered(clip, shape, pack):
        data = render.scene_data(clip, shape, pack, parallax=False, front=False, sharpen=False)
        captions.extend(data["words"])

    monkeypatch.setattr(render, "render", rendered)
    assert pipeline._clip(root, 1, {"hook": "A visit", "start": 0, "end": 10}, Planner(), media, cfg, [], say=lambda m: None) == []
    assert [w["w"] for w in captions] == ["Pompliano", "visits", "Starbase."]
    assert [(w["os"], w["oe"]) for w in captions] == [(0, .8), (1, 1.8), (2, 3.8)]
    assert pipeline._read(d / "words-heard.json")["words"] == heard


def test_mcp_factory_new_accepts_and_validates_vocab(tmp_path, media):
    root = tmp_path / "proj"
    result = mcp_server.h_factory_new(str(root), str(media), vocab=["Pompliano", "Starbase"])
    assert result["ok"] and result["settings"]["vocab"] == ["Pompliano", "Starbase"]
    assert pipeline._read(root / "factory.json")["vocab"] == ["Pompliano", "Starbase"]
    result = mcp_server.h_factory_new(str(tmp_path / "bad"), str(media), vocab=["x" * 81])
    assert not result["ok"] and result["error"] == vocabulary_context(["x" * 81])["omitted"][0]["reason"]


def test_mcp_vocab_is_an_optional_string_list():
    pytest.importorskip("mcp")
    tools = asyncio.run(mcp_server.build_server().list_tools())
    assert len(tools) == 43
    schema = next(t.model_dump(by_alias=True)["inputSchema"] for t in tools if t.name == "factory_new")
    vocab = schema["properties"]["vocab"]
    assert vocab["default"] is None and "vocab" not in schema["required"]
    assert {"type": "array", "items": {"type": "string"}} in vocab["anyOf"]
