"""Optional Jev pre-ranking for the scout, with the network mocked."""
from __future__ import annotations

import json
import urllib.error

import pytest

from myzing import __version__, mcp_server
from myzing.factory import command, jev, network, pipeline
from myzing.factory.tools import FactoryError
from test_factory_transcript_sync import Answers, episode, offline, project, rendering  # noqa: F401

KEY = "test-key-123"


def segs(n=120, step=5, every=3):
    return [{"s": i * step, "e": (i + 1) * step, "text": f"seg{i}" + ("." if i % every == every - 1 else "")} for i in range(n)]


class Fake:
    def __init__(self, fail=(), levels=(2, 1, 1)):
        self.requests, self.fail, self.levels = [], list(fail), levels

    def open(self, req, timeout=None):
        self.requests.append(req)
        if self.fail:
            code = self.fail.pop(0)
            if code:
                raise urllib.error.HTTPError(req.full_url, code, "no", {}, None)
        questions = json.loads(req.data)["questions"]
        answers = {k: {"score": min(self.levels[i], len(q["criteria"]) - 1)} for i, (k, q) in enumerate(questions.items())}
        return Body(json.dumps({"answers": answers}).encode())


class Body:
    def __init__(self, data):
        self.data = data

    def read(self, *args):
        data, self.data = self.data, b""
        return data

    def close(self):
        pass


@pytest.fixture
def api(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(network.urllib.request, "build_opener", lambda *handlers: fake)
    monkeypatch.setattr(jev, "sleep", lambda s: None)
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("ZING_JEV_MODEL", raising=False)
    return fake


@pytest.fixture
def root(tmp_path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "factory.json").write_text('{"offline": false}', encoding="utf-8")
    return tmp_path / "p"


def test_windows_end_on_sentences_within_40_to_90_seconds():
    wins = jev.windows(segs())
    assert [(w["start"], w["end"]) for w in wins[:3]] == [(0, 45), (30, 75), (60, 105)]
    assert all(w["text"].endswith(".") for w in wins) and wins[0]["text"].startswith("seg0 seg1")


def test_windows_start_about_every_30_seconds():
    assert [w["start"] for w in jev.windows(segs())][:5] == [0, 30, 60, 90, 120]


def test_windows_without_a_sentence_end_stop_at_90_seconds_and_short_tails_drop():
    wins = jev.windows(segs(every=1000, n=20))
    assert wins[0]["end"] == 90 and wins[-1]["end"] - wins[-1]["start"] >= 40
    assert jev.windows(segs(n=6)) == []


def test_request_asks_three_questions_with_the_configured_model(api, root, monkeypatch):
    monkeypatch.setenv("ZING_JEV_MODEL", "other/model")
    jev.score(root, segs(n=12))
    body = json.loads(api.requests[0].data)
    assert body["model"] == "other/model" and list(body["questions"]) == ["substance", "hook", "payoff"]
    assert [len(q["criteria"]) for q in body["questions"].values()] == [4, 4, 3]
    assert body["state"].endswith("seg0 seg1 seg2. seg3 seg4 seg5. seg6 seg7 seg8.")


def test_default_model(api, root):
    jev.score(root, segs(n=12))
    assert json.loads(api.requests[0].data)["model"] == "featherless-ai/gemma-4-26B-A4B-classifier"


def test_total_weighs_the_three_questions(api, root):
    api.levels = (3, 3, 2)
    assert jev.score(root, segs(n=12))["windows"][0]["total"] == 1.0
    api.levels = (3, 0, 0)
    root2 = root.parent / "q"
    root2.mkdir()
    assert jev.score(root2, segs(n=12))["windows"][0]["total"] == .5


def test_fractional_scores_are_kept(api, root):
    api.levels = (2.56, 1.17, 1.5)                  # Jev returns the expected rubric level, not a whole number
    got = jev.score(root, segs(n=12))["windows"][0]
    assert got["scores"] == {"substance": 2.56, "hook": 1.17, "payoff": 1.5}
    assert got["total"] == round(.5 * 2.56 / 3 + .3 * 1.17 / 3 + .2 * 1.5 / 2, 3)


def test_key_present_uses_production_url_and_bearer_header(api, root, monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", KEY)
    result = jev.score(root, segs(n=12))
    req = api.requests[0]
    assert req.full_url == "https://api.featherless.ai/v1/classifier" and req.get_method() == "POST"
    assert req.get_header("Authorization") == f"Bearer {KEY}"
    assert req.get_header("User-agent") == f"myzing/{__version__} (+https://myzing.app)"
    assert result["host"] == "api.featherless.ai"


def test_typesafe_key_uses_typesafe_with_jev_latest(api, root, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key-456")
    monkeypatch.setenv("FEATHERLESS_API_KEY", KEY)
    result = jev.score(root, segs(n=12))
    req = api.requests[0]
    assert req.full_url == "https://api.typesafe.ai/v1/systemone" and req.get_header("Authorization") == "Bearer ts-key-456"
    assert json.loads(req.data)["model"] == "jev-latest" and result["host"] == "api.typesafe.ai"
    assert all(k not in p.read_text(encoding="utf-8") for p in root.rglob("*") if p.is_file() for k in ("ts-key-456", KEY))


def test_jev_key_wins_over_the_typesafe_name(api, root, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "jev-key-789")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key-456")
    jev.score(root, segs(n=12))
    assert api.requests[0].get_header("Authorization") == "Bearer jev-key-789"
    assert all("jev-key-789" not in p.read_text(encoding="utf-8") for p in root.rglob("*") if p.is_file())


def test_typesafe_model_can_be_overridden(api, root, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "ts-key-456")
    monkeypatch.setenv("ZING_JEV_MODEL", "jev-preview")
    jev.score(root, segs(n=12))
    assert json.loads(api.requests[0].data)["model"] == "jev-preview"


def test_key_absent_uses_the_demo_with_pacing_and_no_auth(api, root, monkeypatch):
    waits, now = [], [100.0]
    monkeypatch.setattr(jev, "clock", lambda: now[0])
    monkeypatch.setattr(jev, "sleep", lambda s: (waits.append(s), now.__setitem__(0, now[0] + s)))
    jev.score(root, segs(n=40))
    req = api.requests[0]
    assert req.full_url == "https://simple-jev-demo-api.featherless.ai/v1/classifier"
    assert req.get_header("Authorization") is None and len(api.requests) > 2
    assert waits and all(w >= .5 for w in waits)


def test_rate_limits_retry_with_backoff_then_succeed(api, root, monkeypatch):
    waits = []
    monkeypatch.setattr(jev, "sleep", waits.append)
    api.fail = [429, 429]
    assert jev.score(root, segs(n=12))["windows"]
    assert len(api.requests) == 3 and len(waits) >= 2 and max(waits) > min(w for w in waits if w > 0)


def test_rejected_key_fails_without_the_key(api, root, monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", KEY)
    api.fail = [401]
    with pytest.raises(FactoryError) as err:
        jev.score(root, segs(n=12))
    assert "rejected" in str(err.value) and KEY not in str(err.value) and len(api.requests) == 1


def test_missing_key_message_when_the_demo_refuses_with_403(api, root):
    api.fail = [403]
    with pytest.raises(FactoryError, match="JEV_API_KEY"):
        jev.score(root, segs(n=12))


def test_the_key_never_reaches_a_written_file_or_error(api, root, monkeypatch, caplog):
    monkeypatch.setenv("FEATHERLESS_API_KEY", KEY)
    jev.score(root, segs(n=30))
    api.fail = [401]
    (root / "answers" / "jev.json").unlink()
    with pytest.raises(FactoryError) as err:
        jev.score(root, segs(n=30))
    files = [p for p in root.rglob("*") if p.is_file()]
    assert {p.name for p in files} >= {"network.jsonl", "jev.json"} or {p.name for p in files} >= {"network.jsonl"}
    assert all(KEY not in p.read_text(encoding="utf-8") for p in files)
    assert KEY not in str(err.value) and KEY not in caplog.text and KEY not in repr(err.value)


def test_requests_are_logged_in_the_network_ledger(api, root):
    jev.score(root, segs(n=12))
    rows = [json.loads(line) for line in (root / "network.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and rows[0]["host"] == "simple-jev-demo-api.featherless.ai" and "jev" in rows[0]["purpose"]


def test_offline_projects_refuse(api, root):
    (root / "factory.json").write_text('{"offline": true}', encoding="utf-8")
    with pytest.raises(FactoryError, match="offline"):
        jev.score(root, segs(n=12))
    assert not api.requests


def test_cache_is_reused_and_redo_forgets_it(api, root):
    first = jev.score(root, segs(n=30))
    count = len(api.requests)
    saved = json.loads((root / "answers" / "jev.json").read_text(encoding="utf-8"))
    assert saved["model"] and saved["host"] and saved["at"] and saved["windows"][0]["scores"]
    assert jev.score(root, segs(n=30)) == first and len(api.requests) == count
    pipeline.redo(root, "jev")
    assert not (root / "answers" / "jev.json").exists()
    jev.score(root, segs(n=30))
    assert len(api.requests) == 2 * count


def test_a_changed_transcript_rescores(api, root):
    jev.score(root, segs(n=30))
    count = len(api.requests)
    jev.score(root, segs(n=30, step=6))
    assert len(api.requests) > count


def test_shortlist_is_the_best_non_overlapping_windows():
    ws = [{"start": 0, "end": 50, "text": "a b", "total": .9}, {"start": 30, "end": 80, "text": "c", "total": .8},
          {"start": 60, "end": 110, "text": "d", "total": .7}] + [
          {"start": 200 + 60 * i, "end": 250 + 60 * i, "text": "x", "total": .1} for i in range(20)]
    top = jev.shortlist({"windows": ws})
    assert [w["start"] for w in top[:2]] == [0, 60] and len(top) == 15
    assert all(a["end"] <= b["start"] or b["end"] <= a["start"] for i, a in enumerate(top) for b in top[i + 1:])


def test_rank_is_a_setting_and_a_cli_flag(tmp_path, episode):
    media, captions, _ = episode
    assert pipeline.SETTINGS["rank"] is None
    root = tmp_path / "cli"
    assert command.run(["new", str(root), "--media", str(media), "--transcript", str(captions), "--rank", "jev"]) == 0
    assert pipeline._read(root / "factory.json")["rank"] == "jev"


def run_project(tmp_path, episode, monkeypatch, **settings):
    root = project(tmp_path, episode, no_sync_check=True, **settings)
    rendering(monkeypatch, episode[2])
    answers = Answers()
    result = pipeline.run(root, answers, say=lambda m: None)
    return root, answers, result


def test_scout_prompt_gets_the_shortlist_when_rank_is_jev(tmp_path, episode, monkeypatch):
    def fake(project, segments, say=None):
        return {"windows": [{"start": 2000.0, "end": 2060.0, "text": "The big turn came when we lost everything today", "total": .93}]}
    monkeypatch.setattr(jev, "score", fake)
    _, answers, result = run_project(tmp_path, episode, monkeypatch, rank="jev")
    prompt = answers.prompts["scout"]
    assert "ranked these spans as the strongest standalone moments" in prompt
    assert "[2000-2060] 0.93" in prompt and "The big turn came" in prompt and result["state"] == "done"


def test_scout_prompt_has_no_block_without_rank(tmp_path, episode, monkeypatch):
    monkeypatch.setattr(jev, "score", lambda *a, **k: pytest.fail("scored without --rank jev"))
    _, answers, result = run_project(tmp_path, episode, monkeypatch)
    assert "classifier" not in answers.prompts["scout"] and "rank" not in result


def test_a_scoring_failure_runs_the_plain_scout_and_records_why(tmp_path, episode, monkeypatch):
    def broken(*args, **kwargs):
        raise FactoryError("Featherless rejected the key (401)")
    monkeypatch.setattr(jev, "score", broken)
    _, answers, result = run_project(tmp_path, episode, monkeypatch, rank="jev")
    assert "classifier" not in answers.prompts["scout"] and result["state"] == "done"
    assert result["rank"]["state"] == "failed" and "rejected the key" in result["rank"]["reason"]


def test_rank_must_be_jev_or_nothing(tmp_path, episode):
    with pytest.raises(FactoryError, match="rank"):
        project(tmp_path, episode, rank="other")


def test_factory_new_tool_takes_rank(tmp_path, episode):
    media, captions, _ = episode
    result = mcp_server.h_factory_new(str(tmp_path / "m"), str(media), transcript=str(captions), rank="jev")
    assert result["ok"] and pipeline._read(tmp_path / "m" / "factory.json")["rank"] == "jev"
