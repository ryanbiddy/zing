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
                "photos": inputs["photos"], "source": inputs["source"], "tracks": [inputs["track"]], "topic": "one quick fix"}
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
        transcript.append(";".join(value) if key == "tracks" else ",".join(value) if isinstance(value, list)
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
        assert state.questions_asked <= 8


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
        a[q["id"]] = q["recommended"]
    assert [q["id"] for q in questions] == ["platform", "length", "captions", "music"]
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
    text = f"b\n{inputs['clips']}\nb\n?\n{inputs['clips']}\nq\n"
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
    for path, tool in [("a", "match_start"), ("c", "still_concepts"), ("e", "music_check")]:
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
    assert calls[-1]["studio_options"] == {"no_reference": True, "tone": "calm", "captions": "none"}
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
    assert result["status"] == ("running" if owner_alive else "failed")
    assert "owning server" in result["hint"]
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
    assert load_session(inputs["project"]).questions_asked == 8


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
