"""Recorded takes enter the existing factory, gate and learning loop."""
from __future__ import annotations

import copy
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from myzing.channels import bandit, brief, command, learn, outcomes, queue, registry, tick, watch
from myzing.factory import judge, pipeline, source
from myzing.playbook import feeds

NOW = datetime(2026, 11, 6, 18, tzinfo=timezone.utc)
UC = "UC" + "a" * 22
SCRIPT = ("Creators compare opening titles against typical views. A surprising number brings attention to a specific story. "
          "Readers recognize familiar people before watching carefully. My read is that concrete events create curiosity. "
          "Start your next recording with something viewers can picture.")


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(feeds, "request", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(source, "scout_model", lambda: None)
    monkeypatch.setattr(source, "transcribe_episode", refuse)
    monkeypatch.setattr(source, "transcribe_moments", refuse)


@pytest.fixture
def channel(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    return registry.create("Creators", "How creators tell stories", cadence={"timezone": "UTC-08:00"},
                           factory={"moments": 8, "vocab": ["Zing"]}, handles={"youtube": UC}, sources=[
                               {"id": "takes", "kind": "recordings", "name": "My takes", "url": str(incoming),
                                "rights": {"status": "own", "grant": "Recorded by me"}}])


def media(channel, name="take.mp4"):
    path = Path(channel["sources"][0]["url"]) / name
    path.write_bytes(b"local take")
    return path


def seed(channel, day="2026-11-06", script=SCRIPT, status="open", **values):
    path = registry.directory(channel["slug"]) / "brief" / day / "brief.json"
    data = pipeline._read(path, {"schema_version": 1, "date": day, "made_at": NOW.isoformat(),
                                 "channel": channel["slug"], "items": [], "errors": []})
    item = {"n": len(data["items"]) + 1, "id": "yt-one", "series": "breakdowns", "series_name": "Breakdowns",
            "kind": "breakdown", "facts": {"url": "https://www.youtube.com/shorts/abcdefghijk"},
            "receipt": "Creator: 40,000 views, 4x their typical Short", "hook": "A title viewers could picture",
            "script": script, "move": "Show one event", "title": "An opening worth trying", "check": [],
            "pending": None, "status": status, **values}
    data["items"].append(item)
    pipeline._write(path, data)
    return path, item


def rows(channel):
    return watch.read(registry.directory(channel["slug"]) / "sources" / "takes.jsonl")


def transcribe(monkeypatch, text=SCRIPT, start=1, end=36):
    calls = []
    tokens = text.split()
    words = [{"w": token, "s": start + i * (end - start) / len(tokens),
              "e": start + (i + 1) * (end - start) / len(tokens)} for i, token in enumerate(tokens)]

    def run(media, model, **kwargs):
        calls.append((media, kwargs))
        return words
    monkeypatch.setattr(source, "transcribe_episode", run)
    return calls, words


@pytest.mark.parametrize("rights", ["licensed", "permission", "unknown"])
def test_recordings_require_own_rights_on_load(channel, rights):
    data = copy.deepcopy(channel)
    data["sources"][0]["rights"]["status"] = rights
    path = registry.directory(channel["slug"]) / "channel.json"
    pipeline._write(path, data)
    with pytest.raises(registry.ChannelError, match="rights.status must be own for recordings"):
        registry.load(channel["slug"])


def test_source_command_accepts_recordings_and_requires_grant(channel):
    src = channel["sources"][0]
    args = ["source", channel["slug"], "--id", "phone", "--name", "Phone", "--kind", "recordings", "--url", src["url"],
            "--rights", "own", "--grant", "Recorded by me"]
    assert command.run(args) == 0
    assert registry.load(channel["slug"])["sources"][-1]["kind"] == "recordings"
    args[-1] = ""
    assert command.run(args) == 2


def test_match_sets_peg_hook_series_and_reuses_transcript(channel, monkeypatch):
    path, chosen = seed(channel)
    take = media(channel)
    calls, words = transcribe(monkeypatch)
    assert watch.run(channel["slug"], now=NOW) == {"found": 1, "started": 1, "errors": []}
    row, = rows(channel)
    assert row["own"] and row["state"] == "ready"
    assert {key: row[key] for key in ("brief", "item", "series")} == {"brief": "2026-11-06", "item": 1, "series": "breakdowns"}
    project = Path(row["project"])
    cfg = pipeline._read(project / "factory.json")
    assert cfg["moments"] == 0 and cfg["source"] == "takes" and cfg["rights"] == "own"
    assert cfg["news"] == {"peg": chosen["receipt"], "links": [chosen["facts"]["url"]]}
    moment, = pipeline.load_moments(project)["moments"]
    assert (moment["start"], moment["end"], moment["hook"], moment["series"]) == (1, 36, chosen["hook"], "breakdowns")
    recorded = pipeline._read(path)["items"][0]
    assert recorded["status"] == "recorded" and recorded["project"] == str(project)
    assert pipeline._read(project / "words.json") == words
    assert len(calls) == 1 and calls[0] == (take, {"vocab": ["Zing"]})

    class NoScout:
        def ask(self, *a, **k):
            pytest.fail("recording asked for scouting")
    got = pipeline._moments(project, NoScout(), take, cfg, lambda m: None)
    assert len(calls) == 1 and len(got) == 1 and got[0]["series"] == "breakdowns"
    assert watch.run(channel["slug"], now=NOW) == {"found": 0, "started": 0, "errors": []}
    assert rows(channel) == [row]


def test_fixed_segments_match_and_sidecar_words_choose_the_exact_range(channel, monkeypatch):
    seed(channel)
    take = media(channel)
    take.with_suffix(".json").write_text(json.dumps([{"w": word, "s": 2 + i, "e": 2.5 + i}
                                                     for i, word in enumerate(SCRIPT.split())]), encoding="utf-8")
    monkeypatch.setattr(pipeline, "_transcript", lambda *a, **k: [{"s": 0, "e": 100, "text": SCRIPT}])
    assert watch.run(channel["slug"], now=NOW)["started"] == 1
    project = Path(rows(channel)[0]["project"])
    moment = pipeline.load_moments(project)["moments"][0]
    assert moment["start"] == 2 and moment["end"] == len(SCRIPT.split()) + 1.5


def test_unmatched_take_uses_first_twelve_words_and_no_peg(channel, monkeypatch):
    path, _ = seed(channel)
    media(channel)
    text = "Northern mountains gather heavy rainfall across autumn months before colder winter weather arrives."
    transcribe(monkeypatch, text)
    assert watch.run(channel["slug"], now=NOW)["started"] == 1
    row, = rows(channel)
    project = Path(row["project"])
    moment, = pipeline.load_moments(project)["moments"]
    assert moment["hook"] == " ".join(text.split()[:12]) and moment["series"] is None
    assert pipeline._read(project / "factory.json")["news"] is None
    assert row["series"] is None and "brief" not in row
    assert pipeline._read(path)["items"][0]["status"] == "open"


def test_match_uses_content_share_newest_ties_and_only_open_recent_items(channel, monkeypatch):
    old, _ = seed(channel, day="2026-10-23")
    yesterday, _ = seed(channel, day="2026-11-05")
    current, _ = seed(channel)
    seed(channel, status="recorded", hook="Already recorded")
    seed(channel, day="2026-11-07", hook="Future")
    media(channel)
    transcribe(monkeypatch)
    assert watch.run(channel["slug"], now=NOW)["started"] == 1
    assert rows(channel)[0]["brief"] == "2026-11-06" and rows(channel)[0]["item"] == 1
    assert pipeline._read(current)["items"][0]["status"] == "recorded"
    assert pipeline._read(yesterday)["items"][0]["status"] == pipeline._read(old)["items"][0]["status"] == "open"


def test_recording_an_older_brief_keeps_todays_latest_page(channel, monkeypatch):
    previous, _ = seed(channel, day="2026-11-05")
    today, _ = seed(channel, script="Northern mountains receive heavy rainfall during winter storms.")
    brief._page(today.parent, channel, pipeline._read(today))
    latest = today.parent.parent / "latest.html"
    before = latest.read_bytes()
    media(channel)
    transcribe(monkeypatch)
    assert watch.run(channel["slug"], now=NOW)["started"] == 1
    assert rows(channel)[0]["brief"] == "2026-11-05"
    assert "Recorded" in (previous.parent / "brief.html").read_text(encoding="utf-8")
    assert latest.read_bytes() == before


@pytest.mark.parametrize("n,match", [(6, False), (7, True)])
def test_match_threshold_ignores_stop_words_and_repetition(channel, n, match):
    words = "amber berry cedar delta ember field green honey ivory jewel lemon maple north ocean pearl quiet river stone tiger union".split()
    seed(channel, script=" ".join(words) + " their these then have with")
    text = " ".join(words[:n]).upper() + " WITH THEIR " + words[0] * 2
    assert (brief.match(channel["slug"], text, NOW) is not None) is match


def test_old_and_empty_scripts_do_not_match(channel):
    seed(channel, day="2026-10-23")
    seed(channel, script=None)
    seed(channel, script="this that then with")
    assert brief.match(channel["slug"], SCRIPT, NOW) is None
    seed(channel, day="2026-10-24")
    assert brief.match(channel["slug"], SCRIPT, NOW)[0] == "2026-10-24"


@pytest.mark.parametrize("seconds", [2.99, 180.01])
def test_bad_duration_is_logged_without_starting_or_recording(channel, monkeypatch, seconds):
    path, _ = seed(channel)
    media(channel)
    transcribe(monkeypatch, end=1 + seconds)
    result = watch.run(channel["slug"], now=NOW)
    assert result["started"] == 0 and "a clip runs" in result["errors"][0]
    row, = rows(channel)
    assert "project" not in row and "a clip runs" in row["error"]
    assert not list((registry.directory(channel["slug"]) / "projects").iterdir())
    assert pipeline._read(path)["items"][0]["status"] == "open"
    assert watch.run(channel["slug"], now=NOW)["started"] == 0


@pytest.mark.parametrize("seconds", [3, 180])
def test_hand_duration_bounds_are_inclusive(channel, monkeypatch, seconds):
    media(channel)
    monkeypatch.setattr(pipeline, "_transcript", lambda *a, **k: [{"s": 0, "e": seconds, "text": SCRIPT}])
    assert watch.run(channel["slug"], now=NOW)["started"] == 1


def test_transcription_failure_leaves_no_project_and_retries(channel, monkeypatch):
    media(channel)

    def fail(*a, **k):
        raise RuntimeError("speech unavailable")
    monkeypatch.setattr(source, "transcribe_episode", fail)
    result = watch.run(channel["slug"], now=NOW)
    assert result["started"] == 0 and "speech unavailable" in result["errors"][0]
    assert rows(channel)[0]["error"] == "speech unavailable" and "project" not in rows(channel)[0]
    transcribe(monkeypatch)
    result = watch.run(channel["slug"], now=NOW)
    assert result == {"found": 0, "started": 1, "errors": []}
    assert "error" not in rows(channel)[0]


def test_empty_transcript_is_a_source_error(channel, monkeypatch):
    media(channel)
    monkeypatch.setattr(pipeline, "_transcript", lambda *a, **k: [])
    result = watch.run(channel["slug"], now=NOW)
    assert result["started"] == 0 and "no spoken words" in rows(channel)[0]["error"]


def test_invalid_peg_link_uses_factory_validation(channel, monkeypatch):
    path, _ = seed(channel, facts={"url": "file:///private"})
    media(channel)
    transcribe(monkeypatch)
    result = watch.run(channel["slug"], now=NOW)
    assert result["started"] == 0 and "news links must be web addresses" in result["errors"][0]
    assert pipeline._read(path)["items"][0]["status"] == "open"


def test_recovery_after_project_move_keeps_one_clip_and_brief_link(channel, monkeypatch):
    path, _ = seed(channel)
    take = media(channel)
    take.with_suffix(".info.json").write_text(json.dumps({"webpage_url": "file:///private/take.mp4"}), encoding="utf-8")
    calls, _ = transcribe(monkeypatch)
    recorded = brief.recorded

    def fail(*a):
        raise OSError("brief write interrupted")
    monkeypatch.setattr(brief, "recorded", fail)
    assert watch.run(channel["slug"], now=NOW)["started"] == 0
    assert "project" not in rows(channel)[0]
    monkeypatch.setattr(brief, "recorded", recorded)
    assert watch.run(channel["slug"], now=NOW) == {"found": 0, "started": 0, "errors": []}
    row, = rows(channel)
    assert row["series"] == "breakdowns" and row["brief"] == "2026-11-06"
    project = Path(row["project"])
    assert len(calls) == len(pipeline.load_moments(project)["moments"]) == 1
    assert pipeline._read(project / "source.json")["url"] == ""
    assert pipeline._read(path)["items"][0]["project"] == str(project)


def test_pause_after_transcription_does_not_start_or_record(channel, monkeypatch):
    path, _ = seed(channel)
    media(channel)

    def pause(*a, **k):
        (registry.directory(channel["slug"]) / "PAUSE").touch()
        return [{"s": 0, "e": 30, "text": SCRIPT}]
    monkeypatch.setattr(pipeline, "_transcript", pause)
    result = watch.run(channel["slug"], now=NOW)
    assert result["started"] == 0 and not result["errors"]
    assert "project" not in rows(channel)[0]
    assert pipeline._read(path)["items"][0]["status"] == "open"


def test_tick_continues_after_failed_take_and_does_not_advance_it(channel, monkeypatch):
    media(channel, "bad.mp4")
    media(channel, "good.mp4")
    _, words = transcribe(monkeypatch)

    def run(media, model, **kwargs):
        if media.stem == "bad":
            raise RuntimeError("bad take")
        return words
    monkeypatch.setattr(source, "transcribe_episode", run)
    channel["handles"] = {}
    registry.save(channel)
    advanced = []
    result = tick.run([channel["slug"]], now=NOW,
                      runner=lambda project, *a, **k: advanced.append(project) or {})["channels"][channel["slug"]]
    assert result["found"] == 2 and result["started"] == result["advanced"] == 1
    assert "good" in advanced[0].name and "bad take" in result["errors"][0]
    assert (registry.directory(channel["slug"]) / "kits" / "index.html").is_file()


def test_series_reaches_arms_queue_outcomes_and_learn_without_bandit_choices(channel, monkeypatch):
    seed(channel)
    media(channel)
    transcribe(monkeypatch)
    watch.run(channel["slug"], now=NOW)
    project = Path(rows(channel)[0]["project"])
    d = project / "clip01"
    pipeline._write(d / "words.json", {"words": [{"w": "Story", "os": 0, "oe": 34.55}]})
    pipeline._write(d / "plan.json", {"hook": "Story", "shots": [{"from": 0, "layout": "solo"}]})
    pipeline._write(d / "post.json", {"youtube_title": "A story"})
    pipeline._write(d / "context.json", {"flags": []})
    pipeline._write(project / "ratings.json", {"clip01": {"v": "post"}})
    (d / "clip.mp4").write_bytes(b"video")
    cfg = pipeline._read(project / "factory.json")
    moment = pipeline.load_moments(project)["moments"][0]
    arms = pipeline._arms(d, moment, cfg, {})
    plain = pipeline._arms(d, {**moment, "series": None}, cfg, {})
    assert arms == {**plain, "series": "breakdowns"} and "series" not in plain
    pipeline._write(d / "arms.json", arms)
    assert queue.build(channel["slug"], NOW)["added"] == 1
    queued, = queue.read(channel["slug"])
    assert queued["arms"]["series"] == "breakdowns" and queued["own"]
    assert set(queued["arms"]) == set(arms)
    video = {"id": "abcdefghijk", "channel_id": UC, "title": "A story", "short": True,
             "published": (NOW - timedelta(days=1)).isoformat(), "views": 500}
    monkeypatch.setattr(feeds, "feed", lambda *a, **k: [video])
    assert outcomes.track(channel["slug"], now=NOW)["matched"] == 1
    measured, = outcomes.read(channel["slug"])
    assert measured["arms"]["series"] == "breakdowns" and measured["views_24h"] == 500
    outcomes.write(channel["slug"], [{**measured, "id": f"episode/clip{i:02d}", "reward": reward}
                                     for i, reward in enumerate((1, 3, 2), 1)] + [
                                         {**measured, "id": "masked/clip01", "reward": 100, "masked": True}])
    report = learn.learn(channel["slug"])
    assert "Series breakdowns had 3 posts with median reward 2.00." in report["summary"]
    assert "series" not in report["dimensions"] and "series" not in bandit.DIMENSIONS
