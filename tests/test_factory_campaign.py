"""Campaign rules use local files and a fake judge."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from myzing import mcp_server
from myzing.factory import campaign, command, judge, pipeline, postcopy, render, review, scout, serve, source
from myzing.factory.tools import FactoryError, data_path

RUN = subprocess.run
from test_factory_review_fixes import javascript  # noqa: E402  (imported before the fixture blocks subprocess)


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda *a, **k: [])
    monkeypatch.setattr(serve.Studio, "_work", lambda self: None)


def project(tmp_path, brief=None, **settings):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"media")
    path = tmp_path / "campaign.json"
    if brief is not None:
        pipeline._write(path, brief)
    return Path(pipeline.init(tmp_path / "project", media, name="Show", shapes=["9x16"],
                              brief=path if brief is not None else None, **settings)["project"])


def clip(root, seconds=20, hook="A test", text="A test."):
    d = root / "clip01"
    words = [{"w": w, "os": i, "oe": i + .5} for i, w in enumerate(text.split())]
    words[-1]["oe"] = seconds - .45
    pipeline._write(d / "words.json", {"start": 10, "end": 10 + seconds, "duration": seconds, "words": words})
    pipeline._write(d / "cams.json", {"frames": 600, "size": [1920, 1080],
                                     "cams": [{"from": 0, "to": seconds + 1, "mode": "wide", "faces": 2}]})
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [
        {"hook": hook, "start": 10, "end": 10 + seconds, "snapped": True}]})
    pipeline._write(d / "plan.json", {"hook": hook, "shots": [{"from": 0, "layout": "solo"}]})
    return d


class Answers(judge.Judge):
    def __init__(self, root):
        super().__init__(root)
        self.prompts = []

    def ask(self, task, text, images=()):
        self.prompts.append((task, text))
        if task == "scout":
            return {"moments": [{"start": 10, "end": 30, "hook": "A test"}]}
        if task.endswith("-copy"):
            return {field: "A test. #ad" for field in postcopy.FIELDS}
        if task.endswith("-context"):
            return {"flags": []}
        return {"hook": "A test", "shots": [{"from": 0, "layout": "solo"}]}


def fake_render(monkeypatch):
    made = []

    def make(d, shape, pack):
        data = render.scene_data(d, shape, pack, parallax=False, front=False, sharpen=False)
        made.append(data)
        tag = render.suffix(shape, pack)
        pipeline._write(d / f"data{tag}.json", data)
        (d / f"clip{tag}.mp4").write_bytes(b"render")
    monkeypatch.setattr(render, "render", make)
    return made


@pytest.mark.parametrize("rights", campaign.RIGHTS)
def test_rights_are_labels_and_reach_copy_status_and_review(tmp_path, monkeypatch, capsys, rights):
    root = project(tmp_path, rights=rights)
    d = clip(root)
    made = fake_render(monkeypatch)
    got = pipeline.run(root, Answers(root), say=lambda m: None)
    assert len(made) == 1 and not got["failed"]
    assert pipeline._read(root / "factory.json")["rights"] == rights
    assert pipeline._read(d / "post.json")["rights"] == rights
    assert got["rights"] == rights and got["source"]["name"] == "Show"
    assert campaign.RIGHTS[rights] in review.build(root).read_text(encoding="utf-8")
    assert command.run(["status", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["rights"] == rights


def test_rights_default_and_bad_label(tmp_path):
    root = project(tmp_path)
    assert pipeline.status(root)["rights"] == "unknown"
    cfg = pipeline._read(root / "factory.json")
    cfg.pop("rights")
    pipeline._write(root / "factory.json", cfg)
    assert pipeline.status(root)["rights"] == "unknown"
    with pytest.raises(FactoryError, match="rights must be"):
        project(tmp_path, rights="cleared")


@pytest.mark.parametrize("value,why", [
    ([], "JSON object"), (None, "JSON object"), ({"name": 4}, "name must be text"),
    ({"notes": []}, "notes must be text"), ({"disclosure": False}, "disclosure must be text"),
    ({"disclosure": " "}, "disclosure must not be empty"), ({"tags": "#ad"}, "tags must be a list"),
    ({"tags": ["#ad", 2]}, "tags must be a list"), ({"tags": [""]}, "tags must be a list"),
    ({"banned": {}}, "banned must be a list"), ({"banned": [None]}, "banned must be a list"),
    ({"min_seconds": True}, "min_seconds must be a positive number"),
    ({"max_seconds": "60"}, "max_seconds must be a positive number"),
    ({"max_seconds": -1}, "max_seconds must be a positive number"),
    ({"max_seconds": float("inf")}, "max_seconds must be a positive number"),
    ({"min_seconds": float("nan")}, "min_seconds must be a positive number"),
    ({"min_seconds": 60, "max_seconds": 15}, "min_seconds must be no greater"),
    ({"disclosure_seconds": .9}, "between 1 and 5"), ({"disclosure_seconds": 5.1}, "between 1 and 5"),
    ({"disclosure_seconds": False}, "disclosure_seconds must be a positive number"),
    ({"max_second": 60}, "unknown brief fields"),
])
def test_brief_validation(tmp_path, value, why):
    path = tmp_path / "bad.json"
    pipeline._write(path, value)
    with pytest.raises(FactoryError, match=why):
        campaign.load(path)


def test_bad_json_and_missing_files_are_factory_errors(tmp_path):
    path = tmp_path / "bad.json"
    for contents in (None, "{bad json", "name: Campaign X"):
        if contents is not None:
            path.write_text(contents, encoding="utf-8")
        with pytest.raises(FactoryError, match="cannot read brief"):
            campaign.load(path)
    with pytest.raises(FactoryError, match="disclosure must not be empty"):
        project(tmp_path, brief={"disclosure": ""})
    assert not (tmp_path / "project").exists()


def test_cli_and_batch_pass_both_flags(tmp_path, monkeypatch, capsys):
    root = project(tmp_path)
    brief = {"name": "Campaign X", "disclosure": "Paid partnership with X", "disclosure_seconds": 2,
             "tags": ["#ad", "@brand"], "banned": ["gambling"], "min_seconds": 15, "max_seconds": 60,
             "notes": "Keep the answer."}
    path = tmp_path / "brief.json"
    pipeline._write(path, brief)
    assert command.run(["new", str(root), "--media", str(tmp_path / "episode.mp4"),
                        "--rights", "licensed", "--brief", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["rights"] == "licensed"
    path.unlink()
    assert campaign.read(root) == brief
    from myzing.factory import batch
    calls = []
    monkeypatch.setattr(batch, "run", lambda *a, **k: calls.append(k) or {})
    assert command.run(["batch", str(tmp_path), "--out", str(root), "--rights", "own", "--brief", str(path)]) == 0
    assert calls[0]["rights"] == "own" and calls[0]["brief"] == path


@pytest.mark.parametrize("mode", ["context", "launch"])
def test_scout_uses_brief_rules_and_bounds(tmp_path, mode):
    brief = {"min_seconds": 15, "max_seconds": 60, "banned": ["gambling", "competitor names"],
             "notes": "Keep the answer to the opening question."}
    root = project(tmp_path, brief=brief, mode=mode, moments=1)
    pipeline._write(root / "transcript.json", [{"s": 0, "e": 200, "text": "A test."}])
    ask = Answers(root)
    got = pipeline._moments(root, ask, tmp_path / "episode.mp4", pipeline._read(root / "factory.json"), lambda m: None)
    text = ask.prompts[0][1]
    assert got[0]["end"] - got[0]["start"] == 20
    high = 56 if mode == "launch" else 59                    # the scout aims inside the brief: tail pad, end card
    assert f"16 to {high} seconds" in text and "25–70" not in text and "120 seconds" not in text
    assert "Avoid these topics. gambling; competitor names" in text and brief["notes"] in text
    assert "{BRIEF}" not in text and "{LENGTH}" not in text
    with pytest.raises(FactoryError, match=f"at most {high} seconds"):
        pipeline.answer(root, "scout", {"moments": [{"start": 0, "end": 61, "hook": "Long"}]})


def test_scout_checks_each_bound_and_the_sum_of_launch_spans():
    moment = {"hook": "A test", "start": 0, "end": 10}
    assert scout.check({"moments": [moment]}, brief={"max_seconds": 11})     # bounds carry a one-second margin
    with pytest.raises(ValueError, match="at least 16"):
        scout.check({"moments": [moment]}, brief={"min_seconds": 15})
    film = {"hook": "A film", "spans": [{"start": 100, "end": 110}, {"start": 0, "end": 10}]}
    assert scout.check({"moments": [film]}, brief={"min_seconds": 19, "max_seconds": 21})
    with pytest.raises(ValueError, match="at most 18"):
        scout.check({"moments": [film]}, brief={"max_seconds": 19})
    words = [{"w": "Start", "s": 0, "e": 1}, {"w": "end.", "s": 11, "e": 12}]
    assert scout.snap(moment, words)["end"] > 10
    assert scout.snap(moment, words, {"max_seconds": 10}) == moment


def test_tags_append_once_in_brief_order_and_keep_context_links():
    copy = {field: "A test. #advertisement @branded" for field in postcopy.FIELDS}
    copy["x"] = "A test. #ad"
    copy["first_comment"] = "Full talk {SOURCE_URL} at {TIMESTAMP}"
    brief = {"tags": ["#ad", "@brand"]}
    got = postcopy.finalize(copy, {"start": 125}, {"url": "https://youtu.be/abc", "rights": "permission"}, brief)
    assert got["x"] == "A test. #ad\n\n@brand"
    assert got["instagram"].endswith("\n\n#ad @brand")
    assert got["first_comment"] == "Full talk https://youtu.be/abc?t=125s at 2:05"     # a comment, not the post
    assert got["youtube_title"] == "A test. #advertisement @branded #ad @brand"           # one line
    assert postcopy.require_tags(got, brief) == got


def test_one_pick_outside_the_brief_drops_out_and_the_rest_stand():
    picks = [{"hook": "Long", "start": 0, "end": 90}, {"hook": "Fits", "start": 100, "end": 140}]
    assert [m["hook"] for m in scout.check({"moments": picks}, brief={"max_seconds": 60})] == ["Fits"]


@pytest.mark.parametrize("mode,high,hooks", [("context", 29, ["End card", "Fits"]), ("launch", 26, ["Fits"])])
def test_scout_margin_filters_picks_before_word_timing(tmp_path, mode, high, hooks):
    brief = {"min_seconds": 15, "max_seconds": 30}
    root = project(tmp_path, brief=brief, mode=mode, moments=4)
    pipeline._write(root / "transcript.json", [{"s": 0, "e": 200, "text": "A test."}])

    class Picks(Answers):
        def ask(self, task, text, images=()):
            self.prompts.append((task, text))
            return {"moments": [
                {"hook": "Long", "start": 0, "end": 29.8},
                {"hook": "End card", "spans": [{"start": 60, "end": 73.5}, {"start": 30, "end": 43.5}]},
                {"hook": "Short", "start": 90, "end": 105.8},
                {"hook": "Fits", "start": 120, "end": 140},
            ]}

    ask = Picks(root)
    got = pipeline._moments(root, ask, tmp_path / "episode.mp4", pipeline._read(root / "factory.json"), lambda m: None)
    assert [m["hook"] for m in got] == hooks
    assert f"16 to {high} seconds of source material" in ask.prompts[0][1]
    assert brief == {"min_seconds": 15, "max_seconds": 30}
    with pytest.raises(FactoryError, match=f"at most {high} seconds"):
        pipeline.answer(root, "scout", {"moments": [{"hook": "Long", "start": 0, "end": 29.8}]})


@pytest.mark.parametrize("mode,high", [("context", 29), ("launch", 26)])
def test_scout_snap_keeps_the_margin(tmp_path, mode, high):
    brief = {"min_seconds": 15, "max_seconds": 30}
    root = project(tmp_path, brief=brief, mode=mode, moments=1)
    moment = {"hook": "Fits", "start": 0, "end": high - .5}
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [moment]})
    pipeline._write(root / "words.json", [{"w": "Start", "s": .05, "e": 1},
                                          {"w": "the", "s": high - 1, "e": high - .6},
                                          {"w": "end.", "s": high - .1, "e": high + .1}])
    got = pipeline._moments(root, Answers(root), tmp_path / "episode.mp4", pipeline._read(root / "factory.json"),
                           lambda m: None)
    assert got == [{**moment, "snapped": True}]
    short = {"hook": "Fits", "start": 0, "end": 16.2}
    words = [{"w": "Start", "s": 1, "e": 2}, {"w": "end.", "s": 15, "e": 16.15}]
    assert scout.snap(short, words, brief, mode=mode) == short


@pytest.mark.parametrize("brief,mode,bounds", [
    ({"min_seconds": 15}, "context", "at least 16"),
    ({"max_seconds": 30}, "context", "at most 29"),
    ({"max_seconds": 30}, "launch", "at most 26"),
])
def test_scout_prompt_tightens_one_sided_bounds(brief, mode, bounds):
    text = scout.prompt([], 1, mode, brief=brief)
    assert f"{bounds} seconds of source material" in text
    assert "{LENGTH}" not in text


def test_tag_matching_ignores_case_without_appending_duplicates(tmp_path):
    brief = {"tags": ["#Sponsored", "@Brand"]}
    root = project(tmp_path, brief=brief)
    d = clip(root)
    post = {field: "A test. #sponsored @brand" for field in postcopy.FIELDS}
    assert campaign.missing_tags(post["x"], brief["tags"]) == []
    assert campaign.missing_tags("#sponsoredish @branded", brief["tags"]) == brief["tags"]
    assert postcopy.require_tags(post, brief) == post
    pipeline._write(d / "post.json", post)
    assert render.check_brief(d)["flags"] == []


@pytest.mark.parametrize("separator", [" ", "\t\n", ", ", ".", ";", ":", "?!", "'", '"', "()", "-",
                                       "–", "—", "‘’", "“”", ', ("—")! '])
def test_banned_phrases_match_across_spoken_punctuation(tmp_path, separator):
    d = clip(project(tmp_path, brief={"banned": ["competitor names"]}),
             text=f"Competitor{separator}NAMES, not competitors names or competitor namesake.")
    flags = render.check_brief(d)["flags"]
    assert [(f["term"], f["where"]) for f in flags] == [("competitor names", "spoken")]


def test_banned_phrases_keep_word_boundaries(tmp_path):
    d = clip(project(tmp_path, brief={"banned": ["competitor names"]}),
             text="Competitors, names and competitor namesake and competitor other names.")
    assert render.check_brief(d)["flags"] == []


def test_pipeline_appends_tags_without_another_copy_judgment(tmp_path, monkeypatch):
    root = project(tmp_path, brief={"tags": ["#ad", "@brand"]})
    d = clip(root)
    fake_render(monkeypatch)
    ask = Answers(root)
    for _ in range(2):
        assert not pipeline.run(root, ask, say=lambda m: None)["failed"]
    assert sum(task == "clip01-copy" for task, _ in ask.prompts) == 1
    post = pipeline._read(d / "post.json")
    assert all(post[k] == "A test. #ad\n\n@brand" for k in ("x", "instagram", "tiktok"))
    assert post["youtube_title"] == "A test. #ad @brand" and post["first_comment"] == "A test. #ad"
    assert pipeline._read(d / "brief_check.json")["flags"] == []


def test_banned_terms_flag_whole_words_in_hook_copy_and_speech(tmp_path, monkeypatch):
    root = project(tmp_path, brief={"banned": ["gambling", "competitor names", "test"]})
    d = clip(root, hook="GAMBLING", text="Competitor names, not tests or gamblingish.")
    made = fake_render(monkeypatch)
    got = pipeline.run(root, Answers(root), say=lambda m: None)
    flags = pipeline._read(d / "brief_check.json")["flags"]
    assert not got["failed"] and len(made) == 1
    assert {f["term"] for f in flags} == {"gambling", "competitor names", "test"}
    assert [f["where"] for f in flags if f["term"] == "gambling"] == ["hook"]
    assert [f["where"] for f in flags if f["term"] == "competitor names"] == ["spoken"]
    assert got["clips"][0]["brief_flags"] == len(flags)
    assert serve.Studio(root).state()["clips"][0]["brief_check"]["flags"] == flags
    page = review.build(root).read_text(encoding="utf-8")
    assert "Check the brief" in page and "competitor names" in page


@pytest.mark.parametrize("seconds,bounds,message", [
    (61, {"max_seconds": 60}, "clip runs 61 seconds; brief allows at most 60 seconds"),
    (14, {"min_seconds": 15}, "clip runs 14 seconds; brief allows at least 15 seconds"),
])
def test_length_errors_stop_pipeline_and_direct_render(tmp_path, monkeypatch, seconds, bounds, message):
    root = project(tmp_path, brief=bounds)
    d = clip(root, seconds=seconds)
    with pytest.raises(FactoryError, match=message):
        render.render(d)
    made = fake_render(monkeypatch)
    got = pipeline.run(root, Answers(root), say=lambda m: None)
    assert not made and got["failed"] == {"clip01": "clip01 cannot render. " + message}
    assert got["clips"][0]["brief_errors"] == [message]
    assert message in pipeline._read(d / "brief_check.json")["errors"]
    assert message in review.build(root).read_text(encoding="utf-8")


def test_length_includes_endcard_and_cached_clips_are_rechecked(tmp_path, monkeypatch):
    root = project(tmp_path, brief={"max_seconds": 21})
    d = clip(root)
    made = fake_render(monkeypatch)
    pipeline.run(root, Answers(root), say=lambda m: None)
    pipeline._write(root / "brief.json", {"max_seconds": 19})
    assert "clip01" in pipeline.run(root, Answers(root), say=lambda m: None)["failed"] and len(made) == 1
    pipeline._write(root / "brief.json", {"max_seconds": 21})
    plan = pipeline._read(d / "plan.json")
    plan["shots"].append({"from": 20, "layout": "graphic", "graphic": {"kind": "endcard", "name": "Done"}})
    pipeline._write(d / "plan.json", plan)
    with pytest.raises(FactoryError, match="clip runs 23 seconds"):
        render.check_brief(d)


@pytest.mark.parametrize("seconds", [15, 30])
def test_render_keeps_exact_brief_bounds(tmp_path, seconds):
    d = clip(project(tmp_path, brief={"min_seconds": 15, "max_seconds": 30}), seconds=seconds)
    assert render.check_brief(d) == {"seconds": seconds, "errors": [], "flags": []}


def test_removing_brief_clears_stale_checks_and_keeps_videos(tmp_path):
    root = project(tmp_path, brief={"max_seconds": 19, "banned": ["test"]})
    d = clip(root)
    for name in ("clip.mp4", "clip-1x1.mp4"):
        (d / name).write_bytes(b"render")
    got = render.check_brief(d, stop=False)
    assert got["errors"] and got["flags"] and (d / "brief_check.json").is_file()
    (root / "brief.json").unlink()
    for _ in range(2):
        assert render.check_brief(d) is None
        assert not (d / "brief_check.json").exists()
        assert all((d / name).read_bytes() == b"render" for name in ("clip.mp4", "clip-1x1.mp4"))
    assert pipeline.status(root)["clips"][0]["brief_flags"] == 0
    assert pipeline.status(root)["clips"][0]["brief_errors"] == []


def test_one_bad_clip_does_not_stop_the_other_clips(tmp_path, monkeypatch):
    root = project(tmp_path, brief={"max_seconds": 21})
    d = clip(root, seconds=22)
    other = root / "clip02"
    shutil.copytree(d, other)
    words = pipeline._read(other / "words.json")
    words["words"][-1]["oe"] = 19.55
    pipeline._write(other / "words.json", words)
    data = pipeline.load_moments(root)
    data["moments"].append({**data["moments"][0], "end": 30})
    pipeline._write(root / "moments.json", data)
    made = fake_render(monkeypatch)
    got = pipeline.run(root, Answers(root), say=lambda m: None)
    assert set(got["failed"]) == {"clip01"} and len(made) == 1
    assert not (d / "clip.mp4").exists() and (other / "clip.mp4").is_file()


def test_manual_copy_edits_refresh_flags_even_when_length_needs_fixing(tmp_path):
    root = project(tmp_path, brief={"tags": ["#ad"], "banned": ["gambling"], "max_seconds": 19})
    d = clip(root)
    studio = serve.Studio(root)
    assert studio.text({"clip": "clip01", "field": "x", "text": "GAMBLING #advertisement"}) == {"saved": "x"}
    got = pipeline._read(d / "brief_check.json")
    assert len(got["errors"]) == 1 and len(got["flags"]) == len(campaign.POSTED) + 1
    assert {f["kind"] for f in got["flags"]} == {"tags", "banned"}
    assert pipeline._read(d / "post.json")["x"] == "GAMBLING #advertisement"


def test_missing_tags_are_flags_and_a_short_disclosure_is_an_error(tmp_path):
    root = project(tmp_path, brief={"tags": ["#ad"]})
    d = clip(root, seconds=4)
    data = render.scene_data(d, "9x16", "zing", parallax=False, front=False, sharpen=False)
    got = pipeline._read(d / "brief_check.json")
    assert not got["errors"] and len(got["flags"]) == len(campaign.POSTED) and "disclosure" not in data
    pipeline._write(root / "brief.json", {"disclosure": "Paid partnership with X", "disclosure_seconds": 5})
    with pytest.raises(FactoryError, match="missing disclosure for the first 5 seconds"):
        render.render(d)


@pytest.mark.parametrize("shape", render.SHAPES)
@pytest.mark.parametrize("seconds", [None, 1, 3.5, 5])
def test_disclosure_is_timed_scene_data_in_every_shape(tmp_path, shape, seconds):
    brief = {"disclosure": "Paid partnership with X"}
    if seconds is not None:
        brief["disclosure_seconds"] = seconds
    d = clip(project(tmp_path, brief=brief))
    data = render.scene_data(d, shape, "zing", parallax=False, front=False, sharpen=False)
    assert data["disclosure"] == {"text": brief["disclosure"], "from": 0, "to": seconds or 2.0}
    assert data["duration"] == 20 and data["aspect"] == shape
    assert pipeline._read(d / "brief_check.json")["errors"] == []


def test_missing_disclosure_stops_before_capture(tmp_path, monkeypatch):
    d = clip(project(tmp_path, brief={"disclosure": "Paid partnership with X"}))
    data = render.scene_data(d, "9x16", "zing", parallax=False, front=False, sharpen=False)
    data.pop("disclosure")
    monkeypatch.setattr(render, "scene_data", lambda *a: data)
    monkeypatch.setattr(render, "capture", lambda *a, **k: pytest.fail("capture must not start"))
    with pytest.raises(FactoryError, match="missing disclosure for the first 2 seconds"):
        render.render(d)
    assert pipeline._read(d / "brief_check.json")["errors"] == ["missing disclosure for the first 2 seconds"]


def test_disclosure_changes_replace_cached_renders(tmp_path, monkeypatch):
    root = project(tmp_path, brief={"disclosure": "Paid partnership with X"})
    clip(root)
    made = fake_render(monkeypatch)
    ask = Answers(root)
    pipeline.run(root, ask, say=lambda m: None)
    pipeline._write(root / "brief.json", {"disclosure": "Paid partnership with Y", "disclosure_seconds": 3})
    for _ in range(2):
        pipeline.run(root, ask, say=lambda m: None)
    assert [d["disclosure"]["text"] for d in made] == ["Paid partnership with X", "Paid partnership with Y"]


def test_dashboard_shows_rights_and_brief_flags_as_text():
    got = javascript("dashboard.html", """
      ui.project = {state: 'done', source: {name: 'Show <1>'}, rights: 'permission', clips: []};
      render();
      const check = {errors: ['Too long'], flags: [{why: '<img src=x> in hook'}]};
      console.log(JSON.stringify([nodes['#source'].textContent, nodes['#rights'].textContent,
        ...all(briefBlock({brief_check: check})).map(n => n.textContent).filter(Boolean)]));
    """)
    assert got == ["Show <1>", "Rights · you have permission", "Check the brief", "Too long", "<img src=x> in hook"]


@pytest.mark.parametrize("shape", render.SHAPES)
def test_scene_shows_disclosure_from_first_frame_and_hides_at_end(tmp_path, shape):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    d = clip(project(tmp_path, brief={"disclosure": "Paid <partnership> & X", "disclosure_seconds": 3.5}))
    data = render.scene_data(d, shape, "zing", parallax=False, front=False, sharpen=False)
    js = r"""
const fs = require('fs'), vm = require('vm'), data = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {};
function element() { return {style: {setProperty() {}}, dataset: {}, textContent: '', offsetHeight: 60,
  classList: {toggle() {}, add() {}}, decode: async () => {}, firstChild: {style: {}},
  querySelectorAll: () => []}; }
const document = {documentElement: element(), body: element(), fonts: {load: async () => {}},
  getElementById: id => nodes[id] ||= element()};
const context = {window: {DATA: data}, document};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1], context);
(async () => {
  const states = [];
  for (const t of [0, 3.49, 3.5, 0]) {
    await context.window.seek(t);
    const d = nodes.disclosure;
    states.push([d.style.display, d.firstChild.textContent, parseFloat(d.style.top), parseFloat(d.style.width)]);
  }
  console.log(JSON.stringify(states));
})().catch(e => {console.error(e); process.exitCode = 1;});
"""
    got = RUN([node, "-e", js, str(data_path("scene.html"))], input=json.dumps(data),
              capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert got.returncode == 0, got.stderr
    states = json.loads(got.stdout)
    assert [s[0] for s in states] == ["block", "block", "none", "block"]
    assert all(s[1] == data["disclosure"]["text"] and 0 < s[2] < data["H"] and 0 < s[3] < data["W"] for s in states)


@pytest.mark.parametrize("shape,height,top", [("9x16", 60, 80), ("1x1", 60, 140),
                                            ("9x16", 695, 874), ("9x16", 694, 80)])
def test_disclosure_moves_only_when_the_hook_pill_overlaps(tmp_path, shape, height, top):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    d = clip(project(tmp_path, brief={"disclosure": "Paid partnership with X", "disclosure_seconds": 5}))
    data = render.scene_data(d, shape, {"solo_fill": True}, parallax=False, front=False, sharpen=False)
    js = r"""
const fs = require('fs'), vm = require('vm'), data = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {};
function element() { return {style: {setProperty() {}}, dataset: {}, offsetHeight: 60,
  classList: {toggle() {}, add() {}}, decode: async () => {}, firstChild: {style: {}},
  querySelectorAll: () => []}; }
const document = {documentElement: element(), body: element(), fonts: {load: async () => {}},
  getElementById: id => nodes[id] ||= element()};
const context = {window: {DATA: data}, document};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1], context);
document.getElementById('disclosure').offsetHeight = Number(process.argv[2]);
(async () => {
  const states = [];
  for (const t of [.5, 3.1, .5]) {
    await context.window.seek(t);
    states.push([nodes.disclosure.style.display, parseFloat(nodes.disclosure.style.top)]);
  }
  console.log(JSON.stringify(states));
})().catch(e => {console.error(e); process.exitCode = 1;});
"""
    got = RUN([node, "-e", js, str(data_path("scene.html")), str(height)], input=json.dumps(data),
              capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert got.returncode == 0, got.stderr
    assert json.loads(got.stdout) == [["block", top], ["block", 80], ["block", top]]


def test_mcp_new_accepts_rights_and_a_brief_path(tmp_path):
    root = project(tmp_path, brief={"tags": ["#ad"]})
    result = mcp_server.h_factory_new(str(root), str(tmp_path / "episode.mp4"), rights="licensed",
                                     brief=str(tmp_path / "campaign.json"))
    assert result["ok"] and result["rights"] == "licensed" and campaign.read(root) == {"tags": ["#ad"]}
    assert not mcp_server.h_factory_new(str(root), str(tmp_path / "episode.mp4"), rights="invalid")["ok"]
    assert not mcp_server.h_factory_new(str(root), str(tmp_path / "episode.mp4"), brief=str(tmp_path / "absent"))["ok"]


def test_mcp_parameters_are_optional_and_tool_count_stays_44():
    pytest.importorskip("mcp", reason="mcp SDK not installed")
    tools = asyncio.run(mcp_server.build_server().list_tools())
    assert len(tools) == 44
    schema = next(t.model_dump(by_alias=True)["inputSchema"] for t in tools if t.name == "factory_new")
    assert schema["properties"]["rights"]["default"] == "unknown"
    assert schema["properties"]["rights"]["enum"] == list(campaign.RIGHTS)
    assert schema["properties"]["brief"]["default"] is None
    assert not {"rights", "brief"} & set(schema["required"])
