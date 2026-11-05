"""More factory review regressions, without model calls or downloads."""
from __future__ import annotations

import copy
import io
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from myzing.factory import batch, export, judge, network, pick, pipeline, plan, render, serve, source, visuals
from myzing.factory.tools import FactoryError
from test_factory_review_fixes import javascript


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(urllib.request, "build_opener", refuse)
    monkeypatch.setattr(source, "transcribe_episode", refuse)
    monkeypatch.setattr(source, "transcribe_moments", refuse)
    monkeypatch.setattr(serve.Studio, "_work", lambda self: None)


@pytest.fixture
def clip(tmp_path):
    root = tmp_path / "proj"
    pipeline._write(root / "factory.json", {**pipeline.SETTINGS, "moments": 0, "shapes": []})
    pipeline._write(root / "source.json", {"media": str(root / "ep.mp4"), "name": "Show"})
    pipeline._write(root / "transcript.json", [])
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [
        {"start": 0, "end": 10, "hook": "Tools", "snapped": True}]})
    d = root / "clip01"
    pipeline._write(d / "cams.json", {})
    pipeline._write(d / "words.json", {"duration": 10, "words": [
        {"w": w, "os": i, "oe": i + .5} for i, w in enumerate("I use Claude".split())]})
    pipeline._write(d / "post.json", {"x": "I use Claude"})
    return d


def test_4k_export_uses_scaled_sizes_in_every_video_format(clip, monkeypatch):
    data = {"fps": 30, "W": 1080, "H": 1920, "scale": 2, "duration": 1, "hookHtml": "Tools", "words": []}

    def capture(data, file, images, **kwargs):
        images.mkdir()
        pipeline._write(images / "captions.json", [])
    monkeypatch.setattr(render, "scene_data", lambda *args: data)
    monkeypatch.setattr(render, "capture", capture)
    monkeypatch.setattr(export, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(export, "run", lambda *args: Path(args[-1]).write_bytes(b"media"))
    monkeypatch.setattr(export, "compare", lambda *args: [])
    export.export(clip)
    root = ET.parse(clip / "export-9x16" / "timeline.xml")
    sizes = [(s.findtext("width"), s.findtext("height")) for s in root.findall(".//samplecharacteristics")
             if s.find("width") is not None]
    assert sizes == [("2160", "3840")] * 3


@pytest.mark.parametrize("ext,text", [(".srt", "broken captions"), (".json", "{broken")])
def test_bad_transcript_leaves_no_project(tmp_path, ext, text):
    media, transcript, root = tmp_path / "episode.mp4", tmp_path / f"episode{ext}", tmp_path / "proj"
    media.write_bytes(b"media")
    transcript.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        pipeline.init(root, media, transcript=transcript)
    assert not root.exists()


@pytest.fixture
def episodes(tmp_path, monkeypatch):
    inbox, out = tmp_path / "inbox", tmp_path / "projects"
    inbox.mkdir()
    (inbox / "episode.mp4").write_bytes(b"media")
    monkeypatch.setattr(batch.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pipeline, "init", lambda root, media, **kwargs: root.mkdir())
    return inbox, out


@pytest.mark.parametrize("recovers", [False, True])
def test_done_episodes_with_failed_clips_retry_at_most_twice(episodes, monkeypatch, recovers):
    inbox, out = episodes
    calls = []

    def run(root, ask, **kwargs):
        calls.append(root)
        status = {"state": "done", "failed": {} if recovers and len(calls) == 2 else {"clip01": "render failed"}}
        pipeline._write(root / "status.json", status)
        return status
    monkeypatch.setattr(pipeline, "run", run)
    monkeypatch.setattr(pipeline, "status", lambda root: pipeline._read(root / "status.json"))
    results = [batch.run(inbox, out)["episodes"] for _ in range(5)]
    count = 2 if recovers else 3
    assert len(calls) == count
    assert [len(rows) for rows in results] == [1] * count + [0] * (5 - count)
    assert pipeline._read(out / "episode" / "batch.json") == {"retries": count - 1}


def test_watch_does_not_rerun_or_log_unanswered_tasks(episodes, monkeypatch):
    inbox, out = episodes
    calls, ticks = [], []

    def run(root, ask, **kwargs):
        calls.append(root)
        status = {"state": "waiting", "pending": [{"task": "clip01-plan"}]}
        pipeline._write(root / "status.json", status)
        return status

    def sleep(seconds):
        if seconds == 60:
            ticks.append(seconds)
            if len(ticks) == 2:
                raise KeyboardInterrupt
    monkeypatch.setattr(pipeline, "run", run)
    monkeypatch.setattr(pipeline, "status", lambda root: pipeline._read(root / "status.json"))
    monkeypatch.setattr(batch.time, "sleep", sleep)
    batch.run(inbox, out, watch=True)
    assert len(calls) == 1
    assert len((out / "batch.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    pipeline._write(out / "episode" / "answers" / "clip01-plan.json", {})
    assert len(batch.run(inbox, out)["episodes"]) == 1
    assert len(calls) == 2


@pytest.mark.parametrize("ids,want,refs", [
    (["v 1", "fig.1"], ["v-1", "fig-1"], ["v-1", "fig-1"]),
    (["a", "a"], ["a", "a_"], ["a", "a"]),
    (["v 1", "v-1", "!!!"], ["v-1", "v-1_", "item"], ["v-1", "v-1_", "item"]),
])
def test_visual_ids_match_manifest_and_keep_the_first_duplicate(tmp_path, monkeypatch, ids, want, refs):
    from PIL import Image
    requests = [{"id": rid, "query": "rocket"} for rid in ids]

    def process(ctx, req, folder):
        folder.mkdir()
        Image.new("RGB", (16, 16)).save(folder / "photo.jpg")
        return [{"path": f"{folder.name}/photo.jpg", "source": "local", "media_type": "image"}]
    monkeypatch.setattr(visuals, "get_key", lambda name: None)
    monkeypatch.setattr(visuals, "process", process)
    manifest = visuals.find(copy.deepcopy(requests), tmp_path / "visuals", sheet=False, say=lambda m: None)
    raw = plan.check({"hook": "Rocket", "visual_requests": requests, "shots": [
        {"from": i, "layout": "split", "visual": rid} for i, rid in enumerate(ids)]})
    assert [r["id"] for r in raw["visual_requests"]] == list(manifest) == want
    assert [s["visual"] for s in raw["shots"]] == refs
    assert all(s["layout"] == "split" for s in raw["shots"])
    assert pick.sheet(tmp_path / "visuals", raw["visual_requests"], manifest).is_file()
    assert plan.check(copy.deepcopy(raw)) == raw


def test_missing_pick_sheet_finishes_without_visuals(clip):
    root = clip.parent
    raw = {"hook": "Tools", "shots": [{"from": 0, "layout": "split", "visual": "v1"}],
           "visual_requests": [{"id": "v1", "query": "tool"}]}
    pipeline._write(clip / "visuals" / "manifest.json", {"old": [{"path": "old.jpg"}]})
    ask = judge.Judge(root)
    ask.save("clip01-plan", raw)
    log = []
    result = pipeline.run(root, ask, say=log.append)
    assert result["state"] == "done" and result["failed"] == {} and not result["pending"]
    final = pipeline._read(clip / "plan.json")
    assert final["visuals"] == {} and final["shots"] == [{"from": 0, "layout": "solo"}]
    assert any("sheet" in line for line in log)


def test_text_fixes_do_not_expand_the_corrected_form_twice(clip):
    pairs = [("Claude", "Claude Code"), ("Clod", "Claude Code")]
    value = {"hook": "Use CLAUDE CODE", "copy": ["Claude and Clod", 1]}
    fixed = plan._fix_text(value, pairs)
    assert fixed == {"hook": "Use Claude Code", "copy": ["Claude Code and Claude Code", 1]}
    assert plan._fix_text(fixed, pairs) == fixed
    raw = {"hook": "Use Claude Code", "shots": [{"from": 0, "layout": "solo"}],
           "fixes": [{"heard": "Claude", "meant": "Claude Code"}]}
    for _ in range(2):
        assert plan.finalize(clip, raw, {})["hook"] == "Use Claude Code"
        assert pipeline._read(clip / "post.json")["x"] == "I use Claude Code"


def test_redo_plan_prompt_uses_the_original_heard_words(clip):
    root = clip.parent
    heard = pipeline._read(clip / "words.json")
    pipeline._write(clip / "words-heard.json", heard)
    fixed = copy.deepcopy(heard)
    fixed["words"][-1]["w"] = "Claude Code"
    pipeline._write(clip / "words.json", fixed)
    ask = judge.Judge(root)
    ask.save("clip01-plan", {"hook": "Tools", "shots": [{"from": 0, "layout": "solo"}]})
    pipeline.redo(root, "clip01-plan")
    result = pipeline.run(root, ask, say=lambda m: None)
    assert result["state"] == "waiting" and result["failed"] == {}
    prompt = (root / "pending" / "clip01-plan.md").read_text(encoding="utf-8")
    assert "2.00:Claude" in prompt and "Claude Code" not in prompt


@pytest.mark.parametrize("other", ["filter[view]=grid", 'filter="unbalanced'])
def test_dashboard_auth_ignores_malformed_unrelated_cookies(clip, other):
    handler = serve.handler(serve.Studio(clip.parent), 8765, "tok")
    request = object.__new__(handler)
    for token, want in (("tok", True), ("wrong", False)):
        request.headers = {"Cookie": f"{other}; zing_dash_8765={token}"}
        assert request._authenticated() is want


def test_blocked_redirect_is_not_logged_as_contacted(tmp_path):
    net = network.Network(tmp_path)
    fp = io.BytesIO()

    def validate(url):
        raise FactoryError("private host")
    with net.request("https://example.org/start", "visual request") as row:
        row["size"] = 12
        redirect = network._Redirect(net, row, validate)
        with pytest.raises(FactoryError, match="private host"):
            redirect.redirect_request(urllib.request.Request("https://example.org/start"), fp, 302, "Found", {},
                                      "http://127.0.0.1/private")
        assert fp.closed
    rows = [json.loads(line) for line in (tmp_path / "network.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["host"], r["bytes"]) for r in rows] == [("example.org", 12)]


def test_network_summary_accepts_null_and_missing_hosts(tmp_path):
    rows = [{"host": "example.org", "purpose": "site resource"}, {"host": None, "purpose": "site resource"},
            {"purpose": "site resource"}]
    (tmp_path / "network.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    got = network.summary(tmp_path)
    assert got["requests"] == 3 and got["purposes"] == {"site resource": 3}
    assert got["hosts"] == {"?": 2, "example.org": 1}
    assert "? / site resource 2" in got["summary"]


def test_dashboard_discards_optimistic_rating_after_the_post():
    got = javascript("dashboard.html", """
      ui.project = {settings: {pack: 'zing'}};
      const c = {clip: 'clip01', videos: {'clip.mp4': ''}};
      let finish, posted;
      api.rate = () => new Promise(resolve => { finish = resolve; });
      act = (button, call) => posted = call();
      const post = all(clipCard(c)).find(n => n.tagName === 'button' &&
        n.children.some(k => k.textContent === 'Post'));
      post.events.click({currentTarget: post});
      const pending = ui.rated.clip01;
      const optimistic = all(clipCard(c)).filter(n => n.attrs?.['aria-pressed'] === 'true').length;
      finish(); await posted;
      const ratings = all(clipCard(c)).find(n => n.attrs?.['aria-label'] === 'Rate this clip');
      console.log(JSON.stringify({pending, optimistic, kept: Object.hasOwn(ui.rated, 'clip01'),
        pressed: ratings.children.map(n => n.attrs['aria-pressed'])}));
    """)
    assert got == {"pending": "post", "optimistic": 2, "kept": False, "pressed": ["false"] * 3}


@pytest.mark.parametrize("pack", ["zing", "launch"])
def test_dashboard_keeps_shape_tabs_while_a_pack_renders(pack):
    got = javascript("dashboard.html", """
      ui.project = {settings: {pack: PACK}}; ui.pack.clip01 = 'swiss'; ui.shape.clip01 = '4x5';
      const suffix = PACK === 'zing' ? '' : '-' + PACK;
      const c = {clip: 'clip01', videos: {['clip' + suffix + '.mp4']: '', ['clip-4x5' + suffix + '.mp4']: ''}};
      const card = clipCard(c);
      console.log(JSON.stringify({shapes: shapesFor(c).map(s => s.id), shape: ui.shape.clip01,
        enabled: all(card).filter(n => n.attrs?.['data-tab'] && !('disabled' in n.attrs)).map(n => n.attrs['data-tab'])}));
    """.replace("PACK", json.dumps(pack)))
    assert got == {"shapes": ["9x16", "4x5"], "shape": "4x5", "enabled": ["clip019x16", "clip014x5"]}


@pytest.mark.parametrize("words,names,want", [
    ("I'm Ana Smith", ["Ana Smith"], ["Ana Smith"]),
    ("MY NAME IS Ana Smith", ["Ana Smith"], ["Ana Smith"]),
    ("I'm talking to Sam Altman", ["Sam", "Sam Altman"], []),
    ("I'm with Sam Altman", ["Sam Altman"], []),
])
def test_only_self_introductions_allow_solo_name_tags(clip, words, names, want):
    pipeline._write(clip / "words.json", {"words": [
        {"w": w, "os": i, "oe": i + .5} for i, w in enumerate(words.split())]})
    raw = {"hook": "Talk", "shots": [{"from": i, "layout": "solo", "label": {"name": name}}
                                      for i, name in enumerate(names)]}
    final = plan.finalize(clip, raw, {})
    assert [s["label"]["name"] for s in final["shots"] if s.get("label")] == want


@pytest.mark.parametrize("value", [{}, {"flags": "bad"}, {"flags": [None]},
                                  {"flags": [{"kind": "joke", "where": "end"}]}])
def test_bad_context_answer_is_refused_before_saving(clip, value):
    root = clip.parent
    ask = judge.Judge(root)
    with pytest.raises(judge.NeedsAnswer):
        ask.ask("clip01-context", "Check the context")
    pipeline._write(clip / "context.json", {"flags": []})
    with pytest.raises(FactoryError, match="context"):
        pipeline.answer(root, "clip01-context", value)
    assert ask.cached("clip01-context") is None
    assert (root / "pending" / "clip01-context.md").is_file()
    assert pipeline._read(clip / "context.json") == {"flags": []}
