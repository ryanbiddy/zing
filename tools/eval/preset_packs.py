"""Reproducibility and restudy-drift checks for Sprint 4 preset packs."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from myzing import storage
from myzing.profile.packs import build_pack, load_manifest
from myzing.schemas import StyleProfile

PRESET_EVAL_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRESETS_DIR = ROOT / "presets"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_sha256(path: Path) -> str:
    """Match the pack builder's UTF-8 text hashing contract exactly."""
    return hashlib.sha256(
        path.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def discover_manifests(
    presets_dir: Path = DEFAULT_PRESETS_DIR,
) -> dict[str, Path]:
    """Find either flat ``<pack>.json`` or nested ``<pack>/pack.json`` packs."""
    discovered: dict[str, Path] = {}
    candidates = sorted(presets_dir.glob("*.json"))
    candidates.extend(sorted(presets_dir.glob("*/pack.json")))
    for path in candidates:
        manifest = load_manifest(path)
        pack_id = str(manifest.get("pack_id") or manifest.get("name") or "")
        if not pack_id:
            raise ValueError(f"preset manifest has no pack id: {path}")
        if pack_id in discovered:
            raise ValueError(
                f"duplicate preset pack '{pack_id}': "
                f"{discovered[pack_id]} and {path}"
            )
        discovered[pack_id] = path
    return discovered


def stable_profile_payload(profile: StyleProfile) -> dict[str, Any]:
    """Profile content with only run-specific audit fields removed.

    ``built_at``, ``rebuilt_at``, and whether a source was studied or reused
    describe this invocation. Measurements, source identities, warnings, and
    every other provenance field remain part of the reproducibility digest.
    """
    payload = copy.deepcopy(profile.to_dict())
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        provenance.pop("built_at", None)
        pack = provenance.get("preset_pack")
        if isinstance(pack, dict):
            pack.pop("rebuilt_at", None)
            references = pack.get("references")
            if isinstance(references, list):
                for reference in references:
                    if isinstance(reference, dict):
                        reference.pop("outcome", None)
    return payload


def profile_content_sha256(profile: StyleProfile) -> str:
    return _canonical_sha256(stable_profile_payload(profile))


def snapshot_pack(
    manifest_path: Path,
    workspace: Path,
    *,
    profile: StyleProfile | None = None,
) -> dict[str, Any]:
    """Hash a pack manifest, every stored source Breakdown, and its profile."""
    manifest = load_manifest(manifest_path)
    manifest_sha = _manifest_sha256(manifest_path)
    profile_manifest_sha = None
    if profile is not None:
        pack_provenance = profile.provenance.get("preset_pack")
        if isinstance(pack_provenance, dict):
            profile_manifest_sha = pack_provenance.get("manifest_sha256")
    references = []
    with storage.use_workspace(workspace):
        for reference in manifest["references"]:
            slug = storage.slug_for(reference["url"])
            breakdown_path = storage.breakdown_dir(slug) / "breakdown.json"
            references.append(
                {
                    "id": reference["id"],
                    "url": reference["url"],
                    "slug": slug,
                    "breakdown_sha256": (
                        _sha256(breakdown_path)
                        if breakdown_path.is_file()
                        else None
                    ),
                }
            )
    return {
        "preset_eval_version": PRESET_EVAL_VERSION,
        "pack_id": manifest["pack_id"],
        "manifest_sha256": manifest_sha,
        "profile_manifest_sha256": profile_manifest_sha,
        "profile_manifest_matches": (
            profile_manifest_sha == manifest_sha
            if profile is not None
            else None
        ),
        "references": references,
        "profile_content_sha256": (
            profile_content_sha256(profile) if profile is not None else None
        ),
    }


def compare_pack_snapshots(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Return exact drift evidence between two pack builds."""
    drift: list[dict[str, Any]] = []
    for field in (
        "pack_id",
        "manifest_sha256",
        "profile_manifest_sha256",
        "profile_content_sha256",
    ):
        if previous.get(field) != current.get(field):
            drift.append(
                {
                    "kind": field,
                    "before": previous.get(field),
                    "after": current.get(field),
                }
            )

    before_refs = {
        reference["id"]: reference
        for reference in previous.get("references", [])
    }
    after_refs = {
        reference["id"]: reference
        for reference in current.get("references", [])
    }
    for ref_id in sorted(before_refs.keys() | after_refs.keys()):
        before = before_refs.get(ref_id)
        after = after_refs.get(ref_id)
        if before is None or after is None:
            drift.append(
                {
                    "kind": "reference_membership",
                    "reference_id": ref_id,
                    "before": before,
                    "after": after,
                }
            )
            continue
        for field in ("url", "slug", "breakdown_sha256"):
            if before.get(field) != after.get(field):
                drift.append(
                    {
                        "kind": f"reference_{field}",
                        "reference_id": ref_id,
                        "before": before.get(field),
                        "after": after.get(field),
                    }
                )
    return {
        "passed": not drift,
        "drift_count": len(drift),
        "drift": drift,
    }


def evaluate_rebuild(
    manifest_path: Path,
    workspace: Path,
) -> dict[str, Any]:
    """Build the same stored inputs twice and require an identical snapshot."""
    first_profile = build_pack(
        manifest_path,
        workspace=workspace,
        study_missing=False,
    ).profile
    first = snapshot_pack(
        manifest_path,
        workspace,
        profile=first_profile,
    )
    second_profile = build_pack(
        manifest_path,
        workspace=workspace,
        study_missing=False,
    ).profile
    second = snapshot_pack(
        manifest_path,
        workspace,
        profile=second_profile,
    )
    comparison = compare_pack_snapshots(first, second)
    provenance_matches = bool(
        first["profile_manifest_matches"]
        and second["profile_manifest_matches"]
    )
    return {
        "preset_eval_version": PRESET_EVAL_VERSION,
        "pack_id": first["pack_id"],
        "passed": comparison["passed"] and provenance_matches,
        "profile_manifest_matches": provenance_matches,
        "first": first,
        "second": second,
        "drift": (
            comparison["drift"]
            if provenance_matches
            else [
                *comparison["drift"],
                {
                    "kind": "profile_manifest_mismatch",
                    "before": first["profile_manifest_sha256"],
                    "after": second["profile_manifest_sha256"],
                    "expected": first["manifest_sha256"],
                },
            ]
        ),
    }
