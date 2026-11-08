"""Channel scorecards from local briefs, queues and outcomes."""
from __future__ import annotations

import html
import json
import socket
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from myzing.channels import command, digest, outcomes, queue, registry, scorecard
from myzing.factory import judge, pipeline
from myzing.playbook import feeds

NOW = datetime(2026, 11, 6, 18, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(feeds, "request", refuse)
    monkeypatch.setattr(judge.Judge, "ask", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture
def channel():
    return registry.create("Stories", "Player stories", cadence={"timezone": "UTC-08:00"})


def brief(channel, day, items=()):
    path = registry.directory(channel["slug"]) / "brief" / day / "brief.json"
    pipeline._write(path, {"schema_version": 1, "channel": channel["slug"], "date": day,
                           "items": list(items), "errors": []})
    return path


def item(**values):
    return {"series": "news", "status": "recorded", "take": {"kept": .8}, **values}


def posted(channel, i, at=NOW, **values):
    clip = f"clip{i:02d}"
    return {"id": f"episode/{clip}", "project": str(registry.directory(channel["slug"]) / "projects" / "episode"),
            "clip": clip, "slot": at.isoformat(), "posted_at": at.isoformat(), "status": "posted", **values}


def measured(i, views, **values):
    return {"id": f"episode/clip{i:02d}", "posted_at": (NOW - timedelta(days=15 - i)).isoformat(),
            "views_7d": views, "arms": {"series": "news"}, **values}


def rows(channel, **kwargs):
    return {row["id"]: row for row in scorecard.build(channel["slug"], now=NOW, **kwargs)["rows"]}


def ready(channel):
    brief(channel, "2026-10-08", [item() for _ in range(10)])
    queue.write(channel["slug"], [posted(channel, i) for i in range(1, 61)])
    outcomes.write(channel["slug"], [measured(i, 100 if i < 5 else 200) for i in range(10)])


def test_empty_scorecard(channel):
    data = scorecard.build(channel["slug"], now=NOW)
    assert {key: data[key] for key in ("schema_version", "channel", "made_at", "days", "bar", "met", "total", "ready", "problems")} == {
        "schema_version": 1, "channel": channel["slug"], "made_at": NOW.isoformat(), "days": 30,
        "bar": scorecard.BAR, "met": 1, "total": 6, "ready": False, "problems": []}
    got = {row["id"]: row for row in data["rows"]}
    assert list(got) == ["days", "posts", "recorded", "kept", "median", "flags"]
    for key in ("days", "recorded", "kept", "median"):
        assert got[key]["value"] is None and got[key]["met"] is None
    assert got["posts"]["value"] == 0 and got["posts"]["met"] is False
    assert got["flags"]["value"] == 0 and got["flags"]["met"] is True
    assert all(set(row) == {"id", "label", "value", "target", "met", "detail"} for row in data["rows"])
    assert not (registry.directory(channel["slug"]) / "scorecard.json").exists()


@pytest.mark.parametrize("day,age,met", [("2026-11-06", 1, False), ("2026-10-09", 29, False),
                                        ("2026-10-08", 30, True), ("2026-09-01", 67, True)])
def test_days_from_first_brief_inclusive_even_outside_window(channel, day, age, met):
    brief(channel, day)
    brief(channel, "2026-11-07")
    row = rows(channel, days=7)["days"]
    assert row["value"] == age and row["met"] is met and row["target"] == 30
    assert row["detail"] == f"First brief {day}"


def test_future_brief_is_not_a_first_brief(channel):
    brief(channel, "2026-11-07", [item()] * 10)
    assert rows(channel)["days"]["met"] is None
    assert rows(channel)["recorded"]["value"] is None


@pytest.mark.parametrize("count,met", [(0, False), (59, False), (60, True), (61, True)])
def test_post_threshold(channel, count, met):
    queue.write(channel["slug"], [posted(channel, i) for i in range(1, count + 1)])
    row = rows(channel)["posts"]
    assert row["value"] == count and row["met"] is met


@pytest.mark.parametrize("count,done,met", [(9, 9, None), (10, 5, False), (10, 6, True), (19, 9, False)])
def test_recorded_sample_and_series_counts(channel, count, done, met):
    entries = [item(series="news" if i < 10 else "breakdown", status="recorded" if i < done else "ready") for i in range(count)]
    brief(channel, "2026-11-04", entries)
    row = rows(channel)["recorded"]
    assert row["value"] == round(done / count, 2) and row["met"] is met
    assert f"news {min(done, 10)}/{min(count, 10)}" in row["detail"]
    if count > 10:
        assert "breakdown 0/9" in row["detail"]


@pytest.mark.parametrize("values,value,met", [([], None, None), ([.9, .9], .9, None),
                                            ([.1, .6, 1], .6, False), ([.1, .7, 1], .7, True),
                                            ([.6, .7, .9, 1], .8, True)])
def test_kept_median_and_defensive_take_reads(channel, values, value, met):
    entries = [item(take={"kept": v}) for v in values]
    entries += [item(take=take) for take in (None, [], "old", {}, {"kept": "1"}, {"kept": True},
                                           {"kept": float("nan")}, {"kept": float("inf")})]
    entries += [{"status": "recorded"}, item(status="ready", take={"kept": 100})]
    brief(channel, "2026-11-06", entries)
    row = rows(channel)["kept"]
    assert row["value"] == value and row["met"] is met
    assert row["detail"] == f"{len(values)} recorded takes with a kept share"


@pytest.mark.parametrize("values,earlier,newer,met", [([100] * 9, 100, 100, None),
    ([100] * 10, 100, 100, False), ([200] * 5 + [100] * 5, 200, 100, False),
    ([100] * 5 + [200] * 5, 100, 200, True), ([10] * 5 + [20, 30, 40, 50, 60, 70], 10, 45, True)])
def test_median_halves_are_chronological_and_odd_row_goes_to_newer_half(channel, values, earlier, newer, met):
    outcomes.write(channel["slug"], [measured(i, value) for i, value in reversed(list(enumerate(values)))])
    row = rows(channel)["median"]
    assert row["value"] == newer and row["target"] == earlier and row["met"] is met
    assert f"earlier half median {earlier}" in row["detail"]


def test_median_falls_back_to_one_day_for_every_post_when_any_lacks_seven_day(channel):
    data = [measured(i, None if i < 5 else 0, views_24h=100 if i < 5 else 999,
                     arms={"series": "news"} if i < 5 else {}, series="breakdown") for i in range(10)]
    data[0]["views_7d"] = "missing"
    data[1]["views_7d"] = True
    data += [measured(12, "bad", views_24h=True), measured(13, None), measured(14, "bad", views_24h="5")]
    outcomes.write(channel["slug"], data)
    row = rows(channel)["median"]
    assert row["target"] == 100 and row["value"] == 999 and row["met"] is True
    assert row["detail"] == "24-hour views, earlier half median 100, breakdown median 999, news median 100"


def test_channel_local_window_edges_and_posted_slot_fallback(channel):
    now = datetime(2026, 11, 7, 7, 30, tzinfo=timezone.utc)
    times = [datetime.fromisoformat(at) for at in ("2026-10-08T07:59:59+00:00", "2026-10-08T08:00:00+00:00",
             "2026-11-07T07:59:59+00:00", "2026-11-07T08:00:00+00:00")]
    data = [posted(channel, i, at) for i, at in enumerate(times, 1)]
    data += [posted(channel, 5, times[1], posted_at=None), posted(channel, 6, times[1], posted_at=times[0].isoformat())]
    del data[1]["posted_at"]
    data += [posted(channel, i, times[1], status=status) for i, status in enumerate(("queued", "kit", "skipped"), 7)]
    queue.write(channel["slug"], data)
    outcomes.write(channel["slug"], [measured(i, 100 * i, posted_at=at.isoformat(), masked=True) for i, at in enumerate(times)])
    for at in times:
        scorecard.flag(channel["slug"], "claim", "Check it", now=at)
    for day, count, kept in (("2026-10-07", 100, 0), ("2026-10-08", 5, .7), ("2026-11-04", 5, .7),
                             ("2026-11-05", 100, .7), ("2026-11-06", 100, .7), ("2026-11-07", 100, 0)):
        brief(channel, day, [item(take={"kept": kept}) for _ in range(count)])
    got = {row["id"]: row for row in scorecard.build(channel["slug"], now=now)["rows"]}
    assert got["days"]["value"] == 31
    assert got["posts"]["value"] == 3
    assert got["recorded"]["detail"] == "news 10/10" and got["recorded"]["met"] is True
    assert got["kept"]["value"] == .7 and got["kept"]["detail"].startswith("210 ")
    assert got["median"]["target"] == 100 and got["median"]["value"] == 200
    assert got["flags"]["value"] == 4 and got["flags"]["detail"] == "claim 2, masked 2"


def test_days_changes_window_without_changing_bar(channel):
    brief(channel, "2026-10-08", [item()] * 10)
    queue.write(channel["slug"], [posted(channel, 1, NOW - timedelta(days=7)), posted(channel, 2, NOW - timedelta(days=6))])
    data = scorecard.build(channel["slug"], now=NOW, days=7)
    got = {row["id"]: row for row in data["rows"]}
    assert data["days"] == 7 and data["bar"]["days"] == 30
    assert got["days"]["met"] is True and got["posts"]["value"] == 1
    assert got["recorded"]["met"] is None and got["kept"]["met"] is None


@pytest.mark.parametrize("days", [0, -1, True, 1.5, "30", 10 ** 20])
def test_invalid_window(channel, days):
    with pytest.raises(registry.ChannelError, match="days"):
        scorecard.build(channel["slug"], now=NOW, days=days)


def test_bar_override_roundtrip_defaults_and_readiness(channel):
    assert "bar" not in registry.load(channel["slug"])
    assert registry.validate({**channel, "bar": {}})["bar"] == {}
    channel["bar"] = {"days": 1, "posts": 1, "recorded": .5, "kept": .5, "flags": 1}
    registry.save(channel)
    assert registry.load(channel["slug"])["bar"] == channel["bar"]
    brief(channel, "2026-11-04", [item(status="recorded" if i < 5 else "ready", take={"kept": .5}) for i in range(10)])
    queue.write(channel["slug"], [posted(channel, 1)])
    outcomes.write(channel["slug"], [measured(i, 100 if i < 5 else 200) for i in range(10)])
    scorecard.flag(channel["slug"], "other", "A note", now=NOW)
    data = scorecard.build(channel["slug"], now=NOW)
    assert data["ready"] is True and data["met"] == data["total"] == 6 and data["bar"] == channel["bar"]
    registry.save({**channel, "bar": {"posts": 0}})
    assert scorecard.build(channel["slug"], now=NOW)["bar"] == {**scorecard.BAR, "posts": 0}
    assert scorecard.BAR == {"days": 30, "posts": 60, "recorded": .6, "kept": .7, "flags": 0}


@pytest.mark.parametrize("bar", [None, [], "bar", 1, True, {"unknown": 0}, {"median": 1},
    *[{key: value} for key in scorecard.BAR for value in (-1, True, False, "1", None, [], {}, float("nan"), float("inf"))]])
def test_invalid_bar(channel, bar):
    with pytest.raises(registry.ChannelError, match="bar"):
        registry.validate({**channel, "bar": bar})


@pytest.mark.parametrize("key", scorecard.BAR)
def test_bar_accepts_zero_and_fractional_numbers(channel, key):
    for value in (0, .5):
        assert registry.validate({**channel, "bar": {key: value}})["bar"] == {key: value}


def test_ready_requires_all_six_rows(channel):
    ready(channel)
    data = scorecard.build(channel["slug"], now=NOW)
    assert data["ready"] is True and data["met"] == 6
    scorecard.flag(channel["slug"], "strike", "A strike", now=NOW)
    data = scorecard.build(channel["slug"], now=NOW)
    assert data["ready"] is False and data["met"] == 5
    assert data["rows"][-1]["met"] is False


@pytest.mark.parametrize("kind", scorecard.KINDS)
def test_flags_append_and_preserve_text(channel, kind):
    slug = channel["slug"]
    row = scorecard.flag(slug, kind, "  Check café\nagain  ", clip="episode/clip01", now=NOW)
    assert row == {"at": NOW.isoformat(), "kind": kind, "note": "Check café\nagain", "clip": "episode/clip01"}
    path = registry.directory(slug) / "flags.jsonl"
    first = path.read_bytes()
    next_row = scorecard.flag(slug, "other", "x" * 500, now=NOW)
    assert path.read_bytes().startswith(first)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert scorecard.flags(slug) == ([row, next_row], []) and next_row["clip"] is None


def test_flag_uses_one_append_write(channel, monkeypatch):
    path = registry.directory(channel["slug"]) / "flags.jsonl"
    original, writes, modes = Path.open, [], []

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write(self, text):
            writes.append(text)

    def opened(self, mode="r", *args, **kwargs):
        if self == path:
            modes.append(mode)
            return Stream()
        return original(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opened)
    row = scorecard.flag(channel["slug"], "claim", "Check it", now=NOW)
    assert modes == ["a"] and writes == [json.dumps(row, ensure_ascii=False) + "\n"]


@pytest.mark.parametrize("values", [{"kind": "bad"}, {"kind": []}, {"kind": None}, {"note": ""},
    {"note": " \n "}, {"note": "x" * 501}, {"note": None}, {"note": 12}, {"clip": 1}, {"clip": []},
    {"now": NOW.replace(tzinfo=None)}])
def test_flag_validation(channel, values):
    with pytest.raises(registry.ChannelError):
        scorecard.flag(channel["slug"], **{"kind": "claim", "note": "Check it", "now": NOW, **values})
    assert not (registry.directory(channel["slug"]) / "flags.jsonl").exists()


@pytest.mark.parametrize("bad", ["{", "null", "[]", "{}", '{"kind":"claim"}',
    *[json.dumps({"at": NOW.isoformat(), "kind": "claim", "note": "Check it", "clip": None, **values})
      for values in ({"at": "bad"}, {"at": "2026-11-06"}, {"at": 1}, {"kind": "bad"}, {"note": ""}, {"clip": 1})]])
def test_corrupt_flag_lines_are_reported_without_losing_valid_lines(channel, bad):
    slug = channel["slug"]
    first = scorecard.flag(slug, "claim", "One", now=NOW)
    with (registry.directory(slug) / "flags.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(bad + "\n\n")
    last = scorecard.flag(slug, "reused", "Two", now=NOW)
    saved, problems = scorecard.flags(slug)
    assert saved == [first, last] and len(problems) == 1 and "flags.jsonl line 2" in problems[0]
    data = scorecard.build(slug, now=NOW)
    assert data["problems"] == problems
    assert data["rows"][-1]["value"] == 2 and data["rows"][-1]["detail"] == "claim 1, reused 1"


def test_masked_flags_count_without_views_and_require_true(channel):
    outcomes.write(channel["slug"], [measured(i, None, masked=masked) for i, masked in enumerate((True, True, False, "true", 1))])
    row = rows(channel)["flags"]
    assert row["value"] == 2 and row["met"] is False and row["detail"] == "masked 2"


@pytest.mark.parametrize("bad", ["{", "null", "[]", '{}', '{"date":"2026-11-04","items":{}}',
    '{"date":"2026-11-04","items":[null]}', '{"date":"2026-11-03","items":[]}'])
def test_corrupt_brief_and_non_date_folder_are_problems(channel, bad):
    path = brief(channel, "2026-11-04")
    path.write_text(bad, encoding="utf-8")
    root = path.parent.parent
    (root / "not-a-date").mkdir()
    brief(channel, "20261103")
    brief(channel, "2026-11-05", [item()] * 10)
    (root / "latest.html").write_text("ignored", encoding="utf-8")
    data = scorecard.build(channel["slug"], now=NOW)
    assert len(data["problems"]) == 3
    assert all(any(name in problem for problem in data["problems"]) for name in ("2026-11-04/brief.json", "not-a-date", "20261103"))
    assert data["rows"][0]["value"] == 2 and data["rows"][2]["value"] is None


@pytest.mark.parametrize("file,bad", [("queue", "{"), ("queue", "null"), ("queue", "{}"),
    ("outcomes", "{"), ("outcomes", "null"), ("outcomes", "[]"), ("outcomes", "{}"),
    ("outcomes", '{"posted_at":"bad"}'), ("outcomes", '{"posted_at":"2026-11-05","arms":[]}')])
def test_invalid_queue_or_outcomes_file_is_skipped(channel, file, bad):
    ready(channel)
    path = registry.directory(channel["slug"]) / f"{file}.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(bad + "\n")
    data = scorecard.build(channel["slug"], now=NOW)
    assert len(data["problems"]) == 1 and f"{file}.jsonl" in data["problems"][0]
    got = {row["id"]: row for row in data["rows"]}
    assert got["days"]["met"] is True
    assert got["posts"]["value"] == (0 if file == "queue" else 60)
    assert got["median"]["met"] is (None if file == "outcomes" else True)


def test_cli_text_json_open_flag_and_invalid_days(channel, monkeypatch, capsys):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(queue, "datetime", Clock)
    opened = []
    monkeypatch.setattr(command.webbrowser, "open", opened.append)
    slug = channel["slug"]
    assert command.run(["scorecard", slug, "--days", "7", "--open"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["Days — / 30 not enough data", "Posts 0 / 60 no", "Recorded — / 0.6 not enough data",
                     "Kept — / 0.7 not enough data", "Median views — / — not enough data", "Flags 0 / 0 yes",
                     "Ready: no (1 of 6 met)"]
    root = registry.directory(slug)
    assert opened == [(root / "scorecard.html").as_uri()]
    assert pipeline._read(root / "scorecard.json")["days"] == 7
    (root / "scorecard.html").write_text("old", encoding="utf-8")
    assert command.run(["scorecard", slug, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == pipeline._read(root / "scorecard.json") == scorecard.build(slug, now=NOW)
    assert "Channel scorecard" in (root / "scorecard.html").read_text(encoding="utf-8")
    assert command.run(["flag", slug, "--kind", "claim", "--note", "Check it", "--clip", "episode/clip01"]) == 0
    assert json.loads(capsys.readouterr().out) == scorecard.flags(slug)[0][0]
    assert command.run(["flag", slug, "--kind", "other", "--note", " "]) == 2
    assert "note" in capsys.readouterr().err
    assert command.run(["scorecard", slug, "--days", "0"]) == 2
    assert "days" in capsys.readouterr().err


def test_cli_four_of_six_and_ready(channel, monkeypatch, capsys):
    ready(channel)
    build = scorecard.build
    monkeypatch.setattr(scorecard, "build", lambda slug, **kw: build(slug, now=NOW, **kw))
    assert command.run(["scorecard", channel["slug"]]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "Ready: yes (6 of 6 met)"
    scorecard.flag(channel["slug"], "claim", "Check it", now=NOW)
    queue.write(channel["slug"], [])
    assert command.run(["scorecard", channel["slug"]]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "Ready: no (4 of 6 met)"


def test_digest_scorecard_for_older_briefs_only_and_failure_is_isolated(channel, monkeypatch):
    slug = channel["slug"]
    assert "Scorecard" not in digest.build([slug], now=NOW)
    ready(channel)
    other = registry.create("Empty", "Nothing yet")
    text = digest.build([slug, other["slug"]], now=NOW)
    assert text.count("Scorecard: 6 of 6 met") == 1 and "Could not read" not in text

    def fail(*args, **kwargs):
        raise RuntimeError("broken scorecard")
    monkeypatch.setattr(scorecard, "build", fail)
    text = digest.build([slug, other["slug"]], now=NOW)
    assert "Scorecard error. broken scorecard" in text
    assert "0 clips queued in the last 24 hours." in text and "## empty" in text
    assert "Could not read this channel" not in text


def test_page_escapes_series_and_all_displayed_values(channel):
    hostile = '<script>alert("series")</script>&\''
    brief(channel, "2026-11-04", [item(series=hostile)] * 10)
    outcomes.write(channel["slug"], [measured(i, i, arms={"series": hostile}) for i in range(10)])
    data = scorecard.build(channel["slug"], now=NOW)
    data["rows"][0].update(label=hostile, value=hostile, target=hostile, detail=hostile)
    data.update(made_at=hostile, days=hostile, problems=[hostile])
    path = scorecard.page(channel["slug"], data)
    text = path.read_text(encoding="utf-8")
    assert path == registry.directory(channel["slug"]) / "scorecard.html"
    assert hostile not in text and text.count(html.escape(hostile)) >= 9
    assert pipeline._read(path.with_suffix(".json")) == data

    class Page(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags, self.attrs = [], []

        def handle_starttag(self, tag, attrs):
            self.tags.append(tag)
            self.attrs.extend(attrs)
    parsed = Page()
    parsed.feed(text)
    assert parsed.tags.count("article") == 6 and "script" not in parsed.tags
    assert not any(key.startswith("on") or key in ("src", "href") for key, _ in parsed.attrs)
    assert ("content", "width=device-width,initial-scale=1") in parsed.attrs
