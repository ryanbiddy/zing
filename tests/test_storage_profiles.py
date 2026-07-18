"""S2 profile storage: names validated like slugs, honest persistence."""

from __future__ import annotations

import pytest

from myzing import storage
from myzing.schemas import StatSummary, StyleProfile


def make_profile(name: str = "my-taste") -> StyleProfile:
    return StyleProfile(
        name=name,
        source_slugs=["tiktok-1", "tiktok-2", "tiktok-3"],
        genre="talking-head",
        platform="tiktok",
        duration=StatSummary(median=32.0, p25=28.0, p75=41.0, n=3),
        unjudged_source_slugs=["tiktok-3"],
        warnings=["transitions: 2 of 3 sources had detection off"],
    )


# -- name validation ---------------------------------------------------------

def test_profile_names_follow_slug_contract(zing_workspace):
    assert storage.validate_profile_name("my-taste") == "my-taste"
    for bad in ("../escape", "a/b", "a\\b", "UPPER", "", "has space", "dot.name"):
        with pytest.raises(storage.SlugError):
            storage.validate_profile_name(bad)


def test_profile_name_errors_say_profile_not_slug(zing_workspace):
    with pytest.raises(storage.SlugError, match="profile name"):
        storage.validate_profile_name("../escape")


def test_slug_validation_unchanged_by_refactor(zing_workspace):
    assert storage.validate_slug("tiktok-123") == "tiktok-123"
    with pytest.raises(storage.SlugError, match="slug"):
        storage.validate_slug("../escape")


# -- persistence -------------------------------------------------------------

def test_save_load_roundtrip(zing_workspace):
    p = make_profile()
    d = storage.save_profile(p)
    assert d == storage.profile_dir("my-taste")
    loaded = storage.load_profile("my-taste")
    assert loaded.to_dict() == p.to_dict()
    assert loaded.duration.median == 32.0
    assert loaded.unjudged_source_slugs == ["tiktok-3"]


def test_rebuild_keeps_bak(zing_workspace):
    storage.save_profile(make_profile())
    p2 = make_profile()
    p2.source_slugs.append("tiktok-4")
    d = storage.save_profile(p2)
    assert (d / "profile.json.bak").exists()
    assert len(storage.load_profile("my-taste").source_slugs) == 4


def test_load_missing_is_actionable(zing_workspace):
    with pytest.raises(FileNotFoundError, match="no profile named 'ghost'"):
        storage.load_profile("ghost")


# -- index -------------------------------------------------------------------

def test_list_profiles_empty(zing_workspace):
    assert storage.list_profiles() == []


def test_list_profiles_summary_and_honest_errors(zing_workspace):
    storage.save_profile(make_profile())
    bad = storage.profiles_root() / "broken"
    bad.mkdir(parents=True)
    (bad / "profile.json").write_text("{nope", encoding="utf-8")

    index = storage.list_profiles()
    by_name = {e["name"]: e for e in index}
    good = by_name["my-taste"]
    assert good["genre"] == "talking-head"
    assert good["sources"] == 3
    assert good["unjudged_sources"] == 1
    assert good["warnings"] == 1
    assert "error" in by_name["broken"]
