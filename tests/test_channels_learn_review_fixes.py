"""Channel learning and scorecard regressions with local files."""
from __future__ import annotations

import math
import socket
from datetime import datetime, timedelta, timezone

import pytest

from myzing.channels import outcomes, registry, scorecard
from myzing.factory import judge, pipeline
from myzing.playbook import feeds

NOW = datetime(2026, 11, 6, 18, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(feeds, "request", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture
def channel():
    return registry.create("Stories", "Player stories", cadence={"timezone": "UTC+00:00"})


def measured(i, **values):
    return {"id": f"episode/clip{i:02d}", "posted_at": (NOW - timedelta(days=60 - i)).isoformat(), **values}


def brief(channel, items):
    day = (NOW - timedelta(days=2)).date().isoformat()
    pipeline._write(registry.directory(channel["slug"]) / "brief" / day / "brief.json",
                    {"date": day, "items": items})


def rows(channel):
    return {row["id"]: row for row in scorecard.build(channel["slug"], now=NOW)["rows"]}


@pytest.mark.parametrize("basis", ["24h", "7d"])
def test_masked_posts_do_not_move_reward_median(basis):
    data = [measured(i, **{f"views_{basis}": 1000 if i < 30 else 100, "masked": i >= 30}) for i in range(50)]
    outcomes.rewards(list(reversed(data)))
    assert all(row[f"channel_median_{basis}"] == 1000 for row in data)
    assert all(row["reward_basis"] == basis for row in data)
    assert [row["reward"] for row in data[:30]] == [0] * 30
    assert [row["reward"] for row in data[30:]] == pytest.approx([math.log2(150 / 1050)] * 20)
    assert [row["masked"] for row in data] == [False] * 30 + [True] * 20


@pytest.mark.parametrize("basis", ["24h", "7d"])
@pytest.mark.parametrize("count", [0, 4, 5])
def test_reward_needs_five_unmasked_measurements(basis, count):
    data = [measured(i, **{f"views_{basis}": 1000, "masked": i >= count}) for i in range(count + 20)]
    outcomes.rewards(data)
    assert all(row[f"channel_median_{basis}"] == (1000 if count else None) for row in data)
    assert all(row["reward"] == (0 if count == 5 else None) for row in data)


@pytest.mark.parametrize("basis", ["24h", "7d"])
def test_reward_uses_latest_thirty_unmasked_measurements(basis):
    data = [measured(i, **{f"views_{basis}": 10000 if i < 30 else 1000 if i < 60 else 100,
                           "masked": i >= 60}) for i in range(80)]
    outcomes.rewards(list(reversed(data)))
    assert all(row[f"channel_median_{basis}"] == 1000 for row in data)


@pytest.mark.parametrize("count,value,met", [(25, .6, False), (26, .62, True)])
def test_recorded_bar_uses_unrounded_share(channel, count, value, met):
    brief(channel, [{"series": "news", "status": "recorded" if i < count else "ready"} for i in range(42)])
    row = rows(channel)["recorded"]
    assert row["value"] == value and row["target"] == .6 and row["met"] is met
    assert row["detail"] == f"news {count}/42"


@pytest.mark.parametrize("kept,met", [(.699, False), (.7, True), (.704, True)])
def test_kept_bar_uses_unrounded_median(channel, kept, met):
    brief(channel, [{"status": "recorded", "take": {"kept": value}} for value in (.1, kept, 1)])
    row = rows(channel)["kept"]
    assert row["value"] == .7 and row["target"] == .7 and row["met"] is met


@pytest.mark.parametrize("kind", ["folder", "own", "recordings"])
@pytest.mark.parametrize("values", [{}, {"url": ""}, {"url": " \t\n"}])
def test_folder_sources_need_a_path(channel, kind, values):
    channel["sources"] = [{"id": "takes", "name": "My takes", "kind": kind,
                           "rights": {"status": "own", "grant": "Recorded by me"}, **values}]
    with pytest.raises(registry.ChannelError, match=r"set sources\[0\]\.url to the folder to watch"):
        registry.validate(channel)


@pytest.mark.parametrize("kind", ["folder", "own", "recordings"])
def test_folder_sources_keep_their_path(channel, tmp_path, kind):
    channel["sources"] = [{"id": "takes", "name": "My takes", "kind": kind, "url": str(tmp_path / "incoming"),
                           "rights": {"status": "own", "grant": "Recorded by me"}}]
    assert registry.save(channel)["sources"] == channel["sources"]
    assert registry.load(channel["slug"])["sources"] == channel["sources"]


@pytest.mark.parametrize("kind", ["youtube", "podcast", "uoink"])
@pytest.mark.parametrize("values", [{}, {"url": ""}])
def test_other_sources_still_accept_an_empty_url(channel, kind, values):
    channel["sources"] = [{"id": "source", "name": "Source", "kind": kind,
                           "rights": {"status": "unknown"}, **values}]
    assert registry.validate(channel)["sources"] == channel["sources"]


def test_median_row_compares_one_window_when_newer_posts_lack_seven_day(channel):
    from test_channels_scorecard import measured, rows
    data = [measured(i, 1000, views_24h=100) for i in range(5)] + [measured(i, None, views_24h=200) for i in range(5, 10)]
    outcomes.write(channel["slug"], data)
    row = rows(channel)["median"]
    assert row["target"] == 100 and row["value"] == 200 and row["met"] is True
    assert row["detail"].startswith("24-hour views, ")
