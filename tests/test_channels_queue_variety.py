"""Queue look-ahead through slots blocked by variety."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from myzing.channels import bandit, queue, registry
from myzing.factory import pipeline

from test_channels_queue import NOW, channel, episode


def history(channel):
    root = registry.directory(channel["slug"]) / "projects"
    return [{"id": f"old{i}/clip01", "project": str(root / f"old{i}"), "clip": "clip01", "status": "posted",
             "slot": (NOW - timedelta(days=10 - i)).isoformat(), "queued_at": (NOW - timedelta(days=10 - i)).isoformat(),
             "arms": {"archetype": "confession" if i < 5 else "funny"}} for i in range(10)]


def candidates(channel):
    for name, archetype in (("a", "confession"), ("b", "funny")):
        project = episode(channel, name)
        pipeline._write(project / "clip01" / "arms.json", {"archetype": archetype})


def test_variety_block_reaches_a_later_slot_and_clears_old_blockers(channel):
    candidates(channel)
    project = episode(channel, "c", n=4)
    pipeline._write(project / "clip04" / "arms.json", {"archetype": "other"})
    rows = history(channel)
    for i, row in enumerate(rows[6:9], 1):
        row.update(id=f"c/clip{i:02d}", project=str(project.resolve()), clip=f"clip{i:02d}")
    rows[-1].update(slot="2026-11-05T17:00:00-08:00", status="queued")
    queue.write(channel["slug"], rows)
    first = next(queue.slots(channel, rows, NOW))
    assert not queue._episode_ok(str(project.resolve()), first, rows)
    assert not bandit.allowed("archetype", ["confession", "funny"], rows)

    result = queue.build(channel["slug"], NOW, rng=random.Random(0))

    assert result["added"] == 3 and result["blocked"] == {}
    assert [(r["id"], r["slot"]) for r in queue.read(channel["slug"])[10:]] == [
        ("c/clip04", "2026-11-05T20:00:00-08:00"),
        ("a/clip01", "2026-11-06T12:00:00-08:00"),
        ("b/clip01", "2026-11-06T17:00:00-08:00")]


def test_only_variety_blocked_candidates_stop_after_48_slots(channel, monkeypatch):
    candidates(channel)
    queue.write(channel["slug"], history(channel))
    path = registry.directory(channel["slug"]) / "queue.jsonl"
    before = path.read_bytes()
    allowed, calls = bandit.allowed, []

    def check(dimension, candidates, rows):
        calls.append(list(candidates))
        assert len(calls) <= 48
        return allowed(dimension, candidates, rows)

    monkeypatch.setattr(bandit, "allowed", check)
    result = queue.build(channel["slug"], NOW)

    assert result["added"] == 0
    assert result["blocked"] == {f"{name}/clip01": ["Waiting for another archetype under the variety rule."]
                                 for name in ("a", "b")}
    assert calls == [["confession", "funny"]] * 48
    assert path.read_bytes() == before


def test_lookahead_resets_after_adding_a_row(channel):
    channel["seeding"]["every"] = 48
    registry.save(channel)
    episode(channel, n=3, source="mine")

    result = queue.build(channel["slug"], NOW)

    assert result["added"] == 3 and result["blocked"] == {}
    slots = queue.slots(channel, [], NOW)
    positions = {next(slots).isoformat(): i for i in range(97)}
    assert [positions[r["slot"]] for r in queue.read(channel["slug"])] == [0, 48, 96]


def test_failed_candidate_keeps_the_last_slot_for_the_next_clip(channel, monkeypatch):
    channel["seeding"]["every"] = 48
    registry.save(channel)
    episode(channel, "a", n=2, source="mine")
    episode(channel, "b", source="mine")
    title = queue._title

    def fail(row, *args):
        if row["id"] == "a/clip02":
            raise ValueError("bad title")
        return title(row, *args)

    monkeypatch.setattr(queue, "_title", fail)
    result = queue.build(channel["slug"], NOW)

    assert result["added"] == 2
    assert result["blocked"] == {"a/clip02": ["bad title"]}
    slots = queue.slots(channel, [], NOW)
    positions = {next(slots).isoformat(): i for i in range(49)}
    assert [(r["id"], positions[r["slot"]]) for r in queue.read(channel["slug"])] == [
        ("a/clip01", 0), ("b/clip01", 48)]


def test_episode_block_stops_after_the_last_queued_slot(channel, monkeypatch):
    episode(channel, n=4)
    episode_ok, calls = queue._episode_ok, []

    def check(project, slot, rows):
        calls.append(slot)
        return episode_ok(project, slot, rows)

    monkeypatch.setattr(queue, "_episode_ok", check)
    result = queue.build(channel["slug"], NOW)

    assert result["added"] == 3
    assert result["blocked"] == {"episode/clip04": ["Waiting for another episode after three clips in a row."]}
    assert len(set(calls)) == 4


def test_normal_build_keeps_existing_slots_order_and_propensities(channel):
    channel["cadence"]["per_day"] = 2
    registry.save(channel)
    episode(channel, "a", n=3)
    episode(channel, "b", n=3)

    result = queue.build(channel["slug"], NOW, rng=random.Random(0))

    assert result["added"] == 6 and result["blocked"] == {}
    rows = queue.read(channel["slug"])
    assert [(r["id"], r["slot"]) for r in rows] == [
        ("a/clip01", "2026-11-05T12:00:00-08:00"),
        ("a/clip02", "2026-11-05T17:00:00-08:00"),
        ("a/clip03", "2026-11-06T12:00:00-08:00"),
        ("b/clip01", "2026-11-06T17:00:00-08:00"),
        ("b/clip02", "2026-11-07T12:00:00-08:00"),
        ("b/clip03", "2026-11-07T17:00:00-08:00")]
    assert all(r["order_propensity"] == 1 and r["order_policy"] == "bandit" for r in rows)
    assert all(r["arms"]["hour"] == datetime.fromisoformat(r["slot"]).hour for r in rows)
