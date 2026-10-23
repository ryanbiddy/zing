"""Use the existing owned-process supervisor for studio-only operations."""

from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path
from uuid import uuid4

from myzing import storage
from myzing.match.process import Cancelled, run_lock, run_owned
from .models import read_json, write_json

_LOCK = threading.Lock()
_JOBS = {}


@contextmanager
def busy_lock(root):
    """The production lock, with a studio message instead of match_status advice."""
    try:
        lease = run_lock(root)
        lease.__enter__()
    except ValueError:
        raise ValueError(f"Another studio session is already making something in {root}. Wait for it to "
                         "finish, or use another output folder (o on the plan screen).") from None
    try:
        yield
    finally:
        lease.__exit__(None, None, None)


def _discard_abandoned_speech(answers):
    """A killed worker cannot run its download cleanup; do it for the chosen model."""
    from myzing.model_fetch import discard_abandoned
    from myzing.study import speech_models
    if answers.get("speech_model") in speech_models.MODELS:
        try:
            discard_abandoned(speech_models.cache_dir(answers["speech_model"]))
        except (OSError, ValueError):
            pass  # the next download attempt removes them under its lock


def execute(answers, *, progress=None, cancel=None, locked=False):
    root = Path(answers["project"])
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    result_path = root / f"studio-job-{run_id}.json"
    with nullcontext() if locked else busy_lock(root):
        try:
            code = run_owned([sys.executable, "-m", "myzing.studio.worker"],
                         json.dumps({"answers": answers, "result_path": str(result_path)}),
                         progress=progress, cancel=cancel,
                         env={**os.environ, "ZING_HOME": str(storage.resolve_workspace()),
                              "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "PYTHONIOENCODING": "utf-8"})
        except Cancelled:
            raise Cancelled("Studio run cancelled; owned processes stopped.") from None
        finally:
            _discard_abandoned_speech(answers)
    if code not in (0, 1) or not result_path.is_file():
        raise RuntimeError(f"Studio worker exited {code}; resume the saved session to retry.")
    result = read_json(result_path)
    result_path.unlink()
    return result


def reconcile(project):
    """Reconcile both durable records while holding the released production lock."""
    root = Path(project).expanduser().resolve()
    file = root / "studio-job.json"
    if not file.is_file():
        return None
    with _LOCK:
        state = read_json(file)
        active = _JOBS.get(str(root))
        if state.get("status") != "running" or (active and active[0].is_alive()):
            return state
        from myzing.project.locking import _pid_alive
        if state.get("pid") != os.getpid() and _pid_alive(state.get("pid", -1)):
            return state
        try:
            lease = run_lock(root)
            lease.__enter__()
        except ValueError:
            return state
        try:
            from .models import SESSION_NAME, load_session, save_session
            hint = f'Studio run interrupted. Resume with zing studio --resume "{root}".'
            state.update(status="interrupted", error="Studio worker is gone.", hint=hint)
            if (root / SESSION_NAME).is_file():
                session = load_session(root)
                session.status, session.result = "interrupted", {"status": "interrupted", "hint": hint}
                save_session(root, session)
            write_json(file, state)
        finally:
            lease.__exit__(None, None, None)
        return state


def job(answers=None, *, confirmed=False, project=None, cancel=False):
    from .flow import next_step

    if type(confirmed) is not bool or type(cancel) is not bool:
        raise ValueError("confirmed and cancel must be booleans")
    if project:
        root = Path(project).expanduser().resolve()
        file = root / "studio-job.json"
        if not file.is_file():
            raise ValueError("No studio job here. Start a confirmed plan first.")
        reconcile(root)
        with _LOCK:
            active = _JOBS.get(str(root))
            live = active is not None and active[0].is_alive()
            if cancel and live:
                active[1].set()
            state = read_json(file)
        result = {k: v for k, v in state.items() if k != "pid"}
        if cancel:
            result["cancellation_requested"] = live
            result["hint"] = state.get("hint") or ("Cancellation requested; poll until the owned worker stops." if live else
                              "No live job owned by this server. A job in another process must be cancelled through its owning server.")
        return result
    if not confirmed:
        raise ValueError("Show the ready plan and obtain confirmation, then set confirmed=true.")
    step = next_step(answers)
    if step["status"] != "plan":
        raise ValueError("Studio answers are incomplete; call zing_studio for the next question.")
    a = step["answers"]
    if a["path"] not in "abdf":
        raise ValueError("Reuse the existing match_start, still_concepts/still_render or music_check tools listed in this plan.")
    root = Path(a["project"])
    root.mkdir(parents=True, exist_ok=True)
    reconcile(root)
    file = root / "studio-job.json"
    from .models import Session, save_session
    session = Session(answers=a, status="running")
    workspace = storage.resolve_workspace()
    with _LOCK:
        if str(root) in _JOBS:
            return {"status": "running", "project": str(root)}
        lease = run_lock(root)
        lease.__enter__()
        stop = threading.Event()
        try:
            save_session(root, session)
            write_json(file, {"status": "running", "project": str(root), "pid": os.getpid(), "phase": "starting"})
        except BaseException:
            lease.__exit__(None, None, None)
            raise

        def work():
            try:
                def progress(line):
                    write_json(file, {"status": "running", "project": str(root), "pid": os.getpid(), "phase": line})
                with storage.use_workspace(workspace):
                    result = execute(a, progress=progress, cancel=stop, locked=True)
                state = {"status": result["status"], "project": str(root), "result": result}
                session.status, session.result = result["status"], result
            except BaseException as exc:
                status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
                state = {"status": status, "project": str(root), "error": str(exc)}
                session.status, session.result = status, state
            finally:
                try:
                    with _LOCK:
                        write_json(file, state)
                        save_session(root, session)
                        _JOBS.pop(str(root), None)
                finally:
                    lease.__exit__(None, None, None)
        thread = threading.Thread(target=work, daemon=True)
        _JOBS[str(root)] = (thread, stop)
        try:
            thread.start()
        except BaseException:
            _JOBS.pop(str(root), None)
            lease.__exit__(None, None, None)
            raise
    return {"status": "started", "project": str(root), "hint": "Poll zing_studio_run(project=...). Use cancel=true to stop this server's job."}
