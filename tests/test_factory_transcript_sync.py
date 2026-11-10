"""Transcript alignment and word timing without media tools or speech models."""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from myzing import mcp_server
from myzing.factory import command, judge, pipeline, postcopy, source, transcript_sync
from myzing.factory.tools import FactoryError
from myzing.study import speech_models
from test_factory_review_fixes import javascript


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "_speech", refuse)
    monkeypatch.setattr(source, "transcribe_moments", refuse)
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda media: SimpleNamespace(duration=3600.0))
    monkeypatch.setattr(speech_models, "resolve_name", lambda name=None, require_cached=False: "large-v2")
    monkeypatch.setattr(speech_models, "local_path", lambda name: "/models/small" if name == "small" else None)


@pytest.fixture
def episode(tmp_path):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"video")
    words = [{"w": f"word{i}", "s": i, "e": i + 1} for i in range(3600)]
    captions = tmp_path / "episode.srt"

    def stamp(t):
        minutes, seconds = divmod(t, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},000"

    captions.write_text("".join(f"{i // 10 + 1}\n{stamp(i)} --> {stamp(i + 10)}\n"
                                 + " ".join(w["w"] for w in words[i:i + 10]) + "\n\n"
                                 for i in range(0, 3600, 10)), encoding="utf-8")
    return media, captions, words


def project(tmp_path, episode, **settings):
    media, captions, _ = episode
    root = tmp_path / "project"
    pipeline.init(root, media, transcript=captions, **{"shapes": ["9x16"], "moments": 1, **settings})
    return root


def probes(monkeypatch, words, offsets=(323, 323, 323), wrong=(), noisy=False):
    calls = []

    def speech(media, start, end, model=None, **kwargs):
        index = len(calls)
        calls.append((start, end, model, kwargs))
        shifted = transcript_sync.shift(words, offsets[index])
        heard = [{**w, "w": "unrelated" if index in wrong or (noisy and i % 5 == 0) else w["w"].upper() + "!"}
                 for i, w in enumerate(shifted) if start <= w["s"] < end]
        return heard, "en", .99

    monkeypatch.setattr(source, "_speech", speech)
    return calls


class Answers:
    def __init__(self, moments=None):
        self.moments = moments
        self.prompts = {}

    def ask(self, task, text, images=()):
        self.prompts[task] = text
        if task == "scout":
            start = float(re.search(r"\[([\d.]+)-[\d.]+\] word2000\b", text).group(1))
            return {"moments": self.moments or [{"start": start, "end": start + 30, "hook": "A moment"}]}
        if task.endswith("-plan"):
            return {"hook": "A moment", "shots": [{"from": 0, "layout": "solo"}]}
        if task.endswith("-copy"):
            return {k: "A moment" for k in postcopy.FIELDS}
        assert task.endswith("-context")
        return {"flags": []}

    def pending(self):
        return []

    def usage(self):
        return {"calls": len(self.prompts), "cost_usd": 0}


def rendering(monkeypatch, words):
    rendered = []
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces, **kwargs: [
        w for w in words if any(p["start"] - source.MARGIN <= w["s"] < p["end"] + source.MARGIN for p in pieces)])

    def cut(d, media, heard, start, end, **kwargs):
        pipeline._write(d / "cams.json", {})
        pipeline._write(d / "words.json", {"start": start, "duration": end - start, "words": [
            {"w": w["w"], "os": w["s"] - start, "oe": w["e"] - start}
            for w in heard if start <= w["s"] < end]})

    def render(d, shape, pack):
        rendered.append(d.name)
        theme, assets, _ = pipeline.render.pack_data(pack)
        pipeline._write(d / "data.json", {"theme": theme, **assets})
        (d / "clip.mp4").write_bytes(b"video")

    monkeypatch.setattr(pipeline.cut, "cut", cut)
    monkeypatch.setattr(pipeline.render, "render", render)
    return rendered


def test_constant_shift_reaches_scout_cuts_status_and_review(tmp_path, episode, monkeypatch):
    root = project(tmp_path, episode, offline=True, vocab=["Station"])
    calls = probes(monkeypatch, episode[2], noisy=True)
    rendered = rendering(monkeypatch, transcript_sync.shift(episode[2], 323))
    ask, said = Answers(), []
    result = pipeline.run(root, ask, say=said.append)
    assert result["state"] == "done" and result["failed"] == {} and rendered == ["clip01"]
    assert result["settings"]["transcript_offset"] == 323
    saved = pipeline._read(root / "factory.json")["transcript_sync"]
    assert saved["status"] == "matched" and saved["method"] == "probes" and len(saved["probes"]) == 2
    assert all(p["match"] >= .6 and p["offset"] == 323 for p in saved["probes"])
    assert "[2323.0-2333.0] word2000" in ask.prompts["scout"]
    assert pipeline.load_moments(root)["moments"][0]["scout_start"] == 2323
    assert "The transcript was 5:23 behind the video, so Zing shifted it (checked at 2 points)." in said
    assert all(end - start == 20 and model == "small" and options == {"vocab": ["Station"]}
               for start, end, model, options in calls)
    assert [c[0] for c in calls] == [350, 1070]
    assert "Transcript shifted +323 s" in (root / "index.html").read_text(encoding="utf-8")
    assert result["network"]["requests"] == 0
    pipeline.run(root, ask, say=said.append)
    assert len(calls) == 2 and said.count("The transcript was 5:23 behind the video, so Zing shifted it (checked at 2 points).") == 1
    pipeline.redo(root, "scout")
    pipeline.run(root, ask, say=said.append)
    assert len(calls) == 2 and "[2323.0-2333.0] word2000" in ask.prompts["scout"]


@pytest.mark.parametrize("offset", [0, .7, -.7])
def test_aligned_transcript_is_unchanged_and_silent(tmp_path, episode, monkeypatch, offset):
    root = project(tmp_path, episode)
    before = (root / "transcript.json").read_bytes()
    calls = probes(monkeypatch, episode[2], (offset,) * 3)
    said = []
    for _ in range(2):
        result = pipeline.run(root, judge.Judge(root), say=said.append)
        assert result["state"] == "waiting" and result["settings"]["transcript_offset"] == 0
    assert said == [] and len(calls) == 2
    assert (root / "transcript.json").read_bytes() == before


@pytest.mark.parametrize("offset", [-77, .75])
def test_word_json_is_shifted_with_its_segments(tmp_path, episode, monkeypatch, offset):
    media, _, words = episode
    captions = tmp_path / "words.json"
    pipeline._write(captions, words)
    root = tmp_path / "project"
    pipeline.init(root, media, transcript=captions)
    probes(monkeypatch, words, (offset,) * 3)
    said = []
    pipeline.run(root, judge.Judge(root), say=said.append)
    assert pipeline._read(root / "words.json")[0]["s"] == max(0, offset)
    assert pipeline._read(root / "words.json")[0]["w"] == ("word77" if offset == -77 else "word0")
    assert pipeline._read(root / "transcript.json")[0]["s"] == max(0, offset)
    assert pipeline.status(root)["settings"]["transcript_offset"] == offset
    assert len(said) == 1 and ("ahead of" if offset < 0 else "behind") in said[0]


@pytest.mark.parametrize("offsets,wrong", [((323,) * 5, (0, 1, 2, 3, 4)), ((10, 30, 50, 70, 90), ()),
                                          ((0, 1.6, 3.2, 4.8, 6.4), ())])
def test_bad_or_disagreeing_probes_stop_before_scout_and_stay_failed(tmp_path, episode, monkeypatch, offsets, wrong):
    root = project(tmp_path, episode)
    calls = probes(monkeypatch, episode[2], offsets, wrong)
    before = (root / "transcript.json").read_bytes()
    ask = Answers()
    for _ in range(2):
        with pytest.raises(FactoryError) as error:
            pipeline.run(root, ask, say=lambda m: None)
        assert str(error.value) == transcript_sync.MISMATCH.format(project=root)
    assert not ask.prompts and len(calls) == 5
    assert pipeline.status(root)["state"] == "failed"
    assert pipeline._read(root / "factory.json")["transcript_sync"]["status"] == "failed"
    assert (root / "transcript.json").read_bytes() == before


@pytest.mark.parametrize("offsets,wrong,want", [((323, 323, 999), (2,), 323), ((322.5, 324, 900), (), 323.25)])
def test_two_matching_probes_are_enough(tmp_path, episode, monkeypatch, offsets, wrong, want):
    root = project(tmp_path, episode)
    probes(monkeypatch, episode[2], offsets, wrong)
    result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert result["settings"]["transcript_offset"] == want


@pytest.mark.parametrize("flags,method,offset", [(["--offset", "323"], "offset", 323),
                                               (["--offset", "0"], "offset", 0),
                                               (["--no-sync-check"], "disabled", 0)])
def test_cli_explicit_offset_and_opt_out_skip_probes(tmp_path, episode, flags, method, offset, capsys):
    media, captions, _ = episode
    root = tmp_path / "project"
    assert command.run(["new", str(root), "--media", str(media), "--transcript", str(captions), *flags]) == 0
    assert command.run(["run", str(root)]) == 0
    cfg = pipeline._read(root / "factory.json")
    assert cfg["transcript_sync"] == {"status": "skipped", "method": method}
    assert cfg["transcript_offset"] == offset
    assert pipeline._read(root / "transcript.json")[0]["s"] == offset
    assert "sync check" not in capsys.readouterr().err


@pytest.mark.parametrize("settings,method", [({}, "probes"), ({"offset": 0}, "offset"),
                                           ({"no_sync_check": True}, "disabled")])
def test_mcp_keeps_automatic_check_and_explicit_overrides(tmp_path, episode, monkeypatch, settings, method):
    media, captions, words = episode
    root = tmp_path / "project"
    calls = probes(monkeypatch, words, (0, 0, 0))
    assert mcp_server.h_factory_new(str(root), str(media), transcript=str(captions), **settings)["ok"]
    result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert result["settings"]["transcript_sync"]["method"] == method
    assert len(calls) == (2 if method == "probes" else 0)


def test_no_cached_model_skips_once_with_a_note(tmp_path, episode, monkeypatch):
    monkeypatch.setattr(speech_models, "local_path", lambda name: None)
    root = project(tmp_path, episode, offline=True)
    said = []
    for _ in range(2):
        result = pipeline.run(root, judge.Judge(root), say=said.append)
    assert result["state"] == "waiting"
    assert result["settings"]["transcript_sync"] == {"status": "skipped", "method": "no_cached_model"}
    assert said == ["Zing skipped the transcript sync check because no speech model is cached."]


@pytest.mark.parametrize("configured,cached,want", [("small", {"small"}, "small"), ("base", {"base"}, "base"),
                                                   ("large-v2", {"base", "large-v2"}, "base"),
                                                   ("large-v2", {"large-v2"}, "large-v2"), ("base", set(), None),
                                                   ("small", {"base"}, "base"), ("base", {"small.en"}, "small.en")])
def test_probe_model_is_cached_and_prefers_the_episode_scout(monkeypatch, configured, cached, want):
    monkeypatch.setattr(speech_models, "resolve_name", lambda name=None, require_cached=False: configured)
    monkeypatch.setattr(speech_models, "local_path", lambda name: f"/models/{name}" if name in cached else None)
    assert transcript_sync.model() == want


@pytest.mark.parametrize("settings", [{}, {"no_sync_check": True}, {"offset": 0}])
@pytest.mark.parametrize("next_start", [2035, 2200])
def test_word_guard_fails_only_the_mismatched_clip_and_survives_resume(tmp_path, episode, monkeypatch, settings, next_start):
    root = project(tmp_path, episode, moments=2, **settings)
    probes(monkeypatch, episode[2], (0, 0, 0))
    heard = [{**w, "w": "different" if 2000 <= w["s"] < 2030 else w["w"]} for w in episode[2]]
    rendered = rendering(monkeypatch, heard)
    ask = Answers([{"start": start, "end": start + 30, "hook": "A moment"} for start in (2000, next_start)])
    for _ in range(2):
        result = pipeline.run(root, ask, say=lambda m: None)
        assert result["state"] == "done"
        assert result["failed"] == ({} if settings else {
            "clip01": "The words heard at 33:20 do not match the transcript. The transcript may be offset from the video."})
    assert rendered == (["clip01", "clip02"] if settings else ["clip02"])
    assert (root / "clip01").exists() == bool(settings)
    assert ("clip01-plan" in ask.prompts) == bool(settings) and "clip02-plan" in ask.prompts
    pipeline.trim(root, "clip01", 2100, 2130)
    assert "timing_error" not in pipeline.load_moments(root)["moments"][0]


def test_guard_checks_cached_word_timing_before_a_cut(tmp_path, episode, monkeypatch):
    root = project(tmp_path, episode)
    probes(monkeypatch, episode[2], (0, 0, 0))
    pipeline.run(root, judge.Judge(root), say=lambda m: None)
    pipeline._write(root / "words.json", [{"w": "different", "s": i, "e": i + 1} for i in range(2000, 2030)])
    result = pipeline.run(root, Answers(), say=lambda m: None)
    assert "clip01" in result["failed"] and "do not match the transcript" in result["failed"]["clip01"]
    assert not (root / "clip01").exists()


def test_matching_handles_common_words_and_speech_errors():
    words = []
    for i in range(360):
        text = f"We tested the sample{i} near crater{i} and logged sensor{i} today"
        words += [{"w": w, "s": i * 10 + j, "e": i * 10 + j + 1} for j, w in enumerate(text.split())]
    for start in (710, 1790, 2870):
        heard = [w for w in transcript_sync.shift(words, 323) if start <= w["s"] < start + 20]
        for i in range(0, len(heard), 5):
            heard[i]["w"] = "misheard"
        assert transcript_sync.match(heard, transcript_sync.timed(words)) == {"match": .8, "offset": 323}


def test_guard_checks_each_film_span_and_word_order():
    rows = [{"s": 10, "e": 20, "text": "First second third fourth fifth"},
            {"s": 100, "e": 110, "text": "Sixth seventh eighth ninth tenth"}]
    words = transcript_sync.timed(rows)
    assert transcript_sync.guard(rows, words, [[10, 20], [100, 110]]) is None
    words[-5:] = [{**w, "w": "wrong"} for w in words[-5:]]
    assert "1:40" in transcript_sync.guard(rows, words, [[10, 20], [100, 110]])
    assert transcript_sync.coverage(["a", "b", "c", "d", "e"], ["e", "d", "c", "b", "a"]) == .2
    assert transcript_sync.coverage(["a", "b", "c", "d", "e"], ["a", "e"]) == .4
    assert transcript_sync.tokens("DON’T, re-enter! Café.") == ["dont", "re", "enter", "café"]


def test_review_header_shows_signed_offset():
    got = javascript("dashboard.html", """
      ui.project = {state: 'new', clips: [], settings: {transcript_offset: -323}};
      render();
      console.log(JSON.stringify(all(nodes['#meta']).map(n => n.textContent)));
    """)
    assert "Transcript shifted -323 s" in got
