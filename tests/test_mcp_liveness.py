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
