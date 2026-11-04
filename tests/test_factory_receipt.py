"""Receipts follow the finalized shot plan and the selected visual's records."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from myzing.factory import command, judge, pick, pipeline, plan, receipt, serve, source


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


def clip(tmp_path, shots, words=None, **raw) -> Path:
    d = tmp_path / "proj" / "clip01"
    write(d.parent / "factory.json", {"shapes": ["9x16"], "pack": "zing"})
    write(d.parent / "source.json", {"name": "Ana on shipping"})          # names the speaker, so her tag stays
    write(d.parent / "moments.json", {"moments": [{"start": 10, "end": 25, "hook": "A plain hook"}]})
    write(d / "words.json", {"words": words if words is not None else [
        {"w": "Ana", "os": 0, "oe": .3}, {"w": "has", "os": .4, "oe": .7},
        {"w": "2", "os": .8, "oe": 1.1}, {"w": "ships.", "os": 1.2, "oe": 1.5},
        {"w": "Now.", "os": 9.3, "oe": 9.55}], "duration": 12})
    write(d / "plan-raw.json", {"hook": "A plain hook", "shots": shots, **raw})
    write(d / "post.json", {"x": "Keep this copy."})
    return d


def finalize(d, found=None):
    plan.finalize(d, read(d / "plan-raw.json"), found or {})
    saved = read(d / "receipt.json")
    assert saved == receipt.added(d)
    return saved


def test_overlapping_additions_count_once(tmp_path):
    d = clip(tmp_path, [
        {"from": 6, "layout": "graphic", "graphic": {"kind": "counter", "value": 2, "label": "ships"}},
        {"from": 0, "layout": "split", "visual": "v1", "label": {"name": "Ana"}},
        {"from": 8, "layout": "solo"}, {"from": 4, "layout": "solo"}])
    got = finalize(d, {"v1": {"path": "photo.jpg", "credit": "Archive"}})
    assert (got["duration"], got["added"], got["share"]) == (10, 6, .6)
    assert got["by_kind"] == {"picture": 4, "graphic": 2, "quote": 0, "name tag": 3.4, "title": 0}
    assert next(i for i in got["items"] if i["kind"] == "picture")["source"] == "Archive"
    assert sum(got["by_kind"].values()) > got["added"]


def test_solo_only_adds_nothing(tmp_path):
    d = clip(tmp_path, [{"from": 0, "layout": "solo"}, {"from": 7, "layout": "solo"}])
    got = finalize(d)
    assert got == {"duration": 10, "added": 0, "share": 0,
                   "by_kind": {k: 0 for k in receipt.KINDS}, "items": []}
    assert read(d / "post.json") == {"x": "Keep this copy."}


@pytest.mark.parametrize("graphic, text", [
    ({"kind": "counter", "title": "Ships", "value": 2, "suffix": " ships"}, "2 ships"),
    ({"kind": "list", "title": "Ships", "items": [{"text": "Ana has 2 ships"}]}, "Ana has 2 ships"),
    ({"kind": "funnel", "title": "Ships", "rows": [{"value": 2, "text": "2", "label": "ships"}]}, "ships"),
])
def test_graphics_name_the_spoken_source(tmp_path, graphic, text):
    d = clip(tmp_path, [{"from": 0, "layout": "graphic", "graphic": graphic}])
    got = finalize(d)
    assert got["added"] == got["duration"] == got["by_kind"]["graphic"] == 10
    assert got["share"] == 1
    item, = got["items"]
    assert text in item["what"] and item["source"] == "said in the clip" and item["license"] == ""


def test_quote_follows_words_and_hides_the_picture_and_name_tag(tmp_path):
    d = clip(tmp_path, [
        {"from": 0, "layout": "graphic", "graphic": {"kind": "quote", "text": "2 *ships*"}},
        {"from": .5, "layout": "split", "visual": "v1", "label": {"name": "Ana"}}])
    got = finalize(d, {"v1": {"path": "photo.jpg", "credit": "Archive"}})
    quote, = [i for i in got["items"] if i["kind"] == "quote"]
    assert quote == {"from": .68, "to": 2.3, "kind": "quote", "what": "2 ships.",
                     "source": "said in the clip", "license": ""}
    assert got["by_kind"]["quote"] == 1.62 and got["by_kind"]["picture"] == 7.88
    assert got["by_kind"]["name tag"] == 1.78
    assert (got["added"], got["share"]) == (9.5, .95)
    assert all(i["to"] <= .68 or i["from"] >= 2.3 for i in got["items"] if i["kind"] != "quote")


def test_titles_include_the_end_card_hold(tmp_path):
    d = clip(tmp_path, [
        {"from": 0, "layout": "graphic", "graphic": {"kind": "title", "text": "Introducing *Fold*"}},
        {"from": 1, "layout": "graphic", "graphic": {"kind": "endcard", "name": "Fold"}}],
        words=[{"w": "Fold", "os": 0, "oe": .7}])
    got = finalize(d)
    assert (got["duration"], got["added"], got["share"], got["by_kind"]["title"]) == (4, 4, 1, 4)
    assert [(i["from"], i["to"], i["what"]) for i in got["items"]] == [(0, 1, "Introducing Fold"), (1, 4, "Fold")]


def test_receipt_uses_the_final_plan_and_clamps_to_the_clip(tmp_path):
    d = clip(tmp_path, [
        {"from": 0, "layout": "split", "visual": "missing"},
        {"from": 3, "layout": "graphic", "graphic": {"kind": "counter", "value": 99}},
        {"from": 9, "layout": "solo", "label": {"name": "Ana"}},
        {"from": 20, "layout": "graphic", "graphic": {"kind": "counter", "value": 2}}])
    got = finalize(d)
    assert (got["added"], got["share"]) == (1, .1)
    assert got["items"] == [{"from": 9, "to": 10, "kind": "name tag", "what": "Ana",
                             "source": "said in the clip", "license": ""}]
    assert receipt.added(tmp_path)["share"] == 0


def test_dashboard_swaps_rewrite_the_receipt(tmp_path, monkeypatch, zing_workspace):
    requests = [{"id": "v1", "query": "A ship", "entity": "Ship"}]
    d = clip(tmp_path, [{"from": 0, "layout": "split", "visual": "v1"}], visual_requests=requests)
    vis = d / "visuals"
    manifest = {"v1": [
        {"path": "v1/a.jpg", "credit_text": "Archive A", "license": "CC0", "source_url": "https://example.org/a"},
        {"path": "v1/b.jpg", "credit_text": "Archive B", "license": "CC BY 4.0", "source_url": "https://example.org/b"}]}
    write(vis / "requests.json", requests)
    write(vis / "manifest.json", manifest)
    write(vis / "picks.json", {"picks": {"v1": {"pick": 1}}})   # the saved plan is the source of truth
    before = finalize(d, pick.chosen(vis, requests, manifest, {"v1": {"pick": 0}}))
    assert before["items"][0]["source"] == "https://example.org/a"
    post = (d / "post.json").read_bytes()
    monkeypatch.setattr(serve.Studio, "_work", lambda self: None)
    studio = serve.Studio(d.parent)

    def run(label, job):
        job()
        return {"queued": label}
    monkeypatch.setattr(studio, "queue", run)
    rendered = []
    monkeypatch.setattr(studio, "_rerender", lambda path: rendered.append(read(path / "receipt.json")))
    studio.visual({"clip": "clip01", "request": "v1", "index": 1})
    after = read(d / "receipt.json")
    assert after["items"] == [{"from": 0, "to": 10, "kind": "picture", "what": "A ship",
                               "source": "https://example.org/b", "license": "CC BY 4.0"}]
    assert before != after and rendered == [after]
    write(d / "receipt.json", {})
    studio.text({"clip": "clip01", "field": "hook", "text": "Another hook"})
    assert read(d / "receipt.json") == after and rendered == [after, after]
    assert read(d / "plan.json")["hook"] == "Another hook"
    state = studio.state()["clips"][0]
    assert state["receipt"] == after and state["added"] == 1
    assert (d / "post.json").read_bytes() == post


def test_status_and_cli_carry_the_share(tmp_path, capsys):
    d = clip(tmp_path, [{"from": 0, "layout": "solo"}, {"from": 8, "layout": "solo", "label": {"name": "Ana"}}])
    assert pipeline.status(d.parent)["clips"][0]["added"] is None
    got = finalize(d)
    assert pipeline.status(d.parent)["clips"][0]["added"] == got["share"] == .2
    assert command.run(["status", str(d.parent)]) == 0
    assert json.loads(capsys.readouterr().out)["clips"][0]["added"] == .2


@pytest.mark.parametrize("kind", ["plan", "pick"])
def test_redo_removes_the_old_receipt(tmp_path, kind):
    d = clip(tmp_path, [{"from": 0, "layout": "solo"}])
    finalize(d)
    pipeline.redo(d.parent, f"clip01-{kind}")
    assert not (d / "receipt.json").exists()
    assert pipeline.status(d.parent)["clips"][0]["added"] is None
