"""``zing setup``: taste onboarding (S4 Track 2, Lane B).

Two paths to a named taste (a StyleProfile):

- **Preset pack:** pick a curated pack (Lane A curates the reference
  sets per A-Q14); Zing studies its references and builds the profile.
- **Your own links:** paste reference URLs; same machinery, your taste.

Both are IDEMPOTENT and re-entrant: setup inspects what is already
studied, starts studies only for what's missing (the same background
job machinery study_video uses), and builds the profile once every
reference has a breakdown. Run it again after studies finish — it picks
up where it left off. Multiple named tastes are first-class: each setup
names a profile; nothing is singleton.

Pack manifest contract (proposed to Lane A in NOTES, honest-empty until
their packs land): ``presets/<pack-name>/pack.json``::

    {"name": "...", "genre": "<rubric key>", "platform": "...",
     "description": "...",
     "references": [{"id": "...", "url": "...", "why": "..."}]}

Search order: ``ZING_PRESETS_DIR`` env override, then the repo-root
``presets/`` directory (same pattern as the prompt pack).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from myzing import storage

PRESETS_DIR_ENV = "ZING_PRESETS_DIR"


def presets_dir() -> Path:
    override = os.environ.get(PRESETS_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    repo = Path(__file__).resolve().parents[2] / "presets"
    if repo.is_dir():
        return repo
    # Installed wheel (S5 fresh-host): packs ship as package data,
    # drift-tested against the repo copies.
    return Path(__file__).resolve().parent / "_data" / "presets"


def _pack_path(name: str) -> Path | None:
    """Both shipped shapes: flat ``presets/<name>.json`` (Lane A's A-Q14
    format, canonical) and ``presets/<name>/pack.json`` (the originally
    proposed dir form)."""
    root = presets_dir()
    flat = root / f"{name}.json"
    if flat.is_file():
        return flat
    nested = root / name / "pack.json"
    if nested.is_file():
        return nested
    return None


def load_pack(name: str) -> dict[str, Any] | None:
    """A pack manifest by name, or None. Raises ValueError on a manifest
    that exists but lies (missing fields) — a bad pack must be loud."""
    if not name or any(c in name for c in "/\\") or name.startswith("."):
        return None
    path = _pack_path(name)
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    refs = data.get("references")
    if not isinstance(refs, list) or not refs or not all(
        isinstance(r, dict) and r.get("url") for r in refs
    ):
        raise ValueError(
            f"preset pack '{name}' is malformed: references must be a "
            "non-empty list of {url, ...}"
        )
    data.setdefault("name", data.get("pack_id", name))
    return data


def list_packs() -> list[dict[str, Any]]:
    """Summaries of installed packs; honest empties for broken ones."""
    root = presets_dir()
    if not root.is_dir():
        return []
    names: list[str] = []
    for entry in sorted(root.iterdir()):
        if entry.is_file() and entry.suffix == ".json":
            names.append(entry.stem)
        elif entry.is_dir() and (entry / "pack.json").is_file():
            names.append(entry.name)
    packs: list[dict[str, Any]] = []
    for name in names:
        try:
            pack = load_pack(name)
        except (ValueError, OSError, json.JSONDecodeError) as e:
            packs.append({"name": name, "error": str(e)})
            continue
        if pack is None:
            continue
        packs.append({
            "name": pack["name"],
            "genre": pack.get("genre", ""),
            "platform": pack.get("platform", ""),
            "orientation": pack.get("orientation", ""),
            "description": pack.get("description", "")
            or f"{pack.get('genre', '?')} references, curated "
            f"{pack.get('curated_at', '?')}",
            "references": len(pack["references"]),
        })
    return packs


def plan_setup(
    name: str,
    links: list[str],
    genre: str = "",
    platform: str = "",
) -> dict[str, Any]:
    """The idempotent core: what state is each reference in, and is the
    profile buildable right now? Pure inspection — starts nothing."""
    storage.validate_profile_name(name)
    if not links:
        raise ValueError("at least one reference link is required")
    statuses: list[dict[str, Any]] = []
    for url in links:
        slug = storage.slug_for(url)
        has_breakdown = (storage.breakdown_dir(slug) / "breakdown.json").is_file()
        job = storage.read_status(slug) or {}
        state = (
            "studied" if has_breakdown
            else job.get("state", "unstudied")
        )
        statuses.append({"url": url, "slug": slug, "state": state})
    ready = all(s["state"] == "studied" for s in statuses)
    return {
        "profile": name,
        "genre": genre,
        "platform": platform,
        "references": statuses,
        "ready_to_build": ready,
        "unstudied": [s["url"] for s in statuses if s["state"] == "unstudied"],
        "in_progress": [s["slug"] for s in statuses if s["state"] == "running"],
        "failed": [s["slug"] for s in statuses if s["state"] == "failed"],
    }


def pack_manifest_path(name: str) -> Path | None:
    """Public manifest-path lookup (build_pack needs the file, not the dict)."""
    if not name or any(c in name for c in "/\\") or name.startswith("."):
        return None
    return _pack_path(name)


def finish_pack(name: str, *, study_missing: bool = False) -> dict[str, Any]:
    """Build a preset pack's profile through Lane A's build_pack so the
    manifest provenance (pack_id, manifest_sha, per-ref outcomes) is
    stamped (gate defect D-5). Default study_missing=False: the async
    MCP caller starts studies itself and this is the fast final step;
    the CLI passes True to study synchronously in-process (D-3: nothing
    daemonic to die)."""
    path = pack_manifest_path(name)
    if path is None:
        return {"ok": False, "error": f"no preset pack named '{name}'"}
    try:
        from myzing.profile.packs import PackError, build_pack
    except ImportError:
        return {
            "ok": False,
            "error": "the pack builder is not in this build — update Zing",
        }
    try:
        result = build_pack(path, study_missing=study_missing)
    except PackError as e:
        return {"ok": False, "error": f"pack build failed: {e}"}
    except Exception as e:  # noqa: BLE001 — boundary to errors-as-data
        return {"ok": False, "error": f"pack build failed: {type(e).__name__}: {e}"}
    return {
        "ok": True,
        "profile_name": result.profile.name,
        "sources": len(result.profile.source_slugs),
        "unjudged_sources": len(result.profile.unjudged_source_slugs),
        "studied": result.studied,
        "reused": result.reused,
        "ref_failures": [f"{rid}: {why}" for rid, why in result.failed],
        "warnings": result.warnings,
    }


def advance_setup(
    name: str,
    links: list[str],
    genre: str = "",
    platform: str = "",
    pack: str = "",
) -> dict[str, Any]:
    """One idempotent step of onboarding: start missing studies, RESTART
    failed ones (gate defect D-4), build the profile once everything is
    studied. The CLI and the MCP tool both drive this — call it again
    after studies finish. When ``pack`` is set the final build routes
    through build_pack for manifest provenance (D-5)."""
    from myzing import mcp_server

    plan = plan_setup(name, links, genre, platform)
    started: list[str] = []
    restarted: list[str] = []
    start_errors: list[str] = []
    for url in plan["unstudied"]:
        result = mcp_server.h_study_video(url)
        if result.get("ok"):
            started.append(result.get("slug", url))
        else:
            start_errors.append(f"{url}: {result.get('error')}")
    # D-4: a failed study is restartable, not a dead end — the reconcile
    # message says "call study_video again"; setup is the caller that must
    # actually do it.
    failed_urls = [
        s["url"] for s in plan["references"] if s["state"] == "failed"
    ]
    for url in failed_urls:
        result = mcp_server.h_study_video(url)
        if result.get("ok"):
            restarted.append(result.get("slug", url))
        else:
            start_errors.append(f"{url}: {result.get('error')}")
    plan = plan_setup(name, links, genre, platform)
    outcome: dict[str, Any] = {
        "plan": plan,
        "started": started,
        "restarted": restarted,
        "start_errors": start_errors,
        "built": False,
    }
    if plan["ready_to_build"]:
        if pack:
            build = finish_pack(pack)
        else:
            build = mcp_server.h_build_profile(
                name,
                [s["slug"] for s in plan["references"]],
                genre=genre,
                platform=platform,
            )
        outcome["build"] = build
        outcome["built"] = bool(build.get("ok"))
    return outcome


def wait_for_studies(
    name: str,
    links: list[str],
    genre: str = "",
    platform: str = "",
    poll_s: float = 1.0,
    progress=None,
) -> None:
    """Block until no reference study is running (gate defect D-3: the CLI
    spawns daemon workers that die with the process, so a one-shot CLI
    MUST outlive its own jobs). Uses the reconciling status read so a
    dead worker's 'running' is honestly rewritten instead of spinning
    this loop forever."""
    import time as _time

    from myzing import mcp_server

    while True:
        plan = plan_setup(name, links, genre, platform)
        running = []
        for s in plan["references"]:
            status = storage.read_status(s["slug"])
            if status and status.get("state") == "running":
                status = mcp_server._reconcile_running(s["slug"], status)
                if status.get("state") == "running":
                    running.append((s["slug"], status.get("phase", "")))
        if not running:
            return
        if progress:
            progress(running)
        _time.sleep(poll_s)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(argv: list[str]) -> int:
    """``zing setup --pack <name> | --links <url...>`` — non-interactive by
    design (the same flow an AI drives over MCP; no prompts to hang CI)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="zing setup", description="Onboard a named taste (StyleProfile)."
    )
    parser.add_argument("--pack", help="preset pack name (see --list)")
    parser.add_argument("--links", nargs="+", help="your own reference URLs")
    parser.add_argument("--name", help="profile name (default: the pack name)")
    parser.add_argument("--genre", default="", help="rubric genre key")
    parser.add_argument("--platform", default="", help="tiktok|youtube|instagram|x")
    parser.add_argument("--list", action="store_true", help="list preset packs")
    args = parser.parse_args(argv)

    if args.list or (not args.pack and not args.links):
        packs = list_packs()
        if not packs:
            print(
                "No preset packs installed yet (they ship with the curated "
                f"reference sets; looked in {presets_dir()}).\n"
                "You can onboard your own taste today:\n"
                "  zing setup --links <url> <url> ... --name my-taste"
            )
            return 0 if args.list else 2
        print("Preset packs:")
        for p in packs:
            if "error" in p:
                print(f"  {p['name']}: BROKEN — {p['error']}")
            else:
                print(
                    f"  {p['name']} ({p['genre']}, {p['references']} refs) — "
                    f"{p['description']}"
                )
        return 0

    genre, platform = args.genre, args.platform
    if args.pack:
        # D-3 + D-5 (pack path): build_pack studies SYNCHRONOUSLY in this
        # process (nothing daemonic dies with the CLI) and stamps the
        # manifest provenance. One command, cold start to built taste.
        try:
            if load_pack(args.pack) is None:
                names = ", ".join(
                    p["name"] for p in list_packs()
                ) or "(none installed)"
                print(
                    f"zing setup: no pack named '{args.pack}' — "
                    f"available: {names}"
                )
                return 1
        except ValueError as e:
            print(f"zing setup: {e}")
            return 1
        print(f"Building taste from pack '{args.pack}' (studies run now —")
        print("this can take a few minutes per un-studied reference)…")
        build = finish_pack(args.pack, study_missing=True)
        if not build.get("ok"):
            print(f"zing setup: {build.get('error')}")
            return 1
        for line in build.get("ref_failures", []):
            print(f"  reference failed (pack built without it): {line}")
        print(
            f"Taste '{build['profile_name']}' built from "
            f"{build['sources']} references "
            f"({build['unjudged_sources']} awaiting judgment; "
            f"{len(build['studied'])} freshly studied, "
            f"{len(build['reused'])} reused)."
        )
        return 0

    links = args.links
    if not args.name:
        print("zing setup: --name is required with --links")
        return 2
    name = args.name

    # D-3 (links path): the CLI must outlive its own background studies —
    # advance, wait for the jobs it started, advance again; a bounded
    # number of restart rounds so repeated failures end honestly.
    for attempt in range(4):
        try:
            outcome = advance_setup(name, links, genre, platform)
        except (ValueError, storage.SlugError) as e:
            print(f"zing setup: {e}")
            return 1
        for line in outcome["start_errors"]:
            print(f"  could not start study: {line}")
        plan = outcome["plan"]

        if outcome["built"]:
            build = outcome["build"]
            print(
                f"Taste '{name}' built from {build['sources']} references "
                f"({build['unjudged_sources']} awaiting judgment). "
                "Next: judge them with the study prompt, then re-run setup "
                "to fold judgments in on rebuild."
            )
            return 0
        if plan["ready_to_build"]:  # build attempted and failed
            print(
                f"zing setup: profile build failed: "
                f"{outcome['build'].get('error')}"
            )
            return 1
        if not (outcome["started"] or outcome["restarted"] or plan["in_progress"]):
            break  # nothing running, nothing startable — fall through to report
        if outcome["restarted"]:
            print(
                f"Retrying {len(outcome['restarted'])} failed studies "
                f"(round {attempt + 1})…"
            )

        def _progress(running: list) -> None:
            states = ", ".join(f"{slug}:{phase or '…'}" for slug, phase in running)
            print(f"  studying {states}", flush=True)

        wait_for_studies(name, links, genre, platform, progress=_progress)

    plan = plan_setup(name, links, genre, platform)
    print(f"Taste '{name}' could not be completed:")
    for s in plan["references"]:
        status = storage.read_status(s["slug"]) or {}
        detail = f" — {status.get('error', '')}" if s["state"] == "failed" else ""
        print(f"  [{s['state']:>9}] {s['slug']}{detail}")
    print("Fix the causes above (zing doctor helps) and re-run.")
    return 1
