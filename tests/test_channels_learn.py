"""Channel experiments with local snapshots and fake judges."""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from myzing.channels import bandit, command, learn, outcomes, queue, registry
from myzing.factory import judge, pipeline, postcopy, render, scout, source
from myzing.factory.tools import data_path
from myzing.playbook import feeds, watch
from myzing.playbook.common import append_jsonl

NOW = datetime(2026, 11, 5, 18, tzinfo=timezone.utc)
CHANNEL_ID = "UC" + "a" * 22
VIDEO = "abcdefghijk"


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(feeds, "request", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda *a, **kw: [])


@pytest.fixture
def channel():
    return registry.create("Stories", "Player stories", handles={"youtube": "@stories"},
                           cadence={"timezone": "UTC-08:00"})


def episode(channel, name="episode", archetypes=("confession",), title="A story"):
    project = registry.directory(channel["slug"]) / "projects" / name
    pipeline._write(project / "factory.json", {**pipeline.SETTINGS, "channel": channel["slug"],
                                              "rights": "own", "shapes": ["9x16"]})
    pipeline._write(project / "source.json", {"name": "Show"})
    moments = [{"hook": f"Hook {i}", "start": 0, "end": 30, "archetype": a} for i, a in enumerate(archetypes)]
    pipeline._write(project / "moments.json", {"scouted": True, "moments": moments})
    pipeline._write(project / "ratings.json", {f"clip{i:02d}": {"v": "post"} for i in range(1, len(moments) + 1)})
    for i, moment in enumerate(moments, 1):
        d = project / f"clip{i:02d}"
        pipeline._write(d / "post.json", {key: title for key in postcopy.FIELDS})
        pipeline._write(d / "plan.json", {"hook": moment["hook"], "shots": [{"from": 0, "layout": "solo"}]})
        pipeline._write(d / "cams.json", {})
        pipeline._write(d / "words.json", {"start": 0, "duration": 30, "words": [{"w": "Story.", "os": 0, "oe": 29.55}]})
        pipeline._arms(d, moment, pipeline._read(project / "factory.json"), {})
        (d / "clip.mp4").write_bytes(b"placeholder")
    return project


def row(i, reward=None, **values):
    return {"schema_version": 1, "id": f"episode/clip{i + 1:02d}", "channel": "stories", "platform": "youtube",
            "video_id": f"{i:011d}", "posted_at": (NOW + timedelta(days=i)).isoformat(),
            "reward": reward, "masked": False, "arms": {"archetype": "confession"}, **values}


def feed(videos):
    entries = []
    for ident, title, published, views in videos:
        entries.append(f'<entry><yt:videoId>{ident}</yt:videoId><title>{escape(title)}</title>'
                       f'<published>{published.isoformat()}</published><link href="https://www.youtube.com/shorts/{ident}"/>'
                       f'<media:group><media:community><media:statistics views="{views}"/></media:community></media:group></entry>')
    return ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
            'xmlns:media="http://search.yahoo.com/mrss/">' + "".join(entries) + '</feed>')


@pytest.mark.parametrize("archetype", [*scout.ARCHETYPES, None, "wrong", [], {}])
def test_scout_accepts_old_answers_and_only_keeps_known_archetypes(archetype):
    moment = {"start": 1, "end": 31, "hook": "Story"}
    if archetype is not None:
        moment["archetype"] = archetype
    got = scout.check({"moments": [moment]})[0]
    assert got["archetype"] == (archetype if archetype in scout.ARCHETYPES else "other")


def test_copy_titles_are_optional_and_invalid_options_drop():
    answer = {key: "Story" for key in postcopy.FIELDS}
    args = ({"start": 0}, {})
    assert "title_options" not in postcopy.finalize(answer, *args)
    good = [{"text": "Ada Lovelace wrote the program", "pattern": "name_claim"},
            {"text": "Why it worked", "pattern": "how_why"}]
    bad = [None, "title", {}, {"text": "", "pattern": "quote"}, {"text": "x", "pattern": "bad"},
           {"text": 5, "pattern": "question"}, {"text": "x", "pattern": []},
           {"text": "x" * 61, "pattern": "superlative"}, {"text": "two\nlines", "pattern": "quote"}]
    assert postcopy.finalize({**answer, "titles": good + bad}, *args)["title_options"] == good
    assert "title_options" not in postcopy.finalize({**answer, "titles": {}}, *args)
    with pytest.raises(ValueError, match="youtube_title"):
        postcopy.finalize({k: v for k, v in answer.items() if k != "youtube_title"}, *args)


@pytest.mark.parametrize("mode", ["context", "launch"])
def test_prompts_request_closed_arms(mode):
    text = scout.prompt([], 2, mode)
    assert all(a in text for a in scout.ARCHETYPES) and '"archetype"' in text
    text = postcopy.prompt({"hook": "Story"}, {"words": []}, {}, mode)
    assert all(p in text for p in postcopy.PATTERNS) and '"titles"' in text


@pytest.mark.parametrize("belongs", [False, True])
def test_pipeline_selects_title_once_and_records_arms(channel, monkeypatch, belongs):
    project = episode(channel)
    d = project / "clip01"
    (d / "post.json").unlink()
    pipeline._write(project / "brief.json", {"tags": ["#ad"]})
    cfg = pipeline._read(project / "factory.json")
    cfg["channel"] = channel["slug"] if belongs else None
    original = postcopy.choose
    monkeypatch.setattr(postcopy, "choose", lambda post, slug: original(post, slug, random.Random(31)))
    monkeypatch.setattr(render, "render", lambda *a: None)
    monkeypatch.setattr(pipeline, "_context", lambda *a: None)

    class Copy:
        calls = 0

        def ask(self, task, text, images=()):
            if task.endswith("copy"):
                self.calls += 1
                return {**{k: "Original" for k in postcopy.FIELDS}, "titles": [
                    {"text": "Ada Lovelace wrote it", "pattern": "name_claim"},
                    {"text": "How it worked", "pattern": "how_why"}]}
            return {"hook": "Story", "shots": [{"from": 0, "layout": "solo"}]}

    ask = Copy()
    moment = pipeline.load_moments(project)["moments"][0]
    pipeline._clip(project, 1, moment, ask, project / "media.mp4", cfg, [], lambda m: None)
    post = pipeline._read(d / "post.json")
    assert post["youtube_title"] == ("Ada Lovelace wrote it #ad" if belongs else "Original #ad")
    if belongs:
        assert post["title_pattern"] == "name_claim" and post["title_policy"] == "baseline"
        assert .1 < post["title_propensity"] < 1
        assert post["title_candidates"] == ["name_claim", "how_why"]
    else:
        assert "title_propensity" not in post
    arms = pipeline._read(d / "arms.json")
    assert arms["archetype"] == "confession" and arms["length"] == "mid" and arms["density"] == "light"
    assert arms["pack"] == "zing" and arms["hour"] is None
    assert arms["title_propensity"] == post.get("title_propensity") and arms["title_policy"] == post.get("title_policy")
    pipeline._clip(project, 1, moment, ask, project / "media.mp4", cfg, [], lambda m: None)
    assert ask.calls == 1 and pipeline._read(d / "post.json") == post


@pytest.mark.parametrize("seconds,bucket,graphics,density", [(28.99, "short", 0, "light"), (29, "mid", 3, "heavy"),
                                                           (45, "mid", 4, "light"), (45.01, "long", 5, "heavy"),
                                                           (30, "mid", 3, "heavy")])
def test_arms_use_render_length_and_six_graphics_per_minute(channel, seconds, bucket, graphics, density):
    d = episode(channel) / "clip01"
    pipeline._write(d / "words.json", {"words": [{"w": "Story.", "os": 0, "oe": seconds - .45}]})
    pipeline._write(d / "plan.json", {"shots": [{"from": i, "layout": "graphic"} for i in range(graphics)]})
    arms = pipeline._arms(d, {}, {"pack": "swiss"}, {})
    assert (arms["length"], arms["density"], arms["pack"], arms["archetype"]) == (bucket, density, "swiss", "other")


def test_track_matches_ids_before_titles_and_uses_feed_publication(channel):
    episode(channel, "id", title="Renamed")
    episode(channel, "title", title="  Big   Story 🔥 ")
    episode(channel, "emoji", title="Big Story")
    episode(channel, "skip", title="Skipped")
    slug = channel["slug"]
    queue.build(slug, NOW)
    queue.mark(slug, "id/clip01", "posted", "https://youtu.be/" + VIDEO)
    queue.mark(slug, "skip/clip01", "skipped")
    rows = queue.read(slug)
    next(r for r in rows if r["id"] == "title/clip01")["status"] = "kit"
    queue.write(slug, rows)
    requests = []

    def fetch(url):
        requests.append(url)
        return (f'<link rel="canonical" href="https://www.youtube.com/channel/{CHANNEL_ID}">' if "/@" in url else
                feed([(VIDEO, "Different title", NOW - timedelta(hours=24), 500),
                      ("lmnopqrstuv", "big story 🔥", NOW - timedelta(hours=1), 40),
                      ("skipvideo12", "Skipped", NOW - timedelta(hours=24), 999)]))

    result = outcomes.track(slug, fetch=fetch, now=NOW)
    assert result["matched"] == result["posted"] == 2 and len(requests) == 2
    got = {r["id"]: r for r in outcomes.read(slug)}
    assert got["id/clip01"]["video_id"] == VIDEO and got["id/clip01"]["views_24h"] == 500
    assert got["title/clip01"]["views_1h"] == 40 and got["title/clip01"]["views_24h"] is None
    saved = {r["id"]: r for r in queue.read(slug)}
    assert saved["title/clip01"]["posted_at"] == (NOW - timedelta(hours=1)).isoformat()
    assert saved["title/clip01"]["url"].endswith("lmnopqrstuv")
    assert saved["emoji/clip01"]["status"] == "queued" and saved["skip/clip01"]["status"] == "skipped"
    outcomes.track(slug, fetch=fetch, now=NOW)
    assert len(outcomes.read(slug)) == 2 and len(requests) == 3
    assert len((registry.directory(slug) / "snapshots.jsonl").read_text().splitlines()) == 6


def test_duplicate_titles_are_not_guessed_and_handle_is_required(channel):
    episode(channel, "one")
    episode(channel, "two")
    queue.build(channel["slug"], NOW)
    channel["handles"]["youtube"] = CHANNEL_ID
    registry.save(channel)
    got = outcomes.track(channel["slug"], fetch=lambda url: feed([(VIDEO, "A story", NOW, 20)]), now=NOW)
    assert got["matched"] == 0 and outcomes.read(channel["slug"]) == []
    channel["handles"]["youtube"] = ""
    registry.save(channel)
    with pytest.raises(registry.ChannelError, match="handles.youtube"):
        outcomes.track(channel["slug"])


def test_tracking_reuses_velocity_targeting_and_keeps_gaps(channel):
    episode(channel)
    slug, root = channel["slug"], registry.directory(channel["slug"])
    queue.build(slug, NOW)
    queue.mark(slug, "episode/clip01", "posted", "https://www.youtube.com/watch?v=" + VIDEO)
    snapshots = [{"channel_id": CHANNEL_ID, "channel": slug, "id": VIDEO, "title": "A story", "short": True,
                  "published": NOW.isoformat(), "at": (NOW + timedelta(hours=age)).isoformat(), "views": views}
                 for age, views in ((2.1, 10), (17.9, 100), (25, 300), (167, 900))]
    append_jsonl(root / "snapshots.jsonl", snapshots)
    expected = watch.velocity(root)["videos"][0]["views"]
    outcomes.track(slug, fetch=lambda url: f'{{"externalId":"{CHANNEL_ID}"}}' if "/@" in url else feed([]),
                   now=NOW + timedelta(days=8))
    got = outcomes.read(slug)[0]
    assert {k: got[f"views_{k}"] for k in ("1h", "24h", "7d")} == {k: expected[k] for k in ("1h", "24h", "7d")}
    assert (got["views_1h"], got["views_24h"], got["views_7d"]) == (None, 300, 900)
    assert got["reward"] is None and got["reward_basis"] == "7d"


@pytest.mark.parametrize("content", ["Content", "VIDEO"])
def test_studio_csv_merges_without_turning_totals_into_age_views(channel, tmp_path, content):
    slug = channel["slug"]
    saved = row(0, 1, views_24h=500, video_id=VIDEO)
    outcomes.write(slug, [saved])
    path = tmp_path / "Table data.csv"
    path.write_text(f'{content},vIeWs,Average Percentage Viewed,Subscribers,Unused\n'
                    f'{VIDEO},"12,345",125.6%,8,x\nunknown,300,40,1,x\n', encoding="utf-8-sig")
    assert outcomes.metrics(slug, path) == {"matched": 1, "unmatched": 1}
    got = outcomes.read(slug)[0]
    assert (got["studio_views"], got["avg_view_pct"], got["subs"]) == (12345, 125.6, 8)
    assert got["views_24h"] == 500 and got["reward"] == 1
    path.write_text("Content,Views\n", encoding="utf-8")
    with pytest.raises(registry.ChannelError, match="CSV needs"):
        outcomes.metrics(slug, path)
    assert outcomes.read(slug)[0] == got


def test_rewards_choose_seven_days_and_wait_for_five_values():
    rows = [row(i, views_24h=100 + i * 100) for i in range(4)]
    assert all(r["reward"] is None for r in outcomes.rewards(rows))
    rows.append(row(4, views_24h=1000, views_7d=2000))
    outcomes.rewards(rows)
    assert rows[0]["reward"] == pytest.approx(math.log2(150 / 350))
    assert rows[4]["reward_basis"] == "7d" and rows[4]["reward"] is None
    for i, r in enumerate(rows):
        r["views_7d"] = 1000 + i * 1000
    outcomes.rewards(rows)
    assert rows[4]["reward"] == pytest.approx(math.log2(5050 / 3050))
    assert rows[0]["channel_median_24h"] == 300 and rows[0]["channel_median_7d"] == 3000
    recent = [row(i, views_24h=100 if i >= 5 else 100000) for i in range(35)]
    outcomes.rewards(list(reversed(recent)))
    assert recent[-1]["channel_median_24h"] == 100
    assert outcomes.rewards([row(0, views_1h=10)])[0]["reward_basis"] is None


def test_reach_drop_masks_only_last_five_and_persists():
    rows = [row(i, views_24h=1000 if i < 30 else 100) for i in range(35)]
    outcomes.rewards(rows)
    assert [r["masked"] for r in rows] == [False] * 30 + [True] * 5
    rows.append(row(35, views_24h=1000))
    outcomes.rewards(rows)
    assert all(r["masked"] for r in rows[30:35]) and not rows[-1]["masked"]
    for value in (200, None):
        fresh = [row(i, views_24h=1000 if i < 30 else 100) for i in range(35)]
        fresh[-1]["views_24h"] = value
        assert not any(r["masked"] for r in outcomes.rewards(fresh))


def test_variety_and_policy_probabilities():
    rows = [row(i, 20, arms={"archetype": "confession"}, status="kit") for i in range(5)]
    assert bandit.choose("archetype", ["confession", "funny"], rows, random.Random(0))[:2] == ("funny", 1)
    assert bandit.choose("archetype", ["confession"], rows, random.Random(0))[:2] == ("confession", 1)
    assert bandit.allowed("archetype", ["confession", "funny"], [{**r, "status": "skipped"} for r in rows]) == ["confession", "funny"]
    rows += [row(i + 5, 0, arms={"archetype": "funny"}) for i in range(5)]
    with pytest.raises(ValueError, match="variety"):
        bandit.choose("archetype", ["confession", "funny"], rows, random.Random(0))
    rows += [row(i + 10, 0, arms={"archetype": "other"}) for i in range(10)]
    assert bandit.allowed("archetype", ["confession", "funny"], rows) == ["confession", "funny"]
    stats = {"name_claim": {"posterior_mean": 20, "posterior_sd": .001},
             "question": {"posterior_mean": -20, "posterior_sd": .001}}
    assert bandit.probabilities(stats, "name_claim") == pytest.approx({"name_claim": .925, "question": .075})
    probabilities, policies = {}, Counter()
    for seed in range(300):
        value, probability, policy = bandit.choose("title_pattern", ["name_claim", "question", "quote"], [],
                                                  random.Random(seed), baseline="name_claim")
        assert value not in probabilities or probabilities[value] == probability
        probabilities[value] = probability
        policies[policy] += 1
    assert sum(probabilities.values()) == pytest.approx(1) and min(probabilities.values()) >= .15 / 3
    assert set(policies) == {"baseline", "explore", "bandit"}
    assert bandit.choose("title_pattern", ["quote"], [], random.Random(31), baseline="name_claim")[2] == "explore"


def test_prior_maps_minimum_lift_and_masked_rewards_do_not_count(channel):
    prior = {"schema_version": 1, "guidance": ["Try names from the clip."], "lifts": [
        {"feature": "has_name", "lift": 8, "weak": False}, {"feature": "past_tense", "lift": 2, "weak": False},
        {"feature": "has_question", "lift": 10, "weak": True}, {"feature": "has_quote", "lift": 0, "weak": False},
        {"feature": "superlative", "lift": 100, "weak": False}]}
    pipeline._write(registry.directory(channel["slug"]) / "PRIOR.json", prior)
    channel["prior"] = "PRIOR.json"
    registry.save(channel)
    assert bandit.prior(registry.load(channel["slug"])) == prior
    rows = [row(0, 100, masked=True, arms={"title_pattern": "name_claim"}),
            row(1, None, arms={"title_pattern": "name_claim"})]
    stats = bandit.posterior("title_pattern", postcopy.PATTERNS, rows, prior)
    assert stats["name_claim"] == {"n": 0, "mean_reward": None, "posterior_mean": .5, "posterior_sd": math.sqrt(.5)}
    assert stats["question"]["posterior_mean"] == 0 and stats["quote"]["posterior_mean"] == -1
    assert stats["superlative"]["posterior_mean"] == 1
    rows.append(row(2, 2, arms={"title_pattern": "name_claim"}))
    assert bandit.posterior("title_pattern", ["name_claim"], rows, prior)["name_claim"]["posterior_mean"] == 1
    channel["prior"] = "missing.json"
    with pytest.raises(registry.ChannelError, match="prior"):
        bandit.prior(channel)


def test_queue_samples_archetype_and_keeps_fifo_within_it(channel, monkeypatch):
    episode(channel, "a", ("confession", "funny", "funny"))
    episode(channel, "b", ("confession",))
    calls = []

    def choose(dimension, candidates, rows, rng, **kwargs):
        calls.append((dimension, list(candidates)))
        return ("funny" if "funny" in candidates else candidates[0], .4, "explore")
    monkeypatch.setattr(bandit, "choose", choose)
    assert queue.build(channel["slug"], NOW, rng=random.Random(0))["added"] == 4
    rows = queue.read(channel["slug"])
    assert [r["id"] for r in rows] == ["a/clip02", "a/clip03", "a/clip01", "b/clip01"]
    assert all(r["order_propensity"] == .4 and r["order_policy"] == "explore" for r in rows)
    assert all(dimension == "archetype" for dimension, _ in calls)
    for r in rows:
        assert r["arms"]["hour"] == datetime.fromisoformat(r["slot"]).hour
        assert pipeline._read(Path(r["project"]) / r["clip"] / "arms.json") == r["arms"]
    outcomes.write(channel["slug"], [{**row(0, 2), "id": rows[0]["id"], "arms": rows[0]["arms"]}])
    assert len(bandit.history(channel["slug"])) == 4


def test_learn_reports_a_clear_winner_and_ips_needs_twenty(channel):
    rows = [row(i, 2 if i < 12 else -1, arms={"archetype": "confession" if i < 12 else "funny"}) for i in range(24)]
    rows.append(row(24, 100, masked=True, arms={"archetype": "funny"}))
    outcomes.write(channel["slug"], rows)
    result = learn.learn(channel["slug"])
    stats = result["dimensions"]["archetype"]
    assert stats["confession"]["n"] == 12 and stats["confession"]["mean_reward"] == 2
    assert stats["confession"]["posterior_mean"] == pytest.approx(24 / 14)
    assert stats["confession"]["probability_best"] > .9
    assert stats["funny"]["n"] == 12 and stats["funny"]["mean_reward"] == -1
    assert any("confession clips averaged about 4.0x" in s and "12 posts" in s for s in result["summary"])
    assert "Fewer than 20" in result["ips"]["reason"]
    assert pipeline._read(registry.directory(channel["slug"]) / "learned.json") == result
    logged = [row(i, 1 if i % 2 else 2, propensity=.5,
                  arms={"title_pattern": "name_claim" if i % 2 else "quote", "title_candidates": ["name_claim", "quote"]})
              for i in range(20)]
    assert "reason" in learn.ips(logged[:19])
    got = learn.ips(logged)
    assert got["logged_policy_mean_reward"] == 1.5 and got["baseline_ips_mean_reward"] == 1
    assert got["difference"] == .5
    assert "reason" in learn.ips([{**r, "arms": {"title_pattern": "quote"}} for r in logged])


def test_steer_uses_rewards_prior_and_newest_ties_without_changing_post_no(channel):
    episode(channel, archetypes=("confession",) * 12)
    rows = [row(i, i // 2, masked=i == 11, arms={"archetype": "confession"}) for i in range(12)]
    outcomes.write(channel["slug"], rows)
    pipeline._write(registry.directory(channel["slug"]) / "PRIOR.json",
                    {"schema_version": 1, "lifts": [], "guidance": ["Try a past-tense story."]})
    channel["prior"] = "PRIOR.json"
    registry.save(channel)
    taste = [{"v": "no", "hook": "Slow", "why": "Too long"}]
    before = scout.steer("Stories", taste)
    after = scout.steer("Stories", taste, channel["slug"])
    assert after.startswith(before + "WHAT WORKED ON THIS CHANNEL\n")
    assert "Try a past-tense story." in after and "Hook 11 |" not in after
    assert after.count("| confession |") == 10
    assert after.index("Hook 9 |") < after.index("Hook 8 |")
    assert "about 32.0x the channel's typical views" in after
    for mode, filename in (("context", "scout.md"), ("launch", "scout-launch.md")):
        expected = data_path("prompts", filename).read_text(encoding="utf-8")
        expected = (expected.replace("{LENGTH}", scout.length_rule({}, mode)).replace("{BRIEF}", "")
                    .replace("{N}", "2").replace("{STEER}", before).replace("{TRANSCRIPT}", "[0.0-1.0] Story"))
        assert scout.prompt([{"s": 0, "e": 1, "text": "Story"}], 2, mode, focus="Stories", taste=taste).encode() == expected.encode()


def test_pipeline_scout_gets_channel_results(channel):
    project = episode(channel)
    (project / "moments.json").unlink()
    pipeline._write(project / "transcript.json", [{"s": 0, "e": 40, "text": "Story"}])

    class Scout:
        def ask(self, task, text, images=()):
            assert "WHAT WORKED ON THIS CHANNEL" in text
            return {"moments": [{"hook": "Story", "start": 0, "end": 30}]}

    cfg = pipeline._read(project / "factory.json")
    assert pipeline._moments(project, Scout(), project / "media.mp4", cfg, lambda m: None)[0]["archetype"] == "other"


def test_cli_routes_tracking_metrics_and_learning(channel, tmp_path, monkeypatch, capsys):
    slug = channel["slug"]
    monkeypatch.setattr(outcomes, "track", lambda value: {"channel": value, "masked": ["episode/clip01"]})
    assert command.run(["track", slug]) == 0
    assert json.loads(capsys.readouterr().out)["channel"] == slug
    path = tmp_path / "metrics.csv"
    path.write_text("Content,Views,Average percentage viewed,Subscribers\nunknown,1,2,3\n", encoding="utf-8")
    assert command.run(["metrics", slug, "--csv", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"matched": 0, "unmatched": 1}
    assert command.run(["learn", slug]) == 0
    assert json.loads(capsys.readouterr().out)["summary"] == ["No unmasked rewards yet. Track more posted clips."]


def test_tracking_preserves_studio_metrics_and_reports_masked_rows(channel, tmp_path):
    slug, root = channel["slug"], registry.directory(channel["slug"])
    channel["handles"]["youtube"] = CHANNEL_ID
    registry.save(channel)
    project = episode(channel, archetypes=("confession",) * 35)
    arms = {"archetype": "confession", "title_pattern": "name_claim", "title_propensity": .4,
            "title_policy": "bandit", "title_candidates": ["name_claim", "quote"], "hour": 12}
    rows, snapshots = [], []
    for i in range(35):
        published = NOW - timedelta(days=36 - i)
        ident = f"{i:011d}"
        rows.append({"id": f"episode/clip{i + 1:02d}", "project": str(project), "clip": f"clip{i + 1:02d}",
                     "status": "posted", "video_id": ident, "url": f"https://youtu.be/{ident}",
                     "slot": published.isoformat(), "posted_at": published.isoformat(), "arms": arms})
        snapshots.append({"at": (published + timedelta(days=1)).isoformat(), "published": published.isoformat(),
                          "channel_id": CHANNEL_ID, "channel": slug, "id": ident, "title": "A story",
                          "short": True, "views": 1000 if i < 30 else 100})
    queue.write(slug, rows)
    append_jsonl(root / "snapshots.jsonl", snapshots)
    result = outcomes.track(slug, fetch=lambda url: feed([]), now=NOW)
    assert result["masked"] == [r["id"] for r in rows[-5:]]
    assert "reach drop" in result["summary"][0]
    measured = outcomes.read(slug)
    required = {"schema_version", "id", "channel", "platform", "video_id", "url", "posted_at", "arms",
                "propensity", "policy", "views_1h", "views_24h", "views_7d", "avg_view_pct", "subs",
                "channel_median_24h", "channel_median_7d", "reward", "reward_basis", "masked", "updated_at"}
    assert all(required <= r.keys() for r in measured)
    assert all(r["propensity"] == .4 and r["policy"] == "bandit" and r["arms"] == arms for r in measured)
    path = tmp_path / "studio.csv"
    path.write_text("Content,Views,Average percentage viewed,Subscribers\n00000000000,2000,88,3\n", encoding="utf-8")
    outcomes.metrics(slug, path)
    outcomes.track(slug, fetch=lambda url: feed([]), now=NOW + timedelta(hours=1))
    saved = outcomes.read(slug)[0]
    assert (saved["studio_views"], saved["avg_view_pct"], saved["subs"], saved["views_24h"]) == (2000, 88, 3, 1000)
    assert len(outcomes.read(slug)) == 35 and not (root / "outcomes.jsonl.tmp").exists()


def test_titles_without_options_and_variety_without_choices_keep_original(channel):
    post = {"youtube_title": "Original"}
    assert postcopy.choose(post, "missing", random.Random(0)) == post
    rows = [row(i, 1, arms={"title_pattern": "name_claim" if i < 5 else "quote"}) for i in range(10)]
    outcomes.write(channel["slug"], rows)
    post["title_options"] = [{"text": "Name", "pattern": "name_claim"}, {"text": "Quote", "pattern": "quote"}]
    assert postcopy.choose(post, channel["slug"], random.Random(0)) == post


def test_atomic_outcomes_leave_previous_file_on_failed_replacement(channel, monkeypatch):
    outcomes.write(channel["slug"], [row(0, 1)])
    path = registry.directory(channel["slug"]) / "outcomes.jsonl"
    previous = path.read_bytes()

    def refuse(*args):
        raise OSError("replace failed")
    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(OSError, match="replace failed"):
        outcomes.write(channel["slug"], [row(0, 2)])
    assert path.read_bytes() == previous
