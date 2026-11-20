"""Background story builds for MCP, with progress saved beside story.json."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from myzing.storage import _write_atomic

from . import StoryError

_JOBS: dict[str, threading.Thread] = {}
_LOCK = threading.RLock()
STATUS_FILE = "story-status.json"


def _write(directory: Path, result: dict) -> None:
    path = directory / STATUS_FILE
    with _LOCK:
        _write_atomic(path, json.dumps(result, indent=2, ensure_ascii=False) + "\n")


def _run(directory: Path, options: dict) -> None:
    from .command import build

    try:
        result = build(directory, **options)
        _write(directory, {"state": "done", **result})
    except Exception as exc:
        # Unexpected provider exceptions can contain request headers or secrets.
        error = (str(exc) if isinstance(exc, StoryError) else
                 f"Story build could not finish ({type(exc).__name__}); run zing story build for setup details.")
        try:
            _write(directory, {"state": "failed", "error": error})
        except OSError:
            pass  # A saved running marker becomes interrupted after this worker exits.
    finally:
        with _LOCK:
            if _JOBS.get(str(directory)) is threading.current_thread():
                _JOBS.pop(str(directory))


def start(directory: Path, **options) -> dict:
    """Reject contract errors before starting one worker per story directory."""
    from .contract import load

    directory = Path(directory).expanduser().resolve()
    with _LOCK:
        if str(directory) in _JOBS:
            return {"directory": str(directory), "status": "already_running"}
        load(directory, look=options.get("look"), check_layout=False)
        _write(directory, {"state": "running"})
        thread = threading.Thread(target=_run, args=(directory, options),
                                  name=f"zing-story-{directory.name}", daemon=True)
        _JOBS[str(directory)] = thread
        try:
            thread.start()
        except RuntimeError:
            _JOBS.pop(str(directory), None)
            _write(directory, {"state": "failed", "error": "Cannot start the story build worker."})
            raise StoryError("Cannot start the story build worker.") from None
    return {"directory": str(directory), "status": "started"}


def status(directory: Path) -> dict:
    """Read saved state without changing files, including interrupted workers."""
    directory = Path(directory).expanduser().resolve()
    if not (directory / "story.json").is_file():
        raise StoryError(f"{directory} is not a story folder; create one with story_new")
    with _LOCK:
        try:
            result = json.loads((directory / STATUS_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            result = {"state": "draft"}
        except (OSError, ValueError) as exc:
            raise StoryError("Cannot read story-status.json; call story_build to start a new build.") from exc
        if not isinstance(result, dict) or result.get("state") not in {"running", "done", "failed"}:
            if result != {"state": "draft"}:
                raise StoryError("Invalid story-status.json; call story_build to start a new build.")
        running = str(directory) in _JOBS
        if result.get("state") == "running" and not running:
            result["state"] = "interrupted"
            result["hint"] = "The build stopped before finishing; call story_build to run it again."
        return {**result, "directory": str(directory), "running": running}
