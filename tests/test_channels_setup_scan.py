"""Niche scans supply candidates; fresh feeds still decide the watch list."""
from __future__ import annotations

import copy
import html
import json
import socket
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from myzing.channels import brief, command, registry, setup
from myzing.factory import judge
from myzing.playbook import command as playbook_command, feeds, niches
from myzing.playbook.common import SCHEMA_VERSION, read_json, write_json

NOW = datetime(2026, 11, 7, 18, tzinfo=timezone.utc)
MADE_AT = "2026-11-05"
HANDLES = ["@one", "@two", "@three", "@four"]


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))
    monkeypatch.setattr(setup, "datetime", Clock)
    monkeypatch.setattr(niches, "datetime", Clock)

    def refuse(*args, **kwargs):
        pytest.fail("unmocked external operation")
    for name in ("request", "listing", "resolve", "feed"):
        monkeypatch.setattr(feeds, name, refuse)
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
        self.ids, self.rows = {}, {}
        self.calls, self.feed_calls = [], []

    def resolve(self, handle, fetch=None, *, root):
        self.calls.append(handle)
        handle = handle.casefold()
        if handle != "@missing":
            return self.ids.setdefault(handle, "UC" + f"{len(self.ids):022d}")

    def feed(self, ident, fetch=None, *, root):
        handle = next(handle for handle, value in self.ids.items() if value == ident)
        self.feed_calls.append(handle)
        value = self.rows.get(handle, rows())
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


@pytest.fixture
def public(monkeypatch):
    public = Public()
    monkeypatch.setattr(feeds, "resolve", public.resolve)
    monkeypatch.setattr(feeds, "feed", public.feed)
    return public


def scan(tmp_path, names=("Creator stories",), channels=None, **fields):
    path = tmp_path / "scan" / "niches.json"
    channels = channels if channels is not None else [
        {"channel": handle, "status": "listed", "median_views": 200} for handle in HANDLES]
    write_json(path, {"schema_version": SCHEMA_VERSION, "made_at": MADE_AT,
                      "niches": [{"niche": name, "channels": channels} for name in names], **fields})
    return path


def saved():
    return read_json(registry.directory("creator-stories") / "setup.json")


@pytest.mark.parametrize("folder", [False, True])
def test_cli_folder_and_file_default_to_single_niche(public, tmp_path, monkeypatch, folder):
    path = scan(tmp_path)
    before = path.read_bytes()
    monkeypatch.chdir(tmp_path)
    source = Path("scan") if folder else Path("scan/niches.json")
    assert command.run(["setup", "creator-stories", "--from-scan", str(source), "--no-brief"]) == 0
    data = saved()
    assert data["niche"] == registry.load("creator-stories")["niche"] == "Creator stories"
    assert data["scan"] == {"path": str(path.resolve()), "niche": "Creator stories", "made_at": MADE_AT,
                            "candidates": 4, "left_out": 0}
    assert public.calls == HANDLES and all(row["from_scan"] is True for row in data["kept"])
    assert path.read_bytes() == before
    page = (registry.directory("creator-stories") / "setup.html").read_text(encoding="utf-8")
    assert '</h1><p>Candidates came from the niche scan made 2026-11-05 for Creator stories.</p>' in page


def test_cli_selects_scan_niche_ignoring_case_and_spaces(public, tmp_path):
    path = scan(tmp_path, (" NFL stories ", "Creator stories"))
    assert command.run(["setup", "creator-stories", "--from-scan", str(path),
                        "--scan-niche", "  nFl STORIES  ", "--no-brief"]) == 0
    assert saved()["scan"]["niche"] == " NFL stories " and saved()["niche"] == "NFL stories"


def test_page_shows_the_scan_date_for_a_full_timestamp(public, tmp_path):
    path = scan(tmp_path, made_at="2026-11-06T03:32:35.610574+00:00")
    assert command.run(["setup", "creator-stories", "--from-scan", str(path), "--no-brief"]) == 0
    assert saved()["scan"]["made_at"] == "2026-11-06T03:32:35.610574+00:00"
    page = (registry.directory("creator-stories") / "setup.html").read_text(encoding="utf-8")
    assert "Candidates came from the niche scan made 2026-11-06 for Creator stories." in page


@pytest.mark.parametrize("names,selected", [
    (("NFL stories", "Creator stories"), None), (("NFL stories", "Creator stories"), "missing"),
    (("Creator stories",), "missing"), (("Creator stories",), " ")])
def test_unknown_or_ambiguous_niche_lists_names(public, tmp_path, names, selected):
    path = scan(tmp_path, names)
    with pytest.raises(registry.ChannelError) as exc:
        setup.run("creator-stories", from_scan=path, scan_niche=selected, no_brief=True)
    assert str(exc.value) == "choose a niche with --scan-niche: " + " | ".join(names)
    assert public.calls == [] and not registry.directory("creator-stories").exists()


@pytest.mark.parametrize("folder", [False, True])
def test_missing_scan_names_the_file(public, tmp_path, folder):
    source = tmp_path / "missing"
    if folder:
        source.mkdir()
    expected = source / "niches.json" if folder else source
    with pytest.raises(registry.ChannelError) as exc:
        setup.run("creator-stories", from_scan=source, no_brief=True)
    assert str(expected.resolve()) in str(exc.value)
    assert public.calls == []


@pytest.mark.parametrize("text", ["{", "[]", "null", "{}", *[
    json.dumps({"schema_version": value, "niches": []}) for value in (2, None, "1", True)]])
def test_bad_json_and_schema_name_the_scan(public, tmp_path, text):
    path = tmp_path / "niches.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(registry.ChannelError) as exc:
        setup.run("creator-stories", from_scan=path, no_brief=True)
    assert str(path.resolve()) in str(exc.value)
    assert public.calls == [] and not registry.directory("creator-stories").exists()


@pytest.mark.parametrize("explicit", [None, "My own niche"])
def test_long_scan_name_is_clipped_and_explicit_niche_wins(public, tmp_path, explicit):
    name = "Creator stories " * 20
    path = scan(tmp_path, (name,))
    args = ["--niche", explicit] if explicit is not None else []
    assert command.run(["setup", "creator-stories", "--from-scan", str(path), "--no-brief", *args]) == 0
    assert saved()["niche"] == registry.load("creator-stories")["niche"] == (explicit or name[:200])
    assert saved()["scan"]["niche"] == name


@pytest.mark.parametrize("args", [[], ["--niche", "Stories"]])
def test_scan_niche_alone_errors(public, capsys, args):
    assert command.run(["setup", "creator-stories", "--scan-niche", "Stories", *args]) == 1
    assert "--scan-niche requires --from-scan" in capsys.readouterr().err
    with pytest.raises(registry.ChannelError, match="--scan-niche requires --from-scan"):
        setup.run("creator-stories", scan_niche="Stories")
    assert public.calls == []


def test_niche_is_still_required_without_scan(public, capsys):
    with pytest.raises(SystemExit) as exc:
        command.run(["setup", "creator-stories", "--candidates", *HANDLES, "--no-brief"])
    assert exc.value.code == 2
    assert "the following arguments are required: --niche" in capsys.readouterr().err
    assert public.calls == []


def test_listed_by_median_then_skipped_with_stable_ties(public, tmp_path):
    channels = [{"channel": handle, "status": status, "median_views": views} for handle, status, views in (
        ("@skipped", "skipped", 1000), ("@one", "listed", 100), ("@two", "listed", 400),
        ("@also-skipped", "skipped", None), ("@three", "listed", 400), ("@four", "listed", 0))]
    result = setup.run("creator-stories", from_scan=scan(tmp_path, channels=channels), no_brief=True)
    expected = ["@two", "@three", "@one", "@four", "@skipped", "@also-skipped"]
    assert public.calls == expected and public.feed_calls == expected
    assert [row["handle"] for row in result["kept"]] == expected


def test_merge_order_and_duplicates_with_file_scan_and_suggestions(public, tmp_path, monkeypatch):
    path = scan(tmp_path)
    candidates = tmp_path / "candidates.txt"
    candidates.write_text("@two\n@ONE # duplicate\n", encoding="utf-8")

    class Suggestions:
        def __init__(self, project, backend):
            assert backend == "host"

        def ask(self, task, prompt):
            assert task == "suggest-candidates" and "Creator stories" in prompt
            return {"candidates": [{"handle": handle} for handle in ("@THREE", "@five", "@ONE")]}
    monkeypatch.setattr(setup, "Judge", Suggestions)
    result = setup.run("creator-stories", candidates=["https://youtube.com/@one/shorts", "one"],
                       candidates_file=candidates, from_scan=path, suggest=True, no_brief=True)
    assert public.calls == HANDLES + ["@five"]
    assert [(row["handle"], row.get("from_scan", False), row["suggested"]) for row in result["kept"]] == [
        ("@one", False, False), ("@two", False, False), ("@three", True, False), ("@four", True, False),
        ("@five", False, True)]
    assert saved()["scan"]["candidates"] == 4 and saved()["scan"]["left_out"] == 0


def test_scan_provenance_survives_drops_and_fresh_ranking(public, tmp_path):
    channels = [{"channel": handle, "status": "skipped"} for handle in HANDLES + ["@missing", "@small", "@stale", "@failed"]]
    public.rows.update({"@one": rows((1, 2, 3)), "@small": rows((1, 2)), "@stale": rows(age=61),
                        "@failed": OSError("unavailable")})
    result = setup.run("creator-stories", candidates=["@ONE"], from_scan=scan(tmp_path, channels=channels),
                       keep=3, no_brief=True)
    assert [row["handle"] for row in result["kept"]] == ["@two", "@three", "@four"]
    assert result["dropped"] == [
        {"handle": "@missing", "reason": "could not resolve", "from_scan": True},
        {"handle": "@small", "reason": "fewer than 3 Shorts in its 15 newest uploads", "from_scan": True},
        {"handle": "@stale", "reason": "no Short in the last 60 days", "from_scan": True},
        {"handle": "@failed", "reason": "feed failed (unavailable)", "from_scan": True},
        {"handle": "@ONE", "reason": "outside top 3"}]
    assert all(row["from_scan"] is True for row in result["kept"])
    assert saved() == {key: value for key, value in result.items() if key not in ("page", "brief")}
    assert "@small" in public.feed_calls and "@stale" in public.feed_calls and "@failed" in public.feed_calls


def test_scan_row_keeps_provenance_when_outside_top_keep(public, tmp_path):
    result = setup.run("creator-stories", from_scan=scan(tmp_path), keep=3, no_brief=True)
    assert result["dropped"] == [{"handle": "@four", "reason": "outside top 3", "from_scan": True}]


@pytest.mark.parametrize("count,explicit", [(40, 0), (45, 0), (45, 2), (45, 40)])
def test_cap_keeps_first_candidates_and_counts_scan_omissions(public, tmp_path, count, explicit):
    channels = [{"channel": f"@channel{i}", "status": "listed", "median_views": i} for i in range(count)]
    candidates = [f"@manual{i}" for i in range(explicit)]
    result = setup.run("creator-stories", candidates=candidates, from_scan=scan(tmp_path, channels=channels),
                       keep=40, no_brief=True)
    expected = (candidates + [row["channel"] for row in reversed(channels)])[:40]
    assert public.calls == expected and [row["handle"] for row in result["kept"]] == expected
    assert result["scan"]["candidates"] == count and result["scan"]["left_out"] == max(0, count + explicit - 40)
    assert [row.get("from_scan", False) for row in result["kept"]] == [False] * explicit + [True] * (40 - explicit)


def test_cap_does_not_count_duplicates_as_left_out(public, tmp_path):
    channels = [{"channel": f"@channel{i}", "status": "listed", "median_views": i} for i in range(40)]
    channels.append({"channel": "@CHANNEL0", "status": "skipped"})
    result = setup.run("creator-stories", candidates=["@CHANNEL0"], from_scan=scan(tmp_path, channels=channels),
                       keep=40, no_brief=True)
    assert len(public.calls) == 40 and public.calls[0] == "@CHANNEL0"
    assert result["scan"]["candidates"] == 40 and result["scan"]["left_out"] == 0
    assert "from_scan" not in result["kept"][0]


def test_scan_does_not_relax_explicit_candidate_limit(public, tmp_path):
    with pytest.raises(registry.ChannelError, match="at most 40"):
        setup.run("creator-stories", candidates=[f"@channel{i}" for i in range(41)],
                  from_scan=scan(tmp_path), no_brief=True)
    assert public.calls == []


@pytest.mark.parametrize("made_at", [None, '\"><img src=x onerror="alert(1)">'])
def test_page_escapes_scan_sentence_and_handles_missing_date(public, tmp_path, made_at):
    name = '<script>alert("niche")</script>&\''
    path = scan(tmp_path, (name,), made_at=made_at)
    if made_at is None:
        data = read_json(path)
        del data["made_at"]
        write_json(path, data)
    result = setup.run("creator-stories", "My niche", from_scan=path, no_brief=True)
    page = Path(result["page"]).read_text(encoding="utf-8")
    when = f" made {made_at}" if made_at else ""
    sentence = f"Candidates came from the niche scan{when} for {name}."
    assert f"</h1><p>{html.escape(sentence)}</p>" in page and name not in page
    assert result["scan"]["made_at"] == made_at
    tags = []
    parser = HTMLParser()
    parser.handle_starttag = lambda tag, attrs: tags.append(tag)
    parser.feed(page)
    assert "script" not in tags and "img" not in tags


def test_playbook_cli_prints_hint_after_json(public, tmp_path, capsys):
    path, out = tmp_path / "input.json", tmp_path / "scan output"
    write_json(path, {"niches": [{"niche": "Creator stories", "channels": HANDLES}]})
    assert playbook_command.run(["niches", str(path), "--out", str(out), "--min-shorts", "3", "--fresh-days", "0"]) == 0
    captured = capsys.readouterr()
    data = read_json(out / "niches.json")
    assert json.loads(captured.out) == {key: value for key, value in data.items() if key != "local"}
    assert captured.err == (f'Set up a channel from one niche with: zing channels setup SLUG --from-scan "{out}" '
                            '--scan-niche "NAME"\n')
    assert (out / "NICHES.md").read_text(encoding="utf-8") == niches.report(data)
    result = setup.run("creator-stories", from_scan=out, no_brief=True)
    assert len(result["kept"]) == 4 and result["scan"]["made_at"] == NOW.isoformat()


def test_scan_setup_makes_first_brief_with_fake_judge(public, tmp_path, monkeypatch):
    for handle in HANDLES:
        public.rows[handle] = [{**row, "id": f"{handle[1:]}-{row['id']}"} for row in rows((1000,) * 6 + (50_000,), age=2)]
    calls = []

    class Scripts:
        def ask(self, task, prompt):
            calls.append(task)
            return {"hook": "Start with the event that changed the story.",
                    "script": "Start with an event the viewer can picture and check the source before recording. " * 5,
                    "move": "Write one opening from a concrete event.", "title": "A story worth checking", "check": []}
    make = brief.make
    monkeypatch.setattr(brief, "make", lambda slug: make(slug, now=NOW, judge=Scripts(), collectors={"news": lambda *a, **k: []}))
    result = setup.run("creator-stories", from_scan=scan(tmp_path))
    assert "brief_error" not in result and Path(result["brief"]).is_file()
    assert calls == ["script-1", "script-2"] and saved()["first_brief"] == NOW.isoformat()
    assert saved()["scan"] == result["scan"] and all(row["from_scan"] for row in saved()["kept"])
