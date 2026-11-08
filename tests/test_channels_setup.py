"""Channel setup from local feed fixtures and a fake script judge."""
from __future__ import annotations

import copy
import html
import json
import socket
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from myzing.channels import brief, command, registry, scorecard, setup
from myzing.factory import judge, pipeline
from myzing.playbook import feeds

NOW = datetime(2026, 11, 7, 18, tzinfo=timezone.utc)
HANDLES = ["@one", "@two", "@three", "@four"]
IDS = ["UC" + letter * 22 for letter in "abcd"]


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
    monkeypatch.setattr(feeds, "request", refuse)
    monkeypatch.setattr(feeds, "listing", refuse)
    monkeypatch.setattr(judge.Judge, "ask", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def rows(views=(100, 200, 300), age=1):
    return [{"id": f"short{i}", "title": "A story", "channel_title": "Story channel", "short": True,
             "views": value, "published": (NOW - timedelta(days=age + i)).isoformat()}
            for i, value in enumerate(views)]


class Public:
    def __init__(self):
        self.ids = dict(zip(HANDLES, IDS))
        self.rows = {ident: rows((i * 100, i * 200, i * 300)) for i, ident in enumerate(IDS, 1)}
        self.calls = []

    def resolve(self, handle, fetch=None, *, root):
        self.calls.append(("resolve", handle, fetch, root))
        if handle in IDS:
            return handle
        if handle not in self.ids:
            raise ValueError("missing channel")
        return self.ids[handle]

    def feed(self, ident, fetch=None, *, root):
        self.calls.append(("feed", ident, fetch, root))
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


def run(**kwargs):
    return setup.run("creator-stories", "Creator stories", HANDLES, **{"no_brief": True, **kwargs})


def saved():
    return pipeline._read(registry.directory("creator-stories") / "setup.json")


def made(slug):
    day = NOW.date().isoformat()
    path = registry.directory(slug) / "brief" / day / "brief.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    brief._publish(path, "<p>Daily brief</p>")
    return {"date": day}


def test_new_channel_starters_watch_order_and_defaults(public):
    public.rows[IDS[0]].append({**rows()[0], "short": False, "views": 100_000_000})
    result = run(keep=3, feed=public.feed)
    channel = registry.load("creator-stories")
    assert channel["name"] == "Creator Stories" and channel["niche"] == "Creator stories"
    assert channel["series"] == [
        {"id": "blew-up", "name": "Why it blew up", "kind": "breakdown", "per_day": 2, "min_multiple": 3,
         "lesson": "End on one move a viewer can copy this week.", "watch": ["@four", "@three", "@two"]},
        {"id": "news", "name": "What changed", "kind": "news", "per_day": 1, "watch": [], "feeds": [],
         "lesson": "Say who it affects and what to do about it today."},
        {"id": "podcast", "name": "Heard on a podcast", "kind": "clips", "per_day": 0, "lesson": ""}]
    assert all(channel[key] == registry.DEFAULTS[key] for key in ("judge", "approval", "cadence"))
    assert [row["median_views"] for row in result["kept"]] == [800, 600, 400]
    assert result["dropped"] == [{"handle": "@one", "reason": "outside top 3"}]
    assert saved() == {key: value for key, value in result.items() if key not in ("page", "brief")}


def test_existing_settings_and_other_watch_lists_survive(public):
    original = registry.create("My stories", "Keep this niche", "creator-stories", judge="claude",
        approval={"policy": "veto", "veto_hours": 4, "manual_first": 12}, cadence={"per_day": 4, "timezone": "UTC+00:00"},
        network={"name": "Network"}, factory={"mode": "documentary"}, bar={"posts": 90},
        series=[{"id": "news", "name": "News", "kind": "news", "watch": ["@news"]},
                {"id": "first", "name": "First", "kind": "breakdown", "watch": ["@old"], "per_day": 5,
                 "min_multiple": 7, "lesson": "Keep my lesson."},
                {"id": "second", "name": "Second", "kind": "breakdown", "watch": ["@other"]},
                {"id": "clips", "name": "Clips", "kind": "clips", "per_day": 1}])
    root = registry.directory("creator-stories")
    (root / "voice.md").write_text("Use plain words.", encoding="utf-8")
    (root / "queue.jsonl").write_text('{"keep":"this"}\n', encoding="utf-8")
    run(name="Replace me")
    expected = copy.deepcopy(original)
    expected["series"][1]["watch"] = HANDLES[::-1]
    assert registry.load("creator-stories") == expected
    assert (root / "voice.md").read_text(encoding="utf-8") == "Use plain words."
    assert (root / "queue.jsonl").read_text(encoding="utf-8") == '{"keep":"this"}\n'


def test_existing_channel_without_breakdown_is_unchanged(public):
    registry.create("Stories", "Stories", "creator-stories", series=[{"id": "news", "name": "News", "kind": "news"}])
    path = registry.directory("creator-stories") / "channel.json"
    before = path.read_bytes()
    with pytest.raises(registry.ChannelError, match="has no breakdown series"):
        run()
    assert path.read_bytes() == before and public.calls == []
    assert not path.with_name("setup.json").exists()


def test_candidates_file_comments_duplicates_urls_and_spelling(public, tmp_path):
    path = tmp_path / "candidates.txt"
    path.write_text(f"# Sources\n\n @ONE # repeat\nhttps://www.youtube.com/@two/shorts\n"
                    f"@THREE\nhttps://youtube.com/channel/{IDS[3]}/\n{IDS[3]}\n@three\n", encoding="utf-8-sig")
    public.ids["@One"] = IDS[0]
    public.ids["@THREE"] = IDS[2]
    result = setup.run("creator-stories", "Stories", ["@One", "one"], candidates_file=path, no_brief=True)
    assert [row["handle"] for row in result["kept"]] == [IDS[3], "@THREE", "@two", "@One"]
    assert [call[1] for call in public.calls if call[0] == "resolve"] == ["@One", "@two", "@THREE", IDS[3]]
    assert all(call[3] == registry.directory("creator-stories") for call in public.calls)


def test_fetch_is_forwarded_to_resolve_and_injected_feed(public):
    def fetch(url):
        pytest.fail("the fake readers should not fetch")
    run(fetch=fetch, feed=public.feed)
    assert len(public.calls) == 8 and all(call[2] is fetch for call in public.calls)


def test_real_resolve_uses_fetch_and_channel_ledger():
    calls = []

    def fetch(url):
        calls.append(url)
        handle = url.rsplit("/", 1)[-1]
        return f'<link rel="canonical" href="https://www.youtube.com/channel/{IDS[HANDLES.index(handle)]}">'

    def feed(ident, fetch=None, *, root):
        assert root == registry.directory("creator-stories")
        return rows()
    result = run(fetch=fetch, feed=feed)
    assert len(calls) == 4 and len(result["kept"]) == 4
    assert pipeline._read(registry.directory("creator-stories") / "feeds" / "ids.json") == {
        handle[1:]: ident for handle, ident in zip(HANDLES, IDS)}


def test_drop_reasons_and_sixty_day_boundary(public):
    public.ids.update({"@failed": "failed", "@small": "small", "@stale": "stale"})
    public.rows.update({"failed": OSError("feed unavailable"), "small": rows((1, 2)), "stale": rows(age=60.001)})
    public.rows[IDS[0]] = rows(age=60)
    result = setup.run("creator-stories", "Stories", HANDLES + ["@missing", "@failed", "@small", "@stale"], no_brief=True)
    assert result["dropped"] == [
        {"handle": "@missing", "reason": "could not resolve"},
        {"handle": "@failed", "reason": "feed failed (feed unavailable)"},
        {"handle": "@small", "reason": "fewer than 3 Shorts in its 15 newest uploads"},
        {"handle": "@stale", "reason": "no Short in the last 60 days"}]
    assert len(result["kept"]) == 4


@pytest.mark.parametrize("existing", [False, True])
def test_fewer_than_three_survive_without_changing_channel_or_reports(public, existing):
    root = registry.directory("creator-stories")
    if existing:
        run()
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    public.rows[IDS[0]] = rows((1,))
    public.rows[IDS[1]] = rows((2,))
    public.rows[IDS[2]] = rows(age=61)
    with pytest.raises(registry.ChannelError, match="Only 1 candidates survived") as exc:
        run()
    assert "fewer than 3 Shorts in its 15 newest uploads (2)" in str(exc.value) and "no Short in the last 60 days (1)" in str(exc.value)
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_report_times_and_first_brief_minutes(public, monkeypatch):
    times = iter([NOW, NOW + timedelta(seconds=30), NOW + timedelta(seconds=367)])
    monkeypatch.setattr(Clock, "now", classmethod(lambda cls, tz=None: next(times)))

    def make(slug):
        assert saved()["first_brief"] is None
        assert registry.load(slug)["series"][0]["watch"] == HANDLES[::-1]
        return made(slug)
    monkeypatch.setattr(brief, "make", make)
    result = run(no_brief=False)
    data = saved()
    assert set(data) == {"niche", "started", "saved", "first_brief", "minutes", "kept", "dropped"}
    assert data["started"] == NOW.isoformat() and data["saved"] == (NOW + timedelta(seconds=30)).isoformat()
    assert data["first_brief"] == (NOW + timedelta(seconds=367)).isoformat() and data["minutes"] == 6.1
    assert data["kept"][0] == {"handle": "@four", "channel_id": IDS[3], "shorts": 3, "median_views": 800,
                               "newest": (NOW - timedelta(days=1)).isoformat()}
    assert Path(result["brief"]).is_file()
    assert "Niche to first brief 6.1 min" in Path(result["page"]).read_text(encoding="utf-8")


def test_no_brief_has_null_times_and_does_not_call_make(public, monkeypatch):
    monkeypatch.setattr(brief, "make", lambda *a, **k: pytest.fail("brief was requested"))
    result = run()
    assert saved()["first_brief"] is saved()["minutes"] is result["brief"] is None
    assert "brief_error" not in saved()
    assert not (registry.directory("creator-stories") / "brief").exists()


@pytest.mark.parametrize("error", [registry.ChannelError("channel is paused"), RuntimeError("judge failed")])
def test_brief_failure_is_saved_and_cli_exits_zero(public, monkeypatch, capsys, error):
    def fail(slug):
        raise error
    monkeypatch.setattr(brief, "make", fail)
    assert command.run(["setup", "creator-stories", "--niche", "Stories", "--candidates", *HANDLES]) == 0
    data = saved()
    assert data["brief_error"] == str(error) and data["first_brief"] is data["minutes"] is None
    assert registry.load("creator-stories")["series"][0]["watch"] == HANDLES[::-1]
    output = capsys.readouterr()
    assert output.err == "" and f"Brief failed. {error}" in output.out
    assert "kept 4 of 4" in output.out and "Niche to first brief:" not in output.out


def test_stopped_brief_without_page_is_not_timed(public, monkeypatch):
    monkeypatch.setattr(brief, "make", lambda slug: {"date": NOW.date().isoformat()})
    run(no_brief=False)
    assert saved()["brief_error"] == "brief stopped before the page was written"
    assert saved()["minutes"] is None


def test_setup_page_escapes_hostile_title_niche_candidate_and_error(public, monkeypatch):
    hostile = '<script>alert("channel")</script>&\''
    public.rows[IDS[0]] = OSError(hostile)

    def fail(slug):
        raise RuntimeError(hostile)
    monkeypatch.setattr(brief, "make", fail)
    result = setup.run("creator-stories", hostile, HANDLES + [hostile], name=hostile, no_brief=False)
    text = Path(result["page"]).read_text(encoding="utf-8")
    assert hostile not in text and text.count(html.escape(hostile)) == 5
    tags = []
    page = HTMLParser()
    page.handle_starttag = lambda tag, attrs: tags.append(tag)
    page.feed(text)
    assert "script" not in tags and tags.count("table") == 1 and tags.count("tr") == 4
    assert "Median views" in text and "Dropped channels" in text


def test_reports_replace_temp_files(public, monkeypatch):
    replace, replaced = Path.replace, []

    def check(path, target):
        if Path(target).name in ("setup.json", "setup.html"):
            assert path.name == f".{Path(target).name}.tmp" and path.is_file()
            replaced.append(Path(target).name)
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", check)
    run()
    assert replaced == ["setup.json", "setup.html"]
    assert not list(registry.directory("creator-stories").glob(".*.tmp"))


@pytest.mark.parametrize("minutes,met", [(0, True), (6.1, True), (15, True), (15.1, False), (None, None)])
def test_scorecard_adds_only_timed_setup_row(public, minutes, met):
    run()
    root = registry.directory("creator-stories")
    before = scorecard.build("creator-stories", now=NOW)
    assert len(before["rows"]) == 6
    pipeline._write(root / "setup.json", {"minutes": minutes})
    data = scorecard.build("creator-stories", now=NOW)
    assert data["rows"][:6] == before["rows"]
    assert data["total"] == (6 if minutes is None else 7)
    if minutes is not None:
        row = data["rows"][-1]
        assert row["id"] == "setup_minutes" and row["label"] == "Niche to first brief"
        assert row["value"] == minutes and row["target"] == 15 and row["met"] is met
        assert "Niche to first brief" in scorecard.page("creator-stories", data).read_text(encoding="utf-8")
    (root / "setup.json").unlink()
    assert scorecard.build("creator-stories", now=NOW) == before


@pytest.mark.parametrize("text", ["{", "[]", '{"minutes":true}', '{"minutes":-1}', '{"minutes":"2"}', '{"minutes":NaN}'])
def test_bad_setup_report_does_not_break_scorecard(public, text):
    run()
    (registry.directory("creator-stories") / "setup.json").write_text(text, encoding="utf-8")
    data = scorecard.build("creator-stories", now=NOW)
    assert len(data["rows"]) == 6 and len(data["problems"]) == 1
    assert "setup.json is invalid" in data["problems"][0]


def test_cli_end_to_end_makes_real_brief_with_fake_feeds_and_judge(public, monkeypatch, capsys):
    for i, ident in enumerate(IDS):
        public.rows[ident] = [{**row, "id": f"{ident}-{row['id']}"} for row in rows((1000,) * 6 + (50_000 + i,), age=2)]
    calls = []

    class Scripts:
        def ask(self, task, text):
            calls.append(task)
            return {"hook": "Start with the moment that changed the story.",
                    "script": "Start with an event the viewer can picture and check the source before recording. " * 5,
                    "move": "Write one opening from a concrete event.", "title": "A story worth checking", "check": []}
    make = brief.make
    monkeypatch.setattr(brief, "make", lambda slug: make(slug, now=NOW, judge=Scripts(), collectors={"news": lambda *a, **k: []}))
    assert command.run(["setup", "creator-stories", "--niche", "Creator stories", "--name", "Stories",
                        "--candidates", *HANDLES, "--keep", "3", "--min-shorts", "5"]) == 0
    root = registry.directory("creator-stories")
    page = root / "brief" / brief._day(registry.load("creator-stories"), NOW) / "brief.html"
    assert capsys.readouterr().out.splitlines() == ["kept 3 of 4", str(root / "setup.html"), str(page),
                                                 "Niche to first brief: 0.0 min"]
    data = pipeline._read(page.with_suffix(".json"))
    assert len(data["items"]) == 2 and calls == ["script-1", "script-2"]
    assert all(item["script"] and not item["pending"] for item in data["items"]) and not data["errors"]
    assert saved()["first_brief"] == NOW.isoformat() and saved()["minutes"] == 0


def test_cli_file_only_no_brief(public, tmp_path, monkeypatch, capsys):
    path = tmp_path / "candidates.txt"
    path.write_text("\n".join(HANDLES), encoding="utf-8")
    monkeypatch.setattr(brief, "make", lambda *a, **k: pytest.fail("brief was requested"))
    assert command.run(["setup", "creator-stories", "--niche", "Stories", "--candidates-file", str(path), "--no-brief"]) == 0
    assert capsys.readouterr().out.splitlines() == ["kept 4 of 4", str(registry.directory("creator-stories") / "setup.html")]
    assert saved()["first_brief"] is None


@pytest.mark.parametrize("args,message", [
    ([], "supply --candidates"), (["--candidates", "@one", "@two"], "Only 2 candidates survived"),
    (["--keep", "2"], "keep must be"), (["--keep", "41"], "keep must be"), (["--min-shorts", "0"], "min-shorts must be"),
    (["--candidates-file", "missing.txt"], "candidates file could not be read"),
    (["--candidates", *[f"@channel{i}" for i in range(41)]], "at most 40")])
def test_cli_channel_errors_exit_one_without_creating_channel(public, capsys, args, message):
    assert command.run(["setup", "creator-stories", "--niche", "Stories", *args]) == 1
    assert message in capsys.readouterr().err
    assert not (registry.directory("creator-stories") / "channel.json").exists()



def test_ranking_uses_only_the_15_newest_uploads(public):
    # a yt-dlp fallback returns up to 15 long videos plus 15 Shorts; only the newest 15 count, like RSS
    long = [{"id": f"long{i}", "title": "Long", "channel_title": "Long channel", "short": False, "views": 10,
             "published": (NOW - timedelta(hours=i + 1)).isoformat()} for i in range(15)]
    public.ids["@longform"] = "longform"
    public.rows["longform"] = long + rows([900] * 15, age=20)
    result = setup.run("creator-stories", "Stories", HANDLES + ["@longform"], no_brief=True)
    assert {"handle": "@longform", "reason": "fewer than 3 Shorts in its 15 newest uploads"} in result["dropped"]
