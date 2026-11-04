"""Offline clip-factory tests: no FFmpeg, browser, network or model calls."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from myzing.factory import cut, judge, pick, pipeline, plan, postcopy, render, review, scout, source, visuals
from myzing.factory.tools import FactoryError


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(visuals.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)


def words(text: str, start: float = 0.0, step: float = 0.4) -> list[dict]:
    return [{"w": w, "s": round(start + i * step, 2), "e": round(start + i * step + 0.3, 2)}
            for i, w in enumerate(text.split())]


def clip_words(text: str) -> list[dict]:
    return [{"w": w["w"], "os": w["s"], "oe": w["e"]} for w in words(text)]


# ---------------------------------------------------------------- transcripts
def test_srt_and_vtt_cues_become_segments_with_offset():
    srt = "1\n00:00:01,500 --> 00:00:03,000\nHello <i>there</i>.\n\n2\n00:00:03,100 --> 00:00:05,000\nSecond line\nwraps.\n"
    assert source.parse_captions(srt, offset=10) == [{"s": 11.5, "e": 13.0, "text": "Hello there."},
                                                     {"s": 13.1, "e": 15.0, "text": "Second line wraps."}]
    vtt = "WEBVTT\n\n00:00.680 --> 00:06.900 align:start\n>> From the Library of\nCongress.\n"
    assert source.parse_captions(vtt) == [{"s": 0.68, "e": 6.9, "text": ">> From the Library of Congress."}]


def test_rolling_auto_captions_merge_into_one_segment():
    vtt = "WEBVTT\n\n00:01.000 --> 00:02.000\nso the rocket\n\n00:02.000 --> 00:03.000\nso the rocket lifts off\n"
    assert source.parse_captions(vtt) == [{"s": 1.0, "e": 3.0, "text": "so the rocket lifts off"}]


def test_word_json_in_both_shapes(tmp_path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps([{"w": "Hi.", "s": 1, "e": 1.2}, {"w": "Bye.", "s": 2, "e": 2.3}]), encoding="utf-8")
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"words": [{"text": "Hi.", "start": 1, "end": 1.2}]}), encoding="utf-8")
    segs, ws = source.load_transcript(a, offset=1)
    assert ws[0] == {"w": "Hi.", "s": 2.0, "e": 2.2} and [s["text"] for s in segs] == ["Hi.", "Bye."]
    assert source.load_transcript(b)[1] == [{"w": "Hi.", "s": 1.0, "e": 1.2}]


def test_empty_caption_file_is_an_error(tmp_path):
    f = tmp_path / "x.srt"
    f.write_text("nothing here", encoding="utf-8")
    with pytest.raises(ValueError):
        source.load_transcript(f)


# ---------------------------------------------------------------- scout
def test_scout_prompt_and_answer_check():
    text = scout.prompt([{"s": 0, "e": 2.5, "text": "Hello."}], 3)
    assert "[0.0-2.5] Hello." in text and "Pick the 3 strongest" in text
    with pytest.raises(ValueError):
        scout.check({"moments": []})
    with pytest.raises(ValueError):
        scout.check({"moments": [{"start": 50, "end": 40, "hook": "x"}]})
    assert scout.check({"moments": [{"start": 1, "end": 30, "hook": "*Big* news", "score": 8}]})[0]["hook"] == "*Big* news"


def test_snap_drops_filler_and_ends_on_a_sentence():
    ws = words("So yeah the engine failed on the pad and we lost it. Then the crew walked away safe.")
    snapped = scout.snap({"start": 0.0, "end": 5.0, "hook": "h"}, ws)
    assert snapped["start"] == pytest.approx(ws[2]["s"] - 0.05)       # "the", after "So yeah"
    assert snapped["end"] == pytest.approx(ws[11]["e"] + 0.05)        # "it."
    assert snapped["scout_start"] == 0.0


# ---------------------------------------------------------------- cut
def test_pauses_are_removed_and_word_times_remapped():
    ranges = cut.keep_ranges([(2.0, 3.0), (5.0, 6.5)], 1.0, 8.0)
    assert ranges == [[1.0, 2.06], [2.94, 5.06], [6.44, 8.0]]
    assert cut.remap(1.5, ranges) == pytest.approx(0.5)
    assert cut.remap(2.5, ranges) == pytest.approx(1.06)              # inside a removed pause
    assert cut.remap(4.0, ranges) == pytest.approx(1.06 + 1.06)


def test_split_thousands_are_rejoined():
    ws = [{"w": "about", "s": 10.0, "e": 10.2}, {"w": "18", "s": 10.3, "e": 10.5}, {"w": ",000", "s": 10.5, "e": 10.8},
          {"w": "people.", "s": 10.9, "e": 11.2}]
    out = cut.moment_words(ws, 10.0, 11.2, 9.0)
    assert [w["w"] for w in out] == ["about", "18,000", "people."] and out[1]["e"] == pytest.approx(1.8)


def test_burned_captions_are_found_in_busy_bottom_rows():
    np = pytest.importorskip("numpy")
    frames = []
    for _ in range(4):
        g = np.full((100, 80), 30, dtype=np.uint8)
        g[80:90, ::2] = 255                                          # text-like stripes low in the frame
        frames.append(g)
    rows = cut.busy_rows(frames)
    assert rows[85] > 0.4 and rows[20] == 0


# ---------------------------------------------------------------- plan + fact check
def test_fact_check_accepts_spoken_numbers_in_any_form():
    ws = clip_words("They picked eleven people out of 18,000 applicants, about twenty five percent less than a dozen.")
    assert plan.fact_check({"kind": "counter", "value": 18000}, ws) == []
    assert plan.fact_check({"kind": "counter", "value": 11}, ws) == []
    assert plan.fact_check({"kind": "counter", "value": 25}, ws) == []
    assert plan.fact_check({"kind": "counter", "value": 12}, ws) == []
    assert plan.fact_check({"kind": "counter", "value": 19000}, ws) == [19000]
    assert plan.fact_check({"kind": "funnel", "rows": [{"value": 18000, "text": "18,000"}, {"value": 7}]}, ws) == [7]


def test_quotes_must_be_word_for_word():
    ws = clip_words("I never wanted to be the person who quits.")
    assert plan.fact_check({"kind": "quote", "text": "never wanted to be the *person* who quits"}, ws) == []
    assert plan.fact_check({"kind": "quote", "text": "I always wanted to quit"}, ws) == ["quote"]


def test_plan_check_and_finalize_keep_only_honest_shots(tmp_path):
    raw = plan.check({"hook": "*18,000* applied", "shots": [
        {"from": 0, "layout": "split", "visual": "v1"},
        {"from": 1, "layout": "graphic", "graphic": {"kind": "counter", "value": 99}},
        {"from": 2, "layout": "split", "visual": "missing"},
        {"from": 3, "layout": "graphic", "graphic": {"kind": "counter", "value": 18000}}],
        "visual_requests": [{"id": "v1", "query": "astronaut"}]})
    assert raw["shots"][2]["layout"] == "solo"                       # split without a request
    (tmp_path / "words.json").write_text(json.dumps({"words": clip_words("Almost 18,000 people applied.")}), encoding="utf-8")
    final = plan.finalize(tmp_path, raw, {"v1": {"path": "x.jpg", "credit": "NASA"}})
    assert [s["layout"] for s in final["shots"]] == ["split", "solo", "solo", "graphic"]
    assert any("99" in line for line in final["fact_check"])
    assert json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))["visuals"] == {"v1": {"path": "x.jpg", "credit": "NASA"}}
    with pytest.raises(ValueError):
        plan.check({"hook": "x", "shots": [{"from": 0, "layout": "dance"}]})


def test_hook_numbers_must_be_spoken(tmp_path):
    (tmp_path / "words.json").write_text(json.dumps({"words": clip_words("Thousands applied.")}), encoding="utf-8")
    final = plan.finalize(tmp_path, {"hook": "*12,000* applied", "shots": [{"from": 0, "layout": "solo"}]}, {})
    assert any("hook" in line for line in final["fact_check"])


def test_quote_moments_follow_the_spoken_words():
    ws = clip_words("Look at slavery. Cuba has the longest history of slavery of any place. And then.")
    shots = [{"from": 0, "layout": "solo"},
             {"from": 1.0, "layout": "graphic", "graphic": {"kind": "quote", "text": "Cuba has the *longest history* of slavery"}},
             {"from": 4.0, "layout": "graphic", "graphic": {"kind": "quote", "text": "never said this"}}]
    # the captions take over for exactly the quoted words; the shots around them stay on the speaker
    assert render.quotes(shots, ws) == [{"a": 3, "b": 9, "marks": [6, 7], "from": 1.08, "to": 4.7}]
    assert [s["layout"] for s in shots] == ["solo", "solo", "solo"]
    # a word said twice: the one nearest the shot; a quote overlapping another never shows
    late = [{"from": 3.5, "layout": "graphic", "graphic": {"kind": "quote", "text": "*slavery*"}},
            {"from": 3.6, "layout": "graphic", "graphic": {"kind": "quote", "text": "of any place"}}]
    assert render.quotes(late, ws) == [{"a": 9, "b": 9, "marks": [9], "from": 3.48, "to": 4.7}]


def test_one_quote_per_clip(tmp_path):
    (tmp_path / "words.json").write_text(json.dumps({"words": clip_words("Never quit. Keep going, always.")}), encoding="utf-8")
    final = plan.finalize(tmp_path, {"hook": "h", "shots": [
        {"from": 0, "layout": "graphic", "graphic": {"kind": "quote", "text": "Never *quit*"}},
        {"from": 1, "layout": "graphic", "graphic": {"kind": "quote", "text": "Keep *going*"}}]}, {})
    assert [s["layout"] for s in final["shots"]] == ["graphic", "solo"]
    assert any("one quote per clip" in line for line in final["fact_check"])


def test_misheard_names_and_terms_are_fixed_but_numbers_and_meaning_are_not():
    ws = clip_words("We met Buddy Shaw, the chair. Middle least policy, open AI and Buddy Shaw. Ten people trust it.")
    fixed, pairs, log = plan.apply_fixes(ws, [
        {"heard": "Buddy Shaw", "meant": "Buddy Shah"}, {"heard": "Middle least", "meant": "Middle East"},
        {"heard": "open AI", "meant": "OpenAI"}, {"heard": "Ten", "meant": "Twenty"}, {"heard": "trust", "meant": "sell"},
        {"heard": "never said", "meant": "never sad"}])
    text = " ".join(w["w"] for w in fixed)
    assert text == "We met Buddy Shah, the chair. Middle East policy, OpenAI and Buddy Shah. Ten people trust it."
    assert pairs == [("Buddy Shaw", "Buddy Shah"), ("Middle least", "Middle East"), ("open AI", "OpenAI")]
    merged = next(w for w in fixed if w["w"] == "OpenAI")       # two heard words become one, spanning both
    assert (merged["os"], merged["oe"]) == (ws[9]["os"], ws[10]["oe"])
    assert any("(x2)" in line for line in log) and sum("kept caption" in line for line in log) == 2
    assert [w["w"] for w in ws][3] == "Shaw,"                  # the input is left alone


def test_finalize_fixes_captions_graphics_and_copy_and_can_undo(tmp_path):
    heard = {"words": clip_words("Buddy Shaw chairs the trust."), "duration": 2.0}
    (tmp_path / "words.json").write_text(json.dumps(heard), encoding="utf-8")
    (tmp_path / "post.json").write_text(json.dumps({"x": {"text": "Meet buddy shaw."}}), encoding="utf-8")
    raw = {"hook": "Who is *Buddy Shaw*?", "fixes": [{"heard": "Buddy Shaw", "meant": "Buddy Shah"}], "shots": [
        {"from": 0, "layout": "graphic", "graphic": {"kind": "list", "title": "Buddy Shaw", "items": [{"text": "Chairs"}]}}]}
    final = plan.finalize(tmp_path, raw, {})
    read = lambda name: json.loads((tmp_path / name).read_text(encoding="utf-8"))
    assert read("words.json")["words"][1]["w"] == "Shah" and read("words.json")["duration"] == 2.0
    assert read("words-heard.json") == heard
    assert final["hook"] == "Who is *Buddy Shah*?" and final["shots"][0]["graphic"]["title"] == "Buddy Shah"
    assert final["fixes"] == [{"heard": "Buddy Shaw", "meant": "Buddy Shah"}] and raw["hook"] == "Who is *Buddy Shaw*?"
    assert read("post.json") == {"x": {"text": "Meet Buddy Shah."}}
    plan.finalize(tmp_path, {**raw, "fixes": []}, {})            # a redone plan starts again from what was heard
    assert read("words.json") == heard


def test_a_quick_model_finds_moments_and_the_full_model_times_them(tmp_path, monkeypatch):
    from myzing.study import speech_models
    cached = {"small"}
    monkeypatch.setattr(speech_models, "resolve_name", lambda name, require_cached=False: "large-v2")
    monkeypatch.setattr(speech_models, "local_path", lambda name: f"/models/{name}" if name in cached else None)
    assert source.scout_model() == "small"
    cached.clear()
    assert source.scout_model() is None                         # nothing small on disk: never downloads one
    monkeypatch.setattr(speech_models, "resolve_name", lambda name, require_cached=False: "base")
    assert source.scout_model() is None                         # already quick
    asked = []
    monkeypatch.setattr(source, "transcribe_episode", lambda media, model=None: asked.append(model) or words("Hello there."))
    for quick in ("small", None):
        d = tmp_path / str(quick)
        d.mkdir()
        monkeypatch.setattr(source, "scout_model", lambda q=quick: q)
        assert pipeline._transcript(d, tmp_path / "ep.mp4", say=lambda m: None)[0]["text"] == "Hello there."
        assert (d / "words.json").is_file() == (quick is None)  # quick words never reach a clip
    assert asked == ["small", None]


def test_plan_prompt_carries_words_and_style():
    w = {"duration": 4.0, "words": clip_words("Hello there. General Kenobi.")}
    text = plan.prompt({"hook": "h", "topic": "t"}, w, "fun")
    assert "0.00:Hello" in text and "Visual style: FUN" in text and "{WORDS}" not in text


# ---------------------------------------------------------------- pick
def test_picks_and_chosen_visuals(tmp_path):
    manifest = {"v1": [{"path": "v1/a.jpg", "source": "commons", "license": "CC BY 4.0", "creator": "Jo", "rights": "attribution"},
                       {"path": "v1/b.jpg", "source": "nasa", "credit_text": "NASA", "rights": "cleared"}],
                "v2": [{"path": "v2/s.png", "source": "screenshot", "rights": "editorial"}],
                "v3": [{"path": "v3/c.jpg", "source": "loc"}]}
    picks = pick.picks_from({"v1": {"pick": 2, "why": "sharper"}, "v2": {"pick": "1"}, "v3": {"pick": None}})
    assert picks["v1"]["pick"] == 1 and picks["v2"]["pick"] == 0 and picks["v3"]["pick"] is None
    found = pick.chosen(tmp_path, [{"id": "v2", "kind": "logo"}], manifest, picks)
    assert found["v1"]["credit"] == "NASA" and found["v2"]["fit"] == "contain" and "v3" not in found
    unpicked = pick.chosen(tmp_path, [], {"v1": manifest["v1"]}, {})
    assert unpicked["v1"]["credit"] == "Jo · CC BY 4.0"              # finder's top choice when no judge row


def test_sensitive_pick_prompt_forces_context_rules(tmp_path):
    text = pick.prompt(tmp_path / "s.jpg", "fun", "slavery")
    assert "SENSITIVE SUBJECT (slavery)" in text and "sharp human editor" in text
    assert "SENSITIVE" not in pick.prompt(tmp_path / "s.jpg", "fun", None)


# ---------------------------------------------------------------- copy
def test_copy_fills_link_and_timestamp():
    post = postcopy.finalize({"x": "a", "instagram": "b", "tiktok": "c", "youtube_title": "d",
                              "first_comment": "Full talk: {SOURCE_URL} at {TIMESTAMP}"},
                             {"start": 3725.4}, {"url": "https://example.org/talk"})
    assert post["first_comment"] == "Full talk: https://example.org/talk at 1:02:05"
    with pytest.raises(ValueError):
        postcopy.finalize({"x": "a"}, {"start": 0}, {})
    assert "{DATE}" not in postcopy.prompt({"hook": "h"}, {"words": clip_words("Hi.")}, {"name": "Show", "date": "2017"})


# ---------------------------------------------------------------- judge
def test_host_judge_writes_a_prompt_then_uses_the_answer(tmp_path):
    j = judge.Judge(tmp_path)
    with pytest.raises(judge.NeedsAnswer) as caught:
        j.ask("clip01-pick", "Pick one.", images=(tmp_path / "sheet.jpg",))
    pending = j.pending()
    assert pending[0]["task"] == "clip01-pick" and pending[0]["images"][0].endswith("sheet.jpg")
    assert caught.value.path.read_text(encoding="utf-8").endswith("Pick one.")
    j.save("clip01-pick", 'Sure: {"v1": {"pick": 1}} done')
    assert j.ask("clip01-pick", "Pick one.") == {"v1": {"pick": 1}} and j.pending() == []
    with pytest.raises(ValueError):
        j.ask("../escape", "x")


def test_claude_judge_runs_lean_and_logs_cost(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        out = {"result": '{"moments": []}', "total_cost_usd": 0.05, "duration_ms": 4000,
               "usage": {"input_tokens": 3, "cache_creation_input_tokens": 3000, "output_tokens": 400}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")
    monkeypatch.setattr(judge.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(judge.subprocess, "run", fake_run)
    j = judge.Judge(tmp_path, "claude")
    assert j.ask("scout", "find moments") == {"moments": []}
    argv, kwargs = calls[0]
    for flag in ("--system-prompt", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == "" and kwargs["cwd"] == tmp_path / ".judge"
    j.ask("clip01-pick", "look", images=(tmp_path / "s.jpg",))
    assert calls[1][0][calls[1][0].index("--tools") + 1] == "Read"
    assert calls[1][0][calls[1][0].index("--effort") + 1] == "medium"
    assert j.usage() == {"calls": 2, "cost_usd": 0.1}


def test_claude_judge_retries_once_then_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(judge.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(judge.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "limit"))
    with pytest.raises(RuntimeError, match="limit"):
        judge.Judge(tmp_path, "claude", retry_wait=0).ask("scout", "x")


# ---------------------------------------------------------------- pipeline
def project(tmp_path, **settings):
    media = tmp_path / "ep.mp4"
    media.write_bytes(b"\0")
    srt = tmp_path / "ep.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:04,000\nWe built a rocket.\n", encoding="utf-8")
    return pipeline.init(tmp_path / "proj", media, transcript=srt, name="Show", **settings)


def test_init_validates_settings(tmp_path):
    with pytest.raises(FactoryError):
        project(tmp_path, shapes=["2x3"])
    with pytest.raises(FactoryError):
        project(tmp_path, pack="nope")
    with pytest.raises(FactoryError):
        pipeline.init(tmp_path / "p", tmp_path / "missing.mp4")
    status = project(tmp_path, moments=2)
    assert status["state"] == "new" and status["settings"]["moments"] == 2


def test_host_run_stops_at_the_scout_and_answers_are_validated(tmp_path):
    status = project(tmp_path)
    root = Path(status["project"])
    result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert result["state"] == "waiting" and [p["task"] for p in result["pending"]] == ["scout"]
    with pytest.raises(FactoryError):
        pipeline.answer(root, "scout", '{"moments": []}')
    assert [p["task"] for p in pipeline.status(root)["pending"]] == ["scout"]   # still asked after a bad answer
    pipeline.answer(root, "scout", {"moments": [{"start": 1, "end": 4, "hook": "Rocket"}]})
    assert judge.Judge(root).cached("scout")["moments"][0]["hook"] == "Rocket"


def test_host_run_asks_plan_and_copy_together(tmp_path, monkeypatch):
    status = project(tmp_path)
    root = Path(status["project"])
    (root / "words.json").write_text(json.dumps(words("We built a rocket.", 1.0)), encoding="utf-8")
    pipeline.answer(root, "scout", {"moments": [{"start": 1, "end": 2.5, "hook": "Rocket"}]})

    def fake_cut(d, media, ws, start, end):
        d.mkdir(parents=True, exist_ok=True)
        (d / "words.json").write_text(json.dumps({"words": clip_words("We built a rocket."), "duration": 2.0,
                                                  "start": start}), encoding="utf-8")
        (d / "cams.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(pipeline.cut, "cut", fake_cut)
    result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert sorted(p["task"] for p in result["pending"]) == ["clip01-copy", "clip01-plan"]
    pipeline.redo(root, "scout")
    assert not (root / "moments.json").exists()


# ---------------------------------------------------------------- render + review
def test_style_packs():
    assert {"zing", "newsdesk", "swiss"} <= set(render.themes())
    assert render.theme("swiss")["cap_upper"] is False
    with pytest.raises(FactoryError):
        render.theme("../zing")
    assert render.suffix("9x16", "zing") == "" and render.suffix("1x1", "swiss") == "-1x1-swiss"


def test_review_page_lists_rendered_clips_and_flags_rights(tmp_path):
    (tmp_path / "source.json").write_text(json.dumps({"name": "Show <1>"}), encoding="utf-8")
    (tmp_path / "moments.json").write_text(json.dumps({"moments": [{"start": 61, "hook": "*Big* news", "score": 9},
                                                                   {"start": 90, "hook": "unrendered"}]}), encoding="utf-8")
    d = tmp_path / "clip01"
    d.mkdir()
    (d / "clip-1x1.mp4").write_bytes(b"")
    (d / "plan.json").write_text(json.dumps({"shots": [{"layout": "solo"}], "fact_check": ["ok"],
                                             "visuals": {"v1": {"credit": "site", "rights": "editorial"}}}), encoding="utf-8")
    page = review.build(tmp_path).read_text(encoding="utf-8")
    assert "Show &lt;1&gt;" in page and "clip01/clip-1x1.mp4" in page and "1:01 in the episode" in page
    assert "Check rights before posting: editorial" in page and "unrendered" not in page


def test_mcp_handlers_drive_the_host_judge(tmp_path):
    from myzing import mcp_server
    assert not mcp_server.h_factory_new(str(tmp_path / "p"), str(tmp_path / "missing.mp4"))["ok"]
    assert not mcp_server.h_factory_status(str(tmp_path))["ok"]
    root = project(tmp_path)["project"]
    pipeline.run(Path(root), judge.Judge(Path(root)), say=lambda m: None)
    status = mcp_server.h_factory_status(root)
    assert status["ok"] and status["state"] == "waiting" and status["running"] is False
    assert [p["task"] for p in status["pending"]] == ["scout"]
    prompt = mcp_server.h_factory_prompt(root, "scout")
    assert "We built a rocket." in prompt["prompt"] and prompt["images"] == []
    assert not mcp_server.h_factory_prompt(root, "clip09-plan")["ok"]
    assert not mcp_server.h_factory_answer(root, "scout", {"moments": []})["ok"]
    assert mcp_server.h_factory_answer(root, "scout", {"moments": [{"start": 1, "end": 4, "hook": "Rocket"}]})["ok"]
    with pytest.raises(judge.NeedsAnswer):
        judge.Judge(Path(root)).ask("clip01-pick", "Pick.", images=(Path(root) / "sheet.jpg",))
    pick_prompt = mcp_server.h_factory_prompt(root, "clip01-pick")
    assert pick_prompt["prompt"] == "Pick." and pick_prompt["images"][0].endswith("sheet.jpg")


def test_cli_lists_factory():
    from myzing import cli
    assert "factory" in cli._COMMANDS


# ---------------------------------------------------------------- documentary and launch
def test_documentary_mode_keeps_its_archives_and_its_rules(tmp_path):
    text = pick.prompt(tmp_path / "s.jpg", "documentary", "slavery")
    assert "documentary editor" in text and "SENSITIVE SUBJECT (slavery)" in text
    assert "is evidence" in text and "a map, or visual clutter" not in text
    assert "a map, or visual clutter" in pick.prompt(tmp_path / "s.jpg", "context", None)
    ctx = visuals.Ctx(tmp_path, "documentary", False, False, 0, 5)
    route = visuals.route_for(ctx, visuals.Query({"query": "Havana harbor 1890 photograph"}, "photo", "documentary"))
    assert "commons" in route and "loc" in route and not {"pexels", "pixabay", "exa"} & set(route)
    assert "DOCUMENTARY" in plan.prompt({"hook": "h"}, {"duration": 1.0, "words": clip_words("Hi.")}, "documentary")
    doc = render.theme("documentary")
    assert doc["cap_style"] == "kinetic" and doc["cutaway"] == "full" and doc["quote_mark"] == "circle"


def test_launch_films_are_spans_in_a_chosen_order():
    text = scout.prompt([{"s": 0, "e": 2.5, "text": "Watch this."}], 2, "launch")
    assert "launch film" in text and "Build the 2 strongest" in text
    film = scout.check({"moments": [{"hook": "h", "spans": [{"start": 40, "end": 50, "role": "open"},
                                                            {"start": 5, "end": 12, "role": "what"}]}]})[0]
    assert scout.parts(film) == [[40.0, 50.0], [5.0, 12.0]] and (film["start"], film["end"]) == (40.0, 12.0)
    assert scout.parts({"start": 1, "end": 2}) == [[1, 2]]
    with pytest.raises(ValueError):
        scout.check({"moments": [{"hook": "h", "spans": [{"start": 5, "end": 20}, {"start": 10, "end": 30}]}]})
    ws = words("So the robot folds laundry. It learned in a week. We built it to help.", 0.0, 1.0)
    snapped = scout.snap({**film, "spans": [{"start": 9.0, "end": 11.5, "role": "open"}, {"start": 0.0, "end": 4.5}]}, ws)
    assert [round(s["start"], 2) for s in snapped["spans"]] == [8.95, 0.95]      # "We", and "the" after "So"
    assert snapped["spans"][1]["end"] == pytest.approx(ws[4]["e"] + .05)          # "laundry."


def test_launch_title_end_card_and_name_tags_are_grounded(tmp_path):
    (tmp_path / "words.json").write_text(json.dumps({"words": clip_words(
        "I'm Ana, founder of Fold. Fold folds laundry in 90 seconds.")}), encoding="utf-8")
    brand = {"name": "Fold", "url": "fold.app", "cta": "Join the waitlist"}
    final = plan.finalize(tmp_path, {"hook": "h", "shots": [
        {"from": 0, "layout": "solo", "label": {"name": "Ana", "role": "founder of Fold"}},
        {"from": 1, "layout": "solo", "label": {"name": "Ana Smith", "role": "CEO"}},
        {"from": 2, "layout": "graphic", "graphic": {"kind": "title", "text": "Introducing *Fold*"}},
        {"from": 3, "layout": "graphic", "graphic": {"kind": "title", "text": "Introducing *Fold Pro*"}},
        {"from": 4, "layout": "graphic", "graphic": {"kind": "endcard", "name": "Fold", "url": "fold.app",
                                                      "line": "Join the waitlist"}},
        {"from": 5, "layout": "graphic", "graphic": {"kind": "endcard", "name": "Fold", "url": "fold.com",
                                                      "line": "Laundry in 60 seconds"}}]}, {}, brand)
    shots = final["shots"]
    assert shots[0]["label"]["name"] == "Ana" and "label" not in shots[1]
    assert [s["layout"] for s in shots[2:]] == ["graphic", "solo", "graphic", "solo"]
    assert any("name tag" in line for line in final["fact_check"])
    assert shots[4]["graphic"]["url"] == "fold.app"
    assert plan.fact_check({"kind": "endcard", "name": "Fold", "url": "https://www.Fold.app/", "line": "Folding laundry"},
                           clip_words("Fold folds laundry."), brand) == []          # the brand's site, and "folds"
    assert "BRAND: name: Fold; url: fold.app" in plan.prompt({"hook": "h"}, {"duration": 1.0, "words": clip_words("Hi.")},
                                                            "launch", brand)


def test_launch_projects_default_to_landscape_and_check_the_brand(tmp_path):
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"x")
    cfg = pipeline.init(tmp_path / "p", media, mode="launch", brand={"name": "Fold"})["settings"]
    assert cfg["shapes"][0] == "16x9" and cfg["pack"] == "launch" and cfg["moments"] == 2 and cfg["brand"]["name"] == "Fold"
    assert pipeline.init(tmp_path / "q", media, mode="launch", shapes=["9x16"])["settings"]["shapes"] == ["9x16"]
    with pytest.raises(FactoryError):
        pipeline.init(tmp_path / "r", media, mode="launch", brand={"url": "x.app"})
    assert "copy" in postcopy.prompt({"hook": "h"}, {"words": clip_words("Hi.")}, {}, "launch", {"name": "Fold"}).lower()


def test_end_card_ends_within_three_seconds_of_the_last_word(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps({"hook": "h", "shots": [
        {"from": 0, "layout": "solo"}, {"from": 1.0, "layout": "graphic", "graphic": {"kind": "endcard", "name": "Fold"}}]}),
        encoding="utf-8")
    (tmp_path / "words.json").write_text(json.dumps({"words": clip_words("Fold it.")}), encoding="utf-8")
    (tmp_path / "cams.json").write_text(json.dumps({"frames": 30, "size": [1920, 1080], "cams": []}), encoding="utf-8")
    data = render.scene_data(tmp_path, "16x9", "launch", parallax=False)
    assert data["duration"] == pytest.approx(3.7)


def test_films_that_share_spans_transcribe_each_stretch_once(tmp_path, monkeypatch):
    (tmp_path / "transcript.json").write_text(json.dumps([{"s": 0, "e": 400, "text": "Demo."}]), encoding="utf-8")
    films = {"moments": [{"hook": "a", "spans": [{"start": 10, "end": 20}, {"start": 30, "end": 40}, {"start": 300, "end": 310}]},
                         {"hook": "b", "spans": [{"start": 12, "end": 18}, {"start": 300, "end": 305}]}]}
    asked = []
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: asked.extend(pieces) or [])

    class Ask:
        def ask(self, task, text):
            return films
    pipeline._moments(tmp_path, Ask(), tmp_path / "ep.mp4", {"moments": 2, "mode": "launch"}, say=lambda m: None)
    assert asked == [{"start": 10, "end": 40}, {"start": 300, "end": 310}]


def test_a_stretch_in_the_wrong_language_is_redone_in_the_main_one(monkeypatch):
    calls = []

    def speech(media, start=None, end=None, model=None, language=None):
        calls.append((start, language))
        lang = language or ("cy" if start > 300 else "en")       # the short stretch is misheard as Welsh
        return [{"w": lang, "s": start + 1, "e": start + 2}], lang, 0.6
    monkeypatch.setattr(source, "_speech", speech)
    words = source.transcribe_moments(Path("ep.mp4"), [{"start": 10, "end": 200}, {"start": 400, "end": 410}])
    assert [w["w"] for w in words] == ["en", "en"]
    assert calls[-1][1] == "en"
    assert source.main_language([(0, 10, "en", 0.9), (10, 15, "cy", 0.99)]) == "en"
