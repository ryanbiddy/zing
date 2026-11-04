"""Context checks use nearby transcript words and follow changes to the cut and hook."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from myzing.factory import context, judge, pipeline, serve, source


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def flag(kind="dropped_condition", where="start", quote="Only when the room is quiet."):
    return {"kind": kind, "where": where, "quote": quote, "why": "The cut leaves out the condition."}


def clip(tmp_path, start=100, end=110, segments=None, hook="It works") -> Path:
    media = tmp_path / "ep.mp4"
    media.write_bytes(b"\0")
    root = Path(pipeline.init(tmp_path / "proj", media, moments=0, shapes=[])["project"])
    write(root / "moments.json", {"scouted": True, "moments": [
        {"start": start, "end": end, "hook": hook, "snapped": True}]})
    write(root / "transcript.json", segments if segments is not None else [
        {"s": 0, "e": 10, "text": "Welcome to the talk."},
        {"s": 90, "e": 100, "text": "Only when the room is quiet."},
        {"s": 100, "e": 110, "text": "It works."},
        {"s": 110, "e": 120, "text": "But it needs more testing."},
        {"s": 280, "e": 290, "text": "One last condition."},
        {"s": 290, "e": 300, "text": "That is all."}])
    d = root / "clip01"
    write(d / "words.json", {"start": start, "end": end, "duration": end - start, "ranges": [[start, end]],
                              "words": [{"w": "It", "os": 0, "oe": .4},
                                        {"w": "works.", "os": end - start - .4, "oe": end - start}]})
    write(d / "cams.json", {})
    write(d / "post.json", {"x": "Copy stays here."})
    judge.Judge(root).save("clip01-plan", {"hook": hook, "shots": [{"from": 0, "layout": "solo"}]})
    return d


class Answer(judge.Judge):
    def __init__(self, root, value):
        super().__init__(root)
        self.value, self.prompts = value, []

    def ask(self, task, prompt, images=()):
        path = self.project / "answers" / f"{task}.json"
        if task.endswith("-context") and not path.is_file():
            self.prompts.append(prompt)
            if isinstance(self.value, Exception):
                raise self.value
            if isinstance(self.value, str):
                return self.save(task, self.value)
            write(path, self.value)
        return super().ask(task, prompt, images)


@pytest.mark.parametrize("start,end,before,after", [
    (0, 10, [0, 0], [10, 100]),
    (100, 110, [10, 100], [110, 200]),
    (290, 300, [200, 290], [300, 300]),
])
def test_windows_stop_at_episode_edges(tmp_path, start, end, before, after):
    d = clip(tmp_path, start, end)
    j = Answer(d.parent, {"flags": []})
    assert pipeline.run(d.parent, j, say=lambda m: None)["state"] == "done"
    got = read(d / "context.json")
    assert got["window"] == {"before": before, "after": after}
    assert got["flags"] == [] and "error" not in got and "skipped" not in got
    assert len(j.prompts) == 1
    if start == 0:
        assert got["text"]["before"] == "" and got["text"]["after"] == "Only when the room is quiet."
    elif end == 300:
        assert got["text"]["before"] == "One last condition." and got["text"]["after"] == ""


def test_windows_follow_words_through_removed_pauses(tmp_path):
    d = clip(tmp_path)
    words = read(d / "words.json")
    words.update(ranges=[[100, 105], [108, 110]], duration=7,
                 words=[{"w": "It", "os": 1, "oe": 1.4}, {"w": "works.", "os": 6, "oe": 6.5}])
    write(d / "words.json", words)
    pipeline.run(d.parent, Answer(d.parent, {"flags": []}), say=lambda m: None)
    assert read(d / "context.json")["window"] == {"before": [11, 101], "after": [109.5, 199.5]}


def test_launch_checks_each_span_in_playback_order(tmp_path):
    d = clip(tmp_path, segments=[
        {"s": 39, "e": 40, "text": "Second question?"}, {"s": 45, "e": 46, "text": "Only with help."},
        {"s": 199, "e": 200, "text": "First question?"}, {"s": 205, "e": 206, "text": "First condition."},
        {"s": 299, "e": 300, "text": "Goodbye."}])
    spans = [[200, 205], [40, 45]]
    write(d.parent / "moments.json", {"scouted": True, "moments": [
        {"start": 200, "end": 45, "spans": [{"start": a, "end": b} for a, b in spans],
         "hook": "It works", "snapped": True}]})
    write(d / "words.json", {"start": 200, "end": 45, "spans": spans, "duration": 9,
                              "ranges": [[200, 202], [203, 205], [40, 45]], "words": [
                                  {"w": "First answer.", "os": .5, "oe": 3.5},
                                  {"w": "Second answer.", "os": 4, "oe": 9}]})
    j = Answer(d.parent, {"flags": [flag(where="end", quote="Only with help.")]})
    pipeline.run(d.parent, j, say=lambda m: None)
    got = read(d / "context.json")
    assert got["window"] == {"before": [110.5, 200.5], "after": [45, 135]}
    assert got["spans"][0]["window"] == {"before": [110.5, 200.5], "after": [204.5, 294.5]}
    assert got["spans"][1]["window"] == {"before": [0, 40], "after": [45, 135]}
    sent = json.loads(j.prompts[0].split("\n\n")[-1])
    assert [s["words"] for s in sent["spans"]] == ["First answer.", "Second answer."]
    assert all(text in j.prompts[0] for text in ("First question?", "Second question?", "First condition.", "Only with help."))
    assert got["flags"] == [flag(where="end", quote="Only with help.")]


def test_unsupported_quotes_and_unknown_kinds_are_dropped(tmp_path):
    d = clip(tmp_path)
    supported = flag(quote="ONLY WHEN the room is quiet!")
    j = Answer(d.parent, {"flags": [supported, flag(quote="I take it all back."), flag(kind="off_topic"),
                                     flag(quote="work"), flag(quote="!!!"), flag(where="middle")]})
    log = []
    status = pipeline.run(d.parent, j, say=log.append)
    assert read(d / "context.json")["flags"] == [supported]
    assert status["clips"][0]["context_flags"] == 1 and status["failed"] == {}
    assert log == ["clip01 check the context. 1 flag."]
    pipeline.run(d.parent, j, say=log.append)
    assert len(j.prompts) == len(log) == 1
    (d / "context.json").unlink()
    pipeline.run(d.parent, j, say=lambda m: None)
    assert len(j.prompts) == 1 and read(d / "context.json")["flags"] == [supported]


@pytest.mark.parametrize("kind", context.KINDS)
def test_known_kinds_and_hook_quotes_are_kept(tmp_path, kind):
    d = clip(tmp_path, hook="Ana *admits* it works")
    f = flag(kind=kind, where="hook", quote="Ana admits it works") if kind == "hook_claim" else flag(kind=kind)
    pipeline.run(d.parent, Answer(d.parent, {"flags": [f]}), say=lambda m: None)
    assert read(d / "context.json")["flags"] == [f]


def test_quotes_normalize_punctuation_and_keep_whole_words(tmp_path):
    line = "Élodie doesn’t promise results—only trials. " + " ".join(f"word{i}" for i in range(31))
    d = clip(tmp_path, segments=[{"s": 90, "e": 100, "text": line}, {"s": 299, "e": 300, "text": "End."}])
    good = flag(quote="ÉLODIE doesn't promise results, only trials")
    bad = [flag(quote="promise result"), flag(quote=" ".join(f"word{i}" for i in range(31)))]
    pipeline.run(d.parent, Answer(d.parent, {"flags": [good, *bad]}), say=lambda m: None)
    assert read(d / "context.json")["flags"] == [good]


@pytest.mark.parametrize("value", [None, [], {}, {"flags": "bad"}, {"flags": [None]},
                                  {"flags": [{"kind": "joke", "where": "end"}]}, "not JSON", "{bad JSON}",
                                  RuntimeError("judge did not answer"), RuntimeError()])
def test_garbage_is_logged_and_does_not_stop_the_run(tmp_path, value):
    d = clip(tmp_path)
    log = []
    result = pipeline.run(d.parent, Answer(d.parent, value), say=log.append)
    got = read(d / "context.json")
    assert result["state"] == "done" and result["failed"] == {}
    assert got["flags"] == [] and got["error"]
    assert result["clips"][0]["context_flags"] == 0
    assert len(log) == 1 and "context check skipped" in log[0]


@pytest.mark.parametrize("segments", [[], [{"s": 100, "e": 110, "text": "It works."}]])
def test_no_nearby_transcript_skips_the_judge(tmp_path, segments):
    d = clip(tmp_path, segments=segments)
    j = Answer(d.parent, AssertionError("no context to judge"))
    assert pipeline.run(d.parent, j, say=lambda m: None)["state"] == "done"
    got = read(d / "context.json")
    assert got["flags"] == [] and got["skipped"] and not j.prompts
    assert j.pending() == []


def test_host_waits_after_finalizing_then_resumes(tmp_path):
    d = clip(tmp_path)
    j = judge.Judge(d.parent)
    result = pipeline.run(d.parent, j, say=lambda m: None)
    assert (d / "plan.json").is_file() and not (d / "context.json").exists()
    assert result["state"] == "waiting" and [p["task"] for p in result["pending"]] == ["clip01-context"]
    pipeline.answer(d.parent, "clip01-context", {"flags": [flag()]})
    result = pipeline.run(d.parent, j, say=lambda m: None)
    assert result["state"] == "done" and not result["pending"] and result["clips"][0]["context_flags"] == 1
    pipeline.answer(d.parent, "clip01-context", {"flags": []})
    pipeline.run(d.parent, j, say=lambda m: None)
    assert read(d / "context.json")["flags"] == []


def test_trim_forgets_cached_and_pending_context(tmp_path):
    d = clip(tmp_path)
    j = Answer(d.parent, {"flags": [flag()]})
    pipeline.run(d.parent, j, say=lambda m: None)
    pending = d.parent / "pending" / "clip01-context.md"
    pending.parent.mkdir(exist_ok=True)
    pending.write_text("Old prompt", encoding="utf-8")
    j.save("clip02-context", {"flags": []})
    pipeline.trim(d.parent, "clip01", 101, 109)
    assert not d.exists() and not pending.exists() and j.cached("clip01-context") is None
    assert j.cached("clip02-context") == {"flags": []}


def test_a_new_cut_forgets_the_old_context(tmp_path, monkeypatch):
    d = clip(tmp_path)
    j = Answer(d.parent, {"flags": [flag()]})
    pipeline.run(d.parent, j, say=lambda m: None)
    (d / "cams.json").unlink()
    monkeypatch.setattr(pipeline.cut, "cut", lambda *args, **kwargs: write(d / "cams.json", {}))
    j.value = {"flags": []}
    pipeline.run(d.parent, j, say=lambda m: None)
    assert len(j.prompts) == 2 and read(d / "context.json")["flags"] == []


@pytest.mark.parametrize("task", ["scout", "clip01-plan", "clip01-pick", "clip01-context"])
def test_redo_forgets_context(tmp_path, task):
    d = clip(tmp_path)
    j = Answer(d.parent, {"flags": [flag()]})
    pipeline.run(d.parent, j, say=lambda m: None)
    pipeline.redo(d.parent, task)
    assert not (d / "context.json").exists() and j.cached("clip01-context") is None


def test_dashboard_hook_edit_checks_the_new_hook_and_keeps_the_rating(tmp_path, monkeypatch):
    d = clip(tmp_path)
    j = Answer(d.parent, {"flags": [flag()]})
    assert pipeline.status(d.parent)["clips"][0]["context_flags"] == 0
    pipeline.run(d.parent, j, say=lambda m: None)
    pipeline.rate(d.parent, "clip01", "post")
    monkeypatch.setattr(serve.Studio, "_work", lambda self: None)
    studio = serve.Studio(d.parent)
    before = studio.state()["clips"][0]
    assert before["context"] == read(d / "context.json") and before["context_flags"] == 1
    monkeypatch.setattr(studio, "queue", lambda label, job: job())
    monkeypatch.setattr(studio, "_rerender", lambda d: None)
    monkeypatch.setattr(serve, "Judge", lambda *args: j)
    j.value = {"flags": []}
    studio.text({"clip": "clip01", "field": "hook", "text": "It needs testing"})
    after = studio.state()["clips"][0]
    assert after["context_flags"] == 0 and after["rating"]["v"] == "post"
    assert '"hook": "It needs testing"' in j.prompts[-1]
    pipeline.run(d.parent, j, say=lambda m: None)
    assert len(j.prompts) == 2 and read(d / "plan.json")["hook"] == "It needs testing"


def test_context_sees_caption_fixes_and_keeps_the_hook_number_check(tmp_path):
    d = clip(tmp_path, hook="Buddy Shaw has 99 ships")
    words = read(d / "words.json")
    words["words"][0]["w"] = "Buddy Shaw"
    write(d / "words.json", words)
    judge.Judge(d.parent).save("clip01-plan", {"hook": "Buddy Shaw has 99 ships", "shots": [{"from": 0, "layout": "solo"}],
                                               "fixes": [{"heard": "Buddy Shaw", "meant": "Buddy Shah"}]})
    j = Answer(d.parent, {"flags": []})
    pipeline.run(d.parent, j, say=lambda m: None)
    assert "Buddy Shah" in j.prompts[0] and "Buddy Shaw" not in j.prompts[0]
    assert any("hook number not spoken" in s and "99" in s for s in read(d / "plan.json")["fact_check"])
