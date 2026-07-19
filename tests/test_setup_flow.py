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
        "name": "ai-tech-talking-head",
        "genre": "talking-head",
        "platform": "tiktok",
        "description": "fast technical explainers",
        "references": [
            {"id": "r1", "url": LINKS[0], "why": "hook craft (G-TH-1)"},
            {"id": "r2", "url": LINKS[1], "why": "caption style (G-TH-5)"},
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

    def build_profile(name, slugs, genre="", platform=""):
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
    assert storage.load_profile("techie").genre == "talking-head"  # from pack


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
    assert code in (0, 3)
    wait_studies(SLUGS)
    code = setup_flow.run(["--pack", "ai-tech-talking-head"])
    assert code == 0
    assert "built from 2 references" in capsys.readouterr().out
    profile = storage.load_profile("ai-tech-talking-head")  # name from pack
    assert profile.genre == "talking-head"                  # genre from pack


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
