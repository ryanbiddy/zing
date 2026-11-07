"""Daily picks and scripts with public-feed fixtures and local judges."""
from __future__ import annotations

import copy
import json
import shutil
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape

import pytest

from myzing.channels import brief, command, digest, outliers, registry, tick, watch
from myzing.factory import judge, pipeline
from myzing.playbook import feeds, titles

NOW = datetime(2026, 11, 6, 18, tzinfo=timezone.utc)
UC = "UC" + "a" * 22
RUN = subprocess.run
SCRIPT = ("One opening changed the scale of this story. This upload reached forty thousand views while the channel's "
          "typical upload had ten thousand. My read is that the title made the story easy to recognize before anyone "
          "watched it. That is a read, not a measured explanation of its reach. The public count cannot tell us why each "
          "person stayed. Start your next script with the event viewers can picture, then leave them with one specific "
          "choice they can try themselves.")


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(feeds, "request", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def series(ident="stories", kind="breakdown", **values):
    return {"id": ident, "name": ident.title(), "kind": kind,
            **({"watch": ["@stories"]} if kind == "breakdown" else {}), **values}


@pytest.fixture
def channel():
    return registry.create("Creators", "How creators tell stories", cadence={"timezone": "UTC-08:00"}, series=[series()])


def response(**values):
    return {"hook": "One opening changed the scale of this story.", "script": SCRIPT,
            "move": "Start with an event viewers can picture.", "title": "An opening worth trying",
            "check": ["The title made the story easy to recognize."], **values}


class Scripts:
    def __init__(self, **answers):
        self.calls, self.answers = [], answers

    def ask(self, task, text):
        self.calls.append((task, text))
        return self.answers.get(task, response())


def candidate(ident="one", kind="breakdown", **values):
    return {"id": ident, "series": "stories", "kind": kind, "title": "Why this story worked",
            "url": "https://www.youtube.com/shorts/abcdefghijk", "published": (NOW - timedelta(days=3)).isoformat(),
            **({"channel": "@stories", "channel_title": "Stories", "views": 40_000, "median": 10_000,
                "multiple": 4, "age_days": 3, "features": titles.features("Why this story worked")}
               if kind == "breakdown" else {"source": "Platform", "summary": "A public change.", "score": 2, "why": "Changed today."}),
            **values}


def collect(*rows):
    return lambda *a, **kw: list(rows)


def make(channel, *rows, **kwargs):
    return brief.make(channel["slug"], now=NOW, collectors={"breakdown": collect(*(rows or [candidate()]))}, **kwargs)


def folder(channel, day="2026-11-06"):
    return registry.directory(channel["slug"]) / "brief" / day


def test_series_defaults_roundtrip_and_show(channel, capsys):
    channel["series"] += [series("changes", "news"), series("clips", "clips")]
    saved = registry.save(channel)
    assert saved["series"][0] == {**series(), "per_day": 2, "min_multiple": 3, "lesson": ""}
    assert saved["series"][1] == {**series("changes", "news"), "per_day": 1, "watch": [], "feeds": [], "lesson": ""}
    assert saved["series"][2] == {**series("clips", "clips"), "per_day": 0, "lesson": ""}
    assert registry.load(channel["slug"]) == saved
    assert registry.create("Empty", "No series")["series"] == []
    assert command.run(["show", channel["slug"]]) == 0
    assert json.loads(capsys.readouterr().out)["series"] == [
        {"id": s["id"], "kind": s["kind"], "per_day": s["per_day"], "watch": len(s.get("watch", []))} for s in saved["series"]]


@pytest.mark.parametrize("field,value", [
    ("id", "../escape"), ("id", "UPPER"), ("id", "a--b"), ("id", "con"), ("id", "x" * 61), ("id", None),
    ("name", ""), ("name", "x" * 61), ("name", 3), ("kind", "other"), ("kind", []),
    ("per_day", -1), ("per_day", 11), ("per_day", True), ("per_day", 1.5), ("per_day", "2"),
    ("watch", []), ("watch", "@one"), ("watch", ["@one"] * 41), ("watch", ["https://youtube.com/@one"]),
    ("watch", ["UCbad"]), ("watch", [None]), ("watch", ["has spaces"]),
    ("min_multiple", 0), ("min_multiple", 1001), ("min_multiple", True), ("min_multiple", "3"),
    ("min_multiple", float("nan")), ("min_multiple", float("inf")),
    ("lesson", "x" * 401), ("lesson", 3), ("unknown", 1), ("feeds", []),
])
def test_invalid_breakdown_settings(channel, field, value):
    data = copy.deepcopy(channel)
    data["series"][0][field] = value
    with pytest.raises(registry.ChannelError, match=rf"series\[0\].{field}"):
        registry.validate(data)


@pytest.mark.parametrize("value", [None, {}, "stories", [None], [series(), series()]])
def test_invalid_series_container_and_duplicate_ids(channel, value):
    with pytest.raises(registry.ChannelError, match="series"):
        registry.validate({**channel, "series": value})


@pytest.mark.parametrize("kind,field,value", [
    ("clips", "watch", []), ("clips", "feeds", []), ("clips", "min_multiple", 3), ("news", "min_multiple", 3),
    ("news", "feeds", "https://example.org/rss"), ("news", "feeds", ["https://example.org"] * 11),
    ("news", "feeds", ["http://example.org"]), ("news", "feeds", ["file:///rss"]),
    ("news", "feeds", ["https://"]), ("news", "feeds", [None]), ("news", "feeds", ["https://example.org/a b"]),
])
def test_kind_specific_settings(channel, kind, field, value):
    with pytest.raises(registry.ChannelError, match=rf"series\[0\].{field}"):
        registry.validate({**channel, "series": [series(kind=kind, **{field: value})]})


def test_series_limits_are_inclusive(channel):
    data = {**channel, "series": [series(watch=[UC] * 40, name="x" * 60, lesson="x" * 400, per_day=0, min_multiple=1),
                                  series("news", "news", feeds=["https://example.org"] * 10, per_day=10, watch=[], lesson="")]}
    assert registry.validate(data)["series"] == data["series"]
    data["series"][0]["min_multiple"] = 1000
    assert registry.validate(data)["series"][0]["min_multiple"] == 1000


def feed(rows):
    return ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
            'xmlns:media="http://search.yahoo.com/mrss/"><title>Story channel</title>' + ''.join(
                f'<entry><yt:videoId>{ident}</yt:videoId><title>{escape(title)}</title>'
                f'<published>{(NOW - timedelta(days=age)).isoformat()}</published>'
                f'<link href="https://www.youtube.com/{"shorts/" if short else "watch?v="}{ident}"/>'
                f'<media:group><media:community><media:statistics views="{views}"/></media:community></media:group></entry>'
                for ident, age, views, short, title in rows) + '</feed>')


def baseline(n=5, views=2000):
    return [(f"base{i}", 3 + i, views, True, "A story") for i in range(n)]


def test_outliers_baseline_windows_floor_sorting_and_exact_metadata(channel):
    rows = baseline(7) + [("young", .999, 100_000, True, "Too young"), ("old", 21.001, 90_000, True, "Too old"),
                          ("floor", 1, 9999, True, "Below floor"), ("one", 1, 10_000, True, "Why 10 stories?"),
                          ("two", 21, 20_000, False, "A longer upload")] + [(f"long{i}", 3 + i, 1000, False, "Long") for i in range(5)]
    calls = []

    def fetch(url):
        calls.append(url)
        return feed(rows) if "/feeds/" in url else f'<link rel="canonical" href="https://www.youtube.com/channel/{UC}">'
    got = outliers.collect(channel["series"][0], registry.directory(channel["slug"]), fetch=fetch, now=NOW)
    assert [r["id"] for r in got] == ["yt-two", "yt-one"]
    assert [r["median"] for r in got] == [1000, 2000]
    assert [r["multiple"] for r in got] == [20, 5]
    assert [r["format"] for r in got] == ["video", "Short"]
    assert got[1] == {**candidate("yt-one"), "title": "Why 10 stories?", "url": "https://www.youtube.com/shorts/one",
                      "published": (NOW - timedelta(days=1)).isoformat(), "channel_title": "Story channel",
                      "views": 10_000, "median": 2000, "multiple": 5, "age_days": 1, "format": "Short",
                      "features": titles.features("Why 10 stories?")}
    assert got[0]["url"] == "https://www.youtube.com/watch?v=two" and len(calls) == 2
    assert (folder(channel).parent / "feeds" / "ids.json").is_file()


@pytest.mark.parametrize("rows,multiple,expected", [
    (baseline(4) + [("hit", 1, 50_000, True, "Hit")], 3, []),
    (baseline(5, 0) + [("hit", 1, 50_000, True, "Hit")], 3, []),
    (baseline(5, 10_000) + [("hit", 1, 39_999, True, "Hit")], 4, []),
    (baseline(5, 10_000) + [("hit", 1, 40_000, True, "Hit")], 4, ["yt-hit"]),
    ([(f"b{i}", 2, 2000, True, "Base") for i in range(5)] + [("hit", 1, 10_000, True, "Hit")], 3, ["yt-hit"]),
    ([(f"b{i}", 1.999, 2000, True, "Base") for i in range(5)] + [("hit", 1, 10_000, True, "Hit")], 3, []),
])
def test_outlier_thresholds(channel, rows, multiple, expected):
    spec = {**channel["series"][0], "watch": [UC], "min_multiple": multiple}
    got = outliers.collect(spec, registry.directory(channel["slug"]), fetch=lambda url: feed(rows), now=NOW)
    assert [r["id"] for r in got] == expected
    assert not (folder(channel).parent / "errors.jsonl").exists()


def test_outliers_compare_shorts_with_shorts_and_videos_with_videos(channel):
    rows = ([(f"long{i}", 3 + i, 100_000_000, False, "Long") for i in range(5)] + baseline(5)
            + [("hit", 2, 50_000, True, "Short hit"), ("flat", 2, 150_000_000, False, "Usual video")])
    spec = {**channel["series"][0], "watch": [UC], "min_multiple": 3}
    got = outliers.collect(spec, registry.directory(channel["slug"]), fetch=lambda url: feed(rows), now=NOW)
    assert [(r["id"], r["median"], r["multiple"]) for r in got] == [("yt-hit", 2000, 25)]
    only_long = [(f"long{i}", 3 + i, 1000, False, "Long") for i in range(5)] + [("hit", 2, 50_000, True, "Short hit")]
    assert outliers.collect(spec, registry.directory(channel["slug"]), fetch=lambda url: feed(only_long), now=NOW) == []


def test_outlier_errors_are_logged_and_later_channels_continue(channel, monkeypatch):
    root = registry.directory(channel["slug"])
    spec = {**channel["series"][0], "watch": ["@broken", UC]}
    calls = []

    def fetch(url):
        calls.append(url)
        if "@broken" in url:
            raise OSError("missing feed")
        return feed(baseline() + [("hit", 1, 10_000, True, "Hit")])
    assert len(outliers.collect(spec, root, fetch=fetch, now=NOW)) == 1
    assert watch.read(root / "brief" / "errors.jsonl") == [{"at": NOW.isoformat(), "source": "@broken", "error": "missing feed"}]
    assert outliers.collect(spec, root, fetch=fetch, now=NOW, stop=lambda: True) == [] and len(calls) == 2
    calls.clear()
    outliers.collect(spec, root, fetch=fetch, now=NOW, stop=lambda: bool(calls))
    assert len(calls) == 1


def test_picks_series_order_top_counts_seen_and_refill(channel):
    channel["series"] += [series("changes", "news", per_day=2), series("clips", "clips", per_day=1)]
    registry.save(channel)
    calls = []

    def collector(spec, root, **kwargs):
        calls.append(spec["id"])
        if spec["kind"] == "news":
            return [candidate("news", "news"), candidate("top-news", "news", score=4), candidate("low-news", "news", score=1)]
        return [candidate("low", multiple=3), candidate("high", multiple=8), candidate("mid", multiple=5)]
    collectors = {"breakdown": collector, "news": collector, "clips": lambda *a, **k: pytest.fail("clips collected")}
    result = brief.make(channel["slug"], now=NOW, collectors=collectors, judge=Scripts())
    assert [r["id"] for r in result["items"]] == ["high", "mid", "top-news", "news"]
    assert [r["n"] for r in result["items"]] == [1, 2, 3, 4] and calls == ["stories", "changes"]
    assert result["items"][0]["receipt"] == "Stories: 40,000 views, 8x their typical Short"
    assert result["items"][2]["receipt"] == "Platform, Nov 3: Why this story worked"
    assert pipeline._read(folder(channel) / "brief.json") == result
    assert brief.make(channel["slug"], now=NOW, collectors=collectors, judge=Scripts()) == result
    assert calls == ["stories", "changes"]
    next_day = brief.make(channel["slug"], now=NOW + timedelta(days=1), collectors=collectors, judge=Scripts())
    assert [r["id"] for r in next_day["items"]] == ["low", "low-news"]
    seen = pipeline._read(folder(channel).parent / "seen.json")
    assert seen == {**{r["id"]: result["date"] for r in result["items"]}, "low": "2026-11-07", "low-news": "2026-11-07"}


def test_host_pending_answers_refill_without_collecting(channel, tmp_path, monkeypatch):
    result = make(channel, candidate("one"), candidate("two"))
    for item in result["items"]:
        assert item["script"] is None and Path(item["pending"]).is_file()
    assert len(judge.Judge(folder(channel)).pending()) == 2
    monkeypatch.setattr(outliers, "collect", lambda *a, **k: pytest.fail("refill collected"))
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(response()), encoding="utf-8")
    result = brief.answer(channel["slug"], "script-1", path, date="2026-11-06")
    assert result["items"][0]["script"] == SCRIPT and result["items"][0]["pending"] is None
    assert result["items"][1]["script"] is None
    result = brief.answer(channel["slug"], "script-2", json.dumps(response()), date="2026-11-06")
    assert all(r["script"] == SCRIPT for r in result["items"]) and not judge.Judge(folder(channel)).pending()
    assert (folder(channel) / "brief.html").read_bytes() == (folder(channel).parent / "latest.html").read_bytes()
    with pytest.raises(registry.ChannelError, match="task"):
        brief.answer(channel["slug"], "../../escape", response(), date="2026-11-06")


def test_prompt_has_voice_lesson_facts_prior_and_safety_rules(channel):
    root = registry.directory(channel["slug"])
    (root / "voice.md").write_text("Short lines. Keep {FACTS} literal.", encoding="utf-8")
    channel["series"][0]["lesson"] = "Name the opening move."
    registry.save(channel)
    pipeline._write(root / "prior.json", {"guidance": ["Try a past-tense title."], "lifts": []})
    scripts = Scripts()
    make(channel, judge=scripts)
    task, prompt = scripts.calls[0]
    assert task == "script-1"
    for text in (channel["name"], channel["niche"], "Short lines. Keep {FACTS} literal.", "Name the opening move.",
                 "Try a past-tense title.", '"median": 10000', '"views": 40000', '"multiple": 4', '"age_days": 3',
                 '"channel_title": "Stories"', "https://www.youtube.com/shorts/abcdefghijk", '"features"',
                 "my read", "probably", "private life", "invent numbers or quotes", "Return JSON only", "story first"):
        assert text in prompt


@pytest.mark.parametrize("values", [
    {"hook": ""}, {"hook": "word " * 16}, {"hook": 3}, {"script": [SCRIPT]}, {"script": "word " * 59},
    {"script": "word " * 121}, {"move": "word " * 13}, {"move": None}, {"title": "x" * 71},
    {"title": False}, {"check": "a claim"}, {"check": [2]}, {"check": [""]},
])
def test_bad_answers_are_rejected(values):
    with pytest.raises(ValueError):
        brief.check(response(**values))


def test_word_tolerance_and_bad_item_does_not_stop_next(channel):
    for count in (60, 70, 110, 120):
        assert brief.check(response(script="word " * count))["script"]
    result = make(channel, candidate("one"), candidate("two"), judge=Scripts(**{"script-1": {"script": "bad"}}))
    assert result["items"][0]["script"] is None and result["items"][1]["script"] == SCRIPT
    assert len(result["errors"]) == 1 and "script-1" in result["errors"][0]
    assert pipeline._read(folder(channel) / "brief.json")["errors"] == result["errors"]
    fixed = brief.answer(channel["slug"], "script-1", response(), date="2026-11-06")
    assert fixed["items"][0]["script"] == SCRIPT


def test_bad_saved_answer_keeps_its_prompt_for_repair(channel):
    pending = make(channel)["items"][0]["pending"]
    prompt = Path(pending).read_text(encoding="utf-8")
    result = brief.answer(channel["slug"], "script-1", {"script": "bad"}, date="2026-11-06")
    assert result["items"][0]["script"] is None and result["items"][0]["pending"] == pending
    assert Path(pending).read_text(encoding="utf-8") == prompt
    assert result["errors"]
    result = brief.answer(channel["slug"], "script-1", response(), date="2026-11-06")
    assert result["items"][0]["script"] == SCRIPT and not Path(pending).exists()


def test_collector_failure_is_recorded_and_news_can_be_injected(channel, monkeypatch):
    channel["series"] += [series("changes", "news")]
    registry.save(channel)

    def fail(*a, **k):
        raise RuntimeError("feed failed")
    monkeypatch.setattr(brief, "updates", SimpleNamespace(collect=collect(candidate("news", "news"))))
    result = brief.make(channel["slug"], now=NOW, collectors={"breakdown": fail}, judge=Scripts())
    assert [r["id"] for r in result["items"]] == ["news"]
    assert result["errors"] == ["stories feed failed"]


def test_missing_updates_is_a_series_error(channel, monkeypatch):
    import builtins
    channel["series"] += [series("changes", "news")]
    registry.save(channel)
    original = builtins.__import__

    def load(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 1 and "updates" in fromlist:
            raise ImportError("updates is not installed")
        return original(name, globals, locals, fromlist, level)
    monkeypatch.setattr(brief, "updates", None)
    monkeypatch.setattr(builtins, "__import__", load)
    result = make(channel, judge=Scripts())
    assert len(result["items"]) == 1 and result["errors"] == ["changes updates is not installed"]


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_page_escapes_all_text_and_has_only_item_links(channel):
    hostile = '</textarea><script>alert("bad")</script>'
    channel["name"] = hostile
    channel["series"][0]["name"] = hostile
    registry.save(channel)
    answer = response(hook=hostile, script=SCRIPT + " " + hostile, move=hostile, title=hostile, check=[hostile])
    result = make(channel, candidate(title=hostile, channel_title=hostile), judge=Scripts(**{"script-1": answer}))
    page = (folder(channel) / "brief.html").read_text(encoding="utf-8")
    assert hostile not in page and '&lt;/textarea&gt;&lt;script&gt;' in page
    tags = Tags()
    tags.feed(page)
    assert sum(tag == "script" for tag, _ in tags.tags) == 1
    assert sum(tag == "strong" for tag, _ in tags.tags) == 1
    assert sum(tag == "button" for tag, _ in tags.tags) == 1
    assert [(tag, key, value) for tag, attrs in tags.tags for key, value in attrs.items() if key in ("src", "href")] == [
        ("a", "href", result["items"][0]["facts"]["url"])]
    assert "viewport" in page and "22px" in page
    assert (folder(channel).parent / "latest.html").read_text(encoding="utf-8") == page


def test_copy_button_works_with_clipboard_and_fallback(channel):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    make(channel, judge=Scripts())
    page = (folder(channel) / "brief.html").read_text(encoding="utf-8")
    script = page.split("<script>")[1].split("</script>")[0]
    program = '''let click, copied=[], fallback=[];
const text={value:'spoken words',style:{},scrollHeight:480,focus(){fallback.push('focus')},select(){fallback.push('select')}};
const button={dataset:{copy:'script-1'},addEventListener(name,fn){click=fn}};
const document={querySelectorAll:selector=>selector==='textarea'?[text]:[button],getElementById:id=>text,
execCommand:name=>fallback.push(name)};
const navigator={clipboard:{writeText:async value=>copied.push(value)}};
''' + script + '''
(async()=>{await click();navigator.clipboard.writeText=async()=>{throw Error()};await click();
console.log(JSON.stringify([copied,fallback,text.style.height]))})();'''
    result = RUN([node, "-"], input=program, text=True, capture_output=True, timeout=60)   # Node starts slowly on Windows CI
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [["spoken words"], ["focus", "select", "copy"], "480px"]


def test_due_uses_local_day_and_pause(channel):
    before = datetime(2026, 11, 7, 7, 59, tzinfo=timezone.utc)
    after = before + timedelta(minutes=1)
    assert brief.due(channel["slug"], before)
    make(channel, judge=Scripts())
    assert not brief.due(channel["slug"], before) and brief.due(channel["slug"], after)
    (registry.directory(channel["slug"]) / "PAUSE").touch()
    assert not brief.due(channel["slug"], after)
    with pytest.raises(registry.ChannelError, match="paused"):
        brief.make(channel["slug"], now=after)


def test_disabled_and_clips_series_do_not_collect(channel):
    channel["series"] = [series(per_day=0), series("clips", "clips")]
    registry.save(channel)
    assert not brief.due(channel["slug"], NOW)
    assert not make(channel, judge=Scripts())["items"]


def test_stop_after_collect_does_not_commit_partial_picks(channel):
    stopped = []

    def collector(*a, **k):
        stopped.append(True)
        return [candidate()]
    brief.make(channel["slug"], now=NOW, collectors={"breakdown": collector}, stop=lambda: bool(stopped))
    assert not (folder(channel) / "brief.json").exists()
    assert brief.due(channel["slug"], NOW)


def test_stop_during_judge_keeps_picks_and_refills(channel):
    stopped = []

    class Pausing(Scripts):
        def ask(self, task, text):
            stopped.append(True)
            return response()
    result = make(channel, candidate("one"), candidate("two"), judge=Pausing(), stop=lambda: bool(stopped))
    assert result["items"][0]["script"] and result["items"][1]["script"] is None
    fixed = Scripts()
    result = brief.make(channel["slug"], now=NOW, judge=fixed)
    assert all(i["script"] for i in result["items"]) and [task for task, _ in fixed.calls] == ["script-2"]


def test_cli_date_answer_open_and_digest(channel, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(outliers, "collect", collect(candidate()))
    opened = []
    monkeypatch.setattr(command.webbrowser, "open", opened.append)
    assert command.run(["brief", channel["slug"], "--date", "2026-11-06", "--open"]) == 0
    assert capsys.readouterr().out.strip() == str(folder(channel) / "brief.html")
    assert opened == [(folder(channel).parent / "latest.html").as_uri()]
    assert "Brief: 0 scripts ready, 1 waiting for answers." in digest.build([channel["slug"]], now=NOW)
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(response()), encoding="utf-8")
    assert command.run(["brief", channel["slug"], "--date", "2026-11-06", "--answer", "script-1", str(path)]) == 0
    text = digest.build([channel["slug"]], now=NOW)
    assert f"Brief: 1 scripts ready, 0 waiting for answers. {folder(channel).parent / 'latest.html'}" in text
    assert "Brief:" not in digest.build([channel["slug"]], now=NOW + timedelta(days=1))
    for date in ("2026-11-31", "20261106", "../escape"):
        assert command.run(["brief", channel["slug"], "--date", date]) == 2


def test_tick_makes_brief_once_per_day_between_watch_and_factory(channel, monkeypatch):
    calls = []
    monkeypatch.setattr(outliers, "collect", lambda *a, **k: calls.append("brief") or [candidate()])
    monkeypatch.setattr(tick, "_advance", lambda *a: calls.append("factory"))

    def watcher(*a, **k):
        calls.append("watch")
        return {"found": 0, "started": 0}
    first = tick.run([channel["slug"]], now=NOW, watch_fn=watcher)["channels"][channel["slug"]]
    assert first["brief"] == 1 and not first["errors"]
    tick.run([channel["slug"]], now=NOW + timedelta(hours=1), watch_fn=watcher)
    assert calls == ["watch", "brief", "factory", "watch", "factory"]
    tick.run([channel["slug"]], now=NOW + timedelta(days=1), watch_fn=watcher)
    assert calls[-3:] == ["watch", "brief", "factory"]


def test_tick_survives_brief_failure_and_respects_pause(channel, monkeypatch):
    registry.create("Second", "More stories", series=[series()])
    advanced = []

    def fail(*a, **kw):
        raise RuntimeError("brief broke")
    monkeypatch.setattr(brief, "make", fail)
    monkeypatch.setattr(tick, "_advance", lambda slug, *a: advanced.append(slug))
    result = tick.run([channel["slug"], "second"], now=NOW)
    assert advanced == [channel["slug"], "second"]
    assert all(row["errors"] == ["brief brief broke"] for row in result["channels"].values())
    assert all((registry.directory(slug) / "kits" / "index.html").is_file() for slug in advanced)
    advanced.clear()

    def pause(*a, **kw):
        (registry.directory(channel["slug"]) / "PAUSE").touch()
        return {"found": 0, "started": 0}
    result = tick.run([channel["slug"]], now=NOW, watch_fn=pause)["channels"][channel["slug"]]
    assert result["stopped"] == "paused" and not result["errors"] and not advanced
