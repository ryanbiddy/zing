"""``zing serve-mcp``: the MCP stdio server — how AIs touch Zing.

Tool handlers + prompt delivery, built on the official MCP Python SDK
(FastMCP), stdio transport. Design is bound by SPRINT-1-D1 §Critique
resolutions and the B#2 ruling (2026-07-18):

- ``study_video`` is a background job: cheap validation up front, then a
  worker thread; returns ``{ok, slug, status: "started"}`` in under a
  second. Claude Desktop hard-caps tool calls at ~60s, so a synchronous
  minutes-long study would silently fail there (R1-B evidence). Job state
  lives in ``status.json`` in the slug's directory — a crashed process
  leaves honest state on disk. The runner stamps a liveness marker (pid +
  heartbeat) and readers reclassify a ``running`` state whose runner is
  dead or silent as ``failed`` (F-03) — no phantom jobs, ever.
- Errors are DATA: tools return ``{"ok": false, "error": actionable}``
  (uoink house envelope); protocol errors are reserved for malformed calls.
- ``zing_status`` is built on doctor's checks — one source of truth.
- Prompts are served three ways: MCP prompts capability (slash commands in
  Claude clients), the ``get_prompt`` tool (for clients without prompts
  support), and ``zing prompt <name>`` on the CLI.

Handlers are plain functions returning dicts so tests drive them without
the SDK; the SDK is only required to actually serve.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import json
import os
import re
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from myzing import doctor, storage
from myzing.prompt_pack import (
    PROMPTS_DIR_ENV,
    available_prompts,
    load_prompt,
    prompts_dir,
)

# Study phases in pipeline order (B#2 ruling). The engine reports the
# phase it is entering via callback when its seam supports one.
STUDY_PHASES = ("ingest", "shots", "transcribe", "ocr", "audio", "markdown")

_JOBS: dict[str, threading.Thread] = {}
_JOBS_LOCK = threading.Lock()

# F-03: liveness. The job runner refreshes ``heartbeat_at`` this often;
# readers stop believing a `running` status once the last beat is older
# than the stale budget (12 missed beats — clearly not a slow phase).
HEARTBEAT_INTERVAL = 10.0
HEARTBEAT_STALE_AFTER = 120.0

# storage.write_status is read-merge-write: concurrent phase/heartbeat/final
# writes from different threads would silently drop each other's fields.
_STATUS_LOCK = threading.Lock()


def _write_status(slug: str, **fields: Any) -> None:
    with _STATUS_LOCK:
        storage.write_status(slug, **fields)


def _ok(**fields: Any) -> dict[str, Any]:
    return {"ok": True, **fields}


def _err(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def _check_slug(slug: Any) -> dict[str, Any] | None:
    """F-02: slugs are AI-supplied — validate before any storage touch.
    Returns an errors-as-data envelope for a bad slug, None when valid."""
    try:
        storage.validate_slug(slug)
    except storage.SlugError as e:
        return _err(
            f"invalid slug: {e} — slugs are storage-owned names, never "
            "paths; use one returned by study_video() or list_breakdowns()"
        )
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _version() -> str:
    try:
        return importlib.metadata.version("myzing")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# ---------------------------------------------------------------------------
# Job liveness (F-03)
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    """Whether ``pid`` is a currently-running process (best effort, no
    signals sent). Windows needs kernel32 — os.kill(pid, 0) kills there."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_ACCESS_DENIED = 5
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            # access denied means the process exists but isn't ours
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _reconcile_running(slug: str, status: dict[str, Any]) -> dict[str, Any]:
    """F-03: believe a persisted ``running`` state only while its runner is
    demonstrably alive; otherwise rewrite it — on disk too, so every later
    reader agrees — as ``failed`` with an actionable message.

    Liveness, in order: a live worker thread in this process wins outright;
    else the stamped pid must be a living process AND the heartbeat fresh
    (another server process may legitimately own the job).
    """
    if status.get("state") != "running":
        return status
    with _JOBS_LOCK:
        job = _JOBS.get(slug)
        if job is not None and job.is_alive():
            return status
    pid = status.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        reason = (
            "it carries no runner pid — the study was started by a server "
            "that crashed or an older Zing"
        )
    elif pid == os.getpid():
        reason = f"its worker thread in this server (pid {pid}) is gone"
    elif not _pid_alive(pid):
        reason = f"its runner process (pid {pid}) is dead"
    else:
        beat = _parse_ts(status.get("heartbeat_at"))
        if beat is not None:
            age = (datetime.now(timezone.utc) - beat).total_seconds()
            if age <= HEARTBEAT_STALE_AFTER:
                return status  # live foreign runner, fresh heartbeat
            reason = (
                f"its last heartbeat was {int(age)}s ago "
                f"(stale after {int(HEARTBEAT_STALE_AFTER)}s)"
            )
        else:
            reason = f"process {pid} is alive but has never heartbeat"
    error = (
        f"study interrupted — status said 'running' but {reason}; "
        "call study_video again to restart it"
    )
    _write_status(slug, state="failed", error=error, updated_at=_now())
    return {**status, "state": "failed", "error": error}


# ---------------------------------------------------------------------------
# Study job runner
# ---------------------------------------------------------------------------

def _study_api():
    """Lane A's engine seam, or None while it hasn't merged."""
    try:
        api = importlib.import_module("myzing.study.api")
        return api if hasattr(api, "study") else None
    except ImportError:
        return None


def _run_study(study_fn: Any, source: str, slug: str, root: Path) -> None:
    """Worker-thread body: run the engine, persist, record honest state.

    ``root`` is the workspace captured when the job was dispatched (F-15):
    the whole run — engine storage calls, heartbeats, final writes — is
    pinned to it via ``storage.use_workspace``, so a ZING_HOME mutation
    elsewhere in the process mid-run cannot redirect this job's writes.
    ContextVars do not propagate into child threads, so the heartbeat
    thread pins itself too.

    While the engine runs, a side thread refreshes ``heartbeat_at`` every
    ``HEARTBEAT_INTERVAL`` seconds (F-03): a ``running`` status is only
    credible while its runner demonstrably breathes.
    """
    def set_phase(phase: str) -> None:
        _write_status(
            slug, phase=str(phase), heartbeat_at=_now(), updated_at=_now()
        )

    kwargs: dict[str, Any] = {}
    try:
        params = inspect.signature(study_fn).parameters
        for name in ("phase_callback", "progress_callback", "on_phase"):
            if name in params:
                kwargs[name] = set_phase
                break
    except (TypeError, ValueError):
        pass

    stop_beating = threading.Event()

    def _beat() -> None:
        with storage.use_workspace(root):
            while not stop_beating.wait(HEARTBEAT_INTERVAL):
                _write_status(slug, heartbeat_at=_now())

    beater = threading.Thread(
        target=_beat, name=f"zing-heartbeat-{slug}", daemon=True
    )
    with storage.use_workspace(root):
        beater.start()
        try:
            try:
                breakdown = study_fn(source, **kwargs)
            finally:
                # stop the heartbeat BEFORE the final write so a late beat
                # can never resurrect a finished job's `running` state
                stop_beating.set()
                beater.join(timeout=HEARTBEAT_INTERVAL + 5)
            json_path = storage.breakdown_dir(slug) / "breakdown.json"
            if breakdown is not None and not json_path.is_file():
                storage.save_breakdown(breakdown, slug=slug)
            _write_status(
                slug, state="done", finished_at=_now(), updated_at=_now(), error=""
            )
        except Exception as e:  # noqa: BLE001 — boundary: everything becomes honest disk state
            _write_status(
                slug,
                state="failed",
                error=f"{type(e).__name__}: {e}",
                finished_at=_now(),
                updated_at=_now(),
            )
        finally:
            with _JOBS_LOCK:
                _JOBS.pop(slug, None)


def h_study_video(url_or_path: str) -> dict[str, Any]:
    if not isinstance(url_or_path, str) or not url_or_path.strip():
        return _err("url_or_path required: a video URL or a local file path")
    source = url_or_path.strip()

    # Cheap validation first — failures must return in under a second.
    if not shutil.which("ffmpeg"):
        return _err(
            "ffmpeg not found on PATH — Zing cannot measure anything without "
            "it. Run `zing doctor` for the install command."
        )
    is_url = source.lower().startswith(("http://", "https://"))
    if not is_url:
        # F-11: expand once, up front, and use the SAME string everywhere —
        # validation, slug, status, and dispatch. Validating the expanded
        # path but dispatching the raw one meant ok/started followed by an
        # async "no such file: ~/...".
        expanded = Path(source).expanduser()
        if not expanded.is_file():
            return _err(
                f"file not found: {source} — pass a video URL or an existing "
                "local file path"
            )
        source = str(expanded)
    api = _study_api()
    if api is None:
        return _err(
            "the study engine is not in this build yet (Sprint 1 in "
            "progress) — study_video will work here unchanged once it "
            "lands; zing_status().engine_available will flip to true"
        )

    slug = storage.slug_for(source)
    # F-15: capture the workspace NOW and pin the whole job to it — the
    # worker thread must not re-resolve env that may change under it.
    root = storage.workspace_root()
    with _JOBS_LOCK:
        job = _JOBS.get(slug)
        if job is not None and job.is_alive():
            status = storage.read_status(slug) or {}
            return _ok(
                slug=slug,
                status="already_studying",
                phase=status.get("phase", ""),
                hint="poll zing_status() or get_breakdown(slug)",
            )
        _write_status(
            slug,
            state="running",
            phase=STUDY_PHASES[0],
            source=source,
            pid=os.getpid(),  # F-03: liveness marker readers verify
            heartbeat_at=_now(),
            started_at=_now(),
            updated_at=_now(),
            error="",
        )
        thread = threading.Thread(
            target=_run_study, args=(api.study, source, slug, root), daemon=True
        )
        _JOBS[slug] = thread
        thread.start()
    return _ok(
        slug=slug,
        status="started",
        hint=(
            "studying in the background (typically 1–5 minutes). Poll "
            "zing_status() for phase, then get_breakdown(slug) for the result."
        ),
    )


# ---------------------------------------------------------------------------
# Breakdown tools
# ---------------------------------------------------------------------------

def _summarize_breakdown(d: dict[str, Any]) -> dict[str, Any]:
    """Compact view: everything except the big per-event arrays."""
    return {
        "meta": d.get("meta", {}),
        "avg_shot_duration": d.get("avg_shot_duration", 0.0),
        "cuts_per_10s": d.get("cuts_per_10s", []),
        "counts": {
            "shots": len(d.get("shots", [])),
            "words": len(d.get("words", [])),
            "captions": len(d.get("captions", [])),
            "transitions": len(d.get("transitions", [])),
        },
        "audio": {
            k: v
            for k, v in d.get("audio", {}).items()
            if k != "loudness_curve"
        },
        "warnings": d.get("warnings", []),
        "provenance": d.get("provenance", {}),
        "judgment_sections": sorted(d.get("judgment", {})),
        "schema_version": d.get("schema_version", 1),
    }


def h_get_breakdown(slug: str, detail: str = "full") -> dict[str, Any]:
    if detail not in ("full", "summary"):
        return _err("detail must be 'full' or 'summary'")
    bad = _check_slug(slug)
    if bad:
        return bad
    # F-04: status speaks FIRST — breakdown.json may be a superseded
    # snapshot while a re-study runs. F-03: a `running` claim is only
    # believed while its runner is provably alive. Every response carries
    # `state`: running | done | failed | absent.
    status = storage.read_status(slug)
    if status is not None:
        status = _reconcile_running(slug, status)
    state = (status or {}).get("state", "")
    if state == "running":
        prior_exists = (storage.breakdown_dir(slug) / "breakdown.json").is_file()
        hint = "still studying — poll again shortly"
        if prior_exists:
            hint += (
                "; an older, superseded breakdown exists on disk and is "
                "deliberately not served while the re-study runs"
            )
        return _ok(
            slug=slug,
            ready=False,
            state="running",
            phase=status.get("phase", ""),
            started_at=status.get("started_at", ""),
            stale_breakdown_exists=prior_exists,
            hint=hint,
        )
    try:
        b = storage.load_breakdown(slug)
    except FileNotFoundError:
        if state == "failed":
            return {
                **_err(
                    f"study of '{slug}' failed: {status.get('error', 'unknown')} "
                    "— fix the cause (zing doctor helps) and call study_video again"
                ),
                "state": "failed",
            }
        return {
            **_err(
                f"no breakdown for slug '{slug}' — call list_breakdowns() to see "
                "what exists, or study_video() to create it"
            ),
            "state": "absent",
        }
    data = b.to_dict()
    if detail == "summary":
        data = _summarize_breakdown(data)
    if state == "failed":
        # The most recent (re-)study failed but an earlier study succeeded:
        # serve that last-good measurement, explicitly marked, so the
        # caller decides instead of being lied to (F-04 design, documented
        # in the tool description).
        return _ok(
            slug=slug,
            ready=True,
            state="failed",
            restudy_error=status.get("error", "unknown"),
            breakdown=data,
            hint=(
                "the most recent re-study FAILED — this breakdown is the "
                "last successful study's measurement. Fix the cause (zing "
                "doctor helps) and call study_video again, or judge this "
                "data knowingly."
            ),
        )
    return _ok(slug=slug, ready=True, state="done", breakdown=data)


def h_list_breakdowns() -> dict[str, Any]:
    entries = storage.list_breakdowns()
    return _ok(count=len(entries), breakdowns=entries)


def h_generate_thumbnails(slug: str) -> dict[str, Any]:
    """Plain handler: package metadata stays testable without the MCP SDK."""
    bad = _check_slug(slug)
    if bad:
        return bad
    from myzing.thumbs import ThumbnailError, generate_thumbnails

    try:
        package = generate_thumbnails(slug)
    except (OSError, ThumbnailError) as exc:
        return _err(str(exc))
    return _ok(**package)


def mcp_thumbnail_content(slug: str) -> list[Any]:
    """MCP adapter: JSON maps prompts to the attached image blocks."""
    package = h_generate_thumbnails(slug)
    payload = json.dumps(package, ensure_ascii=False)
    if not package.get("ok"):
        return [payload]
    from mcp.server.fastmcp import Image

    return [
        payload,
        *(
            Image(path=candidate["frame_path"])
            for candidate in package["candidates"]
        ),
    ]


def h_save_judgment(
    slug: str,
    judgment: dict[str, Any],
    section: str = "study",
    model: str = "",
) -> dict[str, Any]:
    bad = _check_slug(slug)
    if bad:
        return bad
    if not isinstance(judgment, dict) or not judgment:
        return _err(
            "judgment must be a non-empty JSON object — the shape is defined "
            "in the prompt pack (get_prompt('study'))"
        )
    if not re.fullmatch(r"[a-z0-9_-]+", section or ""):
        return _err("section must be a short slug like 'study'")

    loaded = load_prompt(section)
    prompt_version = "unknown"
    if loaded:
        meta, _text = loaded
        prompt_version = str(meta.get("version", "unknown"))
        required = meta.get("required_keys", [])
        if isinstance(required, list) and required:
            missing = sorted(set(required) - set(judgment))
            if missing:
                return _err(
                    f"judgment for section '{section}' is missing required "
                    f"key(s): {', '.join(missing)} — the expected shape is "
                    f"defined in get_prompt('{section}')"
                )

    stamp: dict[str, Any] = {
        "prompt_version": prompt_version,
        "written_at": _now(),
    }
    if model:
        stamp["model"] = model
    body = dict(judgment)
    body["_meta"] = stamp

    try:
        updated = storage.save_judgment(slug, {section: body})
    except FileNotFoundError as e:
        return _err(f"{e} — study the video first (study_video)")
    return _ok(
        slug=slug,
        section_written=section,
        sections_now=sorted(updated.judgment),
        prompt_version=prompt_version,
        path=str(storage.breakdown_dir(slug) / "breakdown.json"),
    )


def h_zing_status() -> dict[str, Any]:
    checks = doctor.summarize(doctor.run_checks())
    jobs = []
    for entry in storage.list_breakdowns():
        slug = entry.get("slug", "")
        try:
            status = storage.read_status(slug) if slug else None
        except storage.SlugError:
            continue  # foreign dir: already reported by list_breakdowns
        if status:
            # F-03: no phantom jobs — dead runners are reclassified here too
            status = _reconcile_running(slug, status)
        if status and status.get("state") in ("running", "failed"):
            jobs.append(
                {
                    "slug": slug,
                    "state": status.get("state"),
                    "phase": status.get("phase", ""),
                    "error": status.get("error", ""),
                }
            )
    return _ok(
        version=_version(),
        engine_available=_study_api() is not None,
        environment=checks,
        workspace={
            "root": str(storage.workspace_root()),
            "breakdowns": len(storage.list_breakdowns()),
        },
        jobs=jobs,
        prompts=available_prompts(),
    )


# ---------------------------------------------------------------------------
# get_frames (B-Q8, built to handoff/research/B-Q3-get-frames-design.md)
# ---------------------------------------------------------------------------

FRAMES_RECOMMENDED = 6
FRAMES_HARD_CAP = 8
FRAME_MAX_EDGE = 1024


def _extract_frame_jpeg(media: Path, t: float) -> bytes:
    """One frame at ``t`` seconds as JPEG bytes via ffmpeg (no disk cache)."""
    import subprocess

    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-ss", f"{t:.3f}", "-i", str(media),
        "-frames:v", "1",
        "-vf", f"scale='min({FRAME_MAX_EDGE},iw)':-2",
        "-c:v", "mjpeg", "-q:v", "5",
        "-f", "image2pipe", "-",
    ]
    out = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    if out.returncode != 0 or not out.stdout:
        detail = out.stderr.decode(errors="replace").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"ffmpeg exit {out.returncode}")
    return out.stdout


def h_get_frames(slug: str, timestamps: list[float]) -> dict[str, Any]:
    """SDK-free core: returns {ok, frames: [{label, jpeg|None, error}]}.

    The MCP wrapper turns this into interleaved text + image content.
    Per-frame failures (past-the-end timestamps, decode errors) become
    text entries so valid frames in the same call still arrive.
    """
    if not isinstance(timestamps, list) or not timestamps:
        return _err(
            "timestamps required: a list of seconds, e.g. the start times "
            "of the shots you want to see (shots[].start in the breakdown)"
        )
    try:
        times = sorted(float(t) for t in timestamps)
    except (TypeError, ValueError):
        return _err("timestamps must be numbers (seconds from video start)")
    if len(times) > FRAMES_HARD_CAP:
        return _err(
            f"{len(times)} timestamps requested — the cap is "
            f"{FRAMES_HARD_CAP} per call ({FRAMES_RECOMMENDED} recommended "
            "for token budget). Split into a second call."
        )
    if any(t < 0 for t in times):
        return _err("timestamps must be non-negative seconds")
    if not shutil.which("ffmpeg"):
        return _err(
            "ffmpeg not found on PATH — run `zing doctor` for the install "
            "command."
        )
    try:
        b = storage.load_breakdown(slug)
    except FileNotFoundError:
        return _err(
            f"no breakdown for slug '{slug}' — call list_breakdowns() to "
            "see what exists, or study_video() to create it"
        )
    except (ValueError, storage.SlugError) as e:
        return _err(str(e))
    media = storage.find_media(slug)
    if media is None:
        return _err(
            f"breakdown '{slug}' exists but its media file is gone "
            "(media.* not in the workspace) — re-run study_video to refetch "
            "before requesting frames"
        )
    duration = b.meta.duration

    frames: list[dict[str, Any]] = []
    for i, t in enumerate(times, start=1):
        label = f"Frame {i} @ t={t:.2f}s"
        if duration and t > duration:
            frames.append({
                "label": label,
                "jpeg": None,
                "error": f"t={t:.2f}s is past the video's end "
                f"(duration {duration:.2f}s)",
            })
            continue
        try:
            frames.append({
                "label": label,
                "jpeg": _extract_frame_jpeg(media, t),
                "error": "",
            })
        except Exception as e:  # noqa: BLE001 — per-frame honesty beats a dead call
            frames.append({
                "label": label,
                "jpeg": None,
                "error": f"frame extraction failed: {e}",
            })
    return _ok(slug=slug, frames=frames)


def h_push_to_uoink(slug: str) -> dict[str, Any]:
    from myzing import uoink_bridge

    bad = _check_slug(slug)  # the bridge validates too; reject here so the
    if bad:                  # tool's own envelope names the problem
        return bad
    return uoink_bridge.push_breakdown(slug)


def h_get_prompt(name: str = "study") -> dict[str, Any]:
    loaded = load_prompt(name)
    if loaded is None:
        have = available_prompts()
        where = str(prompts_dir())
        if have:
            return _err(
                f"no prompt named '{name}' — available: {', '.join(have)}"
            )
        return _err(
            f"no prompt pack found (looked in {where}) — this build shipped "
            "without prompts; update Zing or set "
            f"{PROMPTS_DIR_ENV} to the pack directory"
        )
    meta, text = loaded
    return _ok(
        name=name,
        version=str(meta.get("version", "unknown")),
        content=text,
    )


# ---------------------------------------------------------------------------
# Server assembly (SDK required only from here down)
# ---------------------------------------------------------------------------

def build_server():
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.prompts import Prompt

    mcp = FastMCP(
        "zing",
        instructions=(
            "Zing studies short videos: deterministic measurements (shots, "
            "word-timed transcript, caption OCR, audio) become a Breakdown "
            "your judgment turns into a style read. Typical flow: "
            "study_video(url) -> poll zing_status() -> get_breakdown(slug) "
            "-> judge it using the 'study' prompt (get_prompt) -> "
            "save_judgment(slug, judgment)."
        ),
    )

    mcp.tool(
        name="study_video",
        description=(
            "Start studying a video (URL or local file path). Returns a slug "
            "immediately and measures in the background (typically 1–5 "
            "minutes): shot boundaries, word-timed transcript, caption OCR, "
            "audio layout. Poll zing_status() for phase, then "
            "get_breakdown(slug)."
        ),
    )(h_study_video)
    mcp.tool(
        name="get_breakdown",
        description=(
            "Fetch a studied video's Breakdown JSON by slug. Every response "
            "carries a `state` field: running | done | failed | absent. The "
            "job status is checked FIRST: while a (re-)study runs you get "
            "ready=false with the current phase — never superseded "
            "measurements (`stale_breakdown_exists` flags that an older "
            "snapshot is on disk). If the latest re-study failed but an "
            "earlier study succeeded, the last successful breakdown is "
            "served with state='failed' plus `restudy_error`, so you decide "
            "whether to judge it. A `running` job whose runner process died "
            "is reported as failed with recovery instructions. "
            "detail='summary' returns meta + pacing + counts without the "
            "per-word/per-caption arrays (use it for long videos)."
        ),
    )(h_get_breakdown)
    mcp.tool(
        name="list_breakdowns",
        description=(
            "List all studied videos in the workspace: slug, platform, "
            "title, duration, measurement counts, judgment sections."
        ),
    )(h_list_breakdowns)
    mcp.tool(
        name="generate_thumbnails",
        description=(
            "For a studied video slug, extract 3-5 source-resolution "
            "thumbnail candidate frames and attach them with three distinct "
            "YouTube image-model prompts (emotion, object/result tease, "
            "story contrast). Deterministic selectors exclude burned-caption "
            "times and cut-adjacent frames, deduplicate near-matches, and "
            "ground every prompt promise in the first-30s transcript. "
            "Requires stored media and ffmpeg."
        ),
        structured_output=False,
    )(mcp_thumbnail_content)
    mcp.tool(
        name="save_judgment",
        description=(
            "Write your judgment of a breakdown back to Zing (hook type, "
            "structure beats, caption style, why it works — the shape is "
            "defined by get_prompt('study')). Each top-level section is "
            "replaced wholesale; pass model=<your model name> for "
            "provenance."
        ),
    )(h_save_judgment)
    mcp.tool(
        name="zing_status",
        description=(
            "Zing's health and state: tool availability (ffmpeg, yt-dlp, "
            "whisper, OCR), workspace stats, running/failed study jobs, "
            "available prompts. Cheap — call freely."
        ),
    )(h_zing_status)
    mcp.tool(
        name="push_to_uoink",
        description=(
            "Optional: push a studied video's breakdown.md into the user's "
            "uoink corpus as a note (only works when the uoink helper is "
            "running locally — zing_status shows it under environment). "
            "Zing is fully standalone without it."
        ),
    )(h_push_to_uoink)

    from mcp.server.fastmcp.utilities.types import Image

    def get_frames(slug: str, timestamps: list[float]) -> list:
        result = h_get_frames(slug, timestamps)
        if not result.get("ok"):
            return [json.dumps(result)]
        content: list = []
        for frame in result["frames"]:
            if frame["jpeg"] is not None:
                content.append(frame["label"])
                content.append(Image(data=frame["jpeg"], format="jpeg"))
            else:
                content.append(f"{frame['label']}: {frame['error']}")
        return content

    mcp.tool(
        name="get_frames",
        description=(
            "SEE the video: extract labeled still frames at the given "
            "timestamps (seconds) from a studied video's stored media. "
            f"Up to {FRAMES_HARD_CAP} per call ({FRAMES_RECOMMENDED} "
            "recommended). Sample at shot boundaries (shots[].start), "
            "hook window 0-3s first, and judge frames together with the "
            "transcript — frames alone under-perform. Frames are "
            f"{FRAME_MAX_EDGE}px longest-edge JPEGs extracted on demand; "
            "nothing is cached."
        ),
    )(get_frames)
    mcp.tool(
        name="get_prompt",
        description=(
            "Fetch a Zing prompt-pack file by name (e.g. 'study': how to "
            "judge a Breakdown and write it back). Use this if your client "
            "doesn't surface MCP prompts as commands."
        ),
    )(h_get_prompt)

    for prompt_name in available_prompts():
        def _make(nm: str):
            def prompt_fn() -> str:
                loaded = load_prompt(nm)
                return loaded[1] if loaded else f"prompt '{nm}' unavailable"
            return prompt_fn

        loaded = load_prompt(prompt_name)
        description = ""
        if loaded:
            description = str(loaded[0].get("description", ""))
        mcp.add_prompt(
            Prompt.from_function(
                _make(prompt_name), name=prompt_name, description=description
            )
        )
    return mcp


def _print_connect_config(target: str) -> int:
    """``zing serve-mcp --print-config [desktop|code]`` — the exact,
    copy-pasteable client config with this environment's real paths.
    Works without the SDK installed (it only prints), but says so."""
    python = sys.executable
    desktop = json.dumps(
        {
            "mcpServers": {
                "zing": {"command": python, "args": ["-m", "myzing.cli", "serve-mcp"]}
            }
        },
        indent=2,
    )
    code_cmd = f'claude mcp add zing -- "{python}" -m myzing.cli serve-mcp'
    if target in ("desktop", ""):
        print("# Claude Desktop — merge into claude_desktop_config.json")
        print("# (Windows: %APPDATA%\\Claude\\  macOS: ~/Library/Application Support/Claude/)")
        print(desktop)
    if target in ("code", ""):
        if target == "":
            print()
        print("# Claude Code — run this once:")
        print(code_cmd)
    try:
        import mcp  # noqa: F401
    except ImportError:
        print(
            '\n# NOTE: the mcp SDK is not installed in this Python yet — run'
            '\n#   python -m pip install "myzing[mcp]"'
            "\n# before connecting a client, or the server will exit at launch.",
        )
    return 0


def run(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv):
        print(
            "usage: zing serve-mcp [--print-config [desktop|code]]\n\n"
            + (__doc__ or "")
        )
        return 0
    if "--print-config" in argv:
        i = argv.index("--print-config")
        target = argv[i + 1] if i + 1 < len(argv) else ""
        if target not in ("", "desktop", "code"):
            print(f"unknown --print-config target '{target}' (use: desktop, code)")
            return 2
        return _print_connect_config(target)
    try:
        import mcp  # noqa: F401
    except ImportError:
        print(
            "zing serve-mcp needs the MCP SDK: "
            'python -m pip install "myzing[mcp]"',
            file=sys.stderr,
        )
        return 2
    server = build_server()
    server.run()  # stdio; blocks until the client disconnects
    return 0
