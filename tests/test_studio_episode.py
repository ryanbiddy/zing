"""Episode interviews and factory hand-offs without renders, peers or browsers."""
from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from myzing import doctor, mcp_server, suite_peer, uoink_bridge
from myzing.factory import judge, pipeline, serve, source
from myzing.studio import command, episode, flow
from myzing.studio.models import load_session, read_json


@pytest.fixture
def inputs(tmp_path, monkeypatch, zing_workspace):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"local episode")
    transcript = media.with_suffix(".srt")
    transcript.write_text("1\n00:00:00,000 --> 00:01:30,000\nA complete episode.\n", encoding="utf-8")
    root = tmp_path / "project"
    probe = {"duration": 1800., "width": 1920, "height": 1080, "has_audio": True,
             "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(to_dict=lambda: dict(probe)))
    monkeypatch.setattr(flow, "default_project", lambda: str(root))
    monkeypatch.setattr(episode.shutil, "which", lambda name: None)

    def refuse(*args, **kwargs):
        pytest.fail("unmocked external operation")

    monkeypatch.setattr(judge.Judge, "ask", refuse)
    monkeypatch.setattr(pipeline, "run", refuse)
    monkeypatch.setattr(source, "transcribe_episode", refuse)
    monkeypatch.setattr(uoink_bridge, "resolve_kept_media", refuse)
    monkeypatch.setattr(serve, "serve", refuse)
    monkeypatch.setattr("webbrowser.open", refuse)
    return SimpleNamespace(media=media, transcript=transcript, project=root, probe=probe)


def complete(inputs, **overrides):
    a = {"path": "g", "episode": str(inputs.media), **overrides}
    questions = []
    for _ in range(8):
        step = flow.next_step(a)
        a = step["answers"]
        if step["status"] == "plan":
            return a, step["plan"], questions
        q = step["question"]
        questions.append(q)
        assert q["reason"] and q["recommended"] is not None
        a[q["id"]] = q["recommended"]
    pytest.fail("interview did not finish")


def answers_file(inputs, **overrides):
    answers, _, _ = complete(inputs, **overrides)
    file = inputs.project.parent / "answers.json"
    file.write_text(json.dumps(answers), encoding="utf-8")
    return file


def test_menu_keeps_existing_numbers_and_offers_episode_last(inputs):
    q = flow.next_step()["question"]
    assert [o["value"] for o in q["options"]] == list("abcdefg")
    assert q["options"][-1]["label"] == "Turn a long episode into Shorts (podcast, talk or stream)"
    assert q["recommended"] == "a"
    assert [flow.normalize("path", str(i)) for i in range(1, 8)] == list("abcdefg")
    only = {"episode": str(inputs.media)}
    assert flow.next_step(only)["question"]["recommended"] == "g"
    assert flow.next_step({**only, "reference": str(inputs.media)})["question"]["recommended"] == "a"
    question = mcp_server.h_zing_studio("g")["question"]
    assert question["id"] == "episode" and question["required"] and question["reason"]


@pytest.mark.parametrize("claude", [False, True])
def test_recommendations_and_plan_use_episode_evidence(inputs, monkeypatch, claude):
    monkeypatch.setattr(episode.shutil, "which", lambda name: "claude" if claude and name == "claude" else None)
    a, plan, questions = complete(inputs)
    assert [q["id"] for q in questions] == ["transcript", "clips", "shapes", "judge", "project"]
    assert a["transcript"] == str(inputs.transcript)
    assert a["clips"] == 3 and a["shapes"] == ["9x16"]
    assert a["judge"] == ("claude" if claude else "host")
    if not claude:
        assert "you or your agent" in questions[3]["reason"].lower()
        assert "review page" in questions[3]["reason"] and "zing factory answer" in questions[3]["reason"]
    assert plan["episode"] == str(inputs.media) and plan["duration"] == 1800
    assert plan["project"] == str(inputs.project) and plan["confirmation_required"]
    assert plan["execution"][0]["tool"] == "zing_studio_run"
    screen = io.StringIO()
    command.show_plan(plan, screen)
    assert "30:00" in screen.getvalue() and all(label in screen.getvalue() for label in ("Episode", "Length", "Transcript", "Clips", "Shapes", "Judge", "Project"))
    assert not inputs.project.exists()


@pytest.mark.parametrize("suffix", [".srt", ".vtt", ".json", None])
def test_transcript_siblings_have_priority_and_enter_accepts(inputs, suffix):
    inputs.transcript.unlink()
    extensions = (".srt", ".vtt", ".json")
    for ext in extensions[extensions.index(suffix):] if suffix else ():
        inputs.media.with_suffix(ext).write_text("[]", encoding="utf-8")
    q = flow.next_step({"path": "g", "episode": str(inputs.media)})["question"]
    assert q["recommended"] == (str(inputs.media.with_suffix(suffix)) if suffix else "none")
    assert command._answer(q, "") == q["recommended"]
    assert command._answer(q, "none") == "none"
    screen = io.StringIO()
    command.show_question(q, screen)
    assert "Enter accepts" in screen.getvalue()


@pytest.mark.parametrize("url", ["https://example.invalid/episode.mp4", "http://example.invalid/talk", "ftp://example.invalid/episode"])
def test_episode_urls_are_refused(inputs, url):
    with pytest.raises(ValueError, match="zing from-uoink.*download"):
        flow.next_step({"path": "g", "episode": url})
    assert not inputs.project.exists()


@pytest.mark.parametrize("duration", [1, 59.99])
def test_short_episodes_are_refused(inputs, duration):
    inputs.probe["duration"] = duration
    with pytest.raises(ValueError, match="at least 60 seconds"):
        complete(inputs)


@pytest.mark.parametrize("duration", [None, float("nan"), float("inf"), 0])
def test_unknown_duration_is_refused(inputs, duration):
    inputs.probe["duration"] = duration
    with pytest.raises(ValueError, match="measure the episode duration"):
        complete(inputs)


def test_video_at_the_minimum_duration_is_accepted(inputs):
    inputs.probe.update(duration=60)
    _, plan, _ = complete(inputs)
    assert plan["duration"] == 60


@pytest.mark.parametrize("streams", [[{"codec_type": "audio"}],
                                     [{"codec_type": "audio"}, {"codec_type": "video", "disposition": {"attached_pic": 1}}]])
def test_audio_only_episodes_are_refused(inputs, streams):
    inputs.probe.update(duration=600, width=None, height=None, streams=streams)
    audio = inputs.media.with_suffix(".mp3")
    audio.write_bytes(b"local audio")
    with pytest.raises(ValueError, match="needs a video file"):
        complete(inputs, episode=str(audio))



@pytest.mark.parametrize("clips", [0, 13, True, 1.5, "two"])
def test_clip_count_is_bounded(inputs, clips):
    with pytest.raises(ValueError, match="1 to 12"):
        complete(inputs, clips=clips)


def test_clip_count_does_not_change_clip_folder_answers(inputs):
    assert flow.normalize("clips", str(inputs.media.parent)) == str(inputs.media.parent)
    for count in (1, 12):
        a, _, _ = complete(inputs, clips=str(count), shapes="9x16,1x1,4x5,16x9")
        assert a["clips"] == count and a["shapes"] == list(episode.SHAPES)
    for value in ([], ["9x16", "9x16"], "4x3"):
        with pytest.raises(ValueError, match="shapes|9x16"):
            complete(inputs, shapes=value)


@pytest.mark.parametrize("no_open", [False, True, "answer"])
def test_confirmation_uses_factory_new_and_dashboard(inputs, monkeypatch, capsys, no_open):
    file = answers_file(inputs, **({"no_open": True} if no_open == "answer" else {}))
    calls, pages, opened = [], [], []
    original = pipeline.init

    def init(project, media, **settings):
        calls.append((project, media, settings))
        return original(project, media, **settings)

    def dashboard(project, **kwargs):
        pages.append((project, kwargs))
        assert load_session(project).status == "ready"
        kwargs["ready"]("http://127.0.0.1:12345/?t=test")

    monkeypatch.setattr(pipeline, "init", init)
    monkeypatch.setattr(serve, "serve", dashboard)
    monkeypatch.setattr("webbrowser.open", opened.append)
    assert command.run(["--answers", str(file), "--json"]) == 0
    assert not calls and not pages
    capsys.readouterr()
    assert command.run(["--answers", str(file), "--yes", "--json", *(["--no-open"] if no_open is True else [])]) == 0
    assert calls == [(inputs.project, inputs.media, {"transcript": inputs.transcript, "name": "episode",
                     "rights": "unknown", "moments": 3, "shapes": ["9x16"]})]
    assert pages[0][0] == inputs.project and pages[0][1]["port"] == 0
    assert pages[0][1]["judge"] == "host" and pages[0][1]["idle_seconds"] == 3600
    event = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert event["event"] == "result" and event["project"] == str(inputs.project)
    assert event["page"] == "http://127.0.0.1:12345/?t=test"
    assert opened == ([] if no_open else [event["page"]])
    assert read_json(inputs.project / "factory.json")["rights"] == "unknown"


def test_stdin_pause_resume_and_finished_resume_keep_project(inputs, monkeypatch, capsys):
    pages = []
    monkeypatch.setattr(serve, "serve", lambda project, **kw: (pages.append(project), kw["ready"]("http://127.0.0.1:12345/")))
    monkeypatch.setattr("sys.stdin", io.StringIO(f"7\n{inputs.media}\nq\n"))
    assert command.run(["--no-open"]) == 0
    assert load_session(inputs.project).status == "paused" and not pages
    monkeypatch.setattr("sys.stdin", io.StringIO("\n\n\n\nyes\n"))
    assert command.run(["--resume", str(inputs.project)]) == 0
    text = capsys.readouterr().out
    assert "Press Run to begin." in text and f'zing factory status "{inputs.project}"' in text
    assert load_session(inputs.project).answers["transcript"] == str(inputs.transcript)  # Enter took the sibling
    assert (inputs.project / "transcript.json").exists()
    settings = read_json(inputs.project / "factory.json")
    marker = inputs.project / "ratings.json"
    marker.write_text('{"clip01":{"v":"post"}}', encoding="utf-8")
    monkeypatch.setattr(pipeline, "init", lambda *a, **kw: pytest.fail("resume recreated the project"))
    assert command.run(["--resume", str(inputs.project), "--yes"]) == 0
    assert len(pages) == 2 and read_json(marker)["clip01"]["v"] == "post"
    assert read_json(inputs.project / "factory.json") == settings


def test_mcp_creates_project_and_returns_factory_next_steps(inputs):
    a, _, _ = complete(inputs)
    assert mcp_server.h_zing_studio(answers=a)["status"] == "plan"
    assert not mcp_server.h_zing_studio_run(a)["ok"] and not inputs.project.exists()
    result = mcp_server.h_zing_studio_run(a, confirmed=True)
    assert result["ok"] and result["project"] == str(inputs.project) and "page" not in result
    assert [step["tool"] for step in result["execution"]] == ["factory_run", "factory_status"]
    assert "factory_run" in result["hint"] and "factory_status" in result["hint"]
    assert load_session(inputs.project).status == "ready"
    assert mcp_server.h_zing_studio_run(a, confirmed=True)["reused"]


def test_claude_dashboard_and_partial_resume_answers(inputs, monkeypatch):
    file = answers_file(inputs, judge="claude")
    pages = []
    monkeypatch.setattr(serve, "serve", lambda project, **kw: (pages.append(kw["judge"]), kw["ready"]("http://127.0.0.1:12345/")))
    assert command.run(["--answers", str(file), "--no-open"]) == 0
    file.write_text('{"clips":12,"shapes":["4x5","16x9"]}', encoding="utf-8")
    assert command.run(["--resume", str(inputs.project), "--answers", str(file), "--yes"]) == 0
    assert pages == ["claude"]
    settings = read_json(inputs.project / "factory.json")
    assert settings["moments"] == 12 and settings["shapes"] == ["4x5", "16x9"]


def test_mcp_defaults_to_a_project_in_the_zing_workspace(inputs):
    from myzing import storage
    a, _, _ = complete(inputs)
    a.pop("project")
    response = mcp_server.h_zing_studio(answers=a)
    root = Path(response["answers"]["project"])
    assert root.parent == storage.resolve_workspace() and not root.exists()
    result = mcp_server.h_zing_studio_run(response["answers"], confirmed=True)
    assert result["ok"] and result["project"] == str(root) and (root / "factory.json").is_file()


def test_another_episode_cannot_replace_a_factory_project(inputs):
    a, _, _ = complete(inputs)
    assert mcp_server.h_zing_studio_run(a, confirmed=True)["ok"]
    original = (inputs.project / "source.json").read_bytes()
    other = inputs.media.with_name("other.mp4")
    other.write_bytes(b"another episode")
    result = mcp_server.h_zing_studio_run({**a, "episode": str(other)}, confirmed=True)
    assert not result["ok"] and "another episode" in result["error"]
    assert (inputs.project / "source.json").read_bytes() == original


def test_uoink_episode_uses_handoff_verification(inputs, monkeypatch):
    from myzing.project.api import hash_file
    data = {"state": "available", "media": {"path": str(inputs.media), "sha256": hash_file(inputs.media),
                                           "byte_length": inputs.media.stat().st_size}}
    refs = []
    monkeypatch.setattr(uoink_bridge, "resolve_kept_media", lambda ref: (refs.append(ref) or {"ok": True, "data": data}))
    a, plan, _ = complete(inputs, episode="uoink:episode-1")
    assert plan["episode"] == str(inputs.media) and set(refs) == {"uoink://item/episode-1"}
    result = mcp_server.h_zing_studio_run(a, confirmed=True)
    assert result["ok"] and read_json(inputs.project / "factory.json")["uoink_ref"] == "uoink://item/episode-1"
    data["media"]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="kept media is unavailable"):
        flow.next_step(a)


def test_uoink_without_kept_media_never_downloads(inputs, monkeypatch):
    monkeypatch.setattr(uoink_bridge, "resolve_kept_media", lambda ref: {"ok": True, "data": {"state": "not_kept"}})
    with pytest.raises(ValueError, match="zing from-uoink"):
        complete(inputs, episode="uoink:episode-1")
    assert not inputs.project.exists()


def test_inputs_and_existing_projects_are_not_overwritten(inputs):
    inputs.project.mkdir()
    transcript = inputs.project / "source.json"
    transcript.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="replace input"):
        complete(inputs, project=str(inputs.project), transcript=str(transcript))
    a, _, _ = complete(inputs, project=str(inputs.project))
    result = mcp_server.h_zing_studio_run(a, confirmed=True)
    assert not result["ok"] and "fresh project" in result["error"]
    assert transcript.read_text() == "[]"


def test_doctor_refused_connection_names_the_current_url(monkeypatch):
    url = "http://127.0.0.1:1"
    monkeypatch.setenv("UOINK_URL", url)
    monkeypatch.setattr(suite_peer, "_get_json", lambda *a: (_ for _ in ()).throw(URLError("connection refused")))
    monkeypatch.setattr(doctor, "_probe_uoink_cached", suite_peer.probe_uoink)
    check = doctor.check_uoink()
    assert check.data["peer"]["error"]["code"] == "unavailable"
    assert check.fix == f"start Uoink, or check UOINK_URL (currently {url})"


@pytest.mark.parametrize("code,fix", [("timeout", "start Uoink"), ("authentication_failed", "check UOINK_TOKEN"),
                                    ("invalid_configuration", "check UOINK_URL"),
                                    ("contract_mismatch", "INTEGRATION-CONTRACT v1"), ("wrong_service", "INTEGRATION-CONTRACT v1")])
def test_doctor_keeps_auth_configuration_and_contract_fixes_separate(monkeypatch, code, fix):
    peer = {"state": "unhealthy", "error": {"code": code, "message": "test failure"}}
    monkeypatch.setattr(doctor, "_probe_uoink_cached", lambda: (peer, "fake probe"))
    assert fix in doctor.check_uoink().fix
