"""Preset-pack builder (S4 Track 2): curated manifest -> batch study ->
preset StyleProfile with full provenance.

A pack manifest (presets/<pack-id>.json) is the reproducibility contract
(LAUNCH-PLAN rules, the truth-hash lesson): stable reference IDs, the
exact URLs, and per-reference verification dates. The builder studies
whatever isn't studied yet, builds the pack profile from the survivors,
and records the manifest's sha256 + per-reference outcomes in provenance
— so a rebuilt pack can prove what it was built from, and drift (a
reference gone dead, a changed manifest) is detectable, never silent.

Regeneration = run the same command on the same manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from myzing import storage
from myzing.schemas import StyleProfile

# A curator-chosen file, like shot_list's import — which is capped, so
# leaving this unbounded was an inconsistency rather than a decision
# (same reasoning as the lease cap, #314). Largest shipped manifest is
# 2.7 KB; 1 MiB is ~400x headroom and turns a pathological file into a
# named error instead of an unbounded read.
MANIFEST_SIZE_LIMIT = 1024 * 1024

MANIFEST_REQUIRED = ("pack_id", "genre", "platform", "references")
REFERENCE_REQUIRED = ("id", "url", "why", "verified_at")


class PackError(RuntimeError):
    """A preset pack could not be built honestly."""


@dataclass
class PackResult:
    profile: StyleProfile
    studied: list[str] = field(default_factory=list)     # freshly studied ids
    reused: list[str] = field(default_factory=list)      # already in workspace
    failed: list[tuple[str, str]] = field(default_factory=list)  # (id, reason)
    warnings: list[str] = field(default_factory=list)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
        if size > MANIFEST_SIZE_LIMIT:
            raise PackError(
                f"pack manifest is {size} bytes, over the "
                f"{MANIFEST_SIZE_LIMIT}-byte limit: {path} — a manifest is "
                "a short curated list, so this is almost certainly the "
                "wrong file"
            )
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackError(f"unreadable pack manifest: {path} ({exc})") from exc
    for key in MANIFEST_REQUIRED:
        if key not in manifest:
            raise PackError(f"pack manifest missing '{key}': {path}")
    references = manifest["references"]
    if not isinstance(references, list) or not references:
        raise PackError(f"pack manifest has no references: {path}")
    seen_ids: set[str] = set()
    for index, reference in enumerate(references):
        for key in REFERENCE_REQUIRED:
            if not reference.get(key):
                raise PackError(
                    f"reference {index} missing '{key}' — every reference "
                    "carries a stable id, url, an OBSERVABLE why (something "
                    "a reader can check by watching the video), and its "
                    "live-verification date (reproducibility rules)"
                )
        if reference["id"] in seen_ids:
            raise PackError(f"duplicate reference id '{reference['id']}'")
        seen_ids.add(reference["id"])
    return manifest


def build_pack(
    manifest_path: Path,
    workspace: Path | None = None,
    *,
    study_missing: bool = True,
) -> PackResult:
    """Build (or regenerate) a preset pack from its manifest."""
    from myzing.profile.api import build_profile
    from myzing.study.api import study
    from myzing.study.proc import MediaError

    manifest = load_manifest(manifest_path)
    manifest_sha = hashlib.sha256(
        manifest_path.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()

    studied: list[str] = []
    reused: list[str] = []
    failed: list[tuple[str, str]] = []
    slugs: list[str] = []
    ref_provenance: list[dict[str, Any]] = []

    for reference in manifest["references"]:
        ref_id, url = reference["id"], reference["url"]
        slug = storage.slug_for(url)
        entry = {
            "id": ref_id,
            "slug": slug,
            "verified_at": reference["verified_at"],
        }
        try:
            storage.load_breakdown(slug)
            reused.append(ref_id)
            entry["outcome"] = "reused"
        except FileNotFoundError:
            if not study_missing:
                failed.append((ref_id, "not studied (study_missing=False)"))
                entry["outcome"] = "missing"
                ref_provenance.append(entry)
                continue
            try:
                study(url, workspace=workspace)
                studied.append(ref_id)
                entry["outcome"] = "studied"
            except MediaError as exc:
                failed.append((ref_id, str(exc).splitlines()[0]))
                entry["outcome"] = "failed"
                ref_provenance.append(entry)
                continue
        slugs.append(slug)
        ref_provenance.append(entry)

    if not slugs:
        # D-12: when everything fails (often one shared root cause), the
        # collected per-reference causes are the only actionable detail —
        # they must survive into the error.
        causes = "; ".join(
            f"{ref_id}: {cause}" for ref_id, cause in failed[:3]
        )
        more = f" (+{len(failed) - 3} more)" if len(failed) > 3 else ""
        raise PackError(
            f"pack '{manifest['pack_id']}': no reference could be studied — "
            "a preset built from nothing would be a lie. Failures: "
            f"{causes}{more}"
        )

    profile = build_profile(
        f"pack-{manifest['pack_id']}",
        slugs,
        workspace=workspace,
        genre=manifest["genre"],
        platform=manifest["platform"],
    )
    profile.warnings.extend(
        f"pack reference {ref_id} excluded: {reason}"
        for ref_id, reason in failed
    )
    profile.provenance["preset_pack"] = {
        "pack_id": manifest["pack_id"],
        "manifest_sha256": manifest_sha,
        "curated_at": manifest.get("curated_at", ""),
        "orientation": manifest.get("orientation", ""),
        "references": ref_provenance,
        "rebuilt_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    storage.save_profile(profile)
    return PackResult(
        profile=profile,
        studied=studied,
        reused=reused,
        failed=failed,
        warnings=list(profile.warnings),
    )
