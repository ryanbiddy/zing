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


def _job_is_live(
    registry: dict[str, threading.Thread], key: str, status: dict[str, Any] | None
) -> bool:
    """Caller holds _JOBS_LOCK. True only when a live worker AND on-disk
    'running' agree — the dispatch-race rule from the #87 fix (a finished
    worker is briefly alive between its final write and cleanup pop),
    shared by study and render jobs."""
    job = registry.get(key)
    return (
        job is not None
        and job.is_alive()
        and (status or {}).get("state") == "running"
    )


def _job_cleanup(registry: dict[str, threading.Thread], key: str) -> None:
    """Worker-side identity-guarded pop: a finishing old worker must never
    evict a newer registration under the same key (that would make the
    liveness reconciler falsely fail the live job as 'worker gone')."""
    with _JOBS_LOCK:
        if registry.get(key) is threading.current_thread():
            registry.pop(key, None)

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


def _missing_slug_err(slug: str) -> dict[str, Any]:
    """The one canonical unknown-slug message (was duplicated and drifting)."""
    return _err(
        f"no breakdown for slug '{slug}' — call list_breakdowns() to see "
        "what exists, or study_video() to create it"
    )


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


def _run_study(
    study_fn: Any,
    source: str,
    slug: str,
    root: Path,
    kept_media: str | None = None,
    handoff: dict[str, Any] | None = None,
) -> None:
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
    if kept_media is not None:
        # B-S6: the bridge hands the engine a kept-media path (A-S6 seam);
        # support was verified at dispatch, and the engine's own fallback
        # honesty (named warnings, refetch) covers everything past here.
        kwargs["kept_media"] = kept_media
    if handoff is not None:
        # Contract v1 §6.1: expected sha256/byte_length/source_ref travel
        # to the engine, which verifies integrity BEFORE analysis and
        # persists path-free source_handoff provenance (A-S6 conformance).
        kwargs["handoff"] = handoff
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
            _job_cleanup(_JOBS, slug)


def h_study_video(
    url_or_path: str, kept_media: str | None = None
) -> dict[str, Any]:
    if not isinstance(url_or_path, str) or not url_or_path.strip():
        return _err("url_or_path required: a video URL or a local file path")
    source = url_or_path.strip()
    # B-S6 seam: a locally kept copy of the URL source (uoink keep_media
    # sidecar hands us a path; corpus-id resolution arrives with contract
    # ratification). Existence is NOT pre-checked — the engine's contract
    # is honest fallback to fetch with the reason named in warnings.
    kept: str | None = None
    if kept_media is not None:
        if not isinstance(kept_media, str) or not kept_media.strip():
            return _err(
                "kept_media, when given, must be a file path (the locally "
                "kept copy of this URL's media)"
            )
        kept = str(Path(kept_media.strip()).expanduser())

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
    if kept is not None and not _engine_supports(api, "kept_media"):
        return _err(
            "this build's study engine has no kept-media support — "
            "update myzing, or call study_video without kept_media"
        )
    return _dispatch_study(api, source, kept)


def _engine_supports(api: Any, param: str) -> bool:
    try:
        return param in inspect.signature(api.study).parameters
    except (TypeError, ValueError):
        return True  # can't introspect — dispatch; the worker records
        #              any TypeError as honest failed state


def _dispatch_study(
    api: Any,
    source: str,
    kept: str | None,
    handoff: dict[str, Any] | None = None,
    hint_extra: str = "",
    **echo: Any,
) -> dict[str, Any]:
    """Shared job dispatch for study_video and study_uoink_item: status
    stamped under the jobs lock, worker pinned to the captured workspace,
    honest already_studying answer for live jobs."""
    slug = storage.slug_for(source)
    # F-15: capture the workspace NOW and pin the whole job to it — the
    # worker thread must not re-resolve env that may change under it.
    root = storage.workspace_root()
    with _JOBS_LOCK:
        status = storage.read_status(slug)
        if _job_is_live(_JOBS, slug, status):
            return _ok(
                slug=slug,
                status="already_studying",
                phase=(status or {}).get("phase", ""),
                hint="poll zing_status() or get_breakdown(slug)",
            )
        _write_status(
            slug,
            state="running",
            phase=STUDY_PHASES[0],
            source=source,
            kept_media=kept or "",
            pid=os.getpid(),  # F-03: liveness marker readers verify
            heartbeat_at=_now(),
            started_at=_now(),
            updated_at=_now(),
            error="",
        )
        thread = threading.Thread(
            target=_run_study,
            args=(api.study, source, slug, root, kept, handoff),
            daemon=True,
        )
        _JOBS[slug] = thread
        thread.start()
    extra: dict[str, Any] = dict(echo)
    if kept:
        extra["kept_media"] = kept
        if not hint_extra:
            hint_extra = (
                " Using the kept local copy — zero network fetch when it "
                "checks out; any fallback to fetching is named in the "
                "breakdown's warnings."
            )
    return _ok(
        slug=slug,
        status="started",
        hint=(
            "studying in the background (typically 1–5 minutes). Poll "
            "zing_status() for phase, then get_breakdown(slug) for the result."
            + hint_extra
        ),
        **extra,
    )


def h_import_shot_list(path: str, slug: str) -> dict[str, Any]:
    """INTEGRATION-CONTRACT v1 §6.2: explicit user-chosen file import.
    The returned envelope IS the contract receipt — path-free, stable
    error codes, idempotent per (document hash, target)."""
    if not isinstance(path, str) or not path.strip():
        return _err("path required: the writer shot-list file you exported")
    if not isinstance(slug, str) or not slug.strip():
        return _err("slug required: the studied breakdown to attach it to")
    from myzing import shot_list

    return shot_list.import_shot_list(path.strip(), slug.strip())


def h_study_uoink_item(item_ref: str) -> dict[str, Any]:
    """INTEGRATION-CONTRACT v1 §9: study a uoink corpus item through the
    kept-media resolver. Accepts ONE uoink reference — never a peer
    path; paths only travel inside the token-gated handoff."""
    if not isinstance(item_ref, str) or not item_ref.strip():
        return _err(
            "item_ref required: a uoink item reference like "
            "'uoink://item/short-123'"
        )
    if not shutil.which("ffmpeg"):
        return _err(
            "ffmpeg not found on PATH — Zing cannot measure anything without "
            "it. Run `zing doctor` for the install command."
        )
    api = _study_api()
    if api is None:
        return _err(
            "the study engine is not in this build yet — "
            "zing_status().engine_available will flip to true when it lands"
        )
    if not (_engine_supports(api, "kept_media") and _engine_supports(api, "handoff")):
        return _err(
            "this build's study engine predates the kept-media handoff "
            "contract — update myzing"
        )

    from myzing import uoink_bridge

    resolved = uoink_bridge.resolve_kept_media(item_ref.strip())
    if not resolved.get("ok"):
        return _err(str(resolved.get("error", "kept-media resolution failed")))
    data = resolved["data"]
    state = data["state"]
    source_url = data.get("source_url")
    media = data.get("media")
    if not source_url:
        # Identity stays URL-derived (stable-IDs rule) and refetch is only
        # allowed from the handoff's source_url — without one there is
        # nothing honest to study when the kept file is absent, and no
        # slug for it when present.
        return _err(
            f"uoink has no source_url for {item_ref} (state={state}) — "
            "zing derives a study's identity from the source URL. If you "
            "have the file, study it directly as a local path instead."
        )
    handoff = {
        "source_ref": data["item_ref"],
        "state": state,
        "sha256": (media or {}).get("sha256"),
        "byte_length": (media or {}).get("byte_length"),
    }
    kept = str(media["path"]) if state == "available" else None
    hint_extra = (
        " Studying from uoink's kept file — zero network fetch when "
        "integrity checks out."
        if kept
        else (
            f" uoink kept no usable file (state={state}) — fetching from the "
            "source URL; provenance will record the refetch and its reason."
        )
    )
    return _dispatch_study(
        api,
        str(source_url),
        kept,
        handoff=handoff,
        hint_extra=hint_extra,
        item_ref=data["item_ref"],
        kept_state=state,
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
        return {**_missing_slug_err(slug), "state": "absent"}
    data = b.to_dict()
    if detail == "summary":
        data = _summarize_breakdown(data)
    # Paths inside a Breakdown (meta.media_path, shots[].keyframe) are
    # relative to the breakdown's own directory (portable on disk) — but an
    # MCP client only sees this JSON, so serve the base dir alongside or
    # those paths are dead ends for filesystem-capable clients.
    b_dir = str(storage.breakdown_dir(slug))
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
            dir=b_dir,
            breakdown=data,
            hint=(
                "the most recent re-study FAILED — this breakdown is the "
                "last successful study's measurement. Fix the cause (zing "
                "doctor helps) and call study_video again, or judge this "
                "data knowingly."
            ),
        )
    return _ok(slug=slug, ready=True, state="done", dir=b_dir, breakdown=data)


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
    receipt: dict[str, Any] = {
        "slug": slug,
        "section_written": section,
        "sections_now": sorted(updated.judgment),
        "prompt_version": prompt_version,
        "path": str(storage.breakdown_dir(slug) / "breakdown.json"),
    }
    if section == "direct":
        # S3: a direction judgment renders to the file a creator reads.
        # The judgment is already saved — a render failure must not
        # pretend otherwise, so it degrades to an honest note.
        from myzing import direction

        try:
            md = direction.render_direction(updated.judgment["direct"], slug)
            md_path = storage.breakdown_dir(slug) / "direction.md"
            md_path.write_text(md, encoding="utf-8")
            receipt["direction_md"] = str(md_path)
        except Exception as e:  # noqa: BLE001 — boundary
            receipt["direction_md_error"] = (
                f"judgment saved, but direction.md failed to render: {e}"
            )
    return _ok(**receipt)


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
# StyleProfile tools (S2)
# ---------------------------------------------------------------------------

def _profile_api():
    """Lane A's profile-builder seam, or None while it hasn't merged."""
    try:
        api = importlib.import_module("myzing.profile.api")
        return api if hasattr(api, "build_profile") else None
    except ImportError:
        return None


def h_build_profile(
    name: str,
    slugs: list[str],
    genre: str = "",
    platform: str = "",
) -> dict[str, Any]:
    try:
        storage.validate_profile_name(name)
    except storage.SlugError as e:
        return _err(f"invalid profile name: {e}")
    if not isinstance(slugs, list) or not slugs:
        return _err(
            "slugs required: the studied videos to aggregate — see "
            "list_breakdowns()"
        )
    for slug in slugs:
        bad = _check_slug(slug)
        if bad:
            return bad
    missing = [
        s for s in slugs
        if not (storage.breakdown_dir(s) / "breakdown.json").is_file()
    ]
    if missing:
        return _err(
            f"no breakdown for: {', '.join(missing)} — study these first "
            "(study_video), or drop them from the list"
        )
    api = _profile_api()
    if api is None:
        return _err(
            "the profile builder is not in this build yet (Sprint 2 in "
            "progress) — build_profile will work here unchanged once it "
            "lands"
        )

    kwargs: dict[str, Any] = {}
    try:
        params = inspect.signature(api.build_profile).parameters
        if "genre" in params:
            kwargs["genre"] = genre
        if "platform" in params:
            kwargs["platform"] = platform
    except (TypeError, ValueError):
        pass
    try:
        profile = api.build_profile(name, slugs, **kwargs)
    except (ValueError, FileNotFoundError, storage.SlugError) as e:
        return _err(f"profile build failed: {e}")
    if genre and not profile.genre:
        profile.genre = genre
    if platform and not profile.platform:
        profile.platform = platform
    if not (storage.profile_dir(name) / "profile.json").is_file():
        storage.save_profile(profile)
    return _ok(
        name=name,
        sources=len(profile.source_slugs),
        unjudged_sources=len(profile.unjudged_source_slugs),
        warnings=profile.warnings,
        path=str(storage.profile_dir(name) / "profile.json"),
        hint="get_profile(name) for the full aggregate",
    )


def h_get_profile(name: str) -> dict[str, Any]:
    try:
        storage.validate_profile_name(name)
    except storage.SlugError as e:
        return _err(f"invalid profile name: {e}")
    try:
        p = storage.load_profile(name)
    except FileNotFoundError:
        return _err(
            f"no profile named '{name}' — call list_profiles() to see what "
            "exists, or build_profile(name, slugs) to create it"
        )
    except ValueError as e:
        return _err(str(e))
    return _ok(
        name=name,
        dir=str(storage.profile_dir(name)),
        profile=p.to_dict(),
    )


def h_list_profiles() -> dict[str, Any]:
    entries = storage.list_profiles()
    return _ok(count=len(entries), profiles=entries)


# ---------------------------------------------------------------------------
# Taste onboarding tools (S4 Track 2)
# ---------------------------------------------------------------------------

def h_list_presets() -> dict[str, Any]:
    from myzing import setup_flow

    packs = setup_flow.list_packs()
    if not packs:
        return _ok(
            count=0,
            presets=[],
            hint=(
                "no preset packs installed yet — onboard a personal taste "
                "with setup_taste(name, links=[...]) today"
            ),
        )
    return _ok(count=len(packs), presets=packs)


def h_setup_taste(
    name: str,
    links: list[str] | None = None,
    pack: str = "",
    genre: str = "",
    platform: str = "",
) -> dict[str, Any]:
    from myzing import setup_flow

    if pack:
        try:
            manifest = setup_flow.load_pack(pack)
        except ValueError as e:
            return _err(str(e))
        if manifest is None:
            names = ", ".join(
                p["name"] for p in setup_flow.list_packs()
            ) or "(none installed)"
            return _err(f"no preset pack named '{pack}' — available: {names}")
        links = [r["url"] for r in manifest["references"]]
        genre = genre or manifest.get("genre", "")
        platform = platform or manifest.get("platform", "")
        # D-5: pack profiles are named by Lane A's build_pack convention;
        # planning must track the name that will actually be written.
        name = f"pack-{manifest.get('pack_id', manifest['name'])}"
    if not links:
        return _err(
            "provide links=[...] (your reference URLs) or pack=<preset name> "
            "— see list_presets()"
        )
    try:
        outcome = setup_flow.advance_setup(
            name, links, genre, platform, pack=pack
        )
    except (ValueError, storage.SlugError) as e:
        return _err(str(e))
    plan = outcome["plan"]
    if outcome["built"]:
        return _ok(
            taste=name,
            state="built",
            build=outcome["build"],
            hint=(
                "judge the references with the study prompt, then call "
                "setup_taste again — rebuilds fold judgments in"
            ),
        )
    if plan["ready_to_build"]:
        return _err(
            f"profile build failed: {outcome['build'].get('error', '?')}"
        )
    return _ok(
        taste=name,
        state="studying",
        references=plan["references"],
        started=outcome["started"],
        start_errors=outcome["start_errors"],
        failed=plan["failed"],
        hint=(
            "studies run in the background — call setup_taste again with the "
            "same arguments once zing_status() shows them done (idempotent)"
        ),
    )


# ---------------------------------------------------------------------------
# Render / export tools (S4 Track 1, Lane B surface over Lane C's engine)
# ---------------------------------------------------------------------------

_RENDER_JOBS: dict[str, threading.Thread] = {}


def _load_edl(edl_path: str):
    """(edl, base_dir, err) — parse cheaply before any job spawns."""
    from myzing.schemas import EDL

    p = Path(edl_path).expanduser()
    if not p.is_file():
        return None, None, _err(
            f"EDL file not found: {edl_path} — pass a path to an edl.json"
        )
    try:
        edl = EDL.from_json(p.read_text(encoding="utf-8"))
    except (ValueError, KeyError, TypeError) as e:
        return None, None, _err(
            f"could not parse EDL {p.name}: {e} — the EDL contract is in "
            "schemas.py (clips/captions/audio)"
        )
    return edl, p.resolve().parent, None


def _render_id_for(edl_path: str) -> str:
    import hashlib

    p = Path(edl_path).expanduser().resolve()
    stem = re.sub(r"[^a-z0-9]+", "-", p.stem.lower()).strip("-") or "edl"
    digest = hashlib.sha256(str(p).encode()).hexdigest()[:8]
    return f"{stem}-{digest}"


def _run_render(edl, base_dir: Path, out_path: Path, render_id: str, root: Path) -> None:
    from myzing.render import pipeline

    with storage.use_workspace(root):
        d = storage.render_dir(render_id)
        try:
            result = pipeline.render_edl(edl, out_path, base_dir=base_dir)
            storage.write_status_at(
                d,
                state="done",
                output=str(result.output_path if hasattr(result, "output_path") else out_path),
                finished_at=_now(),
                updated_at=_now(),
                error="",
            )
        except Exception as e:  # noqa: BLE001 — boundary: honest disk state
            storage.write_status_at(
                d,
                state="failed",
                error=f"{type(e).__name__}: {e}",
                finished_at=_now(),
                updated_at=_now(),
            )
        finally:
            _job_cleanup(_RENDER_JOBS, render_id)


def h_render_edl(edl_path: str, output_path: str = "") -> dict[str, Any]:
    if not shutil.which("ffmpeg"):
        return _err(
            "ffmpeg not found on PATH — run `zing doctor` for the install "
            "command."
        )
    edl, base_dir, bad = _load_edl(edl_path)
    if bad:
        return bad
    render_id = _render_id_for(edl_path)
    root = storage.workspace_root()
    d = storage.render_dir(render_id)
    out = (
        Path(output_path).expanduser().resolve()
        if output_path
        else d / "output.mp4"
    )
    with _JOBS_LOCK:
        if _job_is_live(_RENDER_JOBS, render_id, storage.read_status_at(d)):
            return _ok(
                render_id=render_id,
                status="already_rendering",
                hint="poll get_render(render_id)",
            )
        storage.write_status_at(
            d,
            state="running",
            edl=str(Path(edl_path).expanduser().resolve()),
            output=str(out),
            pid=os.getpid(),
            started_at=_now(),
            updated_at=_now(),
            error="",
        )
        thread = threading.Thread(
            target=_run_render,
            args=(edl, base_dir, out, render_id, root),
            daemon=True,
        )
        _RENDER_JOBS[render_id] = thread
        thread.start()
    return _ok(
        render_id=render_id,
        status="started",
        output=str(out),
        hint=(
            "rendering in the background (seconds to a few minutes). Poll "
            "get_render(render_id)."
        ),
    )


def h_get_render(render_id: str) -> dict[str, Any]:
    try:
        d = storage.render_dir(render_id)
    except storage.SlugError as e:
        return _err(f"invalid render id: {e}")
    status = storage.read_status_at(d)
    if status is None:
        return _err(
            f"no render named '{render_id}' — render_edl(edl_path) starts one"
        )
    if status.get("state") == "running":
        with _JOBS_LOCK:
            job = _RENDER_JOBS.get(render_id)
            if (job is None or not job.is_alive()) and status.get(
                "pid"
            ) == os.getpid():
                # crash honesty, same rule as studies: a running state
                # without its worker is rewritten, not believed
                error = (
                    "render interrupted — status said 'running' but its "
                    "worker is gone; call render_edl again"
                )
                storage.write_status_at(
                    d, state="failed", error=error, updated_at=_now()
                )
                return _ok(render_id=render_id, state="failed", error=error)
    return _ok(render_id=render_id, **{
        k: v for k, v in status.items() if k != "pid"
    })


def h_export_otio(edl_path: str, output_path: str = "") -> dict[str, Any]:
    edl, base_dir, bad = _load_edl(edl_path)
    if bad:
        return bad
    try:
        from myzing.render.otio_export import OTIOExportError, export_otio
    except ImportError:
        return _err(
            "OTIO export needs the render extras: "
            'python -m pip install "myzing[render]"'
        )
    src = Path(edl_path).expanduser().resolve()
    out = (
        Path(output_path).expanduser().resolve()
        if output_path
        else src.with_suffix(".otio")
    )
    try:
        result = export_otio(edl, out, base_dir=base_dir)
    except OTIOExportError as e:
        return _err(f"OTIO export failed: {e}")
    return _ok(
        output=str(out),
        clips=len(edl.clips),
        captions=len(edl.captions),
        audio_tracks=len(edl.audio),
        hint="open the .otio in an NLE (Resolve/Premiere via adapters)",
        detail=str(result),
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
        "-vf",
        f"scale='min({FRAME_MAX_EDGE},iw)':-2:"
        "in_range=auto:out_range=full",
        "-color_range", "pc",
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
    bad = _check_slug(slug)
    if bad:
        return bad
    try:
        b = storage.load_breakdown(slug)
    except FileNotFoundError:
        return _missing_slug_err(slug)
    except ValueError as e:  # corrupt breakdown.json stays errors-as-data
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
            "get_breakdown(slug). Optional kept_media: path to a locally "
            "kept copy of the URL's media (e.g. a uoink keep_media file) — "
            "studies from it with zero network fetch when it checks out; "
            "falls back to fetching with the reason named in warnings."
        ),
    )(h_study_video)
    mcp.tool(
        name="study_uoink_item",
        description=(
            "Study a uoink corpus item by its stable reference "
            "(uoink://item/<id>). Resolves the item's kept media through "
            "uoink's token-gated handoff endpoint (INTEGRATION-CONTRACT v1): "
            "a usable kept file is studied with zero network fetch and "
            "integrity-verified provenance; otherwise zing refetches from "
            "the item's source URL and the provenance names why. Needs "
            "UOINK_URL/UOINK_TOKEN configured; references only — this tool "
            "never accepts a file path."
        ),
    )(h_study_uoink_item)
    mcp.tool(
        name="import_shot_list",
        description=(
            "Import a Writer shot-list export (the user-chosen .md file) "
            "against a studied breakdown. Validates the writer.shot-list v1 "
            "format exactly, stores a content-addressed copy, and returns "
            "the path-free zing.shot-list.import receipt (document sha256 + "
            "writer://script ref + zing://breakdown target). Re-importing "
            "the same file for the same slug is idempotent. The imported "
            "plan is editorial context — zing's measured direction stays "
            "the authority for keeper spans."
        ),
    )(h_import_shot_list)
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

    mcp.tool(
        name="list_presets",
        description=(
            "List installed taste preset packs (curated reference sets with "
            "genre and why-picked notes). Empty is honest: personal tastes "
            "via setup_taste(links=...) work without any packs."
        ),
    )(h_list_presets)
    mcp.tool(
        name="setup_taste",
        description=(
            "Onboard a named taste: from a preset pack OR your own "
            "reference links. Idempotent — starts missing studies in the "
            "background, builds the StyleProfile when all references are "
            "studied; call again with the same arguments to advance. "
            "Multiple named tastes are first-class."
        ),
    )(h_setup_taste)
    mcp.tool(
        name="render_edl",
        description=(
            "Render an EDL json to a video file with ffmpeg (cuts, "
            "word-timed captions, audio mix). Validates cheaply and returns "
            "a render_id immediately; rendering runs in the background "
            "(seconds to a few minutes) — poll get_render(render_id). "
            "Renders without voiceover when no TTS is available (stated)."
        ),
    )(h_render_edl)
    mcp.tool(
        name="get_render",
        description=(
            "A render job's honest state: running / done (with the output "
            "path) / failed (with the error and next step)."
        ),
    )(h_get_render)
    mcp.tool(
        name="export_otio",
        description=(
            "Export an EDL json as an OpenTimelineIO (.otio) timeline that "
            "opens in real NLEs. Fast and synchronous."
        ),
    )(h_export_otio)
    mcp.tool(
        name="build_profile",
        description=(
            "Aggregate N studied+judged reference videos into a "
            "StyleProfile: robust stats (median/p25/p75) of pacing, hook "
            "timing, captions, audio, plus collected judgments. Honest "
            "about coverage (n per stat, unjudged sources named). Fast. "
            "genre = a docs/taste rubric key (e.g. 'talking-head')."
        ),
    )(h_build_profile)
    mcp.tool(
        name="get_profile",
        description=(
            "Fetch a StyleProfile by name: the measured aggregates and "
            "collected judgments to compare new videos against (see the "
            "'compare' prompt)."
        ),
    )(h_get_profile)
    mcp.tool(
        name="list_profiles",
        description=(
            "List stored StyleProfiles: name, genre, platform, source "
            "counts, unjudged-source count, warnings."
        ),
    )(h_list_profiles)

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
