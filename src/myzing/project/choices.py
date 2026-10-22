"""Project-owned draft choices with durable, opt-in peer delivery."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from myzing import engagement, uoink_bridge
from .api import hash_file, load_project, stored_path
from .locking import project_lock
from .models import ProjectError, Record, _version
from .references import item_ref

CHOICES_NAME = "choices.json"


@dataclass
class ChoiceReceipt(Record):
    event_id: str
    project_id: str
    draft: str
    draft_path: str
    draft_sha256: str
    reference: str
    reference_sha256: str | None
    brief_sha256: str | None
    occurred_at: str
    notes: list[str] = field(default_factory=list)
    share_requested: bool = False
    delivery: dict = field(default_factory=lambda: {"state": "local_only"})
    action: str = "draft_chosen"
    version: int = 1

    def __post_init__(self):
        hashes = [self.draft_sha256, self.reference_sha256, self.brief_sha256]
        if (self.draft not in {"A", "B", "C"} or self.action != "draft_chosen"
                or not isinstance(self.event_id, str) or not self.event_id.startswith("zing-choice-")
                or not isinstance(self.draft_path, str) or not self.draft_path
                or not isinstance(self.reference, str) or not self.reference
                or not isinstance(self.occurred_at, str) or not self.occurred_at.endswith("Z")
                or not isinstance(self.notes, list) or any(not isinstance(n, str) for n in self.notes)
                or type(self.share_requested) is not bool or not isinstance(self.delivery, dict)
                or not self.draft_sha256
                or any(h is not None and (not isinstance(h, str) or len(h) != 64
                                         or any(c not in "0123456789abcdef" for c in h)) for h in hashes)):
            raise ProjectError("Invalid choice receipt; restore choices.json before choosing again.")


def _read(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "project_id": "project_" + uuid4().hex,
                "selected": None, "receipts": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        _version(state, "choice memory")
        if (set(state) != {"version", "project_id", "selected", "receipts"}
                or not isinstance(state["project_id"], str) or not state["project_id"]
                or not isinstance(state["receipts"], dict)):
            raise ValueError("invalid shape")
        for key, data in state["receipts"].items():
            receipt = ChoiceReceipt.from_dict(data)
            if receipt.event_id != key or receipt.project_id != state["project_id"]:
                raise ValueError("receipt identity mismatch")
        if state["selected"] is not None and state["selected"] not in state["receipts"]:
            raise ValueError("selected receipt missing")
        return state
    except (ValueError, TypeError) as exc:
        raise ProjectError("Choice memory is invalid; restore choices.json before choosing again.") from exc


def _write(path: Path, state: dict) -> None:
    if path.is_symlink():
        raise ProjectError("Refusing to replace a symlink at choices.json.")
    fd, name = tempfile.mkstemp(prefix=".choices-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def choose_draft(project: str | Path, draft: str, *, note: str | None = None,
                 share_choice: bool = False, draft_file: str | Path | None = None) -> dict:
    """Choose a concrete artifact; repeated choices reuse their original event."""
    if draft not in {"A", "B", "C"}:
        raise ProjectError("Choose draft A, B or C.")
    root = Path(project).expanduser().resolve()
    load_project(root)
    with project_lock(root):
        manifest = load_project(root)
        artifact = Path(draft_file).expanduser().resolve() if draft_file is not None else root / "drafts" / f"{draft}.json"
        if draft_file is None and not artifact.exists() and (root / "drafts" / f"plan-{draft}.json").exists():
            # `zing plan drafts --out <project>/drafts` writes plan-A.json.
            artifact = root / "drafts" / f"plan-{draft}.json"
        if not artifact.is_file():
            raise ProjectError(f"Draft {draft} is missing at {artifact}. Save its plan there or supply --draft-file FILE.")
        before = artifact.stat()
        digest = hash_file(artifact)
        after = artifact.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ProjectError("Draft changed while hashing; retry after writes finish.")
        path = root / CHOICES_NAME
        state = _read(path)
        resolution = manifest.reference.resolution
        ref_sha = resolution.sha256 if resolution and resolution.state == "resolved" else None
        brief_sha = hash_file(root / "brief.json") if (root / "brief.json").is_file() else None
        identity = json.dumps([state["project_id"], draft, digest,
                               manifest.reference.value, ref_sha, brief_sha], separators=(",", ":"))
        event_id = "zing-choice-" + str(uuid5(NAMESPACE_URL, hashlib.sha256(identity.encode("utf-8")).hexdigest()))
        existing = state["receipts"].get(event_id)
        receipt = ChoiceReceipt.from_dict(existing) if existing else ChoiceReceipt(
            event_id, state["project_id"], draft, stored_path(artifact, root), digest,
            manifest.reference.value, ref_sha, brief_sha,
            datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        )
        note = uoink_bridge.redact(note) if note else note
        if note and note not in receipt.notes:
            receipt.notes.append(note)
        if share_choice:
            receipt.share_requested = True
        state["selected"] = event_id
        state["receipts"][event_id] = receipt.to_dict()
        # Commit the observed choice and consent BEFORE any network/spool call.
        _write(path, state)
        if share_choice:
            if manifest.reference.kind != "uoink":
                receipt.delivery = {"state": "unavailable", "reason": "No Uoink item reference; choice remains local."}
            else:
                try:
                    receipt.delivery = engagement.record_choice(
                        item_ref(receipt.reference), receipt.event_id, receipt.occurred_at)
                except (engagement.EngagementStorageError, ProjectError, OSError) as exc:
                    receipt.delivery = {"state": "pending", "reason": uoink_bridge.redact(str(exc))}
            state["receipts"][event_id] = receipt.to_dict()
            _write(path, state)
        return {"receipt_path": str(path), "receipt": receipt.to_dict(),
                "hint": "Observed draft choice saved. Nothing was published."}
