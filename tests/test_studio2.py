"""Studio interview limits, probe reuse, consent and answer provenance."""

import io
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.studio import command, evidence, flow, reference
from myzing.studio.models import Session, load_session, save_session
from test_studio import inputs


@pytest.mark.parametrize("path", ["a", "b", "d"])
@pytest.mark.parametrize("footage", ["general", "screen"])
@pytest.mark.parametrize("kind", ["short", "long", "url"])
@pytest.mark.parametrize("speech", ["skip", "download small.en"])
@pytest.mark.parametrize("custom", [False, True])
def test_every_interview_branch_has_at_most_ten_questions(inputs, monkeypatch, path, footage, kind, speech, custom):
    source = Path(inputs["source"])
    duration = 120 if kind == "long" else 18
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(to_dict=lambda: {
        "duration": duration, "width": 640, "height": 360, "orientation": "landscape", "has_audio": True}))
    monkeypatch.setattr(reference, "quick_read", lambda p, **kw: {"reason": "Fixture preview", "warnings": []})
    monkeypatch.setattr("myzing.study.speech_models.local_path", lambda name: None)
    supplied = {"path": path, "reference": "https://example.invalid/ref.mp4" if kind == "url" else str(source),
                "source": str(source), "clips": inputs["clips"], "footage_kind": footage,
                "reference_range": "0:30-1:20", "reference_download": "yes 0:30-1:20",
                "topic": "A local demonstration", "speech_setup": speech}
    if custom:
        supplied["platform"] = "16:9,1:1"
        # A discovered cursor log adds one question on screen branches.
        root = Path(inputs["project"])
        root.mkdir()
        (root / "cursor.jsonl").touch()
    answers, cache, questions = {"project": inputs["project"]}, {}, []
    for _ in range(16):
        step = flow.next_step(answers, cache=cache)
        answers = step["answers"]
        if step["status"] == "plan":
            break
        assert step["status"] == "question"
        q = step["question"]
        questions.append(q["id"])
        answers[q["id"]] = supplied.get(q["id"], q["recommended"])
    assert step["status"] == "plan", questions
    assert len(questions) <= 10, questions
    if path == "a" and kind == "url":
        assert answers["allow_download"] is True and answers["reference_range"] == "0:30-1:20"
        if footage == "general":
            assert answers["length"] == 50
    if path in "ab":
        assert answers.get("speech_download", False) is speech.startswith("download ")
        if footage == "screen":
            assert answers["cursor_log"] == "none"
            if not custom:
                assert any("No cursor log" in w for w in step["plan"]["warnings"])
    else:
        # Explain is local-only; reference kind and footage do not add questions.
        assert questions == ["path", "source"]


@pytest.mark.parametrize("path", ["a", "d"])
def test_one_probe_per_reference_version_and_interview(inputs, monkeypatch, path):
    calls = []
    def probe(p):
        calls.append(p)
        return SimpleNamespace(to_dict=lambda: {"duration": 18, "width": 640, "height": 360,
                                                "orientation": "landscape", "has_audio": True})
    monkeypatch.setattr("myzing.project.probe.probe_file", probe)
    source = Path(inputs["source"])
    answers = {"path": path, "project": inputs["project"], "reference" if path == "a" else "source": str(source)}
    cache = {}
    for _ in range(9):
        flow.next_step(answers, cache=cache)
    assert calls == [source]
    # Size changes invalidate even if the timestamp is restored.
    stat = source.stat()
    source.write_bytes(source.read_bytes() + b"changed")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    flow.next_step(answers, cache=cache)
    assert len(calls) == 2
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    flow.next_step(answers, cache=cache)
    assert len(calls) == 3
    flow.next_step(answers, cache={})
    assert len(calls) == 4


@pytest.mark.parametrize("path", ["a", "d"])
@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("ffprobe", 120), OSError("unavailable"),
                                  subprocess.CalledProcessError(1, "ffprobe"), ValueError("bad metadata")])
def test_failed_probe_is_unknown_and_cached(inputs, monkeypatch, path, error):
    calls = []
    def stalled(p):
        calls.append(p)
        raise error
    monkeypatch.setattr("myzing.project.probe.probe_file", stalled)
    answers = {"path": path, "project": inputs["project"], "reference" if path == "a" else "source": inputs["source"]}
    cache = {}
    for _ in range(3):
        step = flow.next_step(answers, cache=cache)
        if path == "a":
            assert "duration is unknown" in step["question"]["prompt"]
        else:
            assert any("Cannot probe" in s for s in step["plan"]["evidence"]["unknowns"])
    assert len(calls) == 1


@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("trim", [{"reference_range": "0:30-1:31"}, {"ref_start": 30, "ref_end": 91}, {"ref_end": 61}])
def test_unknown_duration_rejects_overlong_range_before_preview(inputs, monkeypatch, remote, trim):
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: (_ for _ in ()).throw(RuntimeError("failed")))
    monkeypatch.setattr(evidence, "collect", lambda *a: pytest.fail("preview before range validation"))
    with pytest.raises(ValueError, match="supported limit is 60s"):
        flow.next_step({"path": "a", "reference": "https://example.invalid/video" if remote else inputs["source"],
                        "project": inputs["project"], **trim})


@pytest.mark.parametrize("trim", [{}, {"reference_range": "0:30-1:31"}, {"ref_start": 0, "ref_end": 61}])
def test_preview_worker_enforces_the_same_limit(inputs, monkeypatch, trim):
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(to_dict=lambda: {"duration": 120}))
    monkeypatch.setattr("myzing.study.proc.run", lambda *a, **k: pytest.fail("decoded an oversized reference"))
    with pytest.raises(ValueError, match="supported limit is 60s"):
        reference._worker(inputs["source"], inputs["project"], **trim)


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("resume", [False, True])
def test_back_preserves_only_explicit_all(inputs, monkeypatch, explicit, resume):
    flags = ["--reference-range", "all"] if explicit else []
    monkeypatch.setattr("sys.stdin", io.StringIO(f"1\n{inputs['source']}\n" + ("q\n" if resume else "b\nq\n")))
    assert command.run(flags) == 0
    if resume:
        monkeypatch.setattr("sys.stdin", io.StringIO("b\nq\n"))
        assert command.run(["--resume", inputs["project"]]) == 0
    state = load_session(inputs["project"])
    assert (state.answers.get("reference_range") == "all") is explicit


def test_back_keeps_explicit_mcp_answers_without_history(inputs, monkeypatch):
    answers = flow.next_step({"path": "a", "project": inputs["project"], "reference": inputs["source"],
                              "reference_range": "all"})["answers"]
    save_session(inputs["project"], Session(answers=answers, history=["path", "reference"]))
    monkeypatch.setattr("sys.stdin", io.StringIO("b\nq\n"))
    assert command.run(["--resume", inputs["project"]]) == 0
    assert load_session(inputs["project"]).answers["reference_range"] == "all"


def test_combined_download_question_never_assumes_consent(inputs):
    answers = {"path": "a", "project": inputs["project"], "reference": "https://example.invalid/video"}
    q = flow.next_step(answers)["question"]
    assert q["id"] == "reference_download" and q["recommended"] == "no"
    assert flow.next_step({**answers, "reference_download": "no"})["status"] == "blocked"
    with pytest.raises(ValueError, match="reference_download"):
        flow.normalize("reference_download", "0:30-1:20")


def test_back_revokes_combined_reference_consent(inputs, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("1\nhttps://example.invalid/video\nyes 0-30\nb\nq\n"))
    assert command.run([]) == 0
    a = load_session(inputs["project"]).answers
    assert "reference_download" not in a and "allow_download" not in a and "reference_range" not in a


def test_back_revokes_combined_model_consent(inputs, monkeypatch):
    from tools.eval.studio_generated import match_answers
    lines = match_answers(inputs["source"], inputs["clips"], speech="download small.en")
    lines[-1:] = ["b", "skip", "q"]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(lines) + "\n"))
    assert command.run([]) == 0
    a = load_session(inputs["project"]).answers
    assert a["speech_model"] == "skip" and "speech_download" not in a


def test_changing_screen_to_general_drops_only_automatic_screen_defaults(inputs, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(f"2\n{inputs['clips']}\nscreen\nb\ngeneral\nq\n"))
    assert command.run([]) == 0
    a = load_session(inputs["project"]).answers
    assert a["footage_kind"] == "general" and "cursor_log" not in a and "music" not in a


def test_existing_cursor_log_is_offered_and_explicit_external_log_survives(inputs):
    root = Path(inputs["project"])
    root.mkdir()
    log = root / "cursor.jsonl"
    log.touch()
    a = {"path": "b", "project": str(root), "clips": inputs["clips"], "footage_kind": "screen"}
    assert flow.next_step(a)["question"]["id"] == "cursor_log"
    external = root.parent / "external.jsonl"
    external.touch()
    log.unlink()
    assert flow.next_step({**a, "cursor_log": str(external)})["answers"]["cursor_log"] == str(external)


@pytest.mark.parametrize("script", ["studio1", "onboard1"])
@pytest.mark.parametrize("generated", [False, True])
def test_acceptance_script_answers_follow_the_current_interview(inputs, monkeypatch, script, generated):
    from tools.eval.studio_generated import match_answers
    calls = []
    if generated:
        monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(to_dict=lambda: {
            "duration": 18, "width": 640, "height": 360, "orientation": "landscape", "has_audio": False}))
    def execute(a, **kw):
        calls.append(a)
        return {"ok": True, "status": "ready", "outputs": [], "warnings": []}
    monkeypatch.setattr("myzing.studio.execute.run_confirmed", execute)
    speech = "skip" if script == "studio1" else "download small.en"
    lines = match_answers(inputs["source"], inputs["clips"], generated=generated, speech=speech)
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(lines) + "\n"))
    assert command.run([]) == 0
    assert len(calls) == 1 and calls[0]["footage_kind"] == "general"
    assert calls[0]["topic"] == "a short introduction to people making things"
    assert calls[0]["length"] == (6 if generated else 15)
    if script == "onboard1" and not generated:
        assert calls[0]["speech_model"] == "small.en" and calls[0]["speech_download"] is True
    assert load_session(inputs["project"]).status == "ready"
