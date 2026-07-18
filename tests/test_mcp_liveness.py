"""SG-2 coverage sweep: the F-03 crash-honesty machinery.

_pid_alive / _parse_ts / _reconcile_running were the least-covered code in
mcp_server (86% before this file) — and they are exactly the paths that
decide whether a persisted "running" state is believed or honestly
rewritten as failed. Every branch gets a real test, including a live
foreign process (a spawned sleeping python) and a genuinely dead pid.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from myzing import mcp_server, storage

SLUG = "tiktok-live"


def _now_iso(delta_s: float = 0.0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=delta_s)
    ).isoformat(timespec="seconds")


@pytest.fixture
def dead_pid() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"], stdout=subprocess.DEVNULL
    )
    proc.wait(timeout=30)
    return proc.pid


@pytest.fixture
def live_foreign_pid():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
    )
    yield proc.pid
    proc.kill()
    proc.wait(timeout=10)


# -- _pid_alive --------------------------------------------------------------

def test_pid_alive_own_process():
    assert mcp_server._pid_alive(os.getpid()) is True


def test_pid_alive_rejects_nonpositive():
    assert mcp_server._pid_alive(0) is False
    assert mcp_server._pid_alive(-7) is False


def test_pid_alive_dead_process(dead_pid):
    assert mcp_server._pid_alive(dead_pid) is False


def test_pid_alive_live_foreign_process(live_foreign_pid):
    assert mcp_server._pid_alive(live_foreign_pid) is True


# -- _parse_ts ---------------------------------------------------------------

def test_parse_ts_roundtrip():
    ts = _now_iso()
    parsed = mcp_server._parse_ts(ts)
    assert parsed is not None and parsed.isoformat(timespec="seconds") == ts


def test_parse_ts_garbage_is_none():
    assert mcp_server._parse_ts(None) is None
    assert mcp_server._parse_ts("") is None
    assert mcp_server._parse_ts("yesterday-ish") is None
    assert mcp_server._parse_ts(12345) is None


# -- _reconcile_running ------------------------------------------------------

def _running_status(**overrides):
    status = {
        "state": "running",
        "phase": "shots",
        "pid": os.getpid(),
        "heartbeat_at": _now_iso(),
    }
    status.update(overrides)
    return status


def test_reconcile_ignores_non_running(zing_workspace):
    status = {"state": "done"}
    assert mcp_server._reconcile_running(SLUG, status) is status


def test_reconcile_no_pid_fails_honestly(zing_workspace):
    storage.write_status(SLUG, **_running_status())
    result = mcp_server._reconcile_running(SLUG, _running_status(pid=None))
    assert result["state"] == "failed"
    assert "no runner pid" in result["error"]
    assert storage.read_status(SLUG)["state"] == "failed"  # rewritten on disk


def test_reconcile_own_pid_without_thread_is_orphan(zing_workspace):
    # pid == this process but no live thread in _JOBS -> the worker died
    storage.write_status(SLUG, **_running_status())
    result = mcp_server._reconcile_running(SLUG, _running_status())
    assert result["state"] == "failed"
    assert "worker thread" in result["error"]
    assert "study_video again" in result["error"]


def test_reconcile_dead_foreign_pid(zing_workspace, dead_pid):
    storage.write_status(SLUG, **_running_status(pid=dead_pid))
    result = mcp_server._reconcile_running(SLUG, _running_status(pid=dead_pid))
    assert result["state"] == "failed"
    assert f"pid {dead_pid}" in result["error"] and "dead" in result["error"]


def test_reconcile_live_foreign_fresh_heartbeat_is_believed(
    zing_workspace, live_foreign_pid
):
    status = _running_status(pid=live_foreign_pid, heartbeat_at=_now_iso())
    storage.write_status(SLUG, **status)
    result = mcp_server._reconcile_running(SLUG, status)
    assert result["state"] == "running"  # legitimately owned elsewhere
    assert storage.read_status(SLUG)["state"] == "running"  # untouched


def test_reconcile_live_foreign_stale_heartbeat_fails(
    zing_workspace, live_foreign_pid
):
    stale = _now_iso(-(mcp_server.HEARTBEAT_STALE_AFTER + 60))
    status = _running_status(pid=live_foreign_pid, heartbeat_at=stale)
    storage.write_status(SLUG, **status)
    result = mcp_server._reconcile_running(SLUG, status)
    assert result["state"] == "failed"
    assert "heartbeat" in result["error"] and "stale" in result["error"]


def test_reconcile_live_foreign_never_heartbeat_fails(
    zing_workspace, live_foreign_pid
):
    status = _running_status(pid=live_foreign_pid, heartbeat_at="")
    storage.write_status(SLUG, **status)
    result = mcp_server._reconcile_running(SLUG, status)
    assert result["state"] == "failed"
    assert "never heartbeat" in result["error"]


# -- dispatch race: finished-but-not-yet-popped worker -----------------------

def test_restudy_starts_even_while_old_worker_is_mid_cleanup(
    zing_workspace, monkeypatch
):
    """CI-caught race: a completed worker is briefly still alive (and in
    _JOBS) between its final status write and its cleanup pop. A re-study
    arriving in that window used to get 'already_studying' and never ran."""
    import sys as _sys
    import threading
    import types

    api = types.ModuleType("myzing.study.api")

    def study(source: str):
        from myzing.schemas import Breakdown, VideoMeta

        return Breakdown(
            meta=VideoMeta(source_url=source, platform="tiktok")
        )

    api.study = study
    monkeypatch.setitem(_sys.modules, "myzing.study.api", api)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")

    url = "https://www.tiktok.com/@a/video/424242"
    slug = "tiktok-424242"
    # First study already finished: done on disk...
    storage.write_status(
        slug, state="done", phase="markdown", pid=1, finished_at="t"
    )
    # ...but its worker thread is still alive and registered (mid-cleanup).
    lingering_done = threading.Event()
    lingering = threading.Thread(target=lingering_done.wait, daemon=True)
    lingering.start()
    with mcp_server._JOBS_LOCK:
        mcp_server._JOBS[slug] = lingering
    try:
        result = mcp_server.h_study_video(url)
        assert result["ok"] is True
        assert result["status"] == "started", (
            "re-study must start; a finished-but-unpopped worker is not a "
            "running study"
        )
        import time

        deadline = time.time() + 10
        while time.time() < deadline:
            s = storage.read_status(slug)
            if s and s.get("state") in ("done", "failed") and s.get("finished_at") != "t":
                break
            time.sleep(0.01)
        assert storage.load_breakdown(slug).meta.source_url == url
    finally:
        lingering_done.set()
        lingering.join(timeout=10)


def test_finishing_worker_pop_is_identity_guarded(zing_workspace):
    """The old worker's cleanup must not evict a newer thread registered
    under the same slug (that would make _reconcile_running falsely fail
    the live job as 'worker thread gone')."""
    import threading

    slug = "tiktok-guard"
    newer = threading.Thread(target=lambda: None)
    with mcp_server._JOBS_LOCK:
        mcp_server._JOBS[slug] = newer

    def old_worker():
        raise RuntimeError("boom")

    # run an old worker's full body for the same slug; its finally must
    # leave the newer thread's registration in place
    mcp_server._run_study(
        lambda source: (_ for _ in ()).throw(RuntimeError("boom")),
        "src", slug, storage.workspace_root(),
    )
    try:
        assert mcp_server._JOBS.get(slug) is newer
    finally:
        with mcp_server._JOBS_LOCK:
            mcp_server._JOBS.pop(slug, None)
