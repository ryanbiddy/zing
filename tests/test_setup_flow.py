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
    assert result["ok"] is False and "update Zing" in result["error"]


# -- main-red regression 2026-07-19: torn status reads --------------------------

def test_give_up_report_survives_flaky_status_reads(
    zing_workspace, monkeypatch, capsys
):
    """The merge-skew regression: a status read returning None at report
    time must not blank the per-slug error detail — last-known errors
    carried across rounds fill the gap."""
    import sys as _sys
    import types

    api = types.ModuleType("myzing.study.api")

    def study(source, **kw):
        raise RuntimeError("fetch blocked: LOGIN_REQUIRED")

    api.study = study
    monkeypatch.setitem(_sys.modules, "myzing.study.api", api)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")

    real_read = storage.read_status
    flake = {"n": 0}

    def flaky_read(slug):
        flake["n"] += 1
        if flake["n"] % 2 == 0:  # every second read sees the torn window
            return None
        return real_read(slug)

    monkeypatch.setattr(setup_flow.storage, "read_status", flaky_read)
    code = setup_flow.run(["--links", LINKS[0], "--name", "flaky-taste"])
    out = capsys.readouterr().out
    assert code == 1
    assert "could not be completed" in out
    assert "LOGIN_REQUIRED" in out  # detail survives the flaky reads


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
