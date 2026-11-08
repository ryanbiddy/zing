"""Match checkpoints and studio ownership without media tools or model calls."""

import io
import json
import os
import re
import socket
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.match import api, preflight
from myzing.match.process import Cancelled
from myzing.match.state import Checkpoints, read, write
from myzing.project import locking
from myzing.project.api import hash_file
from myzing.project.probe import parse_probe
from myzing.studio import command, flow, jobs
from myzing.studio.execute import run_confirmed
from myzing.studio.models import SESSION_NAME, Session, load_session, save_session, write_json
from test_studio import complete, inputs


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr("subprocess.run", refuse)
    monkeypatch.setattr("subprocess.Popen", refuse)


@pytest.mark.parametrize("name", [r"study-x\..\..\victim", "../victim", "...", "..clip: /\u00e9"])
def test_step_logs_stay_inside_logs(tmp_path, name):
    root = tmp_path / "project"
    root.mkdir()
    victim = root / "victim.log"
    victim.write_text("keep", encoding="utf-8")
    checkpoints = Checkpoints(root, False)
    def measure():
        print("measured")
        return {"outputs": []}
    checkpoints.step(name, [], measure)
    log = Path(checkpoints.data["steps"][name]["log"])
    assert log.resolve().parent == (root / "logs").resolve()
    assert re.fullmatch(r"[A-Za-z0-9._-]+", log.name) and not log.name.startswith(".")
    assert log.read_text(encoding="utf-8") == "measured\n"
    assert victim.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("first,second", [
    ({"ref_start": 0, "ref_end": 2}, {"ref_start": 1, "ref_end": 2}),
    ({"ref_end": 2}, {"ref_end": 3}),
    ({"reference_range": "0-2"}, {"reference_range": "1-3"}),
])
def test_color_checkpoint_changes_with_reference_trim(tmp_path, monkeypatch, first, second):
    clips, root = tmp_path / "clips", tmp_path / "project"
    clips.mkdir()
    source, reference = clips / "clip.mp4", tmp_path / "reference.mp4"
    source.write_bytes(b"clip")
    reference.write_bytes(b"reference")
    probe = parse_probe({"streams": [{"codec_type": "video", "width": 640, "height": 360,
                                     "avg_frame_rate": "30/1"}], "format": {"duration": "10"}})
    monkeypatch.setattr(api.projects, "probe_file", lambda p: probe)
    monkeypatch.setattr(preflight, "check", lambda *a, **k: {"problems": [], "warnings": []})
    monkeypatch.setattr(api, "capabilities", lambda: {"fonts": False, "color": True, "audio": False})
    def study(source, folder, **kwargs):
        path = folder / "study.json"
        trim = {k: kwargs[k] for k in ("ref_start", "ref_end", "reference_range") if k in kwargs}
        write(path, trim)
        return {"path": str(path), "media": str(source) + json.dumps(trim), "outputs": [str(path)]}
    colors = []
    def color(reference, source, folder):
        colors.append(reference)
        path = folder / "grade.json"
        write(path, {"reference": reference})
        return {"path": str(path), "outputs": [str(path)]}
    def recipe(*args, **kwargs):
        raise ValueError("stop after color")
    monkeypatch.setattr(api, "_study", study)
    monkeypatch.setattr(api, "_audio", lambda *a: {"outputs": []})
    monkeypatch.setattr(api, "_color", color)
    monkeypatch.setattr(api, "_recipe", recipe)
    keys = []
    for trim in (first, second, second):
        result = api.match(str(reference), str(clips), root, answers={}, resume=True, color="reference", **trim)
        assert result["failures"][0]["step"] == "style-recipe"
        steps = read(root / "match-state.json")["steps"]
        keys.append(next(row["key"] for name, row in steps.items() if name.startswith("color-")))
    assert keys[0] != keys[1] == keys[2]
    assert len(colors) == 2 and colors[0] != colors[1]


@pytest.mark.parametrize("location", ["nested", "sibling", "parent"])
def test_preflight_ignores_only_nested_output(tmp_path, monkeypatch, location):
    clips = tmp_path / "clips"
    clips.mkdir()
    root = {"nested": clips / "project", "sibling": tmp_path / "project", "parent": tmp_path}[location]
    generated = root / "render-work" / "rendered.mp4"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"truncated")
    source, reference = clips / "clip.mp4", tmp_path / "reference.mp4"
    nearby = clips / "project-other" / "clip.mp4"
    nearby.parent.mkdir()
    for path in (source, reference, nearby):
        path.write_bytes(b"source")
    probed = []
    def probe(path):
        probed.append(path.resolve())
        if path == generated:
            raise ValueError("truncated output")
        return SimpleNamespace(duration=10, has_audio=False, flags=[])
    monkeypatch.setattr(preflight, "probe", probe)
    monkeypatch.setattr(preflight, "optional_warnings", lambda: [])
    monkeypatch.setattr(preflight.shutil, "which", lambda name: name)
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda p: SimpleNamespace(free=1_000_000_000))
    result = preflight.check(str(reference), clips, root / ".." / root.name, answers={})
    assert not result["problems"]
    assert probed == [reference.resolve(), source.resolve(), nearby.resolve()]


@pytest.mark.parametrize("path", ["a", "b"])
@pytest.mark.parametrize("locked", [False, True])
def test_screen_run_holds_production_lock(inputs, monkeypatch, path, locked):
    root = Path(inputs["project"])
    answers = {"path": path, "project": str(root), "clips": inputs["clips"], "reference": inputs["source"],
               "footage_kind": "screen", "topic": "Local app", "platform": "YouTube", "captions": "none",
               "music": "original", "speech_model": "skip"}
    calls = []
    def render(*args, **kwargs):
        with pytest.raises(ValueError, match="Another studio session"):
            with jobs.busy_lock(root):
                pytest.fail("second screen run acquired the lock")
        calls.append(args)
        return {"status": "ready", "screens": [], "warnings": []}
    monkeypatch.setattr("myzing.screen.api.run_folder", render)
    with jobs.busy_lock(root) if locked else nullcontext():
        assert run_confirmed(answers, locked=locked)["ok"]
    assert len(calls) == 1
    with jobs.busy_lock(root):
        pass


@pytest.mark.parametrize("flags,trim", [
    (["--ref-start", "1"], {"ref_start": 1.0}),
    (["--ref-end", "3"], {"ref_end": 3.0}),
    (["--ref-start", "1", "--ref-end", "3"], {"ref_start": 1.0, "ref_end": 3.0}),
    (["--reference-range", "1-3"], {"reference_range": "1-3"}),
    (["--reference-range", "0-2"], {"reference_range": "0-2"}),
])
def test_resume_range_override_invalidates_only_changed_answers(inputs, tmp_path, monkeypatch, capsys, flags, trim):
    answers, _ = complete("d", inputs)
    answers["reference_range"] = "0-2"
    output = tmp_path / "card.json"
    output.write_text("{}", encoding="utf-8")
    result = {"ok": True, "status": "ready", "output_sha256": {str(output): hash_file(output)}}
    save_session(inputs["project"], Session(answers=answers, status="ready", result=result))
    monkeypatch.setattr(jobs, "execute", lambda *a, **k: pytest.fail("plan is not confirmed"))
    assert command.run(["--resume", inputs["project"], *flags, "--json"]) == 0
    session = load_session(inputs["project"])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    if trim == {"reference_range": "0-2"}:
        assert session.result == result and events[0]["event"] == "result"
    else:
        assert session.result == {} and events[0]["event"] == "plan"
    assert {k: session.answers[k] for k in ("ref_start", "ref_end", "reference_range") if k in session.answers} == trim


@pytest.mark.parametrize("key", ["footage_kind", "length_mode"])
@pytest.mark.parametrize("value", [[], {}, ["screen"], {"value": "screen"}])
def test_normalize_rejects_non_string_choices(key, value):
    with pytest.raises(ValueError, match=key + ": choose"):
        flow.normalize(key, value)


@pytest.mark.parametrize("ending", ["cancel", "crash"])
@pytest.mark.parametrize("owner,host,alive,removed", [
    (987654, socket.gethostname(), False, True),
    (987654, socket.gethostname(), True, False),
    (os.getpid(), socket.gethostname(), True, False),
    (987655, socket.gethostname(), False, False),
    (987654, "another-host", False, False),
])
def test_worker_removes_only_its_own_dead_local_locks(tmp_path, monkeypatch, ending, owner, host, alive, removed):
    paths = [tmp_path / ".project.lock", tmp_path / "drafts" / ".project.lock"]
    data = {"pid": owner, "host": host, "token": "worker-lock"}
    def run(*args, **kwargs):
        kwargs["on_started"](987654)
        for path in paths:
            write_json(path, data)
        if ending == "cancel":
            raise Cancelled()
        return 7
    monkeypatch.setattr(jobs, "run_owned", run)
    monkeypatch.setattr(locking, "_pid_alive", lambda pid: alive)
    with pytest.raises(Cancelled if ending == "cancel" else RuntimeError):
        jobs.execute({"project": str(tmp_path)})
    for path in paths:
        assert path.exists() is not removed
        if not removed:
            assert read(path) == data
    with jobs.busy_lock(tmp_path):
        pass


def test_worker_cleanup_preserves_a_replaced_lock(tmp_path, monkeypatch):
    path = tmp_path / ".project.lock"
    replacement = {"pid": os.getpid(), "host": socket.gethostname(), "token": "other-lock"}
    def run(*args, **kwargs):
        kwargs["on_started"](987654)
        write_json(path, {"pid": 987654, "host": socket.gethostname(), "token": "worker-lock"})
        return 7
    def alive(pid):
        write_json(path, replacement)
        return False
    monkeypatch.setattr(jobs, "run_owned", run)
    monkeypatch.setattr(locking, "_pid_alive", alive)
    with pytest.raises(RuntimeError, match="worker exited 7"):
        jobs.execute({"project": str(tmp_path)})
    assert read(path) == replacement


def test_cancelled_worker_saves_final_mcp_session(inputs, monkeypatch):
    answers, _ = complete("b", inputs)
    root, started = Path(inputs["project"]), threading.Event()
    def run(*args, **kwargs):
        kwargs["on_started"](987654)
        write_json(root / ".project.lock", {"pid": 987654, "host": socket.gethostname(), "token": "worker-lock"})
        started.set()
        assert kwargs["cancel"].wait(3)
        raise Cancelled()
    monkeypatch.setattr(jobs, "run_owned", run)
    monkeypatch.setattr(locking, "_pid_alive", lambda pid: pid == os.getpid())
    assert jobs.job(answers, confirmed=True)["status"] == "started"
    with jobs._LOCK:
        thread, stop = jobs._JOBS[str(root)]
    try:
        assert started.wait(3)
        assert jobs.job(project=str(root), cancel=True)["cancellation_requested"]
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()
    assert jobs.job(project=str(root))["status"] == "cancelled"
    assert load_session(root).status == "cancelled"
    assert not (root / ".project.lock").exists()
    assert str(root) not in jobs._JOBS


@pytest.mark.parametrize("path", ["a", "f"])
@pytest.mark.parametrize("json_output", [False, True])
def test_busy_cli_keeps_active_session_bytes(inputs, tmp_path, monkeypatch, capsys, path, json_output):
    answers, _ = complete(path, inputs)
    root = Path(inputs["project"])
    save_session(root, Session(answers=answers, status="running"))
    original = (root / SESSION_NAME).read_bytes()
    supplied = tmp_path / "answers.json"
    write_json(supplied, {**answers, "topic": "another terminal"})
    def execute(*args, **kwargs):
        pytest.fail("busy CLI started production")
    monkeypatch.setattr(jobs, "execute", execute)
    monkeypatch.setattr("myzing.studio.execute.run_confirmed", execute)
    with jobs.busy_lock(root):
        assert command.run(["--resume", str(root), "--answers", str(supplied), "--yes",
                            *(["--json"] if json_output else [])]) == 1
        assert (root / SESSION_NAME).read_bytes() == original
    output = capsys.readouterr()
    assert "Another studio session is already making something" in output.out + output.err
    assert (root / SESSION_NAME).read_bytes() == original


@pytest.mark.parametrize("path", ["a", "f"])
@pytest.mark.parametrize("ending", ["ready", "failed", "interrupt", "crash"])
def test_cli_holds_lock_through_final_save(inputs, tmp_path, monkeypatch, path, ending):
    answers, _ = complete(path, inputs)
    root = Path(inputs["project"])
    supplied = tmp_path / "answers.json"
    write_json(supplied, answers)
    saved = []
    def assert_locked():
        with pytest.raises(ValueError, match="Another studio session"):
            with jobs.busy_lock(root):
                pytest.fail("production lock was released")
    def persist(project, session):
        if session.status != "planned":  # the plan screen only checks the lock is free
            assert_locked()
        saved.append(session.status)
        return save_session(project, session)
    def execute(answers, *, progress, locked):
        assert locked
        assert_locked()
        assert load_session(root).status == "running"
        if ending == "interrupt":
            raise KeyboardInterrupt()
        if ending == "crash":
            raise RuntimeError("worker failed")
        return {"ok": ending == "ready", "status": ending}
    monkeypatch.setattr(command, "save_session", persist)
    monkeypatch.setattr(jobs, "execute", execute)
    monkeypatch.setattr("myzing.studio.execute.run_confirmed", execute)
    assert command.run(["--answers", str(supplied), "--yes", "--json"]) == (0 if ending in {"ready", "interrupt"} else 1)
    status = "paused" if ending == "interrupt" else "failed" if ending == "crash" else ending
    assert saved == ["planned", "running", status]
    assert load_session(root).status == status
    with jobs.busy_lock(root):
        pass


def test_cli_output_change_removes_abandoned_session(inputs, tmp_path, monkeypatch):
    other = tmp_path / "other"
    monkeypatch.setattr("sys.stdin", io.StringIO(f"6\n{inputs['source']}\nsquare\no\n{other}\nq\n"))
    assert command.run([]) == 0
    assert not (Path(inputs["project"]) / SESSION_NAME).exists()
    assert load_session(other).answers["aspects"] == ["1:1"]
