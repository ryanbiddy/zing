"""Match checkpoints, consent, rendered evidence, CLI/MCP, and process ownership."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from myzing.match import evidence
from myzing.match.api import match
from myzing.match.process import Cancelled, run_owned
from myzing.match.state import Checkpoints, StepFailed, read, write


def test_checkpoints_hash_outputs_and_name_failure_logs(tmp_path):
    calls = []
    output = tmp_path / "measurement.json"
    def measure():
        calls.append(1)
        write(output, {"version": 1, "measured": len(calls)})
        return {"outputs": [str(output)]}
    first = Checkpoints(tmp_path, False).step("study", "input", measure)
    assert Checkpoints(tmp_path, True).step("study", "input", measure) == first
    assert len(calls) == 1
    output.write_text("corrupt", encoding="utf-8")
    second = Checkpoints(tmp_path, True).step("study", "input", measure)
    assert second["checkpoint"] != first["checkpoint"]
    assert len(calls) == 2
    def fail():
        print("tool diagnostic")
        raise RuntimeError("broken encoder")
    checkpoints = Checkpoints(tmp_path, True)
    with pytest.raises(StepFailed, match="render-B.*broken encoder.*log:"):
        checkpoints.step("render-B", [], fail)
    failure = checkpoints.failures()[0]
    assert failure["step"] == "render-B"
    assert "tool diagnostic" in Path(failure["log"]).read_text()
    assert "broken encoder" in Path(failure["log"]).read_text()


def test_study_checkpoint_result_tracks_breakdown_content(tmp_path, monkeypatch, zing_workspace):
    """Later steps key on study results; a restudy with new evidence must change them."""
    from myzing.match import api
    from myzing.project.api import hash_file
    from myzing.schemas import Breakdown, Shot, VideoMeta

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    marker = {"value": 1}

    def fake_study(path, **kwargs):
        b = Breakdown(VideoMeta(str(path), "file", duration=2, fps=30, media_path="clip.mp4"),
                      shots=[Shot(0, 0, 2)])
        b.provenance["source_map"] = {"accepted": marker["value"]}
        return b
    monkeypatch.setattr(api, "study", fake_study)
    first = api._study(source, tmp_path / "workspace", raw=True)
    assert first["sha256"] == hash_file(Path(first["path"]))
    marker["value"] = 2  # Same paths and warnings; different measured evidence.
    second = api._study(source, tmp_path / "workspace", raw=True)
    assert (first["path"], first["warnings"]) == (second["path"], second["warnings"])
    assert second["sha256"] != first["sha256"] and second != first


def test_url_without_consent_never_acquires(tmp_path, monkeypatch, zing_workspace):
    clips = tmp_path / "clips"
    clips.mkdir()
    monkeypatch.setattr("myzing.study.ingest.ingest", lambda *a, **k: pytest.fail("acquisition without consent"))
    result = match("https://example.test/video", str(clips), str(tmp_path / "out"), answers={})
    assert result["summary"] == "0 of 3 render complete"
    assert result["failures"][0]["step"] == "reference-resolve"
    assert "--allow-download" in result["failures"][0]["error"]


def test_reports_compare_rendered_measurements_not_the_plan():
    from myzing.schemas import Breakdown, Shot, VideoMeta
    from myzing.style_recipe import build_style_recipe
    from myzing.composition import Composition
    reference = Breakdown(VideoMeta("reference", "file", duration=6, fps=30),
                          shots=[Shot(i, i * 2, i * 2 + 2) for i in range(3)])
    rendered = Breakdown(VideoMeta("output", "file", duration=6, fps=30), shots=[Shot(0, 0, 6)])
    result = evidence.report(build_style_recipe(reference), rendered, {}, None, {"full_decode": True}, Composition())
    assert result["dimensions"]["shot_pace"]["status"] == "miss"
    assert result["dimensions"]["shot_pace"]["observed"] == 6
    assert result["dimensions"]["first_cut"]["status"] == "miss"
    assert result["dimensions"]["caption_placement"]["status"] == "approximate"
    assert result["dimensions"]["color"]["status"] == "approximate"


def test_worker_crash_cannot_reuse_previous_ready_comparison(tmp_path, monkeypatch):
    from myzing.match import jobs
    write(tmp_path / "comparison.json", {"version": 1, "status": "ready", "ready": 3, "run_id": "previous"})
    write(tmp_path / "match-state.json", {"version": 1, "status": "ready", "steps": {}})
    monkeypatch.setattr(jobs, "run_owned", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="interrupted before publishing"):
        jobs.execute({"out": str(tmp_path)})
    assert read(tmp_path / "comparison.json")["status"] == "failed"
    assert read(tmp_path / "comparison.json")["ready"] == 0


def test_url_resume_reuses_verified_acquisition_without_new_consent(tmp_path, monkeypatch, zing_workspace):
    from types import SimpleNamespace
    from myzing.match import api
    clips = tmp_path / "clips"
    clips.mkdir()
    reference = tmp_path / "kept.mp4"
    reference.write_bytes(b"locally retained media")
    acquisitions = []
    def acquire(source):
        acquisitions.append(source)
        return SimpleNamespace(media_path=reference)
    def study(source, *args, **kwargs):
        assert source == str(reference)
        raise RuntimeError("stop at study seam")
    monkeypatch.setattr("myzing.study.ingest.ingest", acquire)
    monkeypatch.setattr(api, "_study", study)
    out = tmp_path / "out"
    first = match("https://example.test/video", str(clips), str(out), answers={}, allow_download=True)
    assert first["failures"][0]["step"] == "reference-study"
    resumed = match("https://example.test/video", str(clips), str(out), answers={}, resume=True)
    assert resumed["failures"][0]["step"] == "reference-study"
    assert len(acquisitions) == 1 and "reference-resolve" in resumed["reused_steps"]
    reference.write_bytes(b"different retained media")
    stale = match("https://example.test/video", str(clips), str(out), answers={}, resume=True)
    assert stale["failures"][0]["step"] == "reference-resolve" and len(acquisitions) == 1


def test_uoink_reference_uses_verified_local_media_without_web_fallback(tmp_path, monkeypatch, zing_workspace):
    from myzing.match import api
    from myzing.project.api import hash_file
    clips = tmp_path / "clips"
    clips.mkdir()
    reference = tmp_path / "kept.mp4"
    reference.write_bytes(b"retained Uoink fixture")
    calls = []
    def resolve(ref):
        calls.append(ref)
        return {"ok": True, "data": {"state": "available", "media": {
            "path": str(reference), "sha256": hash_file(reference), "byte_length": reference.stat().st_size},
            "source_url": "https://example.test/original", "provenance": {"fixture": True}}}
    def study(source, *args, **kwargs):
        assert source == str(reference)
        raise RuntimeError("stop at local study seam")
    monkeypatch.setattr("myzing.project.references.uoink_bridge.resolve_kept_media", resolve)
    monkeypatch.setattr("myzing.study.ingest.ingest", lambda *a, **k: pytest.fail("unexpected fetch"))
    monkeypatch.setattr(api, "_study", study)
    first = match("uoink:123", str(clips), str(tmp_path / "out"), answers={})
    assert first["failures"][0]["step"] == "reference-study" and calls == ["uoink://item/123"]
    monkeypatch.setattr("myzing.project.references.uoink_bridge.resolve_kept_media", lambda ref: {"ok": False, "error": "peer offline"})
    failed = match("uoink:missing", str(clips), str(tmp_path / "offline"), answers={}, allow_download=True)
    assert failed["failures"][0]["step"] == "reference-resolve" and "peer offline" in failed["failures"][0]["error"]


def _alive(pid):
    from myzing.project.locking import _pid_alive
    # A reparented child can briefly remain a Linux zombie, which is already
    # stopped and owns no resources other than its exit record.
    stat = Path(f"/proc/{pid}/stat")
    if os.name != "nt" and stat.exists() and stat.read_text().split()[2] == "Z":
        return False
    return _pid_alive(pid)


def test_cancel_stops_owned_slow_child_tree_and_leaves_unrelated_job():
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    stopped = threading.Event()
    pids = []
    code = ("import sys, subprocess, os, json, time; sys.stdin.readline(); "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=(os.name!='nt')); "
            "print(json.dumps([os.getpid(),p.pid]),flush=True); time.sleep(60)")
    def progress(line):
        pids.extend(json.loads(line))
        stopped.set()
    try:
        with pytest.raises(Cancelled):
            run_owned([sys.executable, "-c", code], "start", cancel=stopped, progress=progress)
        deadline = time.monotonic() + 5
        while any(_alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(.05)
        assert len(pids) == 2 and not any(_alive(pid) for pid in pids)
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)


def test_supervisor_cancellation_preserves_resumable_state(tmp_path, monkeypatch):
    from myzing.match import jobs
    def cancelled(*args, **kwargs):
        write(tmp_path / "match-state.json", {"version": 1, "status": "running", "steps": {
            "study": {"status": "running", "log": str(tmp_path / "logs" / "study.log")}}})
        raise Cancelled("Ctrl+C")
    monkeypatch.setattr(jobs, "run_owned", cancelled)
    result = jobs.execute({"out": str(tmp_path)})
    assert result["status"] == "cancelled"
    assert read(tmp_path / "match-state.json")["steps"]["study"]["status"] == "cancelled"
    assert "--resume" in (tmp_path / "logs" / "study.log").read_text()
    assert read(tmp_path / "comparison.json")["ready"] == 0


def test_cli_noninteractive_requires_answers_and_emits_json(tmp_path, capsys, monkeypatch):
    from myzing.match.command import run
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    code = run(["reference.mp4", "--clips", str(tmp_path), "--out", str(tmp_path / "out"), "--json"])
    assert code == 1
    result = json.loads(capsys.readouterr().out)
    assert "--brief" in result["error"] and "--answers" in result["error"]


def _fake_whisper(monkeypatch, snapshot, calls):
    def model(name, **kwargs):
        calls.append((name, kwargs))
        if len(calls) == 1:
            raise ValueError("no GPU")
        return object()
    utils = type("FakeUtils", (), {"download_model": staticmethod(
        lambda name, local_files_only=False: str(snapshot))})
    monkeypatch.setitem(sys.modules, "faster_whisper", type("FakeWhisper", (), {"WhisperModel": staticmethod(model)}))
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)


def test_local_only_model_load_reaches_both_whisper_attempts(monkeypatch, tmp_path):
    from myzing.study.transcribe import _load_model
    (tmp_path / "tokenizer.json").write_text("{}")
    calls = []
    _fake_whisper(monkeypatch, tmp_path, calls)
    _load_model("cached-model", local_files_only=True)
    assert len(calls) == 2 and all(c["local_files_only"] for _, c in calls)
    assert all(name == str(tmp_path) for name, _ in calls)


@pytest.mark.parametrize("as_directory", [True, False])
def test_local_only_model_without_tokenizer_is_never_constructed(monkeypatch, tmp_path, as_directory):
    from myzing.study.transcribe import _load_model
    (tmp_path / "model.bin").write_bytes(b"x")
    calls = []
    _fake_whisper(monkeypatch, tmp_path, calls)
    with pytest.raises(FileNotFoundError, match="tokenizer.json"):
        _load_model(str(tmp_path) if as_directory else "tiny.en", local_files_only=True)
    assert calls == []


def test_mcp_match_background_status_and_dead_worker(tmp_path, monkeypatch, zing_workspace):
    from myzing import mcp_server as server, storage
    from myzing.match import jobs
    clip_folder = tmp_path / "clips"
    clip_folder.mkdir()
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"fixture")
    entered, release = threading.Event(), threading.Event()
    def execute(options, **kwargs):
        entered.set()
        release.wait(timeout=10)
        return {"status": "partial", "summary": "2 of 3 ready", "ready": 2, "failures": [{"step": "render-B", "log": "B.log"}]}
    monkeypatch.setattr(jobs, "execute", execute)
    output = tmp_path / "out"
    try:
        result = server.h_match_start(str(reference), str(clip_folder), str(output), answers={})
        assert result["ok"] and result["status"] == "started"
        assert entered.wait(timeout=3)
        assert server.h_match_start(str(reference), str(clip_folder), str(output), answers={})["status"] == "already_matching"
        assert server.h_match_status(str(output))["state"] == "running"
    finally:
        release.set()
        thread = server._MATCH_JOBS.get(str(output))
        if thread:
            thread.join(timeout=5)
    status = server.h_match_status(str(output))
    assert status["state"] == "partial" and status["result"]["ready"] == 2
    storage.write_status_at(output / "match-job", state="running", pid=os.getpid())
    assert server.h_match_status(str(output))["state"] == "failed"


def test_mcp_matches_packaging_tool_inventory():
    import importlib.util
    from myzing.mcp_server import build_server
    spec = importlib.util.spec_from_file_location("match_smoke", Path(__file__).resolve().parents[1] / "packaging/mcp_stdio_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import asyncio
    names = {t.name for t in asyncio.run(build_server().list_tools())}
    assert names == module.EXPECTED_TOOLS
    assert {"match_start", "match_status"} <= names


def test_comparison_disclosures_group_repeated_warnings():
    from myzing.match.evidence import group_disclosures

    warnings = [
        "At 0.500000s: LOG-like/flat tonal range: confirm the input transform.",
        "At 1.500000s: LOG-like/flat tonal range: confirm the input transform.",
        "At 2.500000s: LOG-like/flat tonal range: confirm the input transform.",
        "source E:/x/clips/take-0.mp4: Color metadata is incomplete.",
        "source E:/x/clips/take-1.mp4: Color metadata is incomplete.",
        "Fixture ASR: authored words, not measured speech.",
        "Fixture ASR: authored words, not measured speech.",
        "At 4.000000s: A one-off note.",
    ]
    assert group_disclosures(warnings) == [
        "LOG-like/flat tonal range: confirm the input transform. (3x: 0.5s, 1.5s, 2.5s)",
        "Color metadata is incomplete. (2x: take-0.mp4, take-1.mp4)",
        "Fixture ASR: authored words, not measured speech.",
        "4s: A one-off note.",
    ]
