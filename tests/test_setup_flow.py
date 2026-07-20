"""zing setup / setup_taste (S4-B Track 2): packs, idempotent onboarding."""

from __future__ import annotations

import json
import sys
import time
import types

import pytest

from myzing import mcp_server, setup_flow, storage
from myzing.schemas import Breakdown, StatSummary, StyleProfile, VideoMeta

LINKS = [
    "https://www.tiktok.com/@a/video/111",
    "https://www.tiktok.com/@a/video/222",
]
SLUGS = ["tiktok-111", "tiktok-222"]


@pytest.fixture
def pack_dir(tmp_path, monkeypatch):
    d = tmp_path / "presets" / "ai-tech-talking-head"
    d.mkdir(parents=True)
    (d / "pack.json").write_text(json.dumps({
        "pack_id": "ai-tech-talking-head",
        "curated_at": "2026-07-19",
        "genre": "talking-head",
        "platform": "tiktok",
        "orientation": "vertical",
        "references": [
            {"id": "r1", "url": LINKS[0], "why": "hook craft (G-TH-1)",
             "verified_at": "2026-07-19"},
            {"id": "r2", "url": LINKS[1], "why": "caption style (G-TH-5)",
             "verified_at": "2026-07-19"},
        ],
    }), encoding="utf-8")
    monkeypatch.setenv(setup_flow.PRESETS_DIR_ENV, str(tmp_path / "presets"))
    return d


@pytest.fixture
def engines(monkeypatch):
    """Fast fake study + profile builder so onboarding runs end to end."""
    study_api = types.ModuleType("myzing.study.api")

    def study(source, **kw):
        return Breakdown(
            meta=VideoMeta(source_url=source, platform="tiktok", duration=30.0)
        )

    study_api.study = study
    monkeypatch.setitem(sys.modules, "myzing.study.api", study_api)

    profile_api = types.ModuleType("myzing.profile.api")

    def build_profile(name, slugs, workspace=None, genre="", platform=""):
        return StyleProfile(
            name=name, source_slugs=list(slugs), genre=genre, platform=platform,
            duration=StatSummary(median=30.0, n=len(slugs)),
            unjudged_source_slugs=list(slugs),
        )

    profile_api.build_profile = build_profile
    monkeypatch.setitem(sys.modules, "myzing.profile.api", profile_api)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")


def wait_studies(slugs, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(
            (storage.breakdown_dir(s) / "breakdown.json").is_file() for s in slugs
        ):
            return
        time.sleep(0.01)
    raise AssertionError("studies never finished")


# -- packs -------------------------------------------------------------------

def test_real_shipped_packs_load(monkeypatch):
    """Integration truth: the five packs Lane A shipped (flat A-Q14 format)
    must load through this surface — the seam that broke silently once."""
    monkeypatch.delenv(setup_flow.PRESETS_DIR_ENV, raising=False)
    packs = setup_flow.list_packs()
    names = {p["name"] for p in packs}
    assert "ai-tech-talking-head" in names and len(packs) >= 5
    assert all("error" not in p for p in packs), packs
    pack = setup_flow.load_pack("ai-tech-talking-head")
    assert pack["genre"] == "talking-head"
    assert len(pack["references"]) >= 5
    assert all(r["url"].startswith("http") for r in pack["references"])


def test_flat_pack_format(tmp_path, monkeypatch):
    """Lane A's flat presets/<id>.json shape (pack_id, no description)."""
    root = tmp_path / "presets"
    root.mkdir()
    (root / "flatpack.json").write_text(json.dumps({
        "pack_id": "flatpack",
        "curated_at": "2026-07-19",
        "genre": "vlog",
        "platform": "tiktok",
        "references": [{"id": "r1", "url": "https://x.test/1", "why": "w"}],
    }), encoding="utf-8")
    monkeypatch.setenv(setup_flow.PRESETS_DIR_ENV, str(root))
    packs = setup_flow.list_packs()
    assert packs[0]["name"] == "flatpack"
    assert "curated 2026-07-19" in packs[0]["description"]
    assert setup_flow.load_pack("flatpack")["name"] == "flatpack"

def test_no_packs_is_honest(tmp_path, monkeypatch):
    monkeypatch.setenv(setup_flow.PRESETS_DIR_ENV, str(tmp_path / "void"))
    assert setup_flow.list_packs() == []
    result = mcp_server.h_list_presets()
    assert result["ok"] is True and result["count"] == 0
    assert "setup_taste" in result["hint"]  # personal path offered


def test_pack_listing(pack_dir):
    packs = setup_flow.list_packs()
    assert len(packs) == 1
    assert packs[0]["name"] == "ai-tech-talking-head"
    assert packs[0]["references"] == 2


def test_malformed_pack_is_loud(pack_dir):
    (pack_dir / "pack.json").write_text('{"name": "x", "references": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        setup_flow.load_pack("ai-tech-talking-head")
    listing = setup_flow.list_packs()
    assert "error" in listing[0]


# -- onboarding (idempotent) -------------------------------------------------

def test_setup_taste_two_phase(zing_workspace, engines):
    first = mcp_server.h_setup_taste("my-taste", links=LINKS, genre="talking-head")
    assert first["ok"] is True
    assert first["state"] in ("studying", "built")  # fake engine may be instant
    wait_studies(SLUGS)
    second = mcp_server.h_setup_taste("my-taste", links=LINKS, genre="talking-head")
    assert second["ok"] is True and second["state"] == "built"
    profile = storage.load_profile("my-taste")
    assert profile.source_slugs == SLUGS
    assert profile.genre == "talking-head"
    third = mcp_server.h_setup_taste("my-taste", links=LINKS, genre="talking-head")
    assert third["state"] == "built"  # idempotent: rebuild, not error


def test_setup_taste_from_pack(zing_workspace, engines, pack_dir):
    result = mcp_server.h_setup_taste("techie", pack="ai-tech-talking-head")
    assert result["ok"] is True
    wait_studies(SLUGS)
    final = mcp_server.h_setup_taste("techie", pack="ai-tech-talking-head")
    assert final["state"] == "built"
    # D-5: pack profiles carry Lane A's pack-<id> naming convention
    assert final["build"]["profile_name"] == "pack-ai-tech-talking-head"
    assert storage.load_profile("pack-ai-tech-talking-head").genre == "talking-head"


def test_setup_taste_unknown_pack_lists(zing_workspace, pack_dir):
    result = mcp_server.h_setup_taste("x", pack="nope")
    assert result["ok"] is False
    assert "ai-tech-talking-head" in result["error"]


def test_setup_taste_requires_links_or_pack(zing_workspace):
    result = mcp_server.h_setup_taste("x")
    assert result["ok"] is False and "list_presets" in result["error"]


def test_setup_taste_bad_name(zing_workspace):
    result = mcp_server.h_setup_taste("../escape", links=LINKS)
    assert result["ok"] is False


# -- CLI ---------------------------------------------------------------------

def test_cli_list_empty_offers_personal_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(setup_flow.PRESETS_DIR_ENV, str(tmp_path / "void"))
    assert setup_flow.run(["--list"]) == 0
    out = capsys.readouterr().out
    assert "--links" in out and "my-taste" in out


def test_cli_links_flow(zing_workspace, engines, capsys):
    code = setup_flow.run(["--links", *LINKS, "--name", "cli-taste"])
    assert code in (0, 3)
    wait_studies(SLUGS)
    code = setup_flow.run(["--links", *LINKS, "--name", "cli-taste"])
    assert code == 0
    assert "built from 2 references" in capsys.readouterr().out


def test_cli_links_without_name(capsys):
    assert setup_flow.run(["--links", LINKS[0]]) == 2
    assert "--name" in capsys.readouterr().out


# -- SG-2: CLI pack path + failure branches ----------------------------------

def test_cli_pack_flow_defaults_name_and_genre(
    zing_workspace, engines, pack_dir, capsys
):
    code = setup_flow.run(["--pack", "ai-tech-talking-head"])
    assert code == 0  # D-3: one-shot — build_pack studies synchronously
    assert "built from 2 references" in capsys.readouterr().out
    profile = storage.load_profile("pack-ai-tech-talking-head")  # D-5 naming
    assert profile.genre == "talking-head"                       # from pack


def test_cli_unknown_pack_lists_available(pack_dir, capsys):
    assert setup_flow.run(["--pack", "nope"]) == 1
    out = capsys.readouterr().out
    assert "ai-tech-talking-head" in out


def test_cli_malformed_pack_is_loud(pack_dir, capsys):
    (pack_dir / "pack.json").write_text(
        '{"name": "x", "references": []}', encoding="utf-8"
    )
    assert setup_flow.run(["--pack", "ai-tech-talking-head"]) == 1
    assert "malformed" in capsys.readouterr().out


def test_cli_build_failure_reported(zing_workspace, engines, monkeypatch, capsys):
    def broken_build(name, slugs, **kw):
        return {"ok": False, "error": "aggregation exploded"}

    monkeypatch.setattr(mcp_server, "h_build_profile", broken_build)
    setup_flow.run(["--links", *LINKS, "--name", "doomed"])
    wait_studies(SLUGS)
    assert setup_flow.run(["--links", *LINKS, "--name", "doomed"]) == 1
    assert "aggregation exploded" in capsys.readouterr().out


def test_cli_bad_profile_name(zing_workspace, capsys):
    assert setup_flow.run(["--links", LINKS[0], "--name", "../escape"]) == 1
    assert "profile name" in capsys.readouterr().out


def test_plan_setup_requires_links(zing_workspace):
    with pytest.raises(ValueError, match="at least one reference"):
        setup_flow.plan_setup("x", [])


def test_load_pack_rejects_path_shaped_names(pack_dir):
    assert setup_flow.load_pack("../escape") is None
    assert setup_flow.load_pack(".hidden") is None
    assert setup_flow.load_pack("") is None

def test_taste_prompt_flows_into_judgment_backlog():
    """P-B2 surviving form: guidance, not a tool — the taste prompt must
    point at the derivable backlog (judgment_sections via list_breakdowns)."""
    from myzing import prompt_pack

    meta, text = prompt_pack.load_prompt("taste")
    flat = " ".join(text.split())
    assert tuple(int(x) for x in meta["version"].split(".")) >= (0, 1, 1)
    assert "judgment_sections" in flat
    assert "list_breakdowns()" in flat


def test_cli_list_names_the_next_command(pack_dir, capsys):
    """S5 install-gate observation #1: the listing must close the loop."""
    assert setup_flow.run(["--list"]) == 0
    out = capsys.readouterr().out
    assert "zing setup --pack <name>" in out


# -- SG-2: the D-3/D-4 machinery itself --------------------------------------

def test_wait_for_studies_returns_on_orphaned_running(zing_workspace):
    """D-3's subtle case: a 'running' status whose worker died must not
    spin the wait loop forever — the reconciling read flips it."""
    import os

    slug = storage.slug_for(LINKS[0])
    storage.write_status(
        slug, state="running", phase="shots", pid=os.getpid(),
        heartbeat_at="2020-01-01T00:00:00+00:00", started_at="t",
    )
    seen = []
    setup_flow.wait_for_studies(
        "orphan-taste", [LINKS[0]], poll_s=0.01,
        progress=lambda running: seen.append(running),
    )  # must return promptly instead of hanging
    assert (storage.read_status(slug) or {}).get("state") == "failed"


def test_cli_gives_up_honestly_after_bounded_retries(
    zing_workspace, monkeypatch, capsys
):
    """D-4 + give-up: an engine that always fails must end in the
    per-slug failure report with exit 1, not an infinite retry loop."""
    import sys as _sys
    import types

    api = types.ModuleType("myzing.study.api")

    def study(source, **kw):
        raise RuntimeError("fetch blocked: LOGIN_REQUIRED")

    api.study = study
    monkeypatch.setitem(_sys.modules, "myzing.study.api", api)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")

    code = setup_flow.run(["--links", LINKS[0], "--name", "doomed-taste"])
    out = capsys.readouterr().out
    assert code == 1
    assert "Retrying" in out                      # D-4 retry rounds announced
    assert "could not be completed" in out
    assert "LOGIN_REQUIRED" in out                # per-slug error detail shown
    assert "zing doctor" in out                   # actionable next step


def test_finish_pack_error_paths(pack_dir, monkeypatch):
    import sys as _sys
    import types

    packs_mod = types.ModuleType("myzing.profile.packs")

    class PackError(RuntimeError):
        pass

    def broken_build(path, study_missing=False):
        raise PackError("manifest reference r1 vanished")

    packs_mod.PackError = PackError
    packs_mod.build_pack = broken_build
    monkeypatch.setitem(_sys.modules, "myzing.profile.packs", packs_mod)
    result = setup_flow.finish_pack("ai-tech-talking-head")
    assert result["ok"] is False
    assert "manifest reference r1 vanished" in result["error"]

    monkeypatch.setitem(_sys.modules, "myzing.profile.packs", None)
    result = setup_flow.finish_pack("ai-tech-talking-head")
    # Was pinned to "update Zing" — the FOURTH test found pinning this
    # misdiagnosis class. The builder ships in the wheel; an ImportError
    # means the study extras are absent, and updating gets the user the
    # same extras they already lack.
    assert result["ok"] is False
    assert 'myzing[study]' in result["error"]


# -- main-red regression 2026-07-19: torn status reads --------------------------

def test_give_up_report_is_deterministic_under_dead_status_reads(
    zing_workspace, monkeypatch, capsys
):
    """P1 (#181 follow-up), deterministic fault injection: after the
    retry rounds complete, EVERY status read returns None — the summary
    must still carry each slug's failure detail from the CLI's own
    ledger, and must never print transient state categories."""
    import sys as _sys
    import types

    api = types.ModuleType("myzing.study.api")

    def study(source, **kw):
        raise RuntimeError("fetch blocked: LOGIN_REQUIRED")

    api.study = study
    monkeypatch.setitem(_sys.modules, "myzing.study.api", api)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")

    real_read = storage.read_status
    kill_reads = {"on": False}

    def controllable_read(slug):
        if kill_reads["on"]:
            return None  # deterministic: ALL reads dead in this phase
        return real_read(slug)

    monkeypatch.setattr(setup_flow.storage, "read_status", controllable_read)

    # Flip the kill switch the moment the give-up summary begins: the
    # print of the header is the deterministic boundary.
    real_print = print
    import builtins

    def boundary_print(*args, **kw):
        if args and "could not be completed" in str(args[0]):
            kill_reads["on"] = True
        return real_print(*args, **kw)

    monkeypatch.setattr(builtins, "print", boundary_print)

    code = setup_flow.run(["--links", LINKS[0], "--name", "det-taste"])
    out = capsys.readouterr().out
    assert code == 1
    assert "could not be completed" in out
    assert "LOGIN_REQUIRED" in out          # ledger detail survives dead reads
    summary = out[out.index("could not be completed"):]
    assert "[     failed]" in summary       # deterministic category
    for transient in ("running", "unstudied", "unknown"):
        assert transient not in summary, f"transient '{transient}' in summary"


def test_status_writes_are_atomic_under_concurrent_reads(zing_workspace):
    """write_status_at must never expose a torn file: a reader hammering
    read_status_at during 300 merge-writes may see old or new state but
    never None-while-the-file-exists."""
    import threading

    d = storage.breakdown_dir("tiktok-atomic")
    storage.write_status_at(d, state="running", n=0)
    stop = threading.Event()
    torn = []

    def reader():
        while not stop.is_set():
            status = storage.read_status_at(d)
            if status is None:
                torn.append(1)
                return

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(300):
            storage.write_status_at(d, n=i, error=f"detail {i}")
    finally:
        stop.set()
        t.join(timeout=10)
    assert not torn, "a reader observed a torn/absent status.json"
    assert (storage.read_status_at(d) or {}).get("n") == 299


def test_summary_preserves_start_denied_cause(zing_workspace, monkeypatch, capsys):
    """Audit #187 P2: a study denied at START (no status ever written)
    must carry its cause into the final summary, not just the inline
    line — [not-started] alone breaks the ledger's promise."""
    monkeypatch.setattr(mcp_server, "_study_api", lambda: None)  # start denial
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")

    code = setup_flow.run(["--links", LINKS[0], "--name", "denied-taste"])
    out = capsys.readouterr().out
    assert code == 1
    summary = out[out.index("could not be completed"):]
    assert "[not-started]" in summary.replace(" ", "") or "not-started" in summary
    # the CAUSE must reach the summary; the cause is now named
    # accurately (missing extras) rather than as a stale sprint note.
    assert 'myzing[study]' in summary


# -- SG-2: onboarding FAILURE paths (what a new user actually hits) ----------

def test_finish_pack_unknown_name_is_honest(zing_workspace, pack_dir):
    result = setup_flow.finish_pack("no-such-pack")
    assert result["ok"] is False
    assert "no preset pack named 'no-such-pack'" in result["error"]


def test_finish_pack_reports_pack_build_failure(zing_workspace, pack_dir, monkeypatch):
    from myzing.profile.packs import PackError

    def failing(*a, **k):
        raise PackError("no reference could be studied")

    monkeypatch.setattr("myzing.profile.packs.build_pack", failing)
    result = setup_flow.finish_pack("ai-tech-talking-head")
    assert result["ok"] is False
    assert "pack build failed" in result["error"]
    assert "no reference could be studied" in result["error"]


def test_finish_pack_unexpected_error_becomes_data_with_its_type(
    zing_workspace, pack_dir, monkeypatch
):
    """The boundary exists so an engine bug reaches the user as an
    envelope, not a traceback — and names the exception type so the
    report is actionable."""
    def exploding(*a, **k):
        raise RuntimeError("ffprobe vanished")

    monkeypatch.setattr("myzing.profile.packs.build_pack", exploding)
    result = setup_flow.finish_pack("ai-tech-talking-head")
    assert result["ok"] is False
    assert "RuntimeError" in result["error"]
    assert "ffprobe vanished" in result["error"]


def test_cli_lists_a_broken_pack_as_broken(tmp_path, monkeypatch, capsys):
    """A malformed pack must be listed as BROKEN with its reason, not
    hidden — a silently-missing pack is unexplainable to the user."""
    d = tmp_path / "presets"
    d.mkdir()
    (d / "wrecked.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(setup_flow.PRESETS_DIR_ENV, str(d))
    assert setup_flow.run(["--list"]) == 0
    out = capsys.readouterr().out
    assert "BROKEN" in out and "wrecked" in out


def test_cli_pack_build_failure_exits_nonzero_with_reason(
    zing_workspace, pack_dir, monkeypatch, capsys
):
    monkeypatch.setattr(
        setup_flow, "finish_pack",
        lambda name, study_missing=False: {
            "ok": False, "error": "profiles need 2+ studied sources"
        },
    )
    code = setup_flow.run(["--pack", "ai-tech-talking-head"])
    assert code == 1
    assert "profiles need 2+" in capsys.readouterr().out


def test_cli_pack_names_references_it_built_without(
    zing_workspace, pack_dir, monkeypatch, capsys
):
    """A pack that builds from 4 of 5 refs must SAY which one it lost —
    silently building from less than the curated set is the lie D-12
    was filed about, on the setup surface."""
    monkeypatch.setattr(
        setup_flow, "finish_pack",
        lambda name, study_missing=False: {
            "ok": True,
            "profile_name": "pack-ai-tech-talking-head",
            "sources": 1,
            "unjudged_sources": 1,
            "studied": ["r1"],
            "reused": [],
            "ref_failures": ["r2: Video unavailable"],
            "warnings": [],
        },
    )
    assert setup_flow.run(["--pack", "ai-tech-talking-head"]) == 0
    out = capsys.readouterr().out
    assert "reference failed (pack built without it): r2: Video unavailable" in out


def test_wait_for_studies_reports_progress_while_polling(
    zing_workspace, monkeypatch
):
    """The CLI's progress callback is the only thing standing between a
    long study and a user who thinks zing hung."""
    slug = storage.slug_for(LINKS[0])
    storage.write_status(slug, state="running", phase="shots", pid=1)
    seen: list[list] = []
    calls = {"n": 0}

    def fake_reconcile(s, status):
        calls["n"] += 1
        if calls["n"] >= 2:  # second look: the runner is gone
            return {"state": "failed", "error": "runner died"}
        return status

    monkeypatch.setattr(mcp_server, "_reconcile_running", fake_reconcile)
    setup_flow.wait_for_studies(
        "mytaste", [LINKS[0]], poll_s=0.0, progress=seen.append
    )
    assert seen and seen[0][0][0] == slug  # reported the running slug
    assert seen[0][0][1] == "shots"  # ...with its phase, not just a spinner
