"""MCP tool handlers, driven directly (no SDK needed): honest envelopes,
job lifecycle on disk, judgment stamping/validation, prompt access."""

from __future__ import annotations

import ast
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
    api.kept = []  # B-S6: kept_media values the engine actually received
    api.handoffs = []  # contract v1: handoff dicts the engine received

    def study(source: str, phase_callback=None, kept_media=None, handoff=None):
        api.calls.append(source)
        if kept_media is not None:
            api.kept.append(kept_media)
        if handoff is not None:
            api.handoffs.append(handoff)
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


# -- generate_thumbnails -----------------------------------------------------

def test_generate_thumbnails_returns_frames_and_prompts(
    zing_workspace, monkeypatch, tmp_path
):
    frame = tmp_path / "candidate.jpg"
    frame.write_bytes(b"jpeg")
    package = {
        "slug": SLUG,
        "candidates": [
            {
                "frame": "thumbnails/candidate.jpg",
                "frame_path": str(frame),
            }
        ],
        "prompts": [{"archetype": name} for name in ("A", "B", "C")],
        "manifest_path": str(tmp_path / "thumbs.json"),
    }
    monkeypatch.setattr(
        "myzing.thumbs.generate_thumbnails",
        lambda slug: package,
    )

    result = mcp_server.h_generate_thumbnails(SLUG)

    assert result["ok"] is True
    assert result["slug"] == SLUG
    assert result["candidates"][0]["frame_path"] == str(frame)
    content = mcp_server.mcp_thumbnail_content(SLUG)
    assert json.loads(content[0])["ok"] is True
    assert content[1].path == frame


def test_generate_thumbnails_rejects_path_slug(zing_workspace):
    result = mcp_server.h_generate_thumbnails("../../outside")
    assert result["ok"] is False
    assert "invalid slug" in result["error"]


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
    # Was "not in this build yet (Sprint 1 in progress)" — this test
    # PINNED the stale message and so protected it from being noticed.
    # A test asserting a message is also a test asserting that message
    # stays correct; when the world moved, the pin held the lie in place.
    assert 'myzing[study]' in result["error"]


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


def test_study_video_kept_media_reaches_the_engine(
    zing_workspace, fake_engine, tmp_path
):
    """B-S6 seam: the bridge hands the engine a kept-media path — the MCP
    surface passes it through expanded, records it in status, and echoes
    it in the started response."""
    kept = tmp_path / "kept.mp4"
    kept.write_bytes(b"\x00" * 2048)
    result = mcp_server.h_study_video(SRC_URL, kept_media=str(kept))
    assert result["ok"] is True and result["status"] == "started"
    assert result["kept_media"] == str(kept)
    assert "zero network fetch" in result["hint"]
    status = wait_done(result["slug"])
    assert status["state"] == "done"
    assert status["kept_media"] == str(kept)
    assert fake_engine.kept == [str(kept)]


def test_study_video_kept_media_engine_without_support_is_honest(
    zing_workspace, monkeypatch, tmp_path
):
    """An engine build predating A-S6 must be refused at dispatch — not
    silently studied without the kept file (that would be a quiet
    network fetch the caller explicitly tried to avoid)."""
    api = types.ModuleType("myzing.study.api")
    api.study = lambda source, phase_callback=None: None
    monkeypatch.setattr(mcp_server, "_study_api", lambda: api)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")
    result = mcp_server.h_study_video(SRC_URL, kept_media=str(tmp_path / "k.mp4"))
    assert result["ok"] is False
    assert "kept-media support" in result["error"]


def test_study_video_kept_media_blank_is_rejected(zing_workspace, fake_engine):
    result = mcp_server.h_study_video(SRC_URL, kept_media="   ")
    assert result["ok"] is False
    assert "kept_media" in result["error"]


def test_study_video_without_kept_media_omits_the_field(
    zing_workspace, fake_engine
):
    result = mcp_server.h_study_video(SRC_URL)
    assert result["ok"] is True
    assert "kept_media" not in result  # absent, not null — nothing to echo
    assert fake_engine.kept == []


# -- study_uoink_item (INTEGRATION-CONTRACT v1 §9) ---------------------------

UOINK_REF = "uoink://item/short-123"


def resolved_available(tmp_path):
    return {
        "ok": True,
        "data": {
            "item_ref": UOINK_REF,
            "state": "available",
            "source_url": SRC_URL,
            "media": {
                "path": str(tmp_path / "video.mp4"),
                "media_type": "video/mp4",
                "byte_length": 4,
                "sha256": "ab" * 32,
            },
            "provenance": {"kind": "uoink_sidecar"},
        },
    }


def test_study_uoink_item_available_dispatches_kept_and_handoff(
    zing_workspace, fake_engine, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "myzing.uoink_bridge.resolve_kept_media",
        lambda ref: resolved_available(tmp_path),
    )
    result = mcp_server.h_study_uoink_item(UOINK_REF)
    assert result["ok"] is True and result["status"] == "started"
    assert result["slug"] == SLUG  # identity from source_url (stable-IDs rule)
    assert result["item_ref"] == UOINK_REF
    assert result["kept_state"] == "available"
    assert "zero network fetch" in result["hint"]
    status = wait_done(SLUG)
    assert status["state"] == "done"
    assert fake_engine.kept == [str(tmp_path / "video.mp4")]
    assert fake_engine.handoffs == [{
        "source_ref": UOINK_REF,
        "state": "available",
        "sha256": "ab" * 32,
        "byte_length": 4,
    }]


def test_study_uoink_item_not_kept_refetches_with_reasoned_handoff(
    zing_workspace, fake_engine, monkeypatch
):
    resolved = {
        "ok": True,
        "data": {
            "item_ref": UOINK_REF,
            "state": "not_kept",
            "source_url": SRC_URL,
            "media": None,
            "provenance": {"kind": "uoink_sidecar"},
        },
    }
    monkeypatch.setattr(
        "myzing.uoink_bridge.resolve_kept_media", lambda ref: resolved
    )
    result = mcp_server.h_study_uoink_item(UOINK_REF)
    assert result["ok"] is True
    assert result["kept_state"] == "not_kept"
    assert "fetching from the source URL" in result["hint"]
    wait_done(SLUG)
    assert fake_engine.kept == []  # nothing kept to stage
    assert fake_engine.handoffs[0]["state"] == "not_kept"


def test_study_uoink_item_without_source_url_fails_honestly(
    zing_workspace, fake_engine, monkeypatch
):
    resolved = {
        "ok": True,
        "data": {
            "item_ref": UOINK_REF,
            "state": "not_kept",
            "source_url": None,
            "media": None,
            "provenance": {},
        },
    }
    monkeypatch.setattr(
        "myzing.uoink_bridge.resolve_kept_media", lambda ref: resolved
    )
    result = mcp_server.h_study_uoink_item(UOINK_REF)
    assert result["ok"] is False
    assert "no source_url" in result["error"]
    assert fake_engine.calls == []  # nothing honest to study — no dispatch


def test_study_uoink_item_resolver_failure_passes_through(
    zing_workspace, fake_engine, monkeypatch
):
    monkeypatch.setattr(
        "myzing.uoink_bridge.resolve_kept_media",
        lambda ref: {"ok": False, "error": "no uoink helper at X"},
    )
    result = mcp_server.h_study_uoink_item(UOINK_REF)
    assert result["ok"] is False and "no uoink helper" in result["error"]


def test_study_uoink_item_engine_predating_contract_is_refused(
    zing_workspace, monkeypatch
):
    api = types.ModuleType("myzing.study.api")
    api.study = lambda source, phase_callback=None, kept_media=None: None
    monkeypatch.setattr(mcp_server, "_study_api", lambda: api)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")
    result = mcp_server.h_study_uoink_item(UOINK_REF)
    assert result["ok"] is False
    assert "predates the kept-media handoff contract" in result["error"]


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


def test_study_job_pinned_to_dispatch_workspace(zing_workspace, monkeypatch):
    """F-15 regression: mutating ZING_HOME mid-run must not redirect a
    running job's writes. Fails before the use_workspace fix (the worker
    re-resolved env at write time and finished into the wrong root)."""
    import threading

    gate = threading.Event()
    api = types.ModuleType("myzing.study.api")

    def study(source: str):
        assert gate.wait(10), "test gate never opened"
        return make_breakdown(source)

    api.study = study
    monkeypatch.setitem(sys.modules, "myzing.study.api", api)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")

    result = mcp_server.h_study_video(SRC_URL)
    assert result["ok"] is True and result["status"] == "started"

    hijack = zing_workspace.parent / "hijacked-home"
    monkeypatch.setenv(storage.ENV_VAR, str(hijack))  # env changes mid-run
    gate.set()
    with storage.use_workspace(zing_workspace):  # read where the job SHOULD write
        status = wait_done(SLUG)
        assert status["state"] == "done"
        assert (storage.breakdown_dir(SLUG) / "breakdown.json").is_file()
    assert not (hijack / "breakdowns").exists()  # nothing leaked to the new root


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
    # every per-event array in the contract is countable in the summary —
    # a new schema field must not silently vanish from the compact view
    assert set(summary["breakdown"]["counts"]) == {
        "shots", "words", "captions", "transitions",
    }


def test_get_breakdown_serves_base_dir_for_relative_paths(zing_workspace):
    """B-Q10: meta.media_path and shots[].keyframe are breakdown-relative;
    an MCP client can only resolve them if the result carries the base dir."""
    storage.save_breakdown(make_breakdown(), slug=SLUG)
    result = mcp_server.h_get_breakdown(SLUG)
    assert result["dir"] == str(storage.breakdown_dir(SLUG))
    summary = mcp_server.h_get_breakdown(SLUG, detail="summary")
    assert summary["dir"] == str(storage.breakdown_dir(SLUG))
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


# -- SG-2 seventh pass: mcp_server's remaining honest gaps --------------------

def test_version_unknown_when_metadata_absent(monkeypatch):
    import importlib.metadata as md

    def missing(name):
        raise md.PackageNotFoundError(name)

    monkeypatch.setattr(mcp_server.importlib.metadata, "version", missing)
    assert mcp_server._version() == "unknown"


def test_study_api_import_failure_is_engine_absent(monkeypatch):
    real_import = mcp_server.importlib.import_module

    def failing(name, *a, **k):
        if name == "myzing.study.api":
            raise ImportError("broken build")
        return real_import(name, *a, **k)

    monkeypatch.setattr(mcp_server.importlib, "import_module", failing)
    assert mcp_server._study_api() is None


def test_engine_supports_uninspectable_study_dispatches(monkeypatch):
    api = types.ModuleType("myzing.study.api")
    api.study = min  # inspect.signature(min) raises ValueError (overloads)
    assert mcp_server._engine_supports(api, "kept_media") is True


def test_thumbnail_content_error_package_is_single_payload(zing_workspace):
    content = mcp_server.mcp_thumbnail_content("../../bad")
    assert len(content) == 1
    assert json.loads(content[0])["ok"] is False


def test_zing_status_engagement_storage_failure_is_named(
    zing_workspace, monkeypatch
):
    from myzing import engagement

    def boom():
        raise engagement.EngagementStorageError("locked")

    monkeypatch.setattr(engagement, "status", boom)
    result = mcp_server.h_zing_status()
    assert result["ok"] is True  # engagement trouble never fails status
    assert result["engagement"]["state"] == "needs_attention"
    assert result["engagement"]["error"] == "storage_unavailable"


def test_build_profile_engine_failure_is_enveloped(zing_workspace, monkeypatch):
    b = make_breakdown()
    storage.save_breakdown(b, slug=SLUG)
    api = types.ModuleType("myzing.profile.api")

    def build_profile(name, slugs):
        raise ValueError("fewer than 2 usable sources")

    api.build_profile = build_profile
    monkeypatch.setattr(mcp_server, "_profile_api", lambda: api)
    result = mcp_server.h_build_profile("mine", [SLUG])
    assert result["ok"] is False
    assert "profile build failed" in result["error"]
    assert "fewer than 2" in result["error"]


def test_setup_taste_bad_pack_manifest_is_enveloped(zing_workspace, monkeypatch):
    from myzing import setup_flow

    def bad_pack(name):
        raise ValueError("two packs claim the name 'dupe'")

    monkeypatch.setattr(setup_flow, "load_pack", bad_pack)
    result = mcp_server.h_setup_taste("mytaste", pack="dupe")
    assert result["ok"] is False
    assert "two packs claim" in result["error"]


def test_setup_taste_ready_but_build_failed_is_honest(
    zing_workspace, monkeypatch
):
    from myzing import setup_flow

    outcome = {
        "built": False,
        "build": {"error": "profiles need 2+ studied sources"},
        "plan": {"ready_to_build": True, "references": []},
    }
    monkeypatch.setattr(
        setup_flow, "advance_setup", lambda *a, **k: outcome
    )
    result = mcp_server.h_setup_taste("mytaste", links=["https://x.test/v"])
    assert result["ok"] is False
    assert "profiles need 2+" in result["error"]


def test_serve_without_sdk_exits_2_with_install_hint(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "mcp", None)  # import mcp -> ImportError
    assert mcp_server.run([]) == 2
    err = capsys.readouterr().err
    assert "myzing[mcp]" in err and "-e" in err


def test_print_config_notes_missing_sdk(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "mcp", None)
    assert mcp_server.run(["--print-config"]) == 0
    out = capsys.readouterr().out
    assert "mcp SDK is not installed" in out
    assert "source checkout" in out


def test_export_otio_without_render_extras_is_actionable(
    zing_workspace, tmp_path, monkeypatch
):
    edl = tmp_path / "edl.json"
    edl.write_text(json.dumps({
        "version": 1, "source_slug": SLUG, "clips": [],
    }), encoding="utf-8")
    b = make_breakdown()
    storage.save_breakdown(b, slug=SLUG)
    monkeypatch.setitem(sys.modules, "myzing.render.otio_export", None)
    result = mcp_server.h_export_otio(str(edl))
    if result["ok"] is False and "render extras" in result["error"]:
        assert 'myzing[render]' in result["error"]
    else:
        # EDL validation may reject first on this build — either way the
        # handler answered with the envelope, never a traceback.
        assert "ok" in result


# -- F-03 liveness primitive: direct platform pins ----------------------------

def test_pid_alive_own_and_dead_and_invalid():
    assert mcp_server._pid_alive(os.getpid()) is True
    assert mcp_server._pid_alive(dead_pid()) is False
    assert mcp_server._pid_alive(0) is False
    assert mcp_server._pid_alive(-5) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows kernel32 branch")
def test_pid_alive_access_denied_counts_as_alive_windows():
    """The System process (pid 4) denies OpenProcess to user code — a
    process that EXISTS but isn't ours must count as alive (F-03:
    otherwise a study owned by an elevated/other-session server would
    be falsely reconciled to 'failed' while genuinely running)."""
    assert mcp_server._pid_alive(4) is True


# -- SG-3: the §7 receipt precondition, testable now that it has a name -----

def _breakdown_with_handoff(**handoff):
    b = make_breakdown()
    if handoff:
        b.provenance["source_handoff"] = handoff
    return b


EARNED = {
    "acquisition": "kept_media",
    "refetch": False,
    "source_ref": "uoink://item/short-1",
    "sha256": "ab" * 32,
}


def test_engagement_receipt_is_earned_only_by_a_complete_verified_handoff():
    """Contract §7: a receipt claims 'this user opened kept media that we
    verified'. Each clause is a way that claim could be UNEARNED, so a
    partial or hand-written provenance block must mint nothing."""
    assert mcp_server._earned_kept_media_receipt(
        _breakdown_with_handoff(**EARNED)
    ) == EARNED

    unearned = [
        {},                                              # no handoff at all
        {**EARNED, "acquisition": "source_refetch"},     # we refetched
        {**EARNED, "refetch": True},                     # ...and said so
        {k: v for k, v in EARNED.items() if k != "sha256"},      # no hash
        {k: v for k, v in EARNED.items() if k != "source_ref"},  # no ref
        {**EARNED, "sha256": 12345},                     # wrong type
    ]
    for handoff in unearned:
        assert mcp_server._earned_kept_media_receipt(
            _breakdown_with_handoff(**handoff)
        ) is None, handoff


def test_engagement_receipt_not_minted_for_a_refetched_study(
    zing_workspace, monkeypatch
):
    from myzing import engagement

    called = []
    monkeypatch.setattr(
        engagement, "record_opened",
        lambda ref, sha: called.append((ref, sha)) or {"state": "spooled"},
    )
    b = _breakdown_with_handoff(**{**EARNED, "refetch": True})
    mcp_server._record_engagement_if_earned(b, SLUG)
    assert called == []
    assert "engagement" not in b.provenance


def test_engagement_receipt_is_persisted_into_the_breakdown(
    zing_workspace, monkeypatch
):
    from myzing import engagement

    monkeypatch.setattr(
        engagement, "record_opened", lambda ref, sha: {"state": "recorded"}
    )
    b = _breakdown_with_handoff(**EARNED)
    storage.save_breakdown(b, slug=SLUG)
    mcp_server._record_engagement_if_earned(b, SLUG)
    assert b.provenance["engagement"] == {"state": "recorded"}
    assert storage.load_breakdown(SLUG).provenance["engagement"] == {
        "state": "recorded"
    }


def test_study_kwargs_only_passes_what_the_engine_accepts():
    def engine(source, phase_callback=None, kept_media=None, handoff=None):
        ...

    kwargs = mcp_server._study_kwargs(engine, "/tmp/k.mp4", {"state": "available"}, print)
    assert kwargs["kept_media"] == "/tmp/k.mp4"
    assert kwargs["handoff"] == {"state": "available"}
    assert kwargs["phase_callback"] is print

    def minimal(source):
        ...

    assert mcp_server._study_kwargs(minimal, None, None, print) == {}


# -- SG-4: the .mcpb bundle's world (core installed, study extras absent) ---

@pytest.fixture
def extras_absent(monkeypatch):
    """Exactly what the documented one-click .mcpb install produces: the
    core package plus `mcp`, and NO study extras (they carry compiled
    wheels the uv-type bundle deliberately does not ship)."""
    real = mcp_server.importlib.import_module

    def missing(name, *a, **k):
        if name in ("myzing.study.api", "myzing.profile.api"):
            raise ImportError("No module named 'scenedetect'")
        return real(name, *a, **k)

    monkeypatch.setattr(mcp_server.importlib, "import_module", missing)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")


def test_bundle_user_is_told_to_install_extras_not_to_wait(
    zing_workspace, extras_absent
):
    """Found by scanning our own install paths: this message used to say
    'not in this build yet (Sprint 1 in progress) — study_video will work
    here unchanged once it lands'. Sprint 1 shipped long ago; the engine
    IS in the build; the extras are not. It told a user reachable via our
    documented .mcpb path to WAIT for something that already exists —
    unactionable advice for a one-command fix."""
    for result in (
        mcp_server.h_study_video("https://www.tiktok.com/@a/video/1"),
        mcp_server.h_study_uoink_item("uoink://item/short-1"),
    ):
        assert result["ok"] is False
        error = result["error"]
        assert 'myzing[study]' in error
        assert "not in this build yet" not in error
        assert "Sprint" not in error
        assert "once it lands" not in error


def test_profile_builder_absence_names_the_extras_too(zing_workspace, extras_absent):
    b = make_breakdown()
    storage.save_breakdown(b, slug=SLUG)
    result = mcp_server.h_build_profile("mine", [SLUG])
    assert result["ok"] is False
    assert 'myzing[study]' in result["error"]
    assert "Sprint" not in result["error"]


def test_no_user_facing_message_misdiagnoses_a_missing_extra():
    """Two phrasings that shipped for ~15 sprints and could not be acted
    on: a sprint number (internal scheduling, dates the product on the
    user's screen) and "not in this build" (the code IS in the build —
    the EXTRAS are missing, and updating cannot fix that).

    Lane-wide, because the same misdiagnosis was found in two modules on
    two different cycles: mcp_server (#334) and setup_flow (this one).
    Docstrings and comments are exempt — they legitimately cite sprint
    rulings as provenance; only string literals reaching users are
    checked."""
    import re
    from pathlib import Path

    root = Path(mcp_server.__file__).parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            ast.get_docstring(n, clean=False)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if node.value in docstrings:
                continue
            if re.search(r"Sprint \d|not in this build", node.value):
                offenders.append(f"{path.name}:{node.lineno} {node.value[:60]!r}")
    assert not offenders, (
        "user-facing text that misdiagnoses or cites internal scheduling: "
        f"{offenders}"
    )


def test_a_late_heartbeat_cannot_resurrect_a_finished_job(zing_workspace):
    """The invariant the heartbeat comment now credits correctly: the
    beater writes ONLY heartbeat_at. Simulate the worst case the timeout
    join allows — a beat landing AFTER the final write — and the finished
    state must survive."""
    storage.write_status(SLUG, state="running", phase="shots", pid=os.getpid())
    storage.write_status(SLUG, state="done", finished_at="2026-07-20T00:00:00+00:00")

    # exactly what _beat does, arriving late
    storage.write_status(SLUG, heartbeat_at="2026-07-20T00:00:09+00:00")

    status = storage.read_status(SLUG)
    assert status["state"] == "done"          # not resurrected
    assert status["heartbeat_at"].endswith("00:09+00:00")  # merged, harmlessly


def test_slug_for_never_emits_a_dot_as_the_validator_assumes(zing_workspace):
    """storage's validator refuses any '.' and justifies it with 'slug_for()
    never emits a dot'. That is a claim about ANOTHER function, so it is
    exactly the kind that rots silently — pin it, including the file stems
    most likely to break it."""
    for source in (
        r"C:\clips\my.video.file.mp4",
        r"C:\clips\take.1.mp4",
        "/home/x/a.b.c.mov",
        "https://example.com/v.mp4",
        r"C:\clips\....mp4",
    ):
        slug = storage.slug_for(source)
        assert "." not in slug, (source, slug)
        storage.validate_slug(slug)  # and the validator accepts its own output
