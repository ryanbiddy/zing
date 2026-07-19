"""S2 profile MCP tools: honest envelopes, seam auto-wire, idempotent save."""

from __future__ import annotations

import sys
import types

import pytest

from myzing import mcp_server, storage
from myzing.schemas import Breakdown, StatSummary, StyleProfile, VideoMeta

SLUGS = ["tiktok-1", "tiktok-2", "tiktok-3"]


@pytest.fixture
def studied_set(zing_workspace):
    for s in SLUGS:
        b = Breakdown(
            meta=VideoMeta(
                source_url=f"https://www.tiktok.com/@a/video/{s[-1]}",
                platform="tiktok",
            )
        )
        storage.save_breakdown(b, slug=s)


@pytest.fixture
def fake_builder(monkeypatch):
    api = types.ModuleType("myzing.profile.api")
    calls: dict = {}

    def build_profile(name, slugs, genre="", platform=""):
        calls["args"] = (name, list(slugs), genre, platform)
        return StyleProfile(
            name=name,
            source_slugs=list(slugs),
            genre=genre,
            platform=platform,
            duration=StatSummary(median=30.0, n=len(slugs)),
            unjudged_source_slugs=list(slugs),  # nothing judged in this fake
        )

    api.build_profile = build_profile
    monkeypatch.setitem(sys.modules, "myzing.profile.api", api)
    return calls


# -- build_profile -----------------------------------------------------------

def test_build_rejects_bad_name(studied_set):
    result = mcp_server.h_build_profile("../escape", SLUGS)
    assert result["ok"] is False and "profile name" in result["error"]


def test_build_requires_slugs(studied_set):
    result = mcp_server.h_build_profile("my-taste", [])
    assert result["ok"] is False and "list_breakdowns" in result["error"]


def test_build_names_missing_breakdowns(studied_set):
    result = mcp_server.h_build_profile("my-taste", SLUGS + ["tiktok-ghost"])
    assert result["ok"] is False
    assert "tiktok-ghost" in result["error"] and "study_video" in result["error"]


def test_build_builder_absent_is_honest(studied_set, monkeypatch):
    monkeypatch.setattr(mcp_server, "_profile_api", lambda: None)
    result = mcp_server.h_build_profile("my-taste", SLUGS)
    assert result["ok"] is False
    assert "not in this build yet" in result["error"]


def test_build_wires_seam_and_persists(studied_set, fake_builder):
    result = mcp_server.h_build_profile(
        "my-taste", SLUGS, genre="talking-head", platform="tiktok"
    )
    assert result["ok"] is True, result.get("error")
    assert result["sources"] == 3
    assert result["unjudged_sources"] == 3  # honest about the fake's coverage
    assert fake_builder["args"] == ("my-taste", SLUGS, "talking-head", "tiktok")
    loaded = storage.load_profile("my-taste")
    assert loaded.genre == "talking-head"
    assert loaded.duration.median == 30.0


def test_build_does_not_double_save(studied_set, monkeypatch):
    """If the builder persisted via storage itself, the tool must not
    clobber that save (parallel to the study_video idempotence rule)."""
    api = types.ModuleType("myzing.profile.api")

    def build_and_save(name, slugs):
        p = StyleProfile(name=name, source_slugs=list(slugs))
        storage.save_profile(p)
        return p

    api.build_profile = build_and_save
    monkeypatch.setitem(sys.modules, "myzing.profile.api", api)
    result = mcp_server.h_build_profile("my-taste", SLUGS)
    assert result["ok"] is True
    d = storage.profile_dir("my-taste")
    assert not (d / "profile.json.bak").exists()  # no second write happened


# -- get_profile / list_profiles ---------------------------------------------

def test_get_profile_missing_is_actionable(zing_workspace):
    result = mcp_server.h_get_profile("ghost")
    assert result["ok"] is False
    assert "list_profiles" in result["error"] and "build_profile" in result["error"]


def test_get_profile_roundtrip(studied_set, fake_builder):
    mcp_server.h_build_profile("my-taste", SLUGS, genre="talking-head")
    result = mcp_server.h_get_profile("my-taste")
    assert result["ok"] is True
    assert result["profile"]["genre"] == "talking-head"
    assert result["dir"] == str(storage.profile_dir("my-taste"))


def test_list_profiles_tool(studied_set, fake_builder):
    assert mcp_server.h_list_profiles()["count"] == 0
    mcp_server.h_build_profile("my-taste", SLUGS)
    result = mcp_server.h_list_profiles()
    assert result["count"] == 1
    assert result["profiles"][0]["name"] == "my-taste"


# -- SG-2 second pass: uncovered error paths ---------------------------------

def test_build_profile_builder_exception_is_errors_as_data(studied_set, monkeypatch):
    api = types.ModuleType("myzing.profile.api")

    def explode(name, slugs):
        raise ValueError("source tiktok-2 has no measured duration")

    api.build_profile = explode
    monkeypatch.setitem(sys.modules, "myzing.profile.api", api)
    result = mcp_server.h_build_profile("my-taste", SLUGS)
    assert result["ok"] is False
    assert "profile build failed" in result["error"]
    assert "tiktok-2" in result["error"]


def test_build_profile_sets_genre_when_seam_lacks_kwargs(studied_set, monkeypatch):
    """A builder without genre/platform params still yields a tagged profile."""
    api = types.ModuleType("myzing.profile.api")

    def bare_builder(name, slugs):  # no genre/platform kwargs at all
        return StyleProfile(name=name, source_slugs=list(slugs))

    api.build_profile = bare_builder
    monkeypatch.setitem(sys.modules, "myzing.profile.api", api)
    result = mcp_server.h_build_profile(
        "my-taste", SLUGS, genre="vlog", platform="youtube"
    )
    assert result["ok"] is True
    loaded = storage.load_profile("my-taste")
    assert loaded.genre == "vlog" and loaded.platform == "youtube"


def test_get_profile_corrupt_json_is_errors_as_data(zing_workspace):
    d = storage.profiles_root() / "broken"
    d.mkdir(parents=True)
    (d / "profile.json").write_text("{not json", encoding="utf-8")
    result = mcp_server.h_get_profile("broken")
    assert result["ok"] is False  # ValueError path, not an exception


def test_serve_mcp_without_sdk_is_actionable(monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def no_mcp(name, *args, **kwargs):
        if name == "mcp":
            raise ImportError("No module named 'mcp'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_mcp)
    assert mcp_server.run([]) == 2
    assert 'myzing[mcp]' in capsys.readouterr().err
