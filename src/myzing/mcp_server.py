"""``zing serve-mcp``: the MCP stdio server — how AIs touch Zing.

Five tools + prompt delivery, built on the official MCP Python SDK
(FastMCP), stdio transport. Design is bound by SPRINT-1-D1 §Critique
resolutions and the B#2 ruling (2026-07-18):

- ``study_video`` is a background job: cheap validation up front, then a
  worker thread; returns ``{ok, slug, status: "started"}`` in under a
  second. Claude Desktop hard-caps tool calls at ~60s, so a synchronous
  minutes-long study would silently fail there (R1-B evidence). Job state
  lives in ``status.json`` in the slug's directory — a crashed process
  leaves honest state on disk.
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
# Study job runner
# ---------------------------------------------------------------------------

def _study_api():
    """Lane A's engine seam, or None while it hasn't merged."""
    try:
        api = importlib.import_module("myzing.study.api")
        return api if hasattr(api, "study") else None
    except ImportError:
        return None


def _run_study(study_fn: Any, source: str, slug: str) -> None:
    """Worker-thread body: run the engine, persist, record honest state."""
    def set_phase(phase: str) -> None:
        storage.write_status(slug, phase=str(phase), updated_at=_now())

    kwargs: dict[str, Any] = {}
    try:
        params = inspect.signature(study_fn).parameters
        for name in ("phase_callback", "progress_callback", "on_phase"):
            if name in params:
                kwargs[name] = set_phase
                break
    except (TypeError, ValueError):
        pass

    try:
        breakdown = study_fn(source, **kwargs)
        json_path = storage.breakdown_dir(slug) / "breakdown.json"
        if breakdown is not None and not json_path.is_file():
            storage.save_breakdown(breakdown, slug=slug)
        storage.write_status(
            slug, state="done", finished_at=_now(), updated_at=_now(), error=""
        )
    except Exception as e:  # noqa: BLE001 — boundary: everything becomes honest disk state
        storage.write_status(
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
    if not is_url and not Path(source).expanduser().is_file():
        return _err(
            f"file not found: {source} — pass a video URL or an existing "
            "local file path"
        )
    api = _study_api()
    if api is None:
        return _err(
            "the study engine is not in this build yet (Sprint 1 in "
            "progress) — study_video will work here unchanged once it "
            "lands; zing_status().engine_available will flip to true"
        )

    slug = storage.slug_for(source)
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
        storage.write_status(
            slug,
            state="running",
            phase=STUDY_PHASES[0],
            source=source,
            started_at=_now(),
            updated_at=_now(),
            error="",
        )
        thread = threading.Thread(
            target=_run_study, args=(api.study, source, slug), daemon=True
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
    status = storage.read_status(slug)
    try:
        b = storage.load_breakdown(slug)
    except FileNotFoundError:
        if status and status.get("state") == "running":
            return _ok(
                slug=slug,
                ready=False,
                state="running",
                phase=status.get("phase", ""),
                started_at=status.get("started_at", ""),
                hint="still studying — poll again shortly",
            )
        if status and status.get("state") == "failed":
            return _err(
                f"study of '{slug}' failed: {status.get('error', 'unknown')} "
                "— fix the cause (zing doctor helps) and call study_video again"
            )
        return _err(
            f"no breakdown for slug '{slug}' — call list_breakdowns() to see "
            "what exists, or study_video() to create it"
        )
    data = b.to_dict()
    if detail == "summary":
        return _ok(slug=slug, ready=True, breakdown=_summarize_breakdown(data))
    return _ok(slug=slug, ready=True, breakdown=data)


def h_list_breakdowns() -> dict[str, Any]:
    entries = storage.list_breakdowns()
    return _ok(count=len(entries), breakdowns=entries)


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
        status = storage.read_status(slug) if slug else None
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
            "Fetch a studied video's Breakdown JSON by slug. "
            "detail='summary' returns meta + pacing + counts without the "
            "per-word/per-caption arrays (use it for long videos). While a "
            "study is running this reports the current phase instead."
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
