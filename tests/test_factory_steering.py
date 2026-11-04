"""Steering the factory: a focus, the show's past Post/No calls, runners-up, and clips picked or trimmed by hand."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from myzing import mcp_server
from myzing.factory import judge, pipeline, scout, source
from myzing.factory.command import _time
from myzing.factory.tools import FactoryError


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])


def project(tmp_path, name="proj", **settings) -> Path:
    media = tmp_path / "ep.mp4"
    media.write_bytes(b"\0")
    srt = tmp_path / "ep.srt"
    srt.write_text("".join(f"{i + 1}\n00:{i // 6:02d}:{i % 6 * 10:02d},000 --> 00:{i // 6:02d}:{i % 6 * 10 + 9:02d},000\n"
                           f"Line {i + 1} of the talk.\n\n" for i in range(60)), encoding="utf-8")
    return Path(pipeline.init(tmp_path / name, media, transcript=srt, name="Show", **settings)["project"])


class Scout:
    """A judge that answers the scout with as many moments as asked for, and remembers the prompt."""

    def __init__(self):
        self.prompts = []

    def ask(self, task, text, images=()):
        self.prompts.append(text)
        n = int(re.search(r"Pick the (\d+) strongest", text).group(1))
        return {"moments": [{"start": 10 + 60 * i, "end": 40 + 60 * i, "hook": f"Moment {i + 1}", "topic": f"t{i + 1}",
                             "why": f"reason {i + 1}"} for i in range(n)]}


def moments(root: Path, cfg: dict | None = None, ask=None):
    cfg = {**json.loads((root / "factory.json").read_text(encoding="utf-8")), **(cfg or {})}
    return pipeline._moments(root, ask or Scout(), root / "ep.mp4", cfg, say=lambda m: None)


def test_focus_and_settings_are_checked(tmp_path):
    with pytest.raises(FactoryError, match="focus"):
        project(tmp_path, focus="x" * 400)
    with pytest.raises(FactoryError, match="show"):
        project(tmp_path, show="!!!")
    with pytest.raises(FactoryError, match="moments"):
        project(tmp_path, moments=-1)
    assert json.loads((project(tmp_path, focus="pricing", show="My Show") / "factory.json").read_text())["focus"] == "pricing"
    assert _time("1:02:03") == 3723 and _time("90") == 90 and _time("2:30.5") == 150.5


def test_the_scout_is_steered_and_its_runners_up_are_kept(tmp_path):
    root = project(tmp_path, moments=3, focus="the pricing argument")
    ask = Scout()
    got = moments(root, ask=ask)
    assert [m["hook"] for m in got] == ["Moment 1", "Moment 2", "Moment 3"]
    assert "Pick the 6 strongest" in ask.prompts[0] and "WHAT THE USER WANTS: the pricing argument" in ask.prompts[0]
    status = pipeline.status(root)
    assert [b["hook"] for b in status["bench"]] == ["Moment 4", "Moment 5", "Moment 6"]
    assert moments(root, ask=ask) == got and len(ask.prompts) == 1          # scouted once
    assert pipeline.make_bench(root, 1) == "clip04"
    assert [c["hook"] for c in pipeline.status(root)["clips"]][-1] == "Moment 5"
    assert [b["hook"] for b in pipeline.status(root)["bench"]] == ["Moment 4", "Moment 6"]
    assert moments(root, ask=ask)[-1]["snapped"] is True                    # the new clip is timed on the next run
    with pytest.raises(FactoryError):
        pipeline.make_bench(root, 5)


def test_post_and_no_calls_teach_the_next_episode_of_the_show(tmp_path, zing_workspace):
    first = project(tmp_path, "ep1", moments=2, show="The Pod")
    moments(first)
    pipeline.rate(first, "clip01", "post", "the numbers land")
    pipeline.rate(first, "clip02", "fix")
    pipeline.rate(first, "clip02", "no", "rambles")                        # changed their mind: the last call counts
    with pytest.raises(FactoryError):
        pipeline.rate(first, "clip09", "post")
    second = project(tmp_path, "ep2", moments=2, show="the pod")           # same show, written differently
    ask = Scout()
    moments(second, ask=ask)
    prompt = ask.prompts[0]
    assert 'POSTED: "Moment 1" (t1). Their reason: the numbers land' in prompt
    assert 'PASSED: "Moment 2" (t2). Their reason: rambles' in prompt and "POSTED AFTER EDITS" not in prompt
    alone = project(tmp_path, "solo", moments=1)                            # no show: only its own calls count
    moments(alone)
    pipeline.rate(alone, "clip01", "fix", "tighten the end")
    assert pipeline.taste(alone, {"moments": 1})[0]["why"] == "tighten the end"
    assert "THE USER'S PAST CALLS" not in scout.steer(None, [])


def test_clips_picked_by_hand_are_checked_numbered_and_timed(tmp_path):
    root = project(tmp_path, moments=0)
    with pytest.raises(FactoryError, match="inside"):
        pipeline.add_clip(root, 900, 950)                                   # past the end of the episode
    with pytest.raises(FactoryError, match="3 s to 3 min"):
        pipeline.add_clip(root, 10, 11)
    assert pipeline.add_clip(root, 20, 70, "My *pick*") == "clip01"
    assert pipeline.add_clip(root, 100, 130) == "clip02"
    ask = Scout()
    got = moments(root, ask=ask)
    assert not ask.prompts                                                  # moments=0: nothing is scouted
    assert [m["by"] for m in got] == ["hand", "hand"] and all(m["snapped"] for m in got)
    assert pipeline.status(root)["clips"][0]["by"] == "hand"
    scouted = project(tmp_path, "later", moments=2)
    pipeline.add_clip(scouted, 20, 70)
    assert [m["hook"] for m in moments(scouted)] == ["", "Moment 1", "Moment 2"]   # picked before the scout: keeps clip01
    from myzing.factory import plan, postcopy
    words = {"words": [{"w": "hi", "os": 0, "oe": .3}], "duration": 1.0}
    assert "write one from what is said" in plan.prompt(got[1], words)
    assert "write one from what is said" in postcopy.prompt(got[1], words, {})


def test_trimming_a_clip_forgets_what_was_built_from_its_old_words(tmp_path):
    root = project(tmp_path, moments=2)
    moments(root)
    d = root / "clip01"
    d.mkdir()
    (d / "cams.json").write_text("{}", encoding="utf-8")
    j = judge.Judge(root)
    for kind in ("plan", "copy"):
        j.save(f"clip01-{kind}", {"x": 1})
    pipeline.rate(root, "clip01", "no", "starts too late")
    assert pipeline.trim(root, "clip01", 5, 45) == "clip01"
    m = json.loads((root / "moments.json").read_text(encoding="utf-8"))["moments"][0]
    assert (m["start"], m["end"]) == (5, 45) and "snapped" not in m and m["hook"] == "Moment 1"
    assert not d.exists() and j.cached("clip01-plan") is None and j.cached("clip01-copy") is None
    assert "clip01" not in json.loads((root / "ratings.json").read_text(encoding="utf-8"))
    with pytest.raises(FactoryError, match="unknown clip"):
        pipeline.trim(root, "clip07", 5, 45)


def test_mcp_factory_clip(tmp_path):
    root = project(tmp_path, moments=0)
    assert mcp_server.h_factory_clip(str(root), start=20, end=60)["clip"] == "clip01"
    assert mcp_server.h_factory_clip(str(root), clip="clip01", start=25, end=60)["clip"] == "clip01"
    assert not mcp_server.h_factory_clip(str(root), bench=0)["ok"]
    assert not mcp_server.h_factory_clip(str(root))["ok"]
    assert not mcp_server.h_factory_clip(str(root), start=20, end=21)["ok"]
