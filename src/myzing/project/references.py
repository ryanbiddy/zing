"""Resolve external references without copying media or permitting web fallback."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from myzing import storage, uoink_bridge
from .api import _save, hash_file, load_project, stored_path
from .locking import project_lock
from .models import ProjectError, ReferenceResolution
from .paths import resolve_path


def item_ref(value: str) -> str:
    """Translate the inventory shorthand to the existing canonical wire ref."""
    ref = value if value.startswith("uoink://item/") else "uoink://item/" + quote(value[6:], safe="")
    if not value.startswith("uoink:") or uoink_bridge._item_id_from_ref(ref) is None:
        raise ProjectError("Use uoink:<item-id> with one nonempty item ID.")
    return ref


def _verified(path: Path, sha256: str | None = None, size: int | None = None) -> tuple[str, int]:
    if not path.is_file():
        raise ProjectError("Reference media is missing; supply a local file with --file.")
    before = path.stat()
    digest = hash_file(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ProjectError("Reference media changed during verification; retry after writes finish.")
    if (sha256 is not None and digest != sha256) or (size is not None and after.st_size != size):
        raise ProjectError("Reference media hash/size mismatch; refused. Resolve again or supply --file.")
    return digest, after.st_size


def resolve_reference(project: str | Path, *, file: str | Path | None = None) -> ReferenceResolution:
    root = Path(project).expanduser().resolve()
    load_project(root)
    with project_lock(root):
        manifest = load_project(root)
        ref = manifest.reference
        try:
            if file is not None or ref.kind == "file":
                path = Path(file).expanduser().resolve() if file is not None else resolve_path(ref.value, root)
                digest, size = _verified(path)
                resolution = ReferenceResolution(
                    "resolved", str(path), digest, size,
                    provenance={"kind": "user_supplied_file", "original_reference": ref.value},
                )
            elif ref.kind == "uoink":
                canonical = item_ref(ref.value)
                response = uoink_bridge.resolve_kept_media(canonical)
                if not response["ok"]:
                    raise ProjectError(response["error"])
                data = response["data"]
                if data["state"] != "available":
                    raise ProjectError(f"Uoink kept media is {data['state']}; supply a local file with --file.")
                media = data["media"]
                if any(isinstance(value, str) and uoink_bridge.redact(value) != value
                       for value in (media["path"], data["source_url"])):
                    raise ProjectError("Refused a kept-media response containing a credential.")
                path = resolve_path(media["path"], root, entry="kept media")
                digest, size = _verified(path, media["sha256"], media["byte_length"])
                resolution = ReferenceResolution(
                    "resolved", str(path), digest, size, canonical,
                    data["source_url"], data["provenance"],
                )
            else:
                raise ProjectError("This reference is a URL. Supply --file, or explicitly download it with 'zing study <url>'.")
        except (ProjectError, OSError, ValueError) as exc:
            resolution = ReferenceResolution("unresolved", reason=uoink_bridge.redact(str(exc)))
        if ref.resolution != resolution:
            ref.study = None
        ref.resolution, ref.state = resolution, resolution.state
        _save(root, manifest)
        return resolution


def study_reference(project: str | Path, *, workspace: Path | None = None) -> dict:
    """Use the recorded file only, rechecking integrity before and after study."""
    from myzing.study.api import study

    root = Path(project).expanduser().resolve()
    load_project(root)
    with project_lock(root):
        manifest = load_project(root)
        resolution = manifest.reference.resolution
        if resolution is None or resolution.state != "resolved":
            raise ProjectError("Reference unresolved. Run 'zing project resolve-reference <project> [--file FILE]'.")
        path = resolve_path(resolution.path, root)
        def verify():
            try:
                _verified(path, resolution.sha256, resolution.byte_length)
            except (ProjectError, OSError) as exc:
                reason = uoink_bridge.redact(str(exc))
                manifest.reference.resolution = ReferenceResolution("unresolved", reason=reason)
                manifest.reference.state, manifest.reference.study = "unresolved", None
                _save(root, manifest)
                raise ProjectError(reason) from exc

        verify()
        # Passing the local path, never source_url, makes web fallback impossible.
        workspace = storage.resolve_workspace(workspace)
        breakdown = study(str(path), workspace=workspace)
        verify()
        breakdown.provenance["project_reference"] = {
            "version": 1, "reference": manifest.reference.value,
            "sha256": resolution.sha256, "provenance": resolution.provenance,
            "refetch": False,
        }
        slug = storage.slug_for(str(path))
        with storage.use_workspace(workspace):
            storage.save_breakdown(breakdown, slug=slug)
            breakdown_path = storage.breakdown_dir(slug) / "breakdown.json"
        manifest.reference.study = {"state": "done", "breakdown_path": stored_path(breakdown_path, root),
                                    "sha256": hash_file(breakdown_path), "reference_sha256": resolution.sha256}
        _save(root, manifest)
        return manifest.reference.study
