"""Tests for the preset-pack builder (A-Q14/S4 Track 2): manifest
validation, batch-study orchestration, provenance, honest exclusions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myzing import storage
from myzing.profile import packs
from myzing.profile.packs import PackError, build_pack, load_manifest
from tests.test_profile_api import make_source


def write_manifest(path: Path, references=None, **overrides) -> Path:
    manifest = {
        "pack_id": "ai-tech-talking-head",
        "genre": "talking-head",
        "platform": "youtube",
        "orientation": "vertical",
        "curated_at": "2026-07-19",
        "references": references if references is not None else [
            {
                "id": "AITTH-01",
                "url": "https://youtube.com/shorts/ref-one",
                "why": "cold-open claim, word-pop caps (G-TH-1)",
                "verified_at": "2026-07-19",
            },
        ],
    }
    manifest.update(overrides)
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return path


def ref(n: int, url: str) -> dict:
    return {
        "id": f"AITTH-{n:02d}",
        "url": url,
        "why": "rubric-cited why (G-TH-1)",
        "verified_at": "2026-07-19",
    }


# -- manifest validation ----------------------------------------------------

def test_manifest_missing_key_is_loud(tmp_path):
    p = tmp_path / "pack.json"
    p.write_text(json.dumps({"pack_id": "x"}), encoding="utf-8")
    with pytest.raises(PackError, match="missing 'genre'"):
        load_manifest(p)


def test_reference_missing_verification_date_is_loud(tmp_path):
    p = write_manifest(tmp_path / "pack.json", references=[
        {"id": "A-01", "url": "https://x", "why": "y", "verified_at": ""},
    ])
    with pytest.raises(PackError, match="verified_at"):
        load_manifest(p)


def test_duplicate_reference_ids_are_loud(tmp_path):
    p = write_manifest(tmp_path / "pack.json", references=[
        ref(1, "https://youtube.com/shorts/a"),
        ref(1, "https://youtube.com/shorts/b"),
    ])
    with pytest.raises(PackError, match="duplicate reference id"):
        load_manifest(p)


# -- build orchestration ----------------------------------------------------

def test_build_pack_studies_missing_and_reuses_stored(
    zing_workspace, tmp_path, monkeypatch
):
    url_a = "https://youtube.com/shorts/pack-ref-a"
    url_b = "https://youtube.com/shorts/pack-ref-b"
    # ref A already studied; ref B needs studying.
    make_source(storage.slug_for(url_a), 30.0, [5.0], 10.0)

    def fake_study(url, workspace=None):
        make_source(storage.slug_for(url), 40.0, [8.0], 12.0)
    monkeypatch.setattr("myzing.study.api.study", fake_study)

    manifest = write_manifest(tmp_path / "pack.json", references=[
        ref(1, url_a), ref(2, url_b),
    ])

    result = build_pack(manifest)

    assert result.reused == ["AITTH-01"]
    assert result.studied == ["AITTH-02"]
    assert result.failed == []
    pack_prov = result.profile.provenance["preset_pack"]
    assert pack_prov["pack_id"] == "ai-tech-talking-head"
    assert len(pack_prov["manifest_sha256"]) == 64
    assert [r["outcome"] for r in pack_prov["references"]] == [
        "reused", "studied",
    ]
    assert result.profile.genre == "talking-head"
    # persisted under the pack name
    loaded = storage.load_profile("pack-ai-tech-talking-head")
    assert loaded.provenance["preset_pack"]["pack_id"] == "ai-tech-talking-head"


def test_dead_reference_excluded_with_named_warning(
    zing_workspace, tmp_path, monkeypatch
):
    from myzing.study.proc import MediaError

    good = "https://youtube.com/shorts/pack-good"
    dead = "https://youtube.com/shorts/pack-dead"
    make_source(storage.slug_for(good), 30.0, [5.0], 10.0)

    def failing_study(url, workspace=None):
        raise MediaError("yt-dlp could not fetch: Video unavailable")
    monkeypatch.setattr("myzing.study.api.study", failing_study)

    manifest = write_manifest(tmp_path / "pack.json", references=[
        ref(1, good), ref(2, dead),
    ])

    result = build_pack(manifest)

    assert result.failed == [
        ("AITTH-02", "yt-dlp could not fetch: Video unavailable"),
    ]
    assert any(
        "AITTH-02 excluded" in w for w in result.profile.warnings
    )
    assert len(result.profile.source_slugs) == 1


def test_all_dead_references_is_an_error(zing_workspace, tmp_path, monkeypatch):
    from myzing.study.proc import MediaError

    monkeypatch.setattr(
        "myzing.study.api.study",
        lambda url, workspace=None: (_ for _ in ()).throw(
            MediaError("gone")
        ),
    )
    manifest = write_manifest(tmp_path / "pack.json", references=[
        ref(1, "https://youtube.com/shorts/gone-1"),
    ])
    # D-12 (S5 gate): the per-reference causes must survive into the
    # error — when everything fails they are the only actionable detail.
    with pytest.raises(PackError, match="built from nothing") as exc_info:
        build_pack(manifest)
    assert "gone" in str(exc_info.value)
    assert "AITTH-01" in str(exc_info.value)


def test_no_study_mode_fails_unstudied_honestly(
    zing_workspace, tmp_path, monkeypatch
):
    good = "https://youtube.com/shorts/stored-ref"
    make_source(storage.slug_for(good), 30.0, [5.0], 10.0)
    manifest = write_manifest(tmp_path / "pack.json", references=[
        ref(1, good), ref(2, "https://youtube.com/shorts/never-studied"),
    ])

    result = build_pack(manifest, study_missing=False)

    assert result.failed == [("AITTH-02", "not studied (study_missing=False)")]
    assert len(result.profile.source_slugs) == 1


def test_cli_pack_subcommand(zing_workspace, tmp_path, monkeypatch, capsys):
    from myzing import cli

    url = "https://youtube.com/shorts/cli-pack-ref"
    make_source(storage.slug_for(url), 30.0, [5.0], 10.0)
    manifest = write_manifest(tmp_path / "pack.json", references=[ref(1, url)])

    rc = cli.main(["profile", "pack", str(manifest)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "pack pack-ai-tech-talking-head" in out
    assert "1 reused" in out
