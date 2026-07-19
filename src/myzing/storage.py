"""Zing workspace storage: where breakdowns live on disk.

Layout (workspace root is ``~/.zing``, overridable via the ``ZING_HOME``
environment variable — read at call time, never cached at import):

    <root>/
      breakdowns/
        <slug>/
          breakdown.json      # the Breakdown, canonical
          breakdown.md        # human-readable render (optional)
          media.<ext>         # the analyzed media file (optional)

Rules this module enforces (the rest of the codebase relies on them):

- Storage owns slugs. ``slug_for()`` is deterministic: the same URL or the
  same file always maps to the same slug, so re-studying is an update, not
  a duplicate. No other lane invents slugs or paths.
- Re-study preserves judgment. ``save_breakdown()`` carries an existing
  ``judgment`` forward when the incoming Breakdown has none — judgment is
  the user's AI's work, Zing cannot regenerate it. The prior json is kept
  as ``breakdown.json.bak``.
- ``save_judgment()`` merges at the top level only: each top-level key is a
  section (e.g. "study") and is replaced wholesale. No deep merge.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

from myzing.schemas import Breakdown, StyleProfile

ENV_VAR = "ZING_HOME"

# F-15: per-context workspace override. The ZING_HOME env var is process-
# global, so mutating it (the old _workspace_override pattern in study/api)
# races under the MCP job pattern where studies run in worker threads. A
# ContextVar is isolated per thread/async context: set it with
# use_workspace() and every storage call in that context resolves against
# it — no env mutation, no cross-thread bleed.
_WORKSPACE_OVERRIDE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "zing_workspace_override", default=None
)

_SLUG_MAX = 80
_MEDIA_EXTS = (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v", ".ts")

# The slug contract (everything slug_for() produces): lowercase ascii
# letters/digits/hyphens, starting with a letter or digit. slug_for()'s
# longest possible output is ~90 chars (an 80-char sanitized stem plus a
# platform prefix or content hash); 100 leaves headroom without letting
# junk through.
SLUG_MAX_LEN = 100
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


class SlugError(ValueError):
    """A slug failed validation: path traversal attempt, characters outside
    the slug contract, or a value that resolves outside the workspace."""


def workspace_root() -> Path:
    """The Zing workspace directory (not created by this call).

    Resolution order: use_workspace() context override, then ZING_HOME,
    then ``~/.zing``.
    """
    ctx = _WORKSPACE_OVERRIDE.get()
    if ctx:
        return Path(ctx).expanduser()
    override = os.environ.get(ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".zing"


@contextmanager
def use_workspace(root: Path | str) -> Iterator[Path]:
    """Pin the workspace for the current thread/context (F-15).

    Thread-safe replacement for mutating ZING_HOME: other threads and the
    enclosing context are unaffected. Nests; restores on exit.
    """
    token = _WORKSPACE_OVERRIDE.set(str(root))
    try:
        yield Path(root)
    finally:
        _WORKSPACE_OVERRIDE.reset(token)


def breakdowns_root() -> Path:
    return workspace_root() / "breakdowns"


def profiles_root() -> Path:
    return workspace_root() / "profiles"


def _validate_name(name: str, root: Path, kind: str) -> str:
    """Shared name validator (F-02, SECURITY): slugs and profile names.

    Names are storage-owned, never paths. MCP tool arguments are
    AI-generated and may be influenced by untrusted video text, so every
    public name boundary must reject anything that could resolve outside
    its ``root``. Raises :class:`SlugError` (a ``ValueError``) unless
    ``name`` matches the slug contract AND ``root/name`` resolves strictly
    inside ``root``. Returns the name unchanged on success.
    """
    if not isinstance(name, str):
        raise SlugError(f"{kind} must be a string, got {type(name).__name__}")
    if not name.strip():
        raise SlugError(f"{kind} must not be empty")
    if len(name) > SLUG_MAX_LEN:
        raise SlugError(
            f"{kind} is too long ({len(name)} chars, max {SLUG_MAX_LEN})"
        )
    if "/" in name or "\\" in name:
        raise SlugError(f"{kind} must not contain path separators: {name!r}")
    if "." in name:
        # covers '.', '..', '..\\..'-style segments and hidden/dotted names;
        # slug_for() never emits a dot
        raise SlugError(f"{kind} must not contain '.': {name!r}")
    if (
        PurePosixPath(name).is_absolute()
        or PureWindowsPath(name).is_absolute()
        or PureWindowsPath(name).drive
    ):
        raise SlugError(f"{kind} must not be an absolute or drive path: {name!r}")
    if not _SLUG_RE.fullmatch(name):
        raise SlugError(
            f"{kind} {name!r} is outside the naming contract (lowercase "
            "letters, digits, and hyphens, starting with a letter or digit)"
        )
    # Belt and braces: even a contract-shaped name must land inside the
    # workspace once the filesystem has its say (symlinks, junctions, …).
    try:
        resolved = (root / name).resolve()
        resolved.relative_to(root.resolve())
    except ValueError:
        raise SlugError(
            f"{kind} {name!r} resolves outside its workspace directory"
        ) from None
    except OSError as e:
        raise SlugError(f"{kind} {name!r} cannot be resolved: {e}") from None
    return name


def validate_slug(slug: str) -> str:
    """The canonical breakdown-slug validator (F-02, SECURITY)."""
    return _validate_name(slug, breakdowns_root(), "slug")


def validate_profile_name(name: str) -> str:
    """Profile names follow the slug contract (S2: 'validate profile names
    like slugs') and must resolve inside profiles_root()."""
    return _validate_name(name, profiles_root(), "profile name")


def breakdown_dir(slug: str) -> Path:
    """The directory for ``slug``. Validates the slug (see ``validate_slug``);
    every path this module hands out funnels through here."""
    validate_slug(slug)
    return breakdowns_root() / slug


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------

def _sanitize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:_SLUG_MAX].strip("-") or "video"


def _hash8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def _file_slug(path: Path) -> str:
    stem = _sanitize(path.stem)
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(1024 * 1024)
        digest = _hash8(head + str(size).encode())
    except OSError:
        # Unreadable/missing file: still deterministic, keyed on the name.
        digest = _hash8(str(path.name).encode())
    return f"{stem}-{digest}"


def slug_for(url_or_path: str) -> str:
    """Deterministic slug for a video source (URL or local file path).

    URLs map to ``<platform>-<video id>`` when the id is recognizable
    (tiktok, youtube incl. shorts/youtu.be, instagram reel/post), else
    ``<domain>-<url hash>``. Local files map to ``<stem>-<content hash>``
    so the same file re-studied lands in the same place.
    """
    s = url_or_path.strip()
    parsed = urlparse(s)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        host = parsed.netloc.lower().removeprefix("www.")
        parts = [p for p in parsed.path.split("/") if p]

        if host.endswith("tiktok.com"):
            if "video" in parts:
                i = parts.index("video")
                if i + 1 < len(parts):
                    return f"tiktok-{_sanitize(parts[i + 1])}"
            if parts:  # vm.tiktok.com/<code> short links
                return f"tiktok-{_sanitize(parts[-1])}"
        elif host in ("youtu.be",) and parts:
            return f"youtube-{_sanitize(parts[0])}"
        elif host.endswith("youtube.com"):
            if parts and parts[0] in ("shorts", "embed", "live") and len(parts) > 1:
                return f"youtube-{_sanitize(parts[1])}"
            vid = parse_qs(parsed.query).get("v", [""])[0]
            if vid:
                return f"youtube-{_sanitize(vid)}"
        elif host.endswith("instagram.com"):
            if parts and parts[0] in ("reel", "reels", "p", "tv") and len(parts) > 1:
                return f"instagram-{_sanitize(parts[1])}"
        elif (
            host in ("x.com", "twitter.com")
            or host.endswith(".x.com")
            or host.endswith(".twitter.com")
        ):
            # /user/status/<id>, /i/status/<id> — same status id must map to
            # the same slug whether shared as x.com or twitter.com.
            if "status" in parts:
                i = parts.index("status")
                if i + 1 < len(parts):
                    return f"x-{_sanitize(parts[i + 1])}"

        domain = _sanitize(host.split(":")[0])
        return f"{domain}-{_hash8(s.encode())}"

    return _file_slug(Path(s))


# ---------------------------------------------------------------------------
# Media placement
# ---------------------------------------------------------------------------

def media_target(slug: str, ext: str) -> Path:
    """Where the media file for ``slug`` belongs (dir is created).

    Lane A downloads/copies to exactly this path: ``media.<ext>``.
    """
    ext = ext.lstrip(".").lower() or "mp4"
    d = breakdown_dir(validate_slug(slug))
    d.mkdir(parents=True, exist_ok=True)
    return d / f"media.{ext}"


def find_media(slug: str) -> Path | None:
    """The stored media file for ``slug``, or None if absent."""
    d = breakdown_dir(validate_slug(slug))
    if not d.is_dir():
        return None
    for p in sorted(d.iterdir()):
        if p.is_file() and p.stem == "media" and p.suffix.lower() in _MEDIA_EXTS:
            return p
    return None


def resolve_relpath(slug: str, rel: str) -> Path:
    """Absolute path for a breakdown-relative path (media_path, keyframes).

    The contract stores paths relative to the breakdown's own directory so a
    breakdown folder survives being moved or synced; this is the one place
    that joins them back. Absolute inputs pass through unchanged.
    """
    p = Path(rel)
    if p.is_absolute():
        return p
    return breakdown_dir(slug) / p


# ---------------------------------------------------------------------------
# Study job status (status.json in the slug dir)
# ---------------------------------------------------------------------------
# Binding B#2 ruling (2026-07-18): study runs as a background job; state
# lives ON DISK so a crashed helper leaves honest state, never an
# in-memory-only lie. States: running | done | failed.

def write_status_at(d: Path, **fields: Any) -> Path:
    """Merge fields into ``d/status.json`` (created if absent) — the
    generic on-disk job state used by study AND render jobs (S4).

    ATOMIC (main-red regression, 2026-07-19): ``write_text`` truncates
    before writing, so a concurrent reader could observe a torn file and
    treat the job as having no status at all (the D-4 retry loop made
    that window hittable in CI). Temp-file + ``os.replace`` means readers
    see either the old state or the new — never a partial one.
    """
    d.mkdir(parents=True, exist_ok=True)
    path = d / "status.json"
    current = read_status_at(d) or {}
    current.update(fields)
    payload = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
    import tempfile

    handle, tmp_name = tempfile.mkstemp(
        prefix=".status-", suffix=".json", dir=d
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(payload)
        # Windows: os.replace is denied while a reader momentarily holds
        # the destination open (no FILE_SHARE_DELETE in CPython's open).
        # Readers hold it for microseconds — retry briefly, then raise.
        import time as _time

        for attempt in range(50):
            try:
                os.replace(tmp_name, path)
                break
            except PermissionError:
                if attempt == 49:
                    raise
                _time.sleep(0.002)
    except OSError:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def read_status_at(d: Path) -> dict[str, Any] | None:
    """``d/status.json`` as a dict, or None when genuinely absent.

    Transient failures retry briefly (main-red regression, 2026-07-19):
    on Windows, opening the file during a concurrent ``os.replace`` can
    raise a sharing violation — that means "being updated", not "gone",
    and answering None there is how per-slug error detail once vanished
    from a failure report. FileNotFoundError stays an immediate None.
    """
    import time as _time

    path = d / "status.json"
    for attempt in range(20):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            if attempt == 19:
                return None  # honestly unreadable after ~40ms of trying
            _time.sleep(0.002)
    return None


def write_status(slug: str, **fields: Any) -> Path:
    """Merge fields into the slug's status.json (created if absent)."""
    return write_status_at(breakdown_dir(slug), **fields)


def read_status(slug: str) -> dict[str, Any] | None:
    """The slug's study status, or None when absent/unreadable."""
    return read_status_at(breakdown_dir(slug))


def renders_root() -> Path:
    return workspace_root() / "renders"


def render_dir(render_id: str) -> Path:
    """The directory for one render job (validated like a slug)."""
    _validate_name(render_id, renders_root(), "render id")
    return renders_root() / render_id


# ---------------------------------------------------------------------------
# Breakdown persistence
# ---------------------------------------------------------------------------

def save_breakdown(
    b: Breakdown, slug: str | None = None, markdown: str | None = None
) -> Path:
    """Write a Breakdown to the workspace; returns its directory.

    - ``slug`` defaults to ``slug_for(meta.source_url)``; an explicit slug
      is caller input and gets the full ``validate_slug`` treatment.
    - If a previous breakdown.json exists it is kept as breakdown.json.bak,
      and its ``judgment`` is carried forward when ``b.judgment`` is empty.
    - ``markdown``, when given, is written as breakdown.md.
    """
    slug = validate_slug(slug) if slug else slug_for(b.meta.source_url)
    d = breakdown_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    json_path = d / "breakdown.json"

    if json_path.exists():
        if not b.judgment:
            try:
                prior = json.loads(json_path.read_text(encoding="utf-8"))
                if prior.get("judgment"):
                    b.judgment = prior["judgment"]
            except (OSError, ValueError):
                pass  # corrupt prior file: nothing to preserve
        json_path.replace(d / "breakdown.json.bak")

    _write_breakdown_json(d, b)
    if markdown is not None:
        (d / "breakdown.md").write_text(markdown, encoding="utf-8")
    return d


def _write_breakdown_json(d: Path, b: Breakdown) -> None:
    """The one place breakdown.json is serialized — format can't drift."""
    (d / "breakdown.json").write_text(
        b.to_json(indent=2) + "\n", encoding="utf-8"
    )


def load_breakdown(slug: str) -> Breakdown:
    """Load a stored Breakdown. Raises FileNotFoundError with the looked-up
    path when the slug has no breakdown (the caller turns this into an
    actionable message)."""
    json_path = breakdown_dir(validate_slug(slug)) / "breakdown.json"
    if not json_path.is_file():
        raise FileNotFoundError(
            f"no breakdown for slug '{slug}' (looked in {json_path})"
        )
    return Breakdown.from_json(json_path.read_text(encoding="utf-8"))


def save_judgment(slug: str, judgment: dict[str, Any]) -> Breakdown:
    """Merge judgment into a stored Breakdown and persist it.

    Top-level keys are sections; each provided section replaces the stored
    one wholesale (no deep merge — deep merges rot silently). Returns the
    updated Breakdown.
    """
    if not isinstance(judgment, dict):
        raise TypeError(f"judgment must be a dict of sections, got {type(judgment).__name__}")
    validate_slug(slug)
    b = load_breakdown(slug)
    b.judgment.update(judgment)
    _write_breakdown_json(breakdown_dir(slug), b)
    return b


def list_breakdowns() -> list[dict[str, Any]]:
    """Index of stored breakdowns, one summary dict per slug, sorted by slug.

    Never raises on a bad entry: a directory whose breakdown.json is
    missing or corrupt yields ``{"slug": ..., "error": ...}`` so callers
    (MCP, CLI) can report it honestly instead of hiding the whole index.
    """
    root = breakdowns_root()
    if not root.is_dir():
        return []
    index: list[dict[str, Any]] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        try:
            validate_slug(d.name)
        except SlugError as e:
            # a hand-made or foreign directory: report it, never serve it
            index.append({"slug": d.name, "error": f"invalid slug: {e}"})
            continue
        json_path = d / "breakdown.json"
        if not json_path.is_file():
            status = read_status(d.name)
            if status and status.get("state") in ("running", "failed"):
                entry: dict[str, Any] = {"slug": d.name, "study": status["state"]}
                if status.get("phase"):
                    entry["phase"] = status["phase"]
                if status.get("error"):
                    entry["error"] = status["error"]
                index.append(entry)
            else:
                index.append({"slug": d.name, "error": "no breakdown.json"})
            continue
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            meta = raw.get("meta", {})
            index.append({
                "slug": d.name,
                "platform": meta.get("platform", ""),
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "duration": meta.get("duration", 0.0),
                "source_url": meta.get("source_url", ""),
                "shots": len(raw.get("shots", [])),
                "words": len(raw.get("words", [])),
                "has_media": find_media(d.name) is not None,
                "judgment_sections": sorted(raw.get("judgment", {})),
            })
        except (OSError, ValueError) as e:
            index.append({"slug": d.name, "error": f"unreadable breakdown.json: {e}"})
    return index

# ---------------------------------------------------------------------------
# StyleProfile persistence (S2): profiles/<name>/profile.json
# ---------------------------------------------------------------------------

def profile_dir(name: str) -> Path:
    """The directory for profile ``name`` (validated; see
    validate_profile_name). Every profile path funnels through here."""
    validate_profile_name(name)
    return profiles_root() / name


def save_profile(p: StyleProfile) -> Path:
    """Write a StyleProfile; returns its directory. An existing
    profile.json is kept as profile.json.bak (rebuilds are expected as
    the source set grows — never silently destroy the prior aggregate)."""
    d = profile_dir(p.name)
    d.mkdir(parents=True, exist_ok=True)
    json_path = d / "profile.json"
    if json_path.exists():
        json_path.replace(d / "profile.json.bak")
    json_path.write_text(p.to_json(indent=2) + "\n", encoding="utf-8")
    return d


def load_profile(name: str) -> StyleProfile:
    """Load a stored StyleProfile. Raises FileNotFoundError with the
    looked-up path when absent (callers turn this into an actionable
    message)."""
    json_path = profile_dir(name) / "profile.json"
    if not json_path.is_file():
        raise FileNotFoundError(
            f"no profile named '{name}' (looked in {json_path})"
        )
    return StyleProfile.from_json(json_path.read_text(encoding="utf-8"))


def list_profiles() -> list[dict[str, Any]]:
    """Index of stored profiles, one summary per name, sorted. Corrupt
    entries yield {"name", "error"} instead of hiding the whole index."""
    root = profiles_root()
    if not root.is_dir():
        return []
    index: list[dict[str, Any]] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        json_path = d / "profile.json"
        if not json_path.is_file():
            index.append({"name": d.name, "error": "no profile.json"})
            continue
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            index.append({
                "name": d.name,
                "genre": raw.get("genre", ""),
                "platform": raw.get("platform", ""),
                "sources": len(raw.get("source_slugs", [])),
                "unjudged_sources": len(raw.get("unjudged_source_slugs", [])),
                "judged_sections": sorted(
                    k for k in raw.get("judged", {}) if k != "_meta"
                ),
                "warnings": len(raw.get("warnings", [])),
            })
        except (OSError, ValueError) as e:
            index.append({"name": d.name, "error": f"unreadable profile.json: {e}"})
    return index
