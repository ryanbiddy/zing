"""MCP tool handlers, driven directly (no SDK needed): honest envelopes,
job lifecycle on disk, judgment stamping/validation, prompt access."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from myzing import mcp_server, storage
from myzing.schemas import Breakdown, VideoMeta

SRC_URL = "https://www.tiktok.com/@a/video/999"
SLUG = "tiktok-999"


def make_breakdown(url: str = SRC_URL) -> Breakdown:
    return Breakdown(meta=VideoMeta(source_url=url, platform="tiktok", duration=9.0))


@pytest.fixture
def prompts_dir(tmp_path, monkeypatch):
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "study.md").write_text(
        "---\n"
        "name: study\n"
        "description: judge a breakdown\n"
        "version: 0.1.0\n"
        "required_keys: [hook, beats, caption_style, why_it_works]\n"
        "---\n"
        "# Study\nJudge the breakdown.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(mcp_server.PROMPTS_DIR_ENV, str(d))
    return d


@pytest.fixture
def fake_engine(monkeypatch):
    """Inject a fast fake myzing.study.api whose study() returns a Breakdown.

    Records every dispatched source in ``api.calls`` and — like the real
    engine (F-11 repro) — raises on a local path that does not exist, so a
    raw ``~`` path dispatched unexpanded fails exactly the way Lane A's
    ``_stage_local`` does.
    """
    api = types.ModuleType("myzing.study.api")
    api.calls = []

    def study(source: str, phase_callback=None):
        api.calls.append(source)
        if phase_callback:
            phase_callback("shots")
        if source.endswith("boom"):
            raise RuntimeError("yt-dlp exploded")
        is_url = source.lower().startswith(("http://", "https://"))
        if not is_url and not Path(source).is_file():
            raise FileNotFoundError(f"no such file: {source}")
        return make_breakdown(source)

    api.study = study
    monkeypatch.setitem(sys.modules, "myzing.study.api", api)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")
    return api


@pytest.fixture
def live_job():
    """Register a demonstrably-alive worker thread in mcp_server._JOBS for a
    slug, so a `running` status is genuinely live (F-03 readers trust the
    in-process thread before anything else)."""
    registered: list[tuple[str, threading.Event, threading.Thread]] = []

    def register(slug: str) -> None:
        stop = threading.Event()
        t = threading.Thread(target=stop.wait, daemon=True)
        t.start()
        with mcp_server._JOBS_LOCK:
            mcp_server._JOBS[slug] = t
        registered.append((slug, stop, t))

    yield register
    for slug, stop, t in registered:
        stop.set()
        t.join(timeout=5)
        with mcp_server._JOBS_LOCK:
            mcp_server._JOBS.pop(slug, None)


def dead_pid() -> int:
    """A pid that demonstrably belonged to a real, now-exited process."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def old_timestamp(seconds_ago: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    ).isoformat(timespec="seconds")


def wait_done(slug: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = storage.read_status(slug)
        if status and status.get("state") in ("done", "failed"):
            return status
        time.sleep(0.01)
    raise AssertionError(f"study of {slug} never finished")


# -- serve-mcp --print-config ------------------------------------------------

def test_print_config_both_targets(capsys):
    assert mcp_server.run(["--print-config"]) == 0
    out = capsys.readouterr().out
    assert sys.executable in out
    assert "claude_desktop_config.json" in out
    assert "claude mcp add zing" in out
    start = out.index("{")
    end = out.index("\n# Claude Code")
    config = json.loads("\n".join(
        line for line in out[start:end].splitlines() if not line.startswith("#")
    ))
    assert config["mcpServers"]["zing"]["args"] == ["-m", "myzing.cli", "serve-mcp"]


def test_print_config_unknown_target(capsys):
    assert mcp_server.run(["--print-config", "cursor"]) == 2
    assert "desktop, code" in capsys.readouterr().out


# -- study_video -------------------------------------------------------------

def test_study_video_requires_source(zing_workspace):
    result = mcp_server.h_study_video("")
    assert result["ok"] is False and "url_or_path" in result["error"]


def test_study_video_missing_ffmpeg_is_actionable(zing_workspace, monkeypatch):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: None)
    result = mcp_server.h_study_video(SRC_URL)
    assert result["ok"] is False
    assert "ffmpeg" in result["error"] and "zing doctor" in result["error"]


def test_study_video_missing_file_is_actionable(zing_workspace, monkeypatch):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")
    result = mcp_server.h_study_video("C:/nope/ghost.mp4")
    assert result["ok"] is False and "file not found" in result["error"]


def test_study_video_engine_absent_is_honest(zing_workspace, monkeypatch):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(mcp_server, "_study_api", lambda: None)
    result = mcp_server.h_study_video(SRC_URL)
    assert result["ok"] is False
    assert "not in this build yet" in result["error"]


def test_study_video_job_lifecycle(zing_workspace, fake_engine):
    result = mcp_server.h_study_video(SRC_URL)
    assert result["ok"] is True and result["status"] == "started"
    assert result["slug"] == SLUG
    status = wait_done(SLUG)
    assert status["state"] == "done"
    assert status["phase"] == "shots"  # engine's callback was wired through
    loaded = storage.load_breakdown(SLUG)
    assert loaded.meta.source_url == SRC_URL


def test_study_video_failure_leaves_honest_disk_state(zing_workspace, fake_engine):
    result = mcp_server.h_study_video(SRC_URL + "/boom")
    assert result["ok"] is True
    slug = result["slug"]
    status = wait_done(slug)
    assert status["state"] == "failed"
    assert "yt-dlp exploded" in status["error"]
    fetch = mcp_server.h_get_breakdown(slug)
    assert fetch["ok"] is False and "failed" in fetch["error"]
    assert fetch["state"] == "failed"  # F-04: every response carries state


def test_study_video_stamps_liveness_marker(zing_workspace, fake_engine):
    # F-03: the job runner stamps pid + heartbeat so readers can tell a
    # live study from a corpse. write_status merges, so the marker written
    # at start is still visible on the finished status.
    result = mcp_server.h_study_video(SRC_URL)
    assert result["ok"] is True
    status = wait_done(result["slug"])
    assert status["pid"] == os.getpid()
    assert status["heartbeat_at"]


def test_study_video_tilde_path_dispatches_expanded(
    zing_workspace, fake_engine, monkeypatch, tmp_path
):
    # F-11: h_study_video validated Path(source).expanduser() but dispatched
    # the raw string — ok/started followed by an async "no such file".
    home = tmp_path / "home"
    home.mkdir()
    video = home / "take1.mp4"
    video.write_bytes(b"\x00" * 2048)
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows expanduser
    monkeypatch.setenv("HOME", str(home))  # POSIX expanduser
    result = mcp_server.h_study_video("~/take1.mp4")
    assert result["ok"] is True and result["status"] == "started"
    status = wait_done(result["slug"])
    assert status["state"] == "done", status.get("error")
    assert fake_engine.calls == [str(video)]  # the VALIDATED path was dispatched
    assert status["source"] == str(video)


# -- get_breakdown -----------------------------------------------------------

def test_get_breakdown_missing_slug(zing_workspace):
    result = mcp_server.h_get_breakdown("nothing-here")
    assert result["ok"] is False and "list_breakdowns" in result["error"]
    assert result["state"] == "absent"  # F-04: every response carries state


def test_get_breakdown_while_running_reports_phase(zing_workspace, live_job):
    storage.write_status(SLUG, state="running", phase="ocr", started_at="t")
    live_job(SLUG)  # F-03: `running` is only believed while the runner lives
    result = mcp_server.h_get_breakdown(SLUG)
    assert result["ok"] is True and result["ready"] is False
    assert result["state"] == "running"
    assert result["phase"] == "ocr"


def test_get_breakdown_full_and_summary(zing_workspace):
    b = make_breakdown()
    b.words = [  # big arrays should vanish in summary
        __import__("myzing.schemas", fromlist=["Word"]).Word("hi", 0.0, 0.2)
    ] * 30
    storage.save_breakdown(b, slug=SLUG)
    full = mcp_server.h_get_breakdown(SLUG)
    assert full["ok"] and len(full["breakdown"]["words"]) == 30
    summary = mcp_server.h_get_breakdown(SLUG, detail="summary")
    assert summary["ok"] is True
    assert "words" not in summary["breakdown"]
    assert summary["breakdown"]["counts"]["words"] == 30
    bad = mcp_server.h_get_breakdown(SLUG, detail="everything")
    assert bad["ok"] is False


# -- F-03: crash states must become honest -------------------------------------
# S1-REVIEW-lane-a finding 3 / lane-c finding 4: status.json stays `running`
# after the server dies -> get_breakdown says "still studying" forever and
# zing_status lists phantom jobs. Readers must reclassify a `running` state
# whose runner is dead (pid gone, or heartbeat stale) as failed, actionably.


def test_get_breakdown_dead_pid_running_state_becomes_failed(zing_workspace):
    # The exact review repro: a fresh-looking `running` status whose runner
    # process is provably dead (server crashed / machine rebooted).
    storage.write_status(
        SLUG,
        state="running",
        phase="transcribe",
        pid=dead_pid(),
        heartbeat_at=mcp_server._now(),
        started_at=mcp_server._now(),
    )
    result = mcp_server.h_get_breakdown(SLUG)
    assert result["ok"] is False
    assert result["state"] == "failed"
    assert "study_video" in result["error"]  # actionable: how to recover
    # honesty is persisted, not just reported once
    assert storage.read_status(SLUG)["state"] == "failed"


def test_get_breakdown_running_without_liveness_marker_becomes_failed(
    zing_workspace,
):
    # A pre-F-03 status file (no pid/heartbeat) with no live worker thread
    # is exactly the crashed-server artifact — never "still studying".
    storage.write_status(SLUG, state="running", phase="ocr", started_at="t")
    result = mcp_server.h_get_breakdown(SLUG)
    assert result["ok"] is False
    assert result["state"] == "failed"
    assert "study_video" in result["error"]


def test_get_breakdown_stale_heartbeat_becomes_failed(zing_workspace, monkeypatch):
    # Live pid but a heartbeat far past the staleness budget: a hung or
    # pid-reused runner must not keep the AI polling a corpse.
    monkeypatch.setattr(mcp_server, "_pid_alive", lambda pid: True)
    storage.write_status(
        SLUG,
        state="running",
        phase="audio",
        pid=os.getpid() + 1,  # some other process
        heartbeat_at=old_timestamp(mcp_server.HEARTBEAT_STALE_AFTER * 10),
    )
    result = mcp_server.h_get_breakdown(SLUG)
    assert result["ok"] is False
    assert result["state"] == "failed"
    assert "study_video" in result["error"]


def test_get_breakdown_live_foreign_runner_with_fresh_heartbeat_is_running(
    zing_workspace, monkeypatch
):
    # Another server process studying the same slug: alive pid + fresh
    # heartbeat must NOT be reclassified.
    monkeypatch.setattr(mcp_server, "_pid_alive", lambda pid: True)
    storage.write_status(
        SLUG,
        state="running",
        phase="shots",
        pid=os.getpid() + 1,
        heartbeat_at=mcp_server._now(),
    )
    result = mcp_server.h_get_breakdown(SLUG)
    assert result["ok"] is True
    assert result["ready"] is False
    assert result["state"] == "running"


def test_zing_status_reclassifies_dead_runner_no_phantom_jobs(zing_workspace):
    storage.write_status(
        "phantom-slug",
        state="running",
        phase="ingest",
        pid=dead_pid(),
        heartbeat_at=mcp_server._now(),
    )
    result = mcp_server.h_zing_status()
    assert result["ok"] is True
    jobs = {j["slug"]: j for j in result["jobs"]}
    assert jobs["phantom-slug"]["state"] == "failed"
    assert "study_video" in jobs["phantom-slug"]["error"]
    assert storage.read_status("phantom-slug")["state"] == "failed"


# -- F-04: status speaks before breakdown.json ---------------------------------
# S1-REVIEW-lane-c finding 2 repro: save old Breakdown, write status
# state=running -> h_get_breakdown returned ready=true, old data, no state.


def test_get_breakdown_during_restudy_serves_state_not_stale_ready(
    zing_workspace, live_job
):
    storage.save_breakdown(make_breakdown(), slug=SLUG)
    storage.write_status(
        SLUG, state="running", phase="transcribe", started_at="t"
    )
    live_job(SLUG)
    result = mcp_server.h_get_breakdown(SLUG)
    assert result["ok"] is True
    assert result["ready"] is False  # never `ready` while a re-study runs
    assert result["state"] == "running"
    assert result["phase"] == "transcribe"
    assert "breakdown" not in result  # superseded measurements are not served
    assert result["stale_breakdown_exists"] is True


def test_get_breakdown_after_failed_restudy_marks_prior_snapshot(zing_workspace):
    storage.save_breakdown(make_breakdown(), slug=SLUG)
    storage.write_status(SLUG, state="failed", error="whisper exploded")
    result = mcp_server.h_get_breakdown(SLUG)
    assert result["ok"] is True
    assert result["state"] == "failed"  # never plain `ready` after a failure
    assert "whisper exploded" in result["restudy_error"]
    assert "last successful" in result["hint"]
    # the prior snapshot is still served — explicitly marked, caller decides
    assert result["breakdown"]["meta"]["source_url"] == SRC_URL


def test_get_breakdown_done_states_carry_state_field(zing_workspace):
    storage.save_breakdown(make_breakdown(), slug=SLUG)
    legacy = mcp_server.h_get_breakdown(SLUG)  # no status file at all
    assert legacy["ok"] is True and legacy["state"] == "done"
    storage.write_status(SLUG, state="done")
    result = mcp_server.h_get_breakdown(SLUG, detail="summary")
    assert result["ok"] is True and result["ready"] is True
    assert result["state"] == "done"


# -- save_judgment -----------------------------------------------------------

def test_save_judgment_stamps_meta_and_validates(zing_workspace, prompts_dir):
    storage.save_breakdown(make_breakdown(), slug=SLUG)
    partial = {"hook": {"type": "question"}}
    rejected = mcp_server.h_save_judgment(SLUG, partial)
    assert rejected["ok"] is False
    assert "beats" in rejected["error"] and "why_it_works" in rejected["error"]

    complete = {
        "hook": {"type": "question"},
        "beats": [],
        "caption_style": {},
        "why_it_works": "evidence...",
    }
    result = mcp_server.h_save_judgment(SLUG, complete, model="claude-fable-5")
    assert result["ok"] is True
    assert result["prompt_version"] == "0.1.0"
    saved = storage.load_breakdown(SLUG).judgment["study"]
    assert saved["_meta"]["prompt_version"] == "0.1.0"
    assert saved["_meta"]["model"] == "claude-fable-5"
    assert saved["_meta"]["written_at"]


def test_save_judgment_without_pack_still_works(zing_workspace, monkeypatch, tmp_path):
    monkeypatch.setenv(mcp_server.PROMPTS_DIR_ENV, str(tmp_path / "empty"))
    storage.save_breakdown(make_breakdown(), slug=SLUG)
    result = mcp_server.h_save_judgment(SLUG, {"anything": 1}, section="notes")
    assert result["ok"] is True
    assert result["prompt_version"] == "unknown"


def test_save_judgment_no_breakdown_is_actionable(zing_workspace, prompts_dir):
    result = mcp_server.h_save_judgment("ghost", {"hook": 1}, section="notes")
    assert result["ok"] is False and "study_video" in result["error"]


def test_save_judgment_rejects_junk(zing_workspace):
    assert mcp_server.h_save_judgment(SLUG, {})["ok"] is False
    assert mcp_server.h_save_judgment(SLUG, {"a": 1}, section="Bad Section!")["ok"] is False


# -- F-02: slug traversal must be an errors-as-data rejection -----------------
# S1-REVIEW-lane-c finding 1 repro: h_get_breakdown("../../escape") -> ok=true
# and h_save_judgment("../../escape", ...) rewrote a file OUTSIDE ZING_HOME.

TRAVERSAL_SLUGS = [
    "../../escape",
    "..\\..\\escape",
    "/etc/passwd",
    "C:\\Windows\\escape",
    "C:/Windows/escape",
    "nested/inside",
    "nested\\inside",
    "..",
]


def plant_outside_breakdown(tmp_path):
    """With ZING_HOME at tmp_path/'zing-home', breakdowns/../../escape
    resolves to tmp_path/'escape' — plant a victim breakdown there."""
    outside = tmp_path / "escape"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "breakdown.json").write_text(
        make_breakdown().to_json(indent=2) + "\n", encoding="utf-8"
    )
    (outside / "breakdown.md").write_text("# outside the workspace\n", encoding="utf-8")
    return outside


@pytest.mark.parametrize("bad", TRAVERSAL_SLUGS)
def test_get_breakdown_rejects_traversal_as_data(zing_workspace, bad):
    result = mcp_server.h_get_breakdown(bad)
    assert result["ok"] is False
    assert "slug" in result["error"]


@pytest.mark.parametrize("bad", TRAVERSAL_SLUGS)
def test_save_judgment_rejects_traversal_as_data(zing_workspace, bad):
    result = mcp_server.h_save_judgment(bad, {"anything": 1}, section="notes")
    assert result["ok"] is False
    assert "slug" in result["error"]


@pytest.mark.parametrize("bad", TRAVERSAL_SLUGS)
def test_push_to_uoink_rejects_traversal_as_data(zing_workspace, bad, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("a traversal slug must never reach the network")

    monkeypatch.setattr(
        "myzing.uoink_bridge.urllib.request.urlopen", no_network
    )
    result = mcp_server.h_push_to_uoink(bad)
    assert result["ok"] is False
    assert "slug" in result["error"]


def test_get_breakdown_cannot_read_outside_workspace(zing_workspace, tmp_path):
    plant_outside_breakdown(tmp_path)
    result = mcp_server.h_get_breakdown("../../escape")
    assert result["ok"] is False  # the review repro returned ok=true here


def test_save_judgment_cannot_write_outside_workspace(zing_workspace, tmp_path):
    outside = plant_outside_breakdown(tmp_path)
    before = (outside / "breakdown.json").read_text(encoding="utf-8")
    result = mcp_server.h_save_judgment(
        "../../escape", {"pwned": True}, section="notes"
    )
    assert result["ok"] is False
    # the out-of-workspace file is byte-identical — nothing was rewritten
    assert (outside / "breakdown.json").read_text(encoding="utf-8") == before


def test_push_to_uoink_cannot_push_outside_workspace(
    zing_workspace, tmp_path, monkeypatch
):
    plant_outside_breakdown(tmp_path)

    def no_network(*a, **k):
        raise AssertionError("out-of-workspace markdown must never be pushed")

    monkeypatch.setattr(
        "myzing.uoink_bridge.urllib.request.urlopen", no_network
    )
    result = mcp_server.h_push_to_uoink("../../escape")
    assert result["ok"] is False


# -- zing_status / get_prompt ------------------------------------------------

def test_zing_status_shape(zing_workspace, prompts_dir, monkeypatch, live_job):
    monkeypatch.setattr(mcp_server, "_study_api", lambda: None)
    storage.write_status("busy-slug", state="running", phase="audio")
    live_job("busy-slug")  # F-03: only a live runner keeps `running` honest
    result = mcp_server.h_zing_status()
    assert result["ok"] is True
    assert result["engine_available"] is False
    assert {"ok", "required_missing", "checks"} <= set(result["environment"])
    assert result["workspace"]["breakdowns"] == 1
    assert result["jobs"] == [
        {"slug": "busy-slug", "state": "running", "phase": "audio", "error": ""}
    ]
    assert result["prompts"] == ["study"]


def test_get_prompt_roundtrip(prompts_dir):
    result = mcp_server.h_get_prompt("study")
    assert result["ok"] is True
    assert result["version"] == "0.1.0"
    assert "Judge the breakdown" in result["content"]


def test_get_prompt_unknown_name_lists_available(prompts_dir):
    result = mcp_server.h_get_prompt("direct")
    assert result["ok"] is False and "study" in result["error"]


def test_get_prompt_no_pack_is_honest(monkeypatch, tmp_path):
    monkeypatch.setenv(mcp_server.PROMPTS_DIR_ENV, str(tmp_path / "void"))
    result = mcp_server.h_get_prompt("study")
    assert result["ok"] is False and "without prompts" in result["error"]


# -- storage additions used by the server ------------------------------------

def test_status_merge_and_resolve(zing_workspace):
    storage.write_status(SLUG, state="running", phase="ingest")
    storage.write_status(SLUG, phase="shots")
    status = storage.read_status(SLUG)
    assert status["state"] == "running" and status["phase"] == "shots"
    resolved = storage.resolve_relpath(SLUG, "media.mp4")
    assert resolved == storage.breakdown_dir(SLUG) / "media.mp4"


def test_list_breakdowns_shows_running_study_not_error(zing_workspace):
    storage.write_status(SLUG, state="running", phase="ocr")
    entries = storage.list_breakdowns()
    assert entries == [{"slug": SLUG, "study": "running", "phase": "ocr"}]
