"""Suggested channels still need public feed evidence."""
from __future__ import annotations

import copy
import html
import json
import socket
import tomllib
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path

import pytest

from myzing.channels import brief, command, registry, setup
from myzing.factory import judge, pipeline
from myzing.playbook import feeds

NOW = datetime(2026, 11, 7, 18, tzinfo=timezone.utc)
HANDLES = ["@one", "@two", "@three", "@four"]
TASK = "suggest-candidates"


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))
    monkeypatch.setattr(setup, "datetime", Clock)

    def refuse(*args, **kwargs):
        pytest.fail("unmocked external operation")
    for name in ("request", "listing", "resolve", "feed"):
        monkeypatch.setattr(feeds, name, refuse)
    monkeypatch.setattr(judge.Judge, "_claude", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def rows(views=(100, 200, 300), age=1):
    return [{"id": f"short{i}", "title": "A story", "channel_title": "Story channel", "short": True,
             "views": value, "published": (NOW - timedelta(days=age + i)).isoformat()}
            for i, value in enumerate(views)]


class Public:
    def __init__(self):
        self.ids = {handle: "UC" + str(i) * 22 for i, handle in enumerate(HANDLES, 1)}
        self.rows = {ident: rows((i * 100, i * 200, i * 300)) for i, ident in enumerate(self.ids.values(), 1)}
        self.calls = []

    def resolve(self, handle, fetch=None, *, root):
        self.calls.append(handle)
        return self.ids.get("@" + handle.removeprefix("@").casefold())

    def feed(self, ident, fetch=None, *, root):
        value = self.rows[ident]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


@pytest.fixture
def public(monkeypatch):
    public = Public()
    monkeypatch.setattr(feeds, "resolve", public.resolve)
    monkeypatch.setattr(feeds, "feed", public.feed)
    return public


def root():
    return registry.directory("creator-stories")


def answer(value):
    path = root() / "setup" / "answers" / f"{TASK}.json"
    pipeline._write(path, value)
    return path


def run(candidates=(), **kwargs):
    return setup.run("creator-stories", "Creator stories", candidates, **{"suggest": True, "no_brief": True, **kwargs})


@pytest.mark.parametrize("existing", [False, True])
def test_host_pending_leaves_channel_and_feeds_untouched(public, existing):
    if existing:
        registry.create("Stories", "Original niche", "creator-stories", series=[
            {"id": "stories", "name": "Stories", "kind": "breakdown", "watch": ["@old"]}])
    before = {p: p.read_bytes() for p in root().rglob("*") if p.is_file()}
    result = run()
    prompt = root() / "setup" / "pending" / f"{TASK}.md"
    assert result == {"pending": str(prompt), "answer": str(root() / "setup" / "answers" / f"{TASK}.json")}
    assert "Creator stories" in prompt.read_text(encoding="utf-8")
    assert {p: p.read_bytes() for p in root().rglob("*") if p.is_file() and p != prompt} == before
    assert (root() / "channel.json").exists() is existing and public.calls == []


def test_cached_host_answer_scans_kept_and_dropped_candidates(public):
    run()
    suggested = [{"handle": handle, "why": "Posts story Shorts."} for handle in HANDLES]
    suggested += [{"handle": "@missing"}, {"handle": "@small"}, {"handle": "@stale"}, {"handle": "@failed"}]
    public.ids.update({"@small": "small", "@stale": "stale", "@failed": "failed"})
    public.rows.update({"small": rows((1, 2)), "stale": rows(age=61), "failed": OSError("unavailable")})
    path = answer({"candidates": suggested})
    before = path.read_bytes()
    result = run(keep=3)
    assert path.read_bytes() == before
    assert [row["handle"] for row in result["kept"]] == ["@four", "@three", "@two"]
    assert result["dropped"] == [
        {"handle": "@missing", "reason": "could not resolve", "suggested": True},
        {"handle": "@small", "reason": "fewer than 3 Shorts in its 15 newest uploads", "suggested": True},
        {"handle": "@stale", "reason": "no Short in the last 60 days", "suggested": True},
        {"handle": "@failed", "reason": "feed failed (unavailable)", "suggested": True},
        {"handle": "@one", "reason": "outside top 3", "suggested": True}]
    assert all(row["suggested"] is True for row in result["kept"])
    assert result["suggested"] == [{"handle": row["handle"], "why": row.get("why", "")} for row in suggested]
    assert pipeline._read(root() / "setup.json") == {k: v for k, v in result.items() if k not in ("page", "brief")}
    assert registry.load("creator-stories")["series"][0]["watch"] == ["@four", "@three", "@two"]


def test_explicit_candidates_and_file_come_first_and_dedupe(public, tmp_path):
    path = tmp_path / "candidates.txt"
    path.write_text("@two\n@ONE # duplicate\n", encoding="utf-8")
    answer({"candidates": [{"handle": h} for h in ["@ONE", "@three", "@four", "@FOUR"]]})
    result = run(["https://youtube.com/@one/shorts", "one"], candidates_file=path, keep=3)
    assert public.calls == HANDLES
    assert {row["handle"]: row["suggested"] for row in result["kept"] + result["dropped"]} == {
        "@one": False, "@two": False, "@three": True, "@four": True}


@pytest.mark.parametrize("value", [
    None, [], {}, {"candidates": "@one"}, {"candidates": {}}, {"candidates": []},
    {"candidates": [{"handle": "@one"}] * 41}, {"candidates": ["@one"]}, {"candidates": [{}]},
    {"candidates": [{"handle": 1}]}, {"candidates": [{"handle": "@bad handle"}]},
    {"candidates": [{"handle": "https://www.youtube.com/@one"}]},
    {"candidates": [{"handle": "@one", "why": "x" * 201}]},
    {"candidates": [{"handle": "@one", "why": None}]},
])
def test_invalid_answer_is_forgotten_before_any_scan(public, value):
    pending = run()
    path = answer(value)
    with pytest.raises(registry.ChannelError, match="suggest"):
        run()
    assert not path.exists() and not Path(pending["pending"]).exists()
    assert not (root() / "channel.json").exists() and public.calls == []
    assert run() == pending


@pytest.mark.parametrize("count", [40, 41])
def test_merged_candidates_keep_the_existing_limit(public, count):
    handles = [f"@channel{i}" for i in range(count)]
    public.ids.update({handle: "UC" + f"{i:022d}" for i, handle in enumerate(handles)})
    public.rows.update({public.ids[handle]: rows() for handle in handles})
    path = answer({"candidates": [{"handle": h} for h in handles[20:]]})
    if count == 41:
        with pytest.raises(registry.ChannelError, match="at most 40"):
            run(handles[:20])
        assert public.calls == [] and not (root() / "channel.json").exists()
    else:
        result = run(handles[:20], keep=40)
        assert len(result["kept"]) == 40 and public.calls == handles
        assert [row["suggested"] for row in result["kept"]] == [False] * 20 + [True] * 20
    assert path.is_file()


@pytest.mark.parametrize("existing,selected,expected", [
    (None, "claude", "claude"), ("claude", None, "claude"), ("host", None, "host"),
    ("claude", "host", "host"), ("host", "claude", "claude"),
])
def test_judge_selection_is_passed_through_and_saved_for_new_channels(public, monkeypatch, existing, selected, expected):
    if existing:
        registry.create("Stories", "Stories", "creator-stories", judge=existing, series=[
            {"id": "stories", "name": "Stories", "kind": "breakdown", "watch": ["@old"]}])
    calls = []

    class Suggestions:
        def __init__(self, project, backend):
            calls.append((project, backend))

        def ask(self, task, prompt):
            assert task == TASK and "Creator stories" in prompt
            return {"candidates": [{"handle": h} for h in HANDLES]}
    monkeypatch.setattr(setup, "Judge", Suggestions)
    run(judge=selected)
    assert calls == [(root() / "setup", expected)]
    assert registry.load("creator-stories")["judge"] == (existing or expected)


def test_judge_can_be_chosen_without_suggestions(public):
    run(HANDLES, suggest=False, judge="claude")
    assert registry.load("creator-stories")["judge"] == "claude"


def test_invalid_judge_leaves_channel_untouched(public):
    with pytest.raises(registry.ChannelError, match="judge must be host or claude"):
        run(judge="other")
    assert not root().exists() and public.calls == []


def test_page_marks_suggestions_and_escapes_why(public):
    hostile = '\"><script>alert("why")</script>&\''
    answer({"candidates": [{"handle": " @three ", "why": hostile}, {"handle": "@missing", "why": hostile}]})
    result = run(["@one", "@two"])
    text = Path(result["page"]).read_text(encoding="utf-8")
    assert hostile not in text and text.count(html.escape(hostile)) == 2
    assert '@three (suggested)</td>' in text and '@missing (suggested)' in text
    assert '@one (suggested)' not in text
    tags = []
    page = HTMLParser()
    page.handle_starttag = lambda tag, attrs: tags.append((tag, dict(attrs)))
    page.feed(text)
    assert [tag for tag, attrs in tags if attrs.get("title") == hostile] == ["td", "li"]
    assert all(tag != "script" and set(attrs) <= {"lang", "charset", "name", "content", "title"} for tag, attrs in tags)


def test_cli_pending_instructions_and_resume(public, capsys):
    args = ["setup", "creator-stories", "--niche", "Creator stories", "--suggest", "--judge", "host", "--no-brief"]
    assert command.run(args) == 0
    output = capsys.readouterr()
    path = root() / "setup" / "answers" / f"{TASK}.json"
    assert output.err == ""
    assert output.out.splitlines() == [str(root() / "setup" / "pending" / f"{TASK}.md"),
        f"Write the JSON answer to {path} and run the same command again."]
    assert not (root() / "channel.json").exists()
    answer({"candidates": [{"handle": h} for h in HANDLES]})
    assert command.run(args) == 0
    assert capsys.readouterr().out.splitlines() == ["kept 4 of 4", str(root() / "setup.html")]


def test_suggestions_continue_to_the_first_brief(public, monkeypatch):
    pending = run(no_brief=False)
    assert "pending" in pending
    answer({"candidates": [{"handle": h} for h in HANDLES]})
    for i, ident in enumerate(public.ids.values()):
        public.rows[ident] = [{**row, "id": f"{ident}-{row['id']}"} for row in rows((1000,) * 6 + (50_000 + i,))]
    calls = []

    class Scripts:
        def ask(self, task, prompt):
            calls.append(task)
            return {"hook": "Start with the event that changed the story.",
                    "script": "Start with an event the viewer can picture and check the source before recording. " * 5,
                    "move": "Write one opening from a concrete event.", "title": "A story worth checking", "check": []}
    make = brief.make
    monkeypatch.setattr(brief, "make", lambda slug: make(slug, now=NOW, judge=Scripts(), collectors={"news": lambda *a, **k: []}))
    result = run(no_brief=False)
    assert "brief_error" not in result and Path(result["brief"]).is_file()
    assert calls == ["script-1", "script-2"] and result["first_brief"] == NOW.isoformat()
    data = pipeline._read(Path(result["brief"]).with_suffix(".json"))
    assert len(data["items"]) == 2 and all(item["script"] and not item["pending"] for item in data["items"])


def test_prompt_is_available_and_in_package_data():
    path = "_data/channels/prompts/setup-candidates.md"
    text = (resources.files("myzing") / path).read_text(encoding="utf-8")
    assert all(word in text for word in ("{NICHE}", '"candidates"', '"handle"', '"why"', "20 to 30", "public feeds"))
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(fnmatch(path, pattern) for pattern in config["tool"]["setuptools"]["package-data"]["myzing"])
