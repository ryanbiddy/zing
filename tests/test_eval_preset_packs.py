"""Sprint 4 Track 2 preset-pack reproducibility and onboarding gates."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from myzing import mcp_server, setup_flow, storage
from myzing.profile.packs import build_pack
from myzing.schemas import Breakdown, VideoMeta
from tools.eval.preset_packs import (
    compare_pack_snapshots,
    discover_manifests,
    evaluate_rebuild,
    profile_content_sha256,
    snapshot_pack,
)


SHIPPED_PACK_IDS = {
    "ai-tech-talking-head",
    "informative-explainer",
    "product-launch",
    "viral-tiktok-reels",
    "vlog",
}


def test_every_shipped_pack_is_visible_to_setup_flow() -> None:
    visible = {pack["name"] for pack in setup_flow.list_packs()}

    assert visible == SHIPPED_PACK_IDS


def _write_manifest(path: Path) -> dict:
    manifest = {
        "pack_id": "constructed-pack",
        "curated_at": "2026-07-19",
        "genre": "talking-head",
        "platform": "youtube",
        "orientation": "vertical",
        "references": [
            {
                "id": "REF-01",
                "url": "https://www.youtube.com/watch?v=fixture0001",
                "why": "Constructed reference one.",
                "verified_at": "2026-07-19",
            },
            {
                "id": "REF-02",
                "url": "https://www.youtube.com/watch?v=fixture0002",
                "why": "Constructed reference two.",
                "verified_at": "2026-07-19",
            },
        ],
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _save_reference(url: str, duration: float) -> str:
    slug = storage.slug_for(url)
    storage.save_breakdown(
        Breakdown(
            meta=VideoMeta(
                source_url=url,
                platform="youtube",
                duration=duration,
                width=1920,
                height=1080,
                fps=30.0,
            ),
            judgment={
                "study": {
                    "hook": "constructed",
                    "_meta": {"prompt_version": "test"},
                }
            },
        ),
        slug=slug,
    )
    return slug


def test_discovery_covers_all_shipped_manifests() -> None:
    assert set(discover_manifests()) == SHIPPED_PACK_IDS


@pytest.mark.parametrize("pack_id", sorted(SHIPPED_PACK_IDS))
def test_each_shipped_pack_rebuilds_from_identical_mocked_studies(
    pack_id: str,
    zing_workspace: Path,
) -> None:
    manifest_path = discover_manifests()[pack_id]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for index, reference in enumerate(manifest["references"], start=1):
        _save_reference(reference["url"], duration=20.0 + index)

    result = evaluate_rebuild(manifest_path, zing_workspace)

    assert result["passed"] is True
    assert result["profile_manifest_matches"] is True
    assert len(result["first"]["references"]) == len(manifest["references"])


def test_same_inputs_rebuild_to_the_same_profile_content(
    zing_workspace: Path,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "constructed-pack.json"
    manifest = _write_manifest(manifest_path)
    for index, reference in enumerate(manifest["references"], start=1):
        _save_reference(reference["url"], duration=10.0 * index)

    result = evaluate_rebuild(manifest_path, zing_workspace)

    assert result["passed"] is True
    assert result["profile_manifest_matches"] is True
    assert result["drift"] == []
    assert result["first"]["manifest_sha256"] == result["second"][
        "manifest_sha256"
    ]
    assert result["first"]["profile_content_sha256"] == result["second"][
        "profile_content_sha256"
    ]
    assert all(
        reference["breakdown_sha256"]
        for reference in result["first"]["references"]
    )


def test_restudied_reference_reports_input_and_profile_drift(
    zing_workspace: Path,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "constructed-pack.json"
    manifest = _write_manifest(manifest_path)
    for index, reference in enumerate(manifest["references"], start=1):
        _save_reference(reference["url"], duration=10.0 * index)
    before_profile = build_pack(
        manifest_path,
        workspace=zing_workspace,
        study_missing=False,
    ).profile
    before = snapshot_pack(
        manifest_path,
        zing_workspace,
        profile=before_profile,
    )

    changed = manifest["references"][0]
    _save_reference(changed["url"], duration=44.0)
    after_profile = build_pack(
        manifest_path,
        workspace=zing_workspace,
        study_missing=False,
    ).profile
    after = snapshot_pack(
        manifest_path,
        zing_workspace,
        profile=after_profile,
    )

    comparison = compare_pack_snapshots(before, after)

    assert comparison["passed"] is False
    assert {
        (item["kind"], item.get("reference_id"))
        for item in comparison["drift"]
    } == {
        ("profile_content_sha256", None),
        ("reference_breakdown_sha256", changed["id"]),
    }


def test_profile_digest_ignores_only_run_audit_fields(
    zing_workspace: Path,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "constructed-pack.json"
    manifest = _write_manifest(manifest_path)
    for index, reference in enumerate(manifest["references"], start=1):
        _save_reference(reference["url"], duration=10.0 * index)
    profile = build_pack(
        manifest_path,
        workspace=zing_workspace,
        study_missing=False,
    ).profile
    rerun = copy.deepcopy(profile)
    rerun.provenance["built_at"] = "later"
    rerun.provenance["preset_pack"]["rebuilt_at"] = "later"
    rerun.provenance["preset_pack"]["references"][0]["outcome"] = "studied"

    assert profile_content_sha256(rerun) == profile_content_sha256(profile)

    rerun.duration.median += 1.0
    assert profile_content_sha256(rerun) != profile_content_sha256(profile)


def test_mocked_setup_cli_builds_preset_and_personal_profiles_with_provenance(
    zing_workspace: Path,
    monkeypatch,
    capsys,
) -> None:
    def save_study(url: str) -> str:
        slug = _save_reference(url, duration=30.0)
        return slug

    def study_now(url: str) -> dict:
        slug = save_study(url)
        return {"ok": True, "slug": slug}

    monkeypatch.setattr(
        "myzing.study.api.study",
        lambda url, workspace=None: save_study(url),
    )
    monkeypatch.setattr(mcp_server, "h_study_video", study_now)

    preset_code = setup_flow.run(
        [
            "--pack",
            "ai-tech-talking-head",
        ]
    )
    personal_links = [
        "https://www.youtube.com/watch?v=personal001",
        "https://www.youtube.com/watch?v=personal002",
    ]
    personal_code = setup_flow.run(
        [
            "--links",
            *personal_links,
            "--name",
            "personal-smoke",
            "--genre",
            "talking-head",
            "--platform",
            "youtube",
        ]
    )

    assert preset_code == 0
    assert personal_code == 0
    output = capsys.readouterr().out
    assert (
        "Taste 'pack-ai-tech-talking-head' built from 7 references"
        in output
    )
    assert "Taste 'personal-smoke' built from 2 references" in output
    preset_profile = storage.load_profile("pack-ai-tech-talking-head")
    personal_profile = storage.load_profile("personal-smoke")
    assert len(preset_profile.source_slugs) == 7
    assert len(personal_profile.source_slugs) == 2
    assert preset_profile.provenance["preset_pack"]["pack_id"] == (
        "ai-tech-talking-head"
    )
    assert len(
        preset_profile.provenance["preset_pack"]["manifest_sha256"]
    ) == 64
    assert len(preset_profile.judged["study"]) == 7
    assert len(personal_profile.judged["study"]) == 2
