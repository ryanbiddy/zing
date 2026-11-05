"""Review edits through the shared functions, MCP, CLI and page."""
from __future__ import annotations

import asyncio
import json
import subprocess
import threading

import pytest

from myzing import mcp_server
from myzing.factory import command, cut, edit, judge, pipeline, plan, render, serve
from myzing.factory.tools import FactoryError
from test_factory_context import Answer
from test_factory_review_fixes import javascript, prepared, project
from test_mcp_stdio import client


@pytest.fixture
def ready(project, monkeypatch, zing_workspace):
    d = prepared(project)
    calls = []
    j = Answer(project, {"flags": []})

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")

    def rendered(d, shape, pack):
        calls.append((shape, pack))
        return d / f"clip{render.suffix(shape, pack)}.mp4"
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(edit, "Judge", lambda *a: j)
    monkeypatch.setattr(serve, "Judge", lambda *a: j)
    monkeypatch.setattr(serve.Studio, "_work", lambda self: None)
    monkeypatch.setattr(render, "render", rendered)
    return d, j, calls


@pytest.mark.parametrize("verdict,saved", [("post", "post"), ("edits", "fix"), ("no", "no")])
def test_rate(ready, verdict, saved):
    d, _, calls = ready
    assert edit.rate(d.parent, d.name, verdict, "Tighter") == {"saved": d.name}
    row = pipeline._read(d.parent / "ratings.json")[d.name]
    assert (row["v"], row["why"]) == (saved, "Tighter") and not calls


@pytest.mark.parametrize("field", sorted(edit.TEXT_FIELDS))
def test_copy(ready, field):
    d, _, calls = ready
    got = edit.text(d.parent, d.name, field, "  New copy  ")
    assert got["saved"] == field and got["text"] == "New copy"
    assert pipeline._read(d / "post.json")[field] == "New copy" and not calls
    assert edit.text(d.parent, d.name, field, "x" * 2300)["text"] == "x" * 2200


def test_hook_rechecks_facts_context_and_receipt(ready):
    d, j, calls = ready
    flag = {"kind": "hook_claim", "where": "hook", "quote": "99 rockets", "why": "That number was not said."}
    j.value = {"flags": [flag]}
    pipeline._write(d / "context.json", {"flags": []})
    j.save("clip01-context", {"flags": []})
    got = edit.text(d.parent, d.name, "hook", "99 rockets")
    assert got["text"] == "99 rockets" and got["context_flags"] == [flag]
    assert any("hook number not spoken" in f and "99" in f for f in got["fact_check"])
    assert got["receipt"] == pipeline._read(d / "receipt.json")
    assert j.cached("clip01-plan")["hook"] == "99 rockets" and len(j.prompts) == 1
    assert calls == [("9x16", "zing")]


def test_visual_and_status(ready):
    d, _, calls = ready
    got = edit.visual(d.parent, d.name, "v1", 1)
    assert (got["request"], got["index"]) == ("v1", 1)
    assert pipeline._read(d / "plan.json")["visuals"]["v1"]["path"].endswith("b.jpg")
    assert pipeline._read(d / "visuals" / "picks.json")["picks"]["v1"]["pick"] == 1
    request = mcp_server.h_factory_status(str(d.parent))["clips"][0]["visual_requests"][0]
    assert request["id"] == "v1" and request["candidate_count"] == 2 and request["pick"] == 1
    assert [c["index"] for c in request["candidates"]] == [0, 1]
    assert [c["path"] for c in request["candidates"]] == ["a.jpg", "b.jpg"]
    assert calls == [("9x16", "zing")]


def test_render_and_project_shapes(ready):
    d, _, calls = ready
    got = edit.rerender(d.parent, d.name, "4x5", "swiss")
    assert got["rendered"].endswith("clip-4x5-swiss.mp4") and got["shape"] == "4x5" and got["pack"] == "swiss"
    cfg = pipeline._read(d.parent / "factory.json")
    pipeline._write(d.parent / "factory.json", {**cfg, "shapes": ["9x16", "1x1"], "pack": "swiss"})
    edit.text(d.parent, d.name, "hook", "We built a rocket")
    assert calls == [("4x5", "swiss"), ("9x16", "swiss"), ("1x1", "swiss")]


@pytest.mark.parametrize("selector", [{"index": 3}, {"at": 3.2, "old": "rocket."}])
def test_word_keeps_timings_and_refreshes_checks(ready, selector):
    d, j, calls = ready
    before = pipeline._read(d / "words.json")
    got = edit.word(d.parent, d.name, new="Rocket!", **selector)
    after = pipeline._read(d / "words.json")
    assert after == {**before, "words": before["words"][:3] + [{**before["words"][3], "w": "Rocket!"}]}
    assert pipeline._read(d / "words-heard.json") == before
    fix = {"index": 3, "os": 3, "oe": 3.5, "heard": "rocket.", "meant": "Rocket!"}
    assert pipeline._read(d / "word-fixes.json") == [fix]
    assert fix in pipeline._read(d / "plan.json")["fixes"]
    assert (got["index"], got["at"], got["old"], got["new"]) == (3, 3, "rocket.", "Rocket!")
    assert '"words": "We built a Rocket!"' in j.prompts[-1]
    assert any("caption fix" in f and "Rocket!" in f for f in got["fact_check"])
    assert got["receipt"] == pipeline._read(d / "receipt.json") and calls == [("9x16", "zing")]


def test_word_survives_automatic_fixes_and_later_edits(ready):
    d, _, _ = ready
    words = pipeline._read(d / "words.json")
    words["words"][1]["w"] = "Buddy Shaw"
    pipeline._write(d / "words.json", words)
    raw = pipeline._read(d / "plan-raw.json")
    raw["fixes"] = [{"heard": "Buddy Shaw", "meant": "Buddy Shah"}]
    raw["shots"].append({"from": 1, "layout": "graphic", "graphic": {"kind": "quote", "text": "Buddy Shāh"}})
    pipeline._write(d / "plan-raw.json", raw)
    plan.finalize(d, raw, {})
    assert pipeline._read(d / "words.json")["words"][1]["w"] == "Buddy Shah"
    edit.word(d.parent, d.name, 1, "Buddy Shāh")
    edit.word(d.parent, d.name, 3, "ship.")
    edit.word(d.parent, d.name, 3, "rocket!")
    edit.text(d.parent, d.name, "hook", "Buddy Shāh")
    edit.visual(d.parent, d.name, "v1", 1)
    pipeline.run(d.parent, judge.Judge(d.parent), say=lambda m: None)
    after = pipeline._read(d / "words.json")
    assert [w["w"] for w in after["words"]] == ["We", "Buddy Shāh", "a", "rocket!"]
    assert [(w["os"], w["oe"]) for w in after["words"]] == [(w["os"], w["oe"]) for w in words["words"]]
    assert pipeline._read(d / "words-heard.json") == words
    assert any(i["what"] == "Buddy Shāh" for i in pipeline._read(d / "receipt.json")["items"])


def test_word_index_disambiguates_equal_times(ready):
    d, _, _ = ready
    data = pipeline._read(d / "words.json")
    data["words"][1] = dict(data["words"][0])
    pipeline._write(d / "words.json", data)
    with pytest.raises(FactoryError, match="no unique caption word"):
        edit.word(d.parent, d.name, at=.2, old="We", new="They")
    edit.word(d.parent, d.name, 1, "They")
    assert [w["w"] for w in pipeline._read(d / "words.json")["words"]][:2] == ["We", "They"]


@pytest.mark.parametrize("action,values,want", [
    ("rate", {"verdict": "maybe"}, "verdict must"),
    ("copy", {"field": "hook", "text": "hi"}, "unknown field"),
    ("hook", {"text": " "}, "text cannot be empty"),
    ("visual", {"request": "missing", "index": 0}, "no such visual candidate"),
    ("visual", {"request": "v1", "index": -1}, "no such visual candidate"),
    ("visual", {"request": "v1", "index": 2}, "no such visual candidate"),
    ("word", {"index": -1, "new": "hi"}, "no such caption word"),
    ("word", {"index": True, "new": "hi"}, "no such caption word"),
    ("word", {"index": 4, "new": "hi"}, "no such caption word"),
    ("word", {"index": 0, "new": " "}, "text cannot be empty"),
    ("word", {"index": 0, "old": "stale", "new": "hi"}, "caption word 0 is"),
    ("word", {"at": float("nan"), "old": "We", "new": "hi"}, "give a word index"),
    ("word", {"at": 99, "old": "We", "new": "hi"}, "no unique caption word"),
    ("render", {"shape": "2x3"}, "unknown shape"),
    ("render", {"pack": "missing"}, "pack"),
    ("bad", {}, "action must"),
])
def test_bad_edits_do_not_write(ready, action, values, want):
    d, _, calls = ready
    before = {p: p.read_bytes() for p in d.rglob("*.json")}
    with pytest.raises(FactoryError, match=want):
        edit.apply(d.parent, d.name, action, **values)
    assert {p: p.read_bytes() for p in d.rglob("*.json")} == before and not calls


@pytest.mark.parametrize("clip", ["clip99", "../clip01", "clip01/", None])
def test_bad_clip(ready, clip):
    d, _, _ = ready
    with pytest.raises(FactoryError, match="unknown clip"):
        edit.text(d.parent, clip, "x", "hello")


@pytest.mark.parametrize("action,values,key,want", [
    ("rate", {"verdict": "edits", "why": "Tighter"}, "verdict", "edits"),
    ("hook", {"text": "New hook"}, "text", "New hook"),
    ("copy", {"field": "x", "text": "New copy"}, "saved", "x"),
    ("visual", {"request": "v1", "index": 1}, "index", 1),
    ("word", {"index": 3, "new": "Rocket!"}, "new", "Rocket!"),
    ("render", {"shape": "1x1"}, "shape", "1x1"),
])
def test_mcp_edit(ready, action, values, key, want):
    d, _, _ = ready
    got = mcp_server.h_factory_edit(str(d.parent), d.name, action, **values)
    assert got["ok"] and got["action"] == action and got[key] == want
    assert {"fact_check", "context_flags", "receipt", "pending"} <= got.keys()


def test_mcp_errors(ready):
    d, _, _ = ready
    for clip, action, values, want in [
        ("clip99", "word", {"index": 0, "new": "hi"}, "unknown clip"),
        (d.name, "copy", {"field": "bad", "text": "hi"}, "unknown field"),
        (d.name, "visual", {"request": "v1", "index": 99}, "no such visual candidate"),
    ]:
        got = mcp_server.h_factory_edit(str(d.parent), clip, action, **values)
        assert got["ok"] is False and want in got["error"]
    assert "not a factory project" in mcp_server.h_factory_edit(str(d / "missing"), d.name, "render")["error"]


def test_mcp_schema_and_stdio(client, ready):
    tools = asyncio.run(mcp_server.build_server().list_tools())
    assert len(tools) == 44
    schema = next(t.model_dump(by_alias=True)["inputSchema"] for t in tools if t.name == "factory_edit")
    assert schema["required"] == ["project", "clip", "action"]
    assert schema["properties"]["action"]["enum"] == ["rate", "hook", "copy", "visual", "word", "render"]
    d, _, _ = ready
    result = client.send("tools/call", {"name": "factory_edit", "arguments": {
        "project": str(d.parent), "clip": d.name, "action": "copy", "field": "x", "text": "From MCP"}})
    got = json.loads(result["content"][0]["text"])
    assert got["ok"] and got["text"] == "From MCP"
    assert pipeline._read(d / "post.json")["x"] == "From MCP"


def test_host_context_remains_pending_until_answered(ready, monkeypatch):
    d, _, calls = ready
    monkeypatch.setattr(edit, "Judge", judge.Judge)
    got = mcp_server.h_factory_edit(str(d.parent), d.name, "hook", text="New hook")
    assert got["ok"] and got["context"] is None and calls
    assert [p["task"] for p in got["pending"]] == ["clip01-context"]
    assert mcp_server.h_factory_answer(str(d.parent), "clip01-context", {"flags": []})["ok"]
    pipeline.run(d.parent, judge.Judge(d.parent), say=lambda m: None)
    assert pipeline._read(d / "context.json")["flags"] == []


@pytest.mark.parametrize("args,key,want", [
    (["--rate", "edits", "--why", "Tighter"], "verdict", "edits"),
    (["--hook", "New hook"], "text", "New hook"),
    (["--copy", "x", "New copy"], "saved", "x"),
    (["--visual", "v1", "1"], "index", 1),
    (["--word", "3", "Rocket!"], "new", "Rocket!"),
    (["--render", "1x1", "--pack", "swiss"], "pack", "swiss"),
])
def test_cli_edit(ready, capsys, args, key, want):
    d, _, _ = ready
    assert command.run(["edit", str(d.parent), d.name, *args]) == 0
    assert json.loads(capsys.readouterr().out)[key] == want


@pytest.mark.parametrize("args", [[], ["--hook", "Hi", "--rate", "post"]])
def test_cli_needs_one_action(ready, args):
    d, _, calls = ready
    with pytest.raises(SystemExit) as exc:
        command.run(["edit", str(d.parent), d.name, *args])
    assert exc.value.code == 2 and not calls


@pytest.mark.parametrize("args,want", [
    (["--copy", "bad", "hi"], "unknown field"),
    (["--word", "99", "hi"], "no such caption word"),
    (["--hook", "hi", "--why", "reason"], "--why needs --rate"),
    (["--hook", "hi", "--pack", "swiss"], "--pack needs --render"),
])
def test_cli_bad_edit(ready, capsys, args, want):
    d, _, calls = ready
    assert command.run(["edit", str(d.parent), d.name, *args]) == 2
    assert want in capsys.readouterr().err and not calls


def test_studio_keeps_responses_and_queue_labels(ready):
    d, _, calls = ready
    studio = serve.Studio(d.parent)
    assert studio.rate({"clip": d.name, "v": "fix"}) == {"saved": d.name}
    assert studio.text({"clip": d.name, "field": "x", "text": "copy"}) == {"saved": "x"}
    before = pipeline._read(d / "visuals" / "picks.json")
    assert studio.visual({"clip": d.name, "request": "v1", "index": 1}) == {"queued": "clip01: new visual"}
    assert studio.text({"clip": d.name, "field": "hook", "text": "New"}) == {"queued": "clip01: new hook"}
    # queued edits change files when their job runs, so two edits on one clip never overwrite each other
    assert pipeline._read(d / "visuals" / "picks.json") == before and pipeline._read(d / "plan-raw.json")["hook"] != "New"
    assert studio.rerender({"clip": d.name, "shape": "1x1"}) == {"queued": "clip01: 1x1 zing"}
    assert studio.word({"clip": d.name, "index": 3, "new": "Rocket!"}) == {"queued": "clip01: new word"}
    assert not calls
    while not studio.jobs.empty():
        studio.jobs.get_nowait()[1]()
    assert pipeline._read(d / "visuals" / "picks.json")["picks"]["v1"] == {"pick": 1, "why": "chosen in the dashboard"}
    assert pipeline._read(d / "plan-raw.json")["hook"] == "New"
    assert calls == [("9x16", "zing"), ("9x16", "zing"), ("1x1", "zing"), ("9x16", "zing")]
    assert studio.state()["clips"][0]["words"][3]["w"] == "Rocket!"


def test_page_edits_a_word_and_keeps_the_draft():
    got = javascript("dashboard.html", """
      const c = {clip: 'clip01', words: [{w: '<Rocket>', os: 3, oe: 3.5}]};
      renderDetail = () => {}; load = async () => {};
      let sent;
      api.post = async (path, body) => { sent = {path, body}; };
      all(captionBlock(c)).find(n => n.tagName === 'button').events.click();
      const block = captionBlock(c), input = all(block).find(n => n.tagName === 'input');
      input.value = 'Rocket!'; input.events.input({target: input});
      const draft = all(captionBlock(c)).find(n => n.tagName === 'input').value;
      await all(block).find(n => n.tagName === 'form').events.submit({preventDefault() {}});
      console.log(JSON.stringify({draft, sent, left: ui.word.clip01 || null}));
    """)
    assert got == {"draft": "Rocket!", "sent": {"path": "/api/word", "body": {
        "clip": "clip01", "index": 0, "old": "<Rocket>", "new": "Rocket!"}}, "left": None}


@pytest.mark.parametrize("order", [("hook", "visual", "word"), ("visual", "word", "hook"),
                                  ("word", "hook", "visual")])
def test_studio_edits_read_current_files_in_the_worker(ready, order):
    d, j, calls = ready
    studio = serve.Studio(d.parent)

    def earlier_job():
        raw = pipeline._read(d / "plan-raw.json")
        pipeline._write(d / "plan-raw.json", {**raw, "hook_until": 4})
    studio.queue("run", earlier_job)
    before = {p: p.read_bytes() for p in d.parent.rglob("*.json")}
    actions = {
        "hook": lambda: studio.text({"clip": d.name, "field": "hook", "text": "New hook"}),
        "visual": lambda: studio.visual({"clip": d.name, "request": "v1", "index": 1}),
        "word": lambda: studio.word({"clip": d.name, "index": 3, "new": "ship."}),
    }
    for action in order:
        assert actions[action]() == {"queued": f"{d.name}: new {action}"}
    assert {p: p.read_bytes() for p in d.parent.rglob("*.json")} == before and not calls
    studio.jobs.get_nowait()[1]()
    for action in order:
        studio.jobs.get_nowait()[1]()
        assert pipeline._read(d / "plan.json")["hook_until"] == 4
    final = pipeline._read(d / "plan.json")
    assert final["hook"] == j.cached("clip01-plan")["hook"] == "New hook"
    assert final["visuals"]["v1"]["path"].endswith("b.jpg")
    assert pipeline._read(d / "words.json")["words"][3]["w"] == "ship."
    assert calls == [("9x16", "zing")] * 3


def test_studio_visual_jobs_keep_other_picks(ready):
    d, _, _ = ready
    raw = pipeline._read(d / "plan-raw.json")
    raw["visual_requests"].append({"id": "v2", "query": "rocket", "kind": "photo"})
    raw["shots"].append({"from": 2, "layout": "split", "visual": "v2"})
    pipeline._write(d / "plan-raw.json", raw)
    manifest = pipeline._read(d / "visuals" / "manifest.json")
    pipeline._write(d / "visuals" / "manifest.json", {**manifest, "v2": manifest["v1"]})
    studio = serve.Studio(d.parent)
    studio.visual({"clip": d.name, "request": "v1", "index": 1})
    studio.visual({"clip": d.name, "request": "v2", "index": 1})
    studio.jobs.get_nowait()[1]()
    assert "v2" not in pipeline._read(d / "visuals" / "picks.json")["picks"]
    studio.jobs.get_nowait()[1]()
    assert {k: v["pick"] for k, v in pipeline._read(d / "visuals" / "picks.json")["picks"].items()} == {
        "v1": 1, "v2": 1}
    assert all(v["path"].endswith("b.jpg") for v in pipeline._read(d / "plan.json")["visuals"].values())


@pytest.mark.parametrize("action,body,want", [
    ("visual", {"clip": "clip99", "request": "v1", "index": 0}, "unknown clip 'clip99'"),
    ("text", {"clip": "clip99", "field": "hook", "text": "Hi"}, "unknown clip 'clip99'"),
    ("word", {"clip": "clip99", "index": 0, "new": "Hi"}, "unknown clip 'clip99'"),
    ("visual", {"request": "v2", "index": 0}, "no such visual candidate"),
    ("visual", {"request": "v1", "index": 2}, "no such visual candidate"),
    ("visual", {"request": "v1", "index": True}, "no such visual candidate"),
    ("text", {"field": "hook", "text": " "}, "text cannot be empty"),
    ("text", {"field": "x", "text": " "}, "text cannot be empty"),
    ("text", {"field": "bad", "text": "Hi"}, "unknown field 'bad'"),
    ("word", {"index": 4, "new": "Hi"}, "no such caption word; index must be from 0 to 3"),
    ("word", {"index": 0, "new": " "}, "text cannot be empty"),
])
def test_studio_rejects_bad_edits_before_queueing(ready, action, body, want):
    d, _, calls = ready
    studio = serve.Studio(d.parent)
    before = {p: p.read_bytes() for p in d.parent.rglob("*.json")}
    with pytest.raises(FactoryError) as exc:
        getattr(studio, action)({"clip": d.name, **body})
    assert str(exc.value) == want and studio.jobs.empty()
    assert {p: p.read_bytes() for p in d.parent.rglob("*.json")} == before and not calls


def test_mcp_edit_waits_for_factory_run(ready, monkeypatch):
    d, _, calls = ready
    entered, finish = threading.Event(), threading.Event()

    def running(*args, **kwargs):
        entered.set()
        assert finish.wait(5)
    monkeypatch.setattr(pipeline, "run", running)
    monkeypatch.setattr(mcp_server, "_FACTORY_JOBS", {})
    assert mcp_server.h_factory_run(str(d.parent))["status"] == "started"
    worker = mcp_server._FACTORY_JOBS[str(d.parent.resolve())]
    try:
        assert entered.wait(5)
        before = {p: p.read_bytes() for p in d.parent.rglob("*.json")}
        for action in ("rate", "hook", "copy", "visual", "word", "render"):
            got = mcp_server.h_factory_edit(str(d / ".."), d.name, action, text="New hook")
            assert got == {"ok": False, "error":
                           "a factory run is in progress for this project; wait for factory_status to show it finished"}
        assert {p: p.read_bytes() for p in d.parent.rglob("*.json")} == before and not calls
    finally:
        finish.set()
        worker.join(5)
    assert not worker.is_alive() and not mcp_server.h_factory_status(str(d.parent))["running"]
    assert mcp_server.h_factory_edit(str(d.parent), d.name, "hook", text="New hook")["ok"]


def test_mcp_edit_allows_another_project_to_run(ready, monkeypatch):
    d, _, _ = ready
    monkeypatch.setattr(mcp_server, "_FACTORY_JOBS", {str(d.parent / "other"): threading.current_thread()})
    assert mcp_server.h_factory_edit(str(d.parent), d.name, "hook", text="New hook")["ok"]


@pytest.mark.parametrize("kind", ["quote", "title"])
@pytest.mark.parametrize("automatic", [False, True])
def test_manual_word_fix_updates_graphics_and_copy(ready, kind, automatic):
    d, _, _ = ready
    data = pipeline._read(d / "words.json")
    data["words"][1]["w"] = "bult"
    pipeline._write(d / "words.json", data)
    raw = {"hook": "We bult a rocket.", "shots": [{"from": 0, "layout": "graphic",
           "graphic": {"kind": kind, "text": "We bult a rocket."}}],
           "fixes": [{"heard": "bult", "meant": "built"}] if automatic else []}
    pipeline._write(d / "plan-raw.json", raw)
    pipeline._write(d / "post.json", {field: "We bult a rocket." for field in edit.TEXT_FIELDS})
    got = edit.word(d.parent, d.name, 3, "ship.")
    wanted = "We built a ship." if automatic else "We bult a ship."
    final = pipeline._read(d / "plan.json")
    assert final["hook"] == wanted
    assert final["shots"] == [{"from": 0, "layout": "graphic", "graphic": {"kind": kind, "text": wanted}}]
    assert pipeline._read(d / "post.json") == {field: wanted for field in edit.TEXT_FIELDS}
    assert not any("not spoken" in f for f in got["fact_check"])


def test_repeated_word_fix_keeps_the_original_heard_text(ready):
    d, _, _ = ready
    edit.word(d.parent, d.name, 3, "ship.")
    edit.word(d.parent, d.name, 0, "They")
    edit.word(d.parent, d.name, 3, "shuttle.")
    fixes = pipeline._read(d / "word-fixes.json")
    assert fixes == [{"index": 0, "os": 0, "oe": .5, "heard": "We", "meant": "They"},
                     {"index": 3, "os": 3, "oe": 3.5, "heard": "rocket.", "meant": "shuttle."}]
    assert pipeline._read(d / "words.json")["words"][3]["w"] == "shuttle."
    assert pipeline._read(d / "words-heard.json")["words"][3]["w"] == "rocket."
    assert pipeline._read(d / "plan.json")["fixes"] == fixes


def test_recut_discards_old_words_and_manual_fixes(ready, monkeypatch):
    d, _, _ = ready
    edit.word(d.parent, d.name, 3, "ship.")
    monkeypatch.setattr(cut, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(cut, "run", lambda *a: None)
    monkeypatch.setattr(cut, "silences", lambda *a: [])
    monkeypatch.setattr(cut, "cams", lambda *a: {})
    words = [{"w": w, "s": 100 + i, "e": 100.5 + i} for i, w in enumerate("They built a shuttle.".split())]
    got = cut.cut(d, d.parent / "ep.mp4", words, 100, 104)
    assert not (d / "words-heard.json").exists() and not (d / "word-fixes.json").exists()
    plan.finalize(d, pipeline._read(d / "plan-raw.json"), {})
    assert pipeline._read(d / "words.json") == got
    assert [w["w"] for w in got["words"]] == [w["w"] for w in words]
    assert pipeline._read(d / "plan.json")["fixes"] == []


@pytest.mark.parametrize("stderr", ["x" * 600 + "render failed", ("x" * 600 + "render failed").encode(),
                                    b"bad byte \xff", None], ids=["text", "bytes", "bad-utf8", "no-stderr"])
@pytest.mark.parametrize("action,args", [("render", ["--render", "1x1"]), ("hook", ["--hook", "New hook"])])
def test_render_subprocess_errors_are_clean(ready, monkeypatch, capsys, stderr, action, args):
    d, _, _ = ready
    error = subprocess.CalledProcessError(1, ["node", "render.cjs"], stderr=stderr)

    def failed(*args, **kwargs):
        raise error
    monkeypatch.setattr(render, "render", failed)
    detail = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr or str(error)
    got = mcp_server.h_factory_edit(str(d.parent), d.name, action, text="New hook")
    assert got == {"ok": False, "error": detail[-500:]}
    assert command.run(["edit", str(d.parent), d.name, *args]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == f"zing factory: {detail[-500:]}\n"
