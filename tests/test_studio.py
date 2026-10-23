"""Observable interview, consent, persistence and stateless agent behavior."""

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.studio import command, flow, evidence, adapters
from myzing.studio.models import Question, Session, load_session


@pytest.fixture
def inputs(tmp_path, monkeypatch, zing_workspace):
    clips, photos = tmp_path / "clips", tmp_path / "photos"
    clips.mkdir()
    photos.mkdir()
    video = clips / "clip.mp4"
    video.write_bytes(b"fake local footage; probe is stubbed")
    track = tmp_path / "track.wav"
    track.write_bytes(b"fake track")
    probe = {"duration": 18.0, "width": 640, "height": 360, "orientation": "landscape",
             "has_audio": True, "flags": [], "streams": [{"codec_type": "video"}], "notes": []}
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(to_dict=lambda: probe))
    monkeypatch.setattr(flow, "default_project", lambda: str(tmp_path / "project"))
    monkeypatch.setattr("myzing.studio.reference.quick_read", lambda p: {"reason": "Reference quick read failed; style unknown.", "warnings": [], "tone": "natural"})
    return {"clips": str(clips), "photos": str(photos), "source": str(video), "track": str(track), "project": str(tmp_path / "project")}


def complete(path, inputs):
    a = {"path": path, "project": inputs["project"]}
    supplied = {"reference_kind": "file", "reference": inputs["source"], "clips": inputs["clips"],
                "photos": inputs["photos"], "source": inputs["source"], "tracks": [inputs["track"]], "topic": "one quick fix", "speech_model": "skip"}
    while True:
        step = flow.next_step(a)
        if step["status"] == "plan":
            return step["answers"], step["plan"]
        q = step["question"]
        a[q["id"]] = supplied.get(q["id"], q["recommended"])


@pytest.mark.parametrize("path", list("abcdef"))
def test_scripted_stdin_every_path(path, inputs, monkeypatch, capsys):
    calls = []
    result = {"ok": True, "status": "ready", "outputs": ["example-output"], "warnings": ["Speech is unknown."], "next_actions": ["Review output."]}
    def execute(answers, **kwargs):
        calls.append(answers)
        kwargs["progress"]("measure, then render")
        return result
    monkeypatch.setattr("myzing.studio.jobs.execute", execute)
    monkeypatch.setattr("myzing.studio.execute.run_confirmed", execute)
    answers, _ = complete(path, inputs)
    transcript = []
    accepted = {}
    while True:
        step = flow.next_step(accepted)
        if step["status"] == "plan":
            break
        key = step["question"]["id"]
        value = answers[key]
        transcript.append(str("abcdef".index(value) + 1) if key == "path" else  # b always means back
                          ";".join(value) if key == "tracks" else ",".join(value) if isinstance(value, list)
                          else "yes" if value is True else "no" if value is False else str(value))
        accepted[key] = value
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(transcript) + "\nyes\n"))
    assert command.run([]) == 0
    output = capsys.readouterr().out
    assert output.startswith("\nWhat are we making?")
    assert "Recommended:" in output and "Downloads: none" in output
    assert output.index("Plan:") < output.index("Working:")
    assert "Output: example-output" in output and "Speech is unknown" in output
    assert len(calls) == 1 and calls[0]["path"] == path
    state = load_session(inputs["project"])
    assert state.status == "ready" and state.questions_asked == len(transcript)
    assert Session.from_dict(state.to_dict()).to_dict() == state.to_dict()
    assert "1. a." not in output
    if path == "a":
        assert state.questions_asked <= 9


def test_required_path_empty_reprompts_without_enter_acceptance(inputs, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(f"1\n\n{inputs['source']}\nq\n"))
    assert command.run([]) == 0
    text = capsys.readouterr().out
    required = text.split("Drag the reference video here", 1)[1].split("Which folder", 1)[0]
    assert "Enter accepts" not in required and "Recommended:" not in required
    assert "Please type an answer" in required
    assert load_session(inputs["project"]).answers["reference"] == inputs["source"]


def test_reference_measures_drive_defaults_and_custom_shape_is_only_extra(inputs, monkeypatch):
    from myzing.studio.reference import describe
    reference = describe({"duration": 19.7, "aspect": "9:16", "sample_seconds": 19.7,
                         "cuts_per_minute": 66, "has_audio": True, "speech_present": False,
                         "music_present": True, "text_present": False})
    monkeypatch.setattr("myzing.studio.reference.quick_read", lambda p: reference)
    a = {"path": "a", "project": inputs["project"], "reference": inputs["source"], "clips": inputs["clips"], "topic": "demo"}
    questions = []
    cache = {}
    while True:
        step = flow.next_step(a, cache=cache)
        if step["status"] == "plan":
            break
        q = step["question"]
        questions.append(q)
        a[q["id"]] = "skip" if q["id"] == "speech_model" else q["recommended"]
    assert [q["id"] for q in questions] == ["platform", "length", "captions", "music", "speech_model"]
    assert ["9:16" in questions[0]["reason"], "19.7 s" in questions[1]["reason"],
            "No text detected" in questions[2]["reason"], "Music observed" in questions[3]["reason"]] == [True] * 4
    assert all("66 cuts/min" not in q["reason"] for q in questions)
    assert all("66 cuts/min" in q["evidence"]["reference"]["reason"] for q in questions)
    assert step["answers"]["aspects"] == ["9:16"]
    assert step["answers"]["length"] == 20 and step["answers"]["tone"] == "energetic"
    assert step["answers"]["captions"] == "none" and step["answers"]["music"] == "original"
    a["platform"] = "custom"
    assert flow.next_step(a, cache=cache)["question"]["id"] == "aspects"


def test_output_folder_can_change_on_plan_screen(inputs, tmp_path, monkeypatch, capsys):
    other = tmp_path / "other"
    monkeypatch.setattr("sys.stdin", io.StringIO(f"6\n{inputs['source']}\nsquare\no\n{other}\nq\n"))
    assert command.run([]) == 0
    assert load_session(other).answers["aspects"] == ["1:1"]
    text = capsys.readouterr().out
    assert "Where should I save" not in text and "o changes output folder" in text


def test_redelivery_keeps_saved_plan_shape(inputs, tmp_path):
    from myzing.composition import Composition, AssetRef, CompositionClip
    plan = Composition(assets=[AssetRef("s", inputs["source"], None)],
                       clips=[CompositionClip(inputs["source"], 0, 2, 0, id="c", asset_id="s")], width=360, height=640)
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan.to_dict()))
    step = flow.next_step({"path": "f", "source": str(source), "platform": "original"})
    assert step["status"] == "plan" and step["answers"]["aspects"] == ["9:16"]
    assert "360x640, 2 seconds" in step["plan"]["evidence"]["measured"][0]


@pytest.mark.parametrize("timeout", [False, True])
def test_quick_reference_partial_failure_is_bounded_and_unknown(inputs, monkeypatch, timeout):
    from myzing.studio import reference
    from myzing.match.process import Cancelled
    workspaces = []
    def owned(command, payload, **kwargs):
        assert command[-1] == "myzing.studio.reference" and kwargs["cancel"] is not None
        workspaces.append(Path(json.loads(payload)["workspace"]))
        kwargs["progress"](json.dumps({"studio_reference": True, "data": {"duration": 20, "aspect": "16:9", "sample_seconds": 20}}))
        if timeout:
            raise Cancelled()
        kwargs["progress"](json.dumps({"studio_reference": True, "data": {"error": "optional detector missing"}}))
    monkeypatch.setattr("myzing.match.process.run_owned", owned)
    # The fixture replaces the public seam; exercise its original implementation.
    import importlib
    original = importlib.reload(reference).quick_read
    result = original(inputs["source"])
    assert "speech unknown" in result["reason"] and "cut rate unknown" in result["reason"]
    assert any("limit" in w if timeout else "optional detector missing" in w for w in result["warnings"])
    assert workspaces and all(not p.exists() for p in workspaces)


def test_finish_summary_merges_notes_and_uses_measured_results(inputs):
    from myzing.studio.presentation import creator_summary
    rows = {f"{draft}.9x16": {"status": "ready", "video": f"{draft}.mp4", "plan": f"{draft}.json",
                             "dimensions": {"color": {"status": status}, "shot_pace": {"status": "pass"}}}
            for draft, status in [("A", "miss"), ("B", "pass"), ("C", "miss")]}
    result = {"project": inputs["project"], "result": {"drafts": rows}, "warnings": [
        "The detected faces do not fit a full-bleed crop", "The measured subject does not fit a full-bleed crop"]}
    summary = creator_summary(result, {"aspects": ["9:16"]}, {"clips": []})
    assert summary["recommendation"].startswith("Start with draft B (9:16)")
    assert summary["notes"] == ["Some photos need a blurred background to keep faces and subjects inside the frame."]
    assert '--draft B --draft-file "B.json"' in summary["next_actions"][0]
    rows["B.9x16"]["status"] = "failed"
    assert "draft B" not in creator_summary(result, {}, {})["recommendation"]
    rows["B.9x16"]["status"] = "ready"
    for key, row in list(rows.items()):
        for shape in ("16x9", "1x1"):
            rows[key.replace("9x16", shape)] = {**row, "video": f"drafts/draft-{key[0]}.{shape}.mp4"}
    summary = creator_summary(result, {"aspects": ["9:16"]}, {})
    screen = io.StringIO()
    command.show_result({**result, "status": "ready", "creator_summary": summary}, screen)
    text = screen.getvalue()
    assert "Output:" not in text and text.count("Full result:") == 1 and text.count("Note:") == 1
    assert all(len(line) <= 120 for line in text.splitlines() if " | " in line)
    rows["A.9x16"]["dimensions"]["color"]["status"] = "pass"
    assert "No draft is clearly better" in creator_summary(result, {}, {})["recommendation"]


def test_finish_pick_never_counts_abstentions_disagreements_or_unmeasured_color_as_passes(inputs):
    """MATCH2 statuses rank as neither passes nor misses, and are named on the finish screen."""
    from myzing.studio.presentation import creator_summary
    unmeasured = {"status": "approximate", "max_luma_percentile_delta": None,
                  "reason": "No sample had a usable sharp picture area; color is unmeasured."}
    measured = {"status": "approximate", "max_luma_percentile_delta": .08}
    grades = {"A": {"shot_pace": {"status": "detector_disagreement"}, "first_cut": {"status": "not_applicable"},
                    "color": unmeasured},
              "B": {"shot_pace": {"status": "pass"}, "first_cut": {"status": "pass"}, "color": measured},
              "C": {"shot_pace": {"status": "pass"}, "first_cut": {"status": "miss"}, "color": measured}}
    rows = {f"{d}.{shape}": {"status": "ready", "video": f"drafts/draft-{d}.{shape}.mp4", "plan": f"{d}.json",
                             "dimensions": dims} for d, dims in grades.items() for shape in ("16x9", "9x16")}
    result = {"project": inputs["project"], "result": {"drafts": rows}, "warnings": []}
    summary = creator_summary(result, {"aspects": ["16:9"]}, {"clips": []})
    assert summary["recommendation"].startswith("Start with draft B (16:9) because it passes shot pace, first cut (0 ")
    assert "Not passes" not in summary["recommendation"]
    a = next(r for r in summary["deliveries"] if r["draft"] == "A")
    assert a["status"] == "unverified" and "pass" not in a["measurements"].values()
    assert summary["style_summary"] == [
        "Draft A (16:9, 9:16): shot pace detector disagreement; first cut not applicable for this footage; color unmeasured.",
        "Draft C (16:9, 9:16): first cut miss."]
    screen = io.StringIO()
    command.show_result({**result, "status": "ready", "creator_summary": summary}, screen)
    text = screen.getvalue()
    assert "Draft A (16:9, 9:16): shot pace detector disagreement" in text and "Note:" not in text
    # Without B, A has no misses but no passes either: the pick says so and names
    # every non-pass instead of implying a certified match.
    for shape in ("16x9", "9x16"):
        rows.pop(f"B.{shape}")
    pick = creator_summary(result, {"aspects": ["16:9"]}, {})["recommendation"]
    assert pick.startswith("Start with draft A (16:9) because it has the fewest measured style misses (0 measured misses).")
    assert ("Not passes: shot pace detector disagreement, first cut not applicable for this footage, "
            "color unmeasured.") in pick and "it passes" not in pick


def test_progress_translates_internal_asset_and_draft_ids(inputs, tmp_path):
    from myzing.studio.presentation import progress_label
    root = Path(inputs["project"])
    root.mkdir()
    (root / "project.json").write_text(json.dumps({"assets": [{"id": "asset_secret", "path": "korky.mp4", "probe": {"width": 640}}]}))
    a = {"project": str(root), "aspects": ["16:9", "1:1", "9:16"]}
    assert progress_label("study-asset_secret: starting", a) == "Studying korky.mp4 (1 of 1)"
    assert progress_label("render-B.1x1: starting", a) == "Rendering draft B, 1:1 (5 of 9)"
    assert progress_label("study-asset_secret: done", a) is None


def test_back_explain_quit_and_resume(inputs, monkeypatch, capsys):
    # Back from topic changes clips, not the path; ? does not consume an answer.
    text = f"2\n{inputs['clips']}\nb\n?\n{inputs['clips']}\nq\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    assert command.run([]) == 0
    state = load_session(inputs["project"])
    assert state.status == "paused" and "topic" not in state.answers
    assert state.answers["clips"] == inputs["clips"]
    output = capsys.readouterr().out
    assert '"unknowns"' in output and "Continue: zing studio --resume" in output
    monkeypatch.setattr("sys.stdin", io.StringIO("a small demo\n\n\n\n\n\nq\n"))
    assert command.run(["--resume", inputs["project"]]) == 0
    state = load_session(inputs["project"])
    assert state.answers["topic"] == "a small demo" and state.status == "paused"


@pytest.mark.parametrize("termination", ["q\n", ""])
def test_quit_before_project_saves_resumable_session(tmp_path, monkeypatch, termination):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(termination))
    assert command.run([]) == 0
    assert load_session(tmp_path / "zing-workspace/studio").status == "paused"


def test_unknown_evidence_and_missing_ffprobe(inputs, monkeypatch):
    from myzing.study.proc import ToolMissing
    def missing(_):
        raise ToolMissing("ffprobe")
    monkeypatch.setattr("myzing.project.probe.probe_file", missing)
    a = {"path": "b", "project": inputs["project"], "clips": inputs["clips"], "topic": "demo"}
    q = flow.next_step(a)["question"]
    assert "unknown" in q["reason"]
    assert "ffprobe" in " ".join(q["evidence"]["unknowns"])
    assert "talking-head" not in json.dumps(q)


def test_json_answers_never_read_stdin_and_yes_is_not_download_consent(inputs, tmp_path, monkeypatch, capsys):
    a, _ = complete("a", inputs)
    a.update(reference_kind="url", reference="https://example.test/reference.mp4")
    answer_file = tmp_path / "answers.json"
    answer_file.write_text(json.dumps(a))
    monkeypatch.setattr("sys.stdin", None)
    monkeypatch.setattr("myzing.studio.execute.run_confirmed", lambda *a, **k: pytest.fail("unconfirmed download"))
    assert command.run(["--answers", str(answer_file), "--yes", "--json"]) == 2
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["question"]["id"] == "allow_download"
    a["allow_download"] = False
    answer_file.write_text(json.dumps(a))
    assert command.run(["--answers", str(answer_file), "--yes", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["event"] == "blocked"


def test_answers_plan_only_then_run_json(inputs, tmp_path, monkeypatch, capsys):
    a, _ = complete("e", inputs)
    answer_file = tmp_path / "answers.json"
    answer_file.write_text(json.dumps(a))
    monkeypatch.setattr("sys.stdin", None)
    monkeypatch.setattr(command.jobs, "execute", lambda *a, **k: pytest.fail("plan must be confirmed"))
    assert command.run(["--answers", str(answer_file), "--json"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e["event"] for e in events] == ["plan", "confirmation_required"]
    def execute(*args, progress):
        progress("audio analysis")
        return {"ok": True, "status": "ready", "outputs": []}
    monkeypatch.setattr(command.jobs, "execute", execute)
    assert command.run(["--answers", str(answer_file), "--yes", "--json"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e["event"] for e in events] == ["plan", "progress", "result"]


@pytest.mark.parametrize("path", list("abcdef"))
def test_mcp_question_flow_is_stateless(path, inputs):
    from myzing.mcp_server import h_zing_studio
    a, _ = complete(path, inputs)
    partial = {"project": inputs["project"]}
    while True:
        first = h_zing_studio(path, partial)
        assert first == h_zing_studio(path, partial) and first["ok"]
        if first["status"] == "plan":
            assert first["plan"]["confirmation_required"] is True
            break
        q = first["question"]
        assert {"id", "prompt", "options", "recommended", "reason", "evidence"} <= q.keys()
        assert Question.from_dict(q).to_dict() == q
        partial[q["id"]] = a[q["id"]]
    assert not Path(inputs["project"]).exists()


def test_existing_jobs_are_reused_and_runner_requires_confirmation(inputs):
    from myzing.mcp_server import h_zing_studio_run
    for path, tool in [("c", "still_concepts"), ("e", "music_check")]:
        a, plan = complete(path, inputs)
        assert plan["execution"][0]["tool"] == tool
        assert not h_zing_studio_run(a, confirmed=True)["ok"]
    a, plan = complete("b", inputs)
    assert plan["execution"][0]["tool"] == "zing_studio_run"
    assert "confirmation" in h_zing_studio_run(a)["error"]


@pytest.mark.parametrize("key,value", [("length", float("nan")), ("length", True), ("aspects", ["4:3"]),
                                      ("allow_download", "sure"), ("tone", "magic"), ("made_up", 1)])
def test_invalid_automation_answers_fail_without_writes(key, value, inputs):
    with pytest.raises(ValueError):
        flow.next_step({"path": "b", "project": inputs["project"], key: value})
    assert not Path(inputs["project"]).exists()


def test_saved_reference_offer_and_search_use_fake_peer_contract(inputs, monkeypatch):
    from urllib.parse import urlparse, parse_qs
    from conftest import FakeHTTPResponse
    from test_suite_peer import make_manifest
    from test_uoink_search_contract import search_body
    from myzing import uoink_bridge as bridge
    monkeypatch.setenv("UOINK_URL", "http://127.0.0.1:61983")
    monkeypatch.setenv("UOINK_TOKEN", "fake-studio-token")
    manifest = make_manifest()
    manifest["service"]["capabilities"].append("uoink.corpus.read/1")
    monkeypatch.setattr(bridge.suite_peer, "_get_json", lambda url: (200, manifest))
    calls = []
    def peer(request, **kwargs):
        calls.append(request)
        assert request.method == "GET" and request.data is None
        assert parse_qs(urlparse(request.full_url).query) == {"q": ["soft cuts"], "limit": ["20"]}
        assert "fake-studio-token" not in request.full_url and ":5179" not in request.full_url
        return FakeHTTPResponse(json.dumps(search_body()).encode())
    monkeypatch.setattr(bridge.urllib.request, "urlopen", peer)
    a = {"path": "a", "project": inputs["project"]}
    assert any(o["value"] == "uoink" for o in flow.next_step(a)["question"]["options"])
    a.update(reference_kind="uoink", reference_query="soft cuts")
    q = flow.next_step(a)["question"]
    assert q["id"] == "reference" and q["recommended"].startswith("uoink://item/")
    assert len(calls) == 1
    monkeypatch.delenv("UOINK_TOKEN")
    assert not evidence.saved_references_available()
    assert not any(o["value"] == "uoink" for o in flow.next_step({"path": "a", "project": inputs["project"]})["question"]["options"])


def test_explain_adapter_lazy_contract_and_failure_not_hidden(inputs, tmp_path, monkeypatch, capsys):
    import sys
    from types import ModuleType
    module = ModuleType("myzing.explain.api")
    calls = []
    def explain(source, out, **kwargs):
        calls.append((source, out, kwargs))
        return {"ok": False, "error": "missing optional detector; install its extra"}
    module.explain_video = explain
    monkeypatch.setitem(sys.modules, "myzing.explain.api", module)
    result = adapters.explain_video(inputs["source"], tmp_path)
    assert not result["ok"] and "detector" in result["error"]
    from myzing.studio.execute import run_confirmed
    a, _ = complete("d", inputs)
    finished = run_confirmed(a)
    assert not finished["ok"] and "detector" in finished["error"]
    command.show_result(finished, sys.stdout)
    assert "missing optional detector; install its extra" in capsys.readouterr().out
    assert calls[0][2] == {"transitions": True, "offline": True}


def test_missing_explain_falls_back_to_offline_study_and_inspect(inputs, tmp_path, monkeypatch):
    import sys
    from myzing import storage
    monkeypatch.setitem(sys.modules, "myzing.explain.api", None)
    calls = []
    def study(source, **kwargs):
        calls.append(kwargs)
        with storage.use_workspace(kwargs["workspace"]):
            folder = storage.breakdown_dir(storage.slug_for(source))
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "breakdown.json").write_text("{}")
            (folder / "breakdown.md").write_text("Measured fallback")
        return SimpleNamespace(meta=SimpleNamespace(duration=5), shots=[], words=[], captions=[], warnings=["Speech unknown"])
    def inspect(source, out, **kwargs):
        Path(out).write_bytes(b"test PNG placeholder")
        return SimpleNamespace(warnings=[])
    monkeypatch.setattr("myzing.study.api.study", study)
    monkeypatch.setattr("myzing.inspect.timeline.inspect_timeline", inspect)
    result = adapters.explain_video(inputs["source"], tmp_path / "out")
    assert result["fallback"] and Path(result["card_md"]).is_file()
    assert calls[0]["local_models_only"] is True and calls[0]["detect_transitions"] is True
    assert "study + inspect" in result["summary"][0]


def test_style_preferences_are_not_measurements():
    from myzing.director.selection import envelope
    from myzing.style_recipe import StyleRecipe, ObservationProvenance
    recipe = StyleRecipe(ObservationProvenance("brief.json"))
    for tone, pace in [("calm", 4), ("natural", 2), ("energetic", 1)]:
        result = adapters.style_envelope(envelope(recipe), {"no_reference": True, "tone": tone})
        assert result.median_shot == pace and "not a measurement" in result.basis["pacing"]
    assert recipe.measured == []


def test_studio_pace_preference_is_never_a_reference_band():
    """MATCH2 bands come from measured reference shots only."""
    from myzing.director.selection import envelope, reference_band
    from myzing.schemas import Breakdown, Shot, VideoMeta
    from myzing.style_recipe import StyleRecipe, ObservationProvenance, build_style_recipe
    preference = adapters.style_envelope(envelope(StyleRecipe(ObservationProvenance("brief.json"))),
                                         {"no_reference": True, "tone": "calm"})
    assert preference.median_shot == 4 and reference_band(preference.median_shot, preference)["lower"] is None
    measured = envelope(build_style_recipe(Breakdown(VideoMeta("ref", "file", duration=4, fps=30),
                                                     shots=[Shot(i, i * .8, (i + 1) * .8) for i in range(5)])))
    band = reference_band(measured.median_shot, measured)
    assert (band["lower"], band["upper"]) == pytest.approx((.55, 1.05))


def test_failed_drafts_shortages_and_next_actions_remain_visible(capsys):
    command.show_result({"status": "partial", "outputs": ["A.mp4"], "warnings": ["Blocked captions"],
                         "result": {"summary": "1 of 3 ready", "failures": [{"step": "render-B", "error": "failed"}],
                                    "shortages": [{"code": "footage_short"}]}, "next_actions": ["Try another track"]}, __import__("sys").stdout)
    text = capsys.readouterr().out
    assert all(s in text for s in ("1 of 3", "render-B", "footage_short", "Blocked captions", "Try another track"))


def test_no_reference_delegates_inventory_brief_study_and_director(inputs, monkeypatch):
    from myzing.studio.execute import no_reference
    from myzing.project.probe import parse_probe
    from myzing.studio.models import read_json
    probe = parse_probe({"format": {"duration": "18"}, "streams": [
        {"codec_type": "video", "width": 640, "height": 360, "avg_frame_rate": "30/1", "r_frame_rate": "30/1"}]})
    monkeypatch.setattr("myzing.project.api.probe_file", lambda _: probe)
    calls = []
    monkeypatch.setattr("myzing.study.api.study", lambda source, **kwargs: calls.append((source, kwargs)))
    def direct(root, recipe, out, **kwargs):
        calls.append(kwargs)
        assert read_json(recipe)["measured"] == []
        return {"status": "shortage", "summary": {"shortages": [{"code": "not_enough_distinct_footage"}]}}
    monkeypatch.setattr("myzing.director.api.plan_drafts", direct)
    a, _ = complete("b", inputs)
    a.update(tone="calm", captions="none")
    root = Path(inputs["project"])
    result = no_reference(a, root, lambda _: None)
    assert (root / "project.json").is_file() and (root / "brief.json").is_file()
    assert calls[0][1]["local_models_only"] and calls[0][1]["raw_mode"]
    assert calls[-1]["studio_options"] == {"no_reference": True, "tone": "calm", "captions": "none", "speech_model": "skip"}
    assert result["shortages"][0]["code"] == "not_enough_distinct_footage"


def test_supplied_music_inventory_uses_probe_and_hash_without_copying(inputs, monkeypatch):
    from myzing.project import api
    from myzing.project.probe import parse_probe
    from myzing.project.models import Probe
    from myzing.studio.models import read_json
    video = parse_probe({"format": {"duration": "18"}, "streams": [
        {"codec_type": "video", "width": 640, "height": 360, "avg_frame_rate": "30/1"}]})
    audio = parse_probe({"format": {"duration": "30"}, "streams": [{"codec_type": "audio"}]})
    monkeypatch.setattr(api, "probe_file", lambda _: video)
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda _: audio)
    root = Path(inputs["project"])
    api.init_project(inputs["source"], inputs["clips"], root)
    adapters.register_music(root, [inputs["track"]])
    manifest = api.load_project(root)
    music = next(a for a in manifest.assets if a.id.startswith("studio_music_"))
    assert music.state == "ready" and music.probe.has_audio
    assert music.sha256 == api.hash_file(Path(inputs["track"]))
    assert api.resolve_path(music.path, root) == Path(inputs["track"])
    assert not list(root.rglob("*.wav"))
    adapters.register_music(root, [inputs["track"]])
    assert len(api.load_project(root).assets) == 2


def test_mcp_runner_start_poll_cancel_owns_process_job(inputs, monkeypatch):
    import threading
    from myzing.studio import jobs
    gate = threading.Event()
    entered = threading.Event()
    a, _ = complete("f", inputs)
    def work(answers, *, progress, cancel, locked):
        assert locked and answers["path"] == "f"
        entered.set()
        assert cancel.wait(3), "test should cancel the owned job"
        raise KeyboardInterrupt()
    monkeypatch.setattr(jobs, "execute", work)
    result = jobs.job(a, confirmed=True)
    assert result["status"] == "started" and entered.wait(2)
    assert jobs.job(project=inputs["project"])["status"] == "running"
    assert jobs.job(project=inputs["project"], cancel=True)["cancellation_requested"] is True
    with jobs._LOCK:
        active = jobs._JOBS.get(inputs["project"])
    if active:
        active[0].join(3)
    assert jobs.job(project=inputs["project"])["status"] == "cancelled"
    assert load_session(inputs["project"]).status == "cancelled"


def test_reserved_output_cannot_replace_input_json(inputs):
    root = Path(inputs["project"])
    root.mkdir()
    source = root / "studio-session.json"
    source.write_text('{"original":true}')
    with pytest.raises(ValueError, match="replace input"):
        flow.next_step({"path": "f", "project": str(root), "source": str(source)})
    assert source.read_text() == '{"original":true}'


def test_session_versions_are_rejected_before_resume(inputs, monkeypatch):
    root = Path(inputs["project"])
    root.mkdir()
    (root / "studio-session.json").write_text('{"version":2,"answers":{}}')
    monkeypatch.setattr("sys.stdin", None)
    assert command.run(["--resume", str(root), "--json"]) == 1
    assert json.loads((root / "studio-session.json").read_text())["version"] == 2


def test_session_save_refuses_an_unrelated_file(inputs, monkeypatch):
    root = Path(inputs["project"])
    root.mkdir()
    target = root / "studio-session.json"
    target.write_text('{"original_plan":true}')
    monkeypatch.setattr("sys.stdin", io.StringIO(f"f\n{root}\n"))
    assert command.run([]) == 1
    assert target.read_text() == '{"original_plan":true}'


def test_redelivery_motion_failure_uses_disclosed_full_picture_fallback(tmp_path, monkeypatch):
    from myzing.studio.models import write_json, read_json
    calls = []
    report = tmp_path / "delivery.json"
    monkeypatch.setattr(adapters, "load_edit", lambda _: object())
    def render(plan, out, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ValueError("reframe keyframes exceed max_velocity")
        write_json(report, {"status": "ready", "deliveries": {}, "warnings": ["Original framing warning"]})
        return {"status": "ready", "report": str(report), "deliveries": {}, "warnings": ["Original framing warning"]}
    monkeypatch.setattr("myzing.render.deliveries.render_deliveries", render)
    result = adapters.deliver(tmp_path / "source.json", tmp_path / "out.mp4", ["1:1"])
    assert "framing" not in calls[0] and calls[1]["framing"] == "blurfill"
    assert "crop-motion bound" in result["warnings"][0]
    assert read_json(report)["warnings"] == result["warnings"]
    assert result["warnings"][1:] == ["Original framing warning"]


def test_public_results_link_instead_of_repeating_director_evidence():
    from myzing.studio.execute import _public_metadata
    result = _public_metadata({"deliveries": {"1:1": {"warnings": ["P17 planning evidence: {huge payload}",
                               "MUSIC1 evidence: {huge payload}", "Low resolution source"]}}, "plan": "plan.json"})
    assert result["deliveries"]["1:1"]["warnings"] == ["Low resolution source"]
    assert result["plan"] == "plan.json"


def test_phone_captions_preserve_words_and_times_in_short_groups():
    from myzing.director.plans import captions_for
    from myzing.schemas import Word
    words = [Word(text, i * .2, i * .2 + .18) for i, text in
             enumerate("one two three four five six seven eight nine".split())]
    sequence = [SimpleNamespace(asset_id="clip", start=0, end=2, duration=2)]
    studies = [SimpleNamespace(asset_id="clip", words=words)]
    style = SimpleNamespace(all_caps_rate=0, position="lower", words_visible=4)
    recipe = SimpleNamespace(approximations=SimpleNamespace(layout=None))
    brief = SimpleNamespace(exact_spellings=[])
    ordinary = captions_for(sequence, studies, style, recipe, None, brief)
    phone = captions_for(sequence, studies, style, recipe, None, brief, phone=True)
    assert [len(c.words) for c in ordinary] == [9]
    assert [len(c.words) for c in phone] == [4, 4, 1]
    assert [(w.text, w.start, w.end) for c in phone for w in c.words] == [(w.text, w.start, w.end) for w in words]
    assert all(c.style.size == 60 and c.font is None and c.layout is None for c in phone)


def test_mcp_declined_download_is_consent_error(inputs):
    from myzing.mcp_server import h_zing_studio, _err
    result = h_zing_studio("a", {"project": inputs["project"],
                               "reference": "https://example.invalid/reference.mp4", "allow_download": False})
    assert result == _err("Download declined. Go back to use a local reference or save and quit.")
    assert not Path(inputs["project"]).exists()


@pytest.mark.parametrize("owner_alive", [True, False])
def test_studio_cannot_cancel_a_foreign_job(inputs, monkeypatch, owner_alive):
    import os
    from myzing.studio.models import write_json, read_json
    from myzing.mcp_server import h_zing_studio_run
    root = Path(inputs["project"])
    root.mkdir()
    write_json(root / "studio-job.json", {"status": "running", "project": str(root), "pid": os.getpid() + 100000})
    monkeypatch.setattr("myzing.project.locking._pid_alive", lambda pid: owner_alive)
    result = h_zing_studio_run(project=str(root), cancel=True)
    assert result["ok"] and result["cancellation_requested"] is False
    assert result["status"] == ("running" if owner_alive else "interrupted")
    assert ("owning server" if owner_alive else "--resume") in result["hint"]
    assert "pid" not in result
    assert read_json(root / "studio-job.json")["status"] == result["status"]


def test_reference_summary_once_and_recommended_option_labels(inputs, monkeypatch, capsys):
    from myzing.studio.reference import describe
    ref = describe({"duration": 20, "aspect": "16:9", "sample_seconds": 20,
                    "cuts_per_minute": 63, "has_audio": True, "speech_present": True,
                    "music_present": True, "text_present": False, "text_samples": 3})
    monkeypatch.setattr("myzing.studio.reference.quick_read", lambda p: ref)
    monkeypatch.setattr("sys.stdin", io.StringIO(
        f"1\n{inputs['source']}\n{inputs['clips']}\na local story\n\n\n\n\nq\n"))
    assert command.run([]) == 0
    text = capsys.readouterr().out
    assert text.count("Your reference is 20.0 s, 16:9; about 63 cuts/min") == 1
    assert text.index("Reading the reference...") < text.index(ref["reason"])
    assert "Recommended: 5 (Keep source / reference shape)" in text
    assert "Recommended: 1 (No added captions)" in text
    assert "Recommended: 1 (Keep my clips' audio)" in text
    assert "Recommended: original" not in text and "Recommended: none" not in text
    assert load_session(inputs["project"]).questions_asked == 9


def test_explain_success_summary_and_all_cards_reach_finish(inputs, monkeypatch):
    from myzing.studio.execute import run_confirmed
    from myzing.studio.models import read_json
    from myzing.explain import api
    calls = []
    def explain(source, out, **kwargs):
        calls.append((source, kwargs))
        paths = {f"card_{suffix}": str(Path(out) / f"card.{suffix}") for suffix in ("json", "md", "png")}
        for file in paths.values():
            Path(file).write_bytes(b"test card placeholder")
        return {"ok": True, **paths, "summary": ["Twenty seconds; measured rapid cuts.", "No text detected in sampled frames."]}
    monkeypatch.setattr(api, "explain_video", explain)
    a, _ = complete("d", inputs)
    result = run_confirmed(a)
    assert result["ok"] and calls == [(inputs["source"], {"transitions": True, "offline": True})]
    assert read_json(Path(inputs["project"]) / "studio-result.json") == result
    screen = io.StringIO()
    command.show_result(result, screen)
    text = screen.getvalue()
    for line in result["result"]["summary"]:
        assert text.count(line) == 1
    for suffix in ("json", "md", "png"):
        assert f"card.{suffix}" in text
    assert "fallback" not in text


# STUDIO1 review regressions (each reproduced against a7f33a7 first).

def test_b_at_the_first_question_means_back_not_path_b(inputs, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(f"b\n2\n{inputs['clips']}\nq\n"))
    assert command.run([]) == 0
    text = capsys.readouterr().out
    opening = text.split("Which folder", 1)[0]
    assert "Already at the first question" in opening and "b goes back" not in opening
    state = load_session(inputs["project"])
    assert state.answers["path"] == "b" and state.answers["clips"] == inputs["clips"]
    assert state.history == ["path", "clips"]


@pytest.mark.parametrize("typed, posix, expected", [
    ('"C:\\My Clips\\ref.mp4"', False, "C:\\My Clips\\ref.mp4"),       # Windows Explorer drag
    ('"C:\\My Clips\\ref.mp4" ', False, "C:\\My Clips\\ref.mp4"),
    ("'/srv/footage/My Clips' ", True, "/srv/footage/My Clips"),        # GNOME Terminal drag
    ("/Volumes/Footage/My\\ Clips/ref\\ 1.mp4 ", True, "/Volumes/Footage/My Clips/ref 1.mp4"),  # macOS Terminal drag
    ("C:\\My\\ Clips", False, "C:\\My\\ Clips"),                        # Windows backslashes are separators
])
def test_dragged_paths_lose_terminal_quoting(typed, posix, expected):
    assert flow.clean_path_text(typed, posix=posix) == expected


def test_single_quoted_folder_is_accepted(inputs):
    assert flow.normalize("clips", f"'{inputs['clips']}'") == inputs["clips"]
    with pytest.raises(ValueError, match="local folder"):
        flow.normalize("clips", '"\\\\server\\share\\clips"')
    # POSIX unescaping must not turn a pasted share path into a relative one.
    assert flow.clean_path_text("\\\\server\\share\\clips", posix=True) == "\\\\server\\share\\clips"
    assert flow.clean_path_text("/tmp/my\\ clips", posix=True) == "/tmp/my clips"


def test_output_folder_that_collides_is_refused_and_not_written(inputs, monkeypatch, capsys):
    clips = Path(inputs["clips"])
    monkeypatch.setattr("sys.stdin", io.StringIO(f"2\n{clips}\ndemo\n2\n8\n\n\n\nskip\no\n{clips}\nq\n"))
    assert command.run([]) == 0
    assert "Keeping " + inputs["project"] in capsys.readouterr().out
    assert not (clips / "studio-session.json").exists()
    assert load_session(inputs["project"]).answers["project"] == inputs["project"]


def test_cancelled_match_saves_and_says_how_to_continue(inputs, monkeypatch, capsys):
    cancelled = {"ok": False, "status": "cancelled", "project": inputs["project"], "outputs": [], "warnings": [],
                 "result": {"drafts": {}}, "next_actions": []}
    monkeypatch.setattr("myzing.studio.execute.run_confirmed", lambda answers, **_: cancelled)
    a, _ = complete("a", inputs)
    file = Path(inputs["project"]).parent / "answers.json"
    file.write_text(json.dumps(a))
    assert command.run(["--answers", str(file), "--yes"]) == 0
    text = capsys.readouterr().out
    assert "Continue: zing studio --resume" in text and "Studio: cancelled" not in text
    state = load_session(inputs["project"])
    assert state.status == "paused" and state.result["status"] == "cancelled"


def test_shortage_notes_name_the_blocker_and_actions_point_at_resume(inputs, monkeypatch):
    from myzing.studio.presentation import creator_summary
    from myzing.studio.execute import run_confirmed
    monkeypatch.setattr("myzing.studio.evidence.speech_model_note", lambda: "The speech model 'large-v2' is not downloaded, and studio never downloads models. More.")
    study = {"code": "study_required", "missing": "No project clip has a usable study.", "remedy": "Run zing study."}
    result = {"project": inputs["project"], "status": "shortage", "warnings": [], "result": {"shortages": [study]}}
    notes = creator_summary(result, {"path": "b"}, {"clips": []})["notes"]
    assert "not enough usable moments" not in notes[0] and "'large-v2' is not downloaded" in notes[0]
    result["result"]["shortages"] = [{"code": "target_length", "missing": "Only 3s", "remedy": "Shorten."}]
    assert "not enough usable moments" in creator_summary(result, {"path": "b"}, {})["notes"][0]
    result["result"]["shortages"] = [{"code": "font_asset", "missing": "Font asset_0123abcd missing.", "remedy": "Restore it."}]
    assert creator_summary(result, {"path": "b"}, {})["notes"][0] == "Planning stopped: Font missing. Restore it."
    monkeypatch.setattr(adapters, "explain_video", lambda *a, **k: {"ok": False, "error": "no video stream"})
    a, _ = complete("d", inputs)
    failed = run_confirmed(a)
    assert failed["next_actions"][0].startswith("Fix the error above, then retry: zing studio --resume")
    assert not any("style card" in action for action in failed["next_actions"])


def test_fallback_notes_hide_internal_ids_fields_and_pre_run_caveats(inputs):
    from myzing.studio.presentation import creator_summary
    warnings = ["A/B/C can be blocked by footage shortages or invalid speech timing; no missing words or style measurements are invented.",
                "ASR repair tos.mp4: 1 word timings interpolated; originals retained in inventory.asr_repair.",
                "caption geometry: 224 coverage gap(s); see caption-geometry.json",
                "font candidates track text-0007: insufficient glyph pixels",
                "captions[3] reads at 27.8 characters/second; guidance allows 20",
                "Source audio follows each clip. 'none' adds no music/SFX; it does not remove embedded sounds."]
    result = {"project": inputs["project"], "status": "ready", "warnings": warnings, "result": {}}
    assert creator_summary(result, {"path": "e"}, {"clips": []})["notes"] == [warnings[-1]]
    # A finished edit counts its disclaimers instead of listing engine jargon (V1 HD run: 81).
    rows = {"A.16x9": {"status": "ready", "video": "A.mp4", "plan": "A.json", "dimensions": {"color": {"status": "pass"}}}}
    result["result"] = {"drafts": rows}
    assert creator_summary(result, {"path": "a"}, {"clips": []})["notes"] == [
        "6 detailed notes on measurement limits, color and framing are in the full result."]
    result["warnings"] = [*warnings, "clip clip-2: Selected zoomfill: crop enlargement 5.455x exceeds 2.5x"]
    assert creator_summary(result, {"path": "a"}, {})["notes"] == [
        "Some shots are enlarged more than 2.5x to fill the frame; check them for softness."]


def test_agent_sessions_default_inside_the_zing_workspace(inputs, tmp_path, monkeypatch):
    from myzing import storage
    from myzing.mcp_server import h_zing_studio
    elsewhere = tmp_path / "server-cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    response = h_zing_studio(path="d", answers={"source": inputs["source"]})
    assert response["ok"] and response["status"] == "plan"
    project = Path(response["answers"]["project"])
    assert project.parent == storage.resolve_workspace() and project.name == "studio"
    assert not (elsewhere / "zing-workspace").exists() and not project.exists()


def test_two_terminal_sessions_in_one_folder_claim_different_projects(tmp_path, monkeypatch, zing_workspace):
    monkeypatch.chdir(tmp_path)
    first, second = flow.reserve_project(), flow.reserve_project()
    assert Path(first).name == "studio" and Path(second).name == "studio-2"
    assert Path(first).is_dir() and Path(second).is_dir()


def test_style_breakdown_default_output_moves_out_of_the_video_folder(tmp_path, monkeypatch, zing_workspace):
    from myzing import storage
    probe = {"duration": 8.0, "width": 1280, "height": 720, "orientation": "landscape", "has_audio": True,
             "flags": [], "streams": [{"codec_type": "video"}], "notes": []}
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(to_dict=lambda: probe))
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "talk.mp4").write_bytes(b"stub")
    monkeypatch.chdir(videos)
    step = flow.next_step({"path": "d", "source": str(videos / "talk.mp4"), "project": flow.default_project()})
    assert step["status"] == "plan" and Path(step["plan"]["output_folder"]).parent == storage.resolve_workspace()
    assert not any("Low-resolution" in w for w in step["plan"]["warnings"])
    with pytest.raises(ValueError, match="outside the video's folder"):
        flow.next_step({"path": "d", "source": str(videos / "talk.mp4"), "project": str(videos / "mine")})


def test_reference_shape_follows_display_rotation_and_bad_files_stop_early(inputs, monkeypatch, capsys):
    from myzing.studio import reference
    rotated = {"duration": 8.0, "width": 1280, "height": 720, "rotation": 90.0, "orientation": "portrait",
               "has_audio": False, "flags": []}
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(to_dict=lambda: rotated))
    def stop(*args, **kwargs):
        raise RuntimeError("sample not needed")
    monkeypatch.setattr("myzing.study.proc.run", stop)
    with pytest.raises(RuntimeError):
        reference._worker(inputs["source"], str(Path(inputs["project"]).parent))
    first = json.loads(capsys.readouterr().out.splitlines()[0])["data"]
    assert first["aspect"] == "9:16" and first["orientation"] == "portrait"
    assert [reference.aspect_label(*size) for size in [(1920, 1080), (1920, 1088), (862, 360)]] == ["16:9", "about 16:9", "862x360"]
    portrait = reference.describe({"duration": 8.0, "aspect": "9:16", "orientation": "portrait", "sample_seconds": 8})
    monkeypatch.setattr("myzing.studio.reference.quick_read", lambda p: portrait)
    step = flow.next_step({"path": "a", "project": inputs["project"], "reference": inputs["source"],
                           "clips": inputs["clips"], "topic": "t", "platform": "original", "length": 8,
                           "captions": "none", "music": "original"})
    assert step["answers"]["aspects"] == ["9:16"]
    for read, message in [({"no_video": True}, "no video stream"), ({"unreadable": "moov atom not found"}, "cannot be read")]:
        monkeypatch.setattr("myzing.studio.reference.quick_read", lambda p, read=read: reference.describe(dict(read)))
        with pytest.raises(ValueError, match=message):
            flow.next_step({"path": "a", "project": inputs["project"], "reference": inputs["source"]})


def test_long_reference_length_names_the_cap(inputs, monkeypatch):
    from myzing.studio.reference import describe
    monkeypatch.setattr("myzing.studio.reference.quick_read",
                        lambda p: describe({"duration": 1200.0, "aspect": "16:9", "sample_seconds": 20}))
    a = {"path": "a", "project": inputs["project"], "reference": inputs["source"], "clips": inputs["clips"],
         "topic": "t", "platform": "original"}
    q = flow.next_step(a)["question"]
    assert q["id"] == "length" and q["recommended"] == 60
    assert "closest length studio supports" in q["reason"] and "follow it" not in q["reason"]


def test_caption_reason_reports_measured_speech_absence(inputs, monkeypatch):
    from myzing.studio.reference import describe
    read = describe({"duration": 8.0, "aspect": "16:9", "sample_seconds": 8, "has_audio": True,
                     "speech_present": False, "speech_ratio": 0.0, "text_present": True, "text_samples": 3})
    monkeypatch.setattr("myzing.studio.reference.quick_read", lambda p: read)
    a = {"path": "a", "project": inputs["project"], "reference": inputs["source"], "clips": inputs["clips"],
         "topic": "t", "platform": "original", "length": 8}
    q = flow.next_step(a)["question"]
    assert q["id"] == "captions" and q["recommended"] == "none"
    assert "speech 0%" in read["reason"] and "no speech detected" in q["reason"] and "unknown" not in q["reason"]


def test_invalid_answers_json_names_the_file(tmp_path, monkeypatch, capsys):
    file = tmp_path / "answers.json"
    file.write_text("not json")
    monkeypatch.chdir(tmp_path)
    assert command.run(["--answers", str(file)]) == 1
    assert "answers.json is not valid JSON" in capsys.readouterr().err
    assert not (tmp_path / "zing-workspace").exists()


def test_concurrent_sessions_wait_for_the_save_lock_and_get_a_studio_busy_message(inputs):
    import threading
    import time
    from myzing.match.process import run_lock
    from myzing.project.locking import project_lock
    from myzing.studio import jobs
    from myzing.studio.models import save_session
    root = Path(inputs["project"])
    root.mkdir()
    held = threading.Event()
    def hold():
        with project_lock(root):
            held.set()
            time.sleep(.3)
    thread = threading.Thread(target=hold)
    thread.start()
    held.wait(5)
    save_session(root, Session(answers={"path": "d", "project": str(root)}))  # waits instead of failing
    thread.join()
    assert not (root / ".project.lock").exists()
    with run_lock(root):
        with pytest.raises(ValueError, match="Another studio session is already making something"):
            jobs.execute({"path": "d", "project": str(root)})


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows sharing violation on rename")
def test_project_lock_release_retries_a_transient_sharing_violation(tmp_path, monkeypatch):
    from myzing.project import locking
    calls = []
    original = Path.rename
    def rename(self, target):
        calls.append(self.name)
        if self.name == locking.LOCK_NAME and len(calls) < 3:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return original(self, target)
    monkeypatch.setattr(Path, "rename", rename)
    with locking.project_lock(tmp_path):
        pass
    assert len(calls) == 3 and not (tmp_path / locking.LOCK_NAME).exists()


def test_plan_reports_explicit_skip(inputs):
    _, plan = complete("b", inputs)
    assert any("captions and whole-line continuity are unavailable" in w for w in plan["warnings"])
