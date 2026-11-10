"""The archive-to-factory path uses local fixtures and a fake judge."""
from __future__ import annotations

import copy
import json
import socket
import urllib.request
from pathlib import Path

import pytest

from myzing import cli
from myzing.channels import resurface, resurface_command, resurface_match as match
from myzing.factory import command, judge, pipeline


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "build_opener", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "Test Show"
    write(root / "ep.json", [{"s": i * 20, "e": (i + 1) * 20, "text": text} for i, text in enumerate([
        "Lee Sample: We tested a smaller engine.", "It used less fuel on the test stand.",
        "We still needed to test it in flight."])])
    write(root / "manifest.json", [{"id": "ep1", "title": "An engine test", "date": "2020-04-03",
                                   "guests": ["Lee Sample"], "transcript": "ep.json",
                                   "url": "https://example.org/episode", "media": "episode.mp4"}])
    (root / "episode.mp4").write_bytes(b"local test media")
    return root


def answer(candidate):
    return {**{key: candidate[key] for key in ("id", "start", "end", "quote")},
            "why": "The engine test explains the fuel claim.",
            "on_screen_context": "Lee Sample on Test Show, April 2020",
            "risk_note": "The engine had not been tested in flight."}


class Fake:
    def __init__(self, picks=True):
        self.calls, self.picks = [], picks

    def ask(self, task, prompt):
        data = json.loads(prompt[prompt.rindex('{"entity"'):])
        self.calls.append((task, data))
        return {"picks": [answer(data["candidates"][0])] if self.picks else []}


def replay(archive, **kwargs):
    return resurface.replay(archive, **{"entity": "Lee Sample", "headline": "Lee Sample builds a smaller engine",
                                       "url": "https://example.org/news", "date": "2025-06-07", **kwargs})


@pytest.fixture
def brief(archive):
    return Path(replay(archive, judge=Fake())["briefs"][0])


def event(entity="Lee Sample", day="2025-06-07"):
    return {"entity": entity, "signal": "google_trends", "traffic": 2000,
            "headlines": [{"title": entity + " builds a smaller engine", "url": "https://example.org/news"}],
            "first_seen": day + "T12:00:00+00:00", "geo": "US"}


def test_replay_creates_a_dated_brief_with_checked_picks(archive):
    fake = Fake()
    result = replay(archive, judge=fake)
    assert result["state"] == "done" and len(result["briefs"]) == len(fake.calls) == 1
    path = Path(result["briefs"][0])
    assert path.parent == archive / ".zing" / "briefs" / "2025-06-07-lee-sample"
    data = read(path)
    assert data["event"]["expires"] == "2025-06-09T00:00:00+00:00"
    pick = data["picks"][0]
    assert pick["date"] == "2020-04-03" and pick["kind"] == "appearance"
    assert (pick["start"], pick["end"]) == (0, 60)
    assert pick["rights"] == "unknown"
    page = path.with_suffix(".html").read_text(encoding="utf-8")
    for value in ("2020-04-03", pick["quote"], pick["why"], pick["on_screen_context"], pick["risk_note"],
                  'href="https://example.org/news"', "Rights · unknown"):
        assert value in page
    assert replay(archive, judge=fake) == result
    assert len(fake.calls) == 1


def test_host_stops_and_factory_answer_resumes(archive, capsys):
    args = [str(archive), "--entity", "Lee Sample", "--headline", "An engine test", "--date", "2025-06-07"]
    assert cli.main(["resurface", "replay", *args]) == 0
    path = next((archive / ".zing" / "briefs").glob("*/brief.json"))
    data = read(path)
    pending = data["pending"]
    prompt = Path(pending["prompt_path"])
    assert prompt.is_file() and data["status"] == "waiting"
    assert prompt.read_text(encoding="utf-8") == match.prompt(data["candidates"], "Lee Sample", "An engine test", 5)
    assert str(prompt) in capsys.readouterr().out
    response = archive / "answer.json"
    write(response, {"picks": [answer(data["candidates"][0])]})
    assert command.run(["answer", str(path.parent), pending["task"], str(response)]) == 0
    assert resurface_command.run(["replay", *args]) == 0
    assert read(path)["status"] == "ready" and len(read(path)["picks"]) == 1
    assert not prompt.exists()


def test_bad_cached_host_answer_stays_pending(archive):
    result = replay(archive)
    path = Path(result["briefs"][0])
    task = result["pending"][0]["task"]
    data = read(path)
    judge.Judge(path.parent).save(task, {"picks": [{**answer(data["candidates"][0]), "quote": "Invented."}]})
    assert replay(archive)["state"] == "waiting"
    assert read(path)["picks"] == []


def test_watch_saves_each_event_once_and_uses_guests_and_aliases(archive, monkeypatch):
    write(archive / "aliases.json", {"Lee Sample": ["Sample"], "New Guest": ["NG"]})
    feeds = archive / "feeds.txt"
    feeds.write_text("# publisher feeds\nhttps://example.org/rss\n", encoding="utf-8")
    calls = []

    def watch(names, **kwargs):
        calls.append((names, kwargs))
        return [event(), event("New Guest")]
    monkeypatch.setattr(resurface.signals, "watch", watch)
    fake = Fake()
    result = resurface.watch(archive, feeds=feeds, geo="GB", judge=fake, n=2)
    assert len(result["briefs"]) == 2
    assert calls[0] == ({"Lee Sample": ["Sample"], "New Guest": ["NG"]},
                        {"feeds": ["https://example.org/rss"], "geo": "GB", "state_dir": archive / ".zing"})
    assert resurface.watch(archive, feeds=feeds, judge=fake)["briefs"] == []
    assert len(list((archive / ".zing" / "briefs").glob("*/brief.json"))) == 2
    assert len(fake.calls) == 1


def test_watch_retains_unasked_events_when_host_stops(archive, monkeypatch):
    events = [event(), event("Nobody")]
    monkeypatch.setattr(resurface.signals, "watch", lambda *a, **k: events)
    result = resurface.watch(archive)
    assert result["state"] == "waiting"
    paths = list((archive / ".zing" / "briefs").glob("*/brief.json"))
    assert len(paths) == 2
    pending = result["pending"][0]
    judge.Judge(Path(pending["prompt_path"]).parent.parent).save(pending["task"], {"picks": []})
    events.clear()
    result = resurface.watch(archive)
    assert result["state"] == "done" and len(result["briefs"]) == 2
    assert {read(path)["status"] for path in paths} == {"no_candidates", "no_picks"}


@pytest.mark.parametrize("entity,picks,note", [("Nobody", True, "No candidates found."),
                                              ("Lee Sample", False, "No picks passed review.")])
def test_empty_results_still_have_a_brief(archive, entity, picks, note):
    result = replay(archive, entity=entity, judge=Fake(picks))
    path = Path(result["briefs"][0])
    assert read(path)["picks"] == []
    assert note in path.with_suffix(".html").read_text(encoding="utf-8")


def test_watch_errors_are_reported_without_a_fake_brief(archive, monkeypatch, capsys):
    error = {"signal": "google_trends", "error": "Feed unavailable"}
    monkeypatch.setattr(resurface.signals, "watch", lambda *a, **k: [error])
    assert resurface_command.run(["watch", str(archive), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["briefs"] == [] and result["errors"] == [error]


def test_same_day_events_and_slug_collisions_do_not_overwrite(archive):
    first = replay(archive, judge=Fake())
    second = replay(archive, headline="Another engine test", judge=Fake())
    assert first["briefs"] != second["briefs"]
    assert replay(archive, headline="Another engine test", judge=Fake()) == second
    assert read(Path(first["briefs"][0]))["event"]["headlines"][0]["title"] == "Lee Sample builds a smaller engine"


def test_make_uses_local_override_original_date_and_exact_pick(archive, brief, tmp_path, capsys):
    media = tmp_path / "override.mp4"
    media.write_bytes(b"test")
    project = tmp_path / "Project"
    assert cli.main(["resurface", "make", str(brief), "--pick", "1", "--media", str(media),
                     "--out", str(project), "--shapes", "9x16,16x9"]) == 0
    src, cfg = read(project / "source.json"), read(project / "factory.json")
    assert src["date"] == "2020-04-03" and src["media"] == str(media)
    assert src["on_screen_context"] == read(brief)["picks"][0]["on_screen_context"]
    assert cfg["moments"] == 0 and cfg["shapes"] == ["9x16", "16x9"]
    assert cfg["news"] == {"peg": "Lee Sample builds a smaller engine", "links": ["https://example.org/news"]}
    assert cfg["rights"] == src["rights"] == "unknown"
    moments = read(project / "moments.json")["moments"]
    assert len(moments) == 1 and (moments[0]["start"], moments[0]["end"]) == (0, 60)
    assert read(project / "transcript.json") == read(archive / "ep.json")
    assert f'zing factory run "{project}"' in capsys.readouterr().out


def test_make_resolves_manifest_media_relative_to_archive(archive, brief):
    result = resurface.make(brief.parent, pick=1)
    project = Path(result["project"])
    assert project == brief.parent / "pick-1"
    assert read(project / "source.json")["media"] == str(archive / "episode.mp4")
    with pytest.raises(ValueError, match="not empty"):
        resurface.make(brief, pick=1)


@pytest.mark.parametrize("media", ["", "https://example.org/episode.mp4"])
def test_url_only_manifest_refuses_without_a_download(archive, brief, media, capsys):
    rows = read(archive / "manifest.json")
    rows[0]["media"] = media
    write(archive / "manifest.json", rows)
    assert resurface_command.run(["make", str(brief), "--pick", "1"]) == 2
    error = capsys.readouterr().err
    assert "Download the media yourself only if you have the rights" in error and "--media" in error
    assert not (brief.parent / "pick-1").exists()


@pytest.mark.parametrize("settings,expected", [({}, "unknown"), ({"rights": "public-domain"}, "public-domain"),
                                             ({"rights": "owned"}, "owned"),
                                             ({"rights": "grant.txt"}, "permission"),
                                             ({"grant": "grant.txt"}, "permission"),
                                             ({"rights": "missing.txt"}, "unknown"),
                                             ({"rights": "licensed"}, "unknown")])
def test_archive_rights_are_on_the_brief_and_project(archive, settings, expected):
    write(archive / "archive.json", settings)
    (archive / "grant.txt").write_text("Written permission for this fixture.", encoding="utf-8")
    brief = Path(replay(archive, judge=Fake())["briefs"][0])
    assert read(brief)["picks"][0]["rights"] == expected
    assert f"Rights · {expected}" in brief.with_suffix(".html").read_text(encoding="utf-8")
    project = Path(resurface.make(brief, pick=1)["project"])
    assert read(project / "factory.json")["rights"] == read(project / "source.json")["rights"] == expected


def test_row_rights_override_archive_rights_and_missing_grant_stays_unknown(archive, brief):
    write(archive / "archive.json", {"rights": "public-domain"})
    rows = read(archive / "manifest.json")
    rows[0]["rights"] = "unknown"
    write(archive / "manifest.json", rows)
    assert resurface.make(brief, pick=1)["rights"] == "unknown"
    rows[0]["rights"] = "owned"
    write(archive / "manifest.json", rows)
    assert resurface.rights(archive, "ep1") == "owned"


def test_grants_can_be_relative_or_absolute_local_files(archive, tmp_path):
    (tmp_path / "grant.txt").write_text("Outside the archive.", encoding="utf-8")
    for value in ("../grant.txt", str(tmp_path / "grant.txt")):
        write(archive / "archive.json", {"rights": value})
        assert resurface.rights(archive, "ep1") == "permission"
    for value in ("https://example.org/grant", "//example.org/grant", "."):
        write(archive / "archive.json", {"rights": value})
        assert resurface.rights(archive, "ep1") == "unknown"


def test_make_accepts_the_brief_page_and_keeps_a_trimmed_pick(brief):
    data = read(brief)
    data["picks"][0].update(start=20, quote=" ".join(cue["text"] for cue in data["picks"][0]["cues"][1:]))
    write(brief, data)
    project = Path(resurface.make(brief.with_suffix(".html"), pick=1)["project"])
    assert [(m["start"], m["end"]) for m in read(project / "moments.json")["moments"]] == [(20, 60)]


def test_watch_alias_search_reaches_the_named_guest(archive, monkeypatch):
    write(archive / "aliases.json", {"Lee Sample": ["Sample"]})
    monkeypatch.setattr(resurface.signals, "watch", lambda *a, **k: [event("Sample")])
    result = resurface.watch(archive, judge=Fake())
    assert read(Path(result["briefs"][0]))["picks"][0]["on_screen_context"] == "Lee Sample on Test Show, April 2020"


def test_changed_transcript_and_forged_pick_are_rejected(archive, brief):
    original = read(brief)
    data = copy.deepcopy(original)
    data["picks"][0]["on_screen_context"] = "Lee Sample on Test Show, April 2025"
    write(brief, data)
    with pytest.raises(ValueError, match="original month"):
        resurface.make(brief, pick=1)
    write(brief, original)
    cues = read(archive / "ep.json")
    cues[0]["text"] = "The transcript changed."
    write(archive / "ep.json", cues)
    with pytest.raises(ValueError, match="candidate id"):
        resurface.make(brief, pick=1)
    assert not (brief.parent / "pick-1").exists()


def test_html_escapes_headlines_and_does_not_link_unsafe_urls(archive, monkeypatch):
    row = event()
    row["headlines"] = [{"title": "<script>Engine news</script>", "url": "javascript:alert(1)"}]
    monkeypatch.setattr(resurface.signals, "watch", lambda *a, **k: [row])
    path = Path(resurface.watch(archive, judge=Fake())["briefs"][0]).with_suffix(".html")
    page = path.read_text(encoding="utf-8")
    assert "<script>" not in page and "&lt;script&gt;Engine news&lt;/script&gt;" in page
    assert "javascript:" not in page


def test_build_and_status_show_bad_rows_and_incomplete_episodes(archive, capsys):
    rows = read(archive / "manifest.json")
    rows[0]["duration"] = 300
    write(archive / "manifest.json", [*rows, {"id": "bad"}])
    assert cli.main(["resurface", "build", str(archive)]) == 0
    assert "1 episodes" in capsys.readouterr().out
    assert cli.main(["resurface", "status", str(archive)]) == 0
    text = capsys.readouterr().out
    assert "1 bad rows" in text and "missing title" in text
    assert "1 incomplete episodes" in text and "ep1" in text


@pytest.mark.parametrize("pick", [0, -1, 2, True])
def test_invalid_pick_does_not_create_a_project(brief, pick):
    with pytest.raises(ValueError, match="pick number"):
        resurface.make(brief, pick=pick)
