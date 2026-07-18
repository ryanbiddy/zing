"""Storage: slugs, workspace layout, persistence, judgment preservation."""

from __future__ import annotations

import json

import pytest

from myzing import storage
from myzing.schemas import Breakdown, Shot, VideoMeta


def make_breakdown(url: str = "https://www.tiktok.com/@a/video/123") -> Breakdown:
    return Breakdown(
        meta=VideoMeta(source_url=url, platform="tiktok", title="t", duration=12.0),
        shots=[Shot(index=0, start=0.0, end=12.0)],
    )


# -- workspace root ----------------------------------------------------------

def test_workspace_root_env_override(zing_workspace):
    assert storage.workspace_root() == zing_workspace


def test_workspace_root_defaults_to_home(monkeypatch):
    monkeypatch.delenv(storage.ENV_VAR, raising=False)
    root = storage.workspace_root()
    assert root.name == ".zing"


# -- slugs -------------------------------------------------------------------

def test_slug_tiktok_video_id():
    assert (
        storage.slug_for("https://www.tiktok.com/@user/video/7301234567890123456")
        == "tiktok-7301234567890123456"
    )


def test_slug_tiktok_short_link():
    assert storage.slug_for("https://vm.tiktok.com/ZMabc123/") == "tiktok-zmabc123"


def test_slug_youtube_forms_agree():
    expected = "youtube-dqw4w9wgxcq"
    assert storage.slug_for("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == expected
    assert storage.slug_for("https://youtu.be/dQw4w9WgXcQ") == expected
    assert storage.slug_for("https://www.youtube.com/shorts/dQw4w9WgXcQ") == expected


def test_slug_x_status_dedupes_across_domains():
    """B-Q4: the same status shared as x.com or twitter.com is one video."""
    expected = "x-1815234567890123456"
    assert (
        storage.slug_for("https://x.com/somebody/status/1815234567890123456")
        == expected
    )
    assert (
        storage.slug_for("https://twitter.com/somebody/status/1815234567890123456")
        == expected
    )
    assert (
        storage.slug_for(
            "https://mobile.twitter.com/somebody/status/1815234567890123456"
        )
        == expected
    )
    assert (
        storage.slug_for("https://x.com/i/status/1815234567890123456") == expected
    )
    assert (
        storage.slug_for(
            "https://x.com/somebody/status/1815234567890123456?s=20&t=abc"
        )
        == expected
    )


def test_slug_x_non_status_urls_fall_back_deterministically():
    profile = "https://x.com/somebody"
    slug = storage.slug_for(profile)
    assert slug.startswith("x-com-")
    assert slug == storage.slug_for(profile)


def test_slug_instagram_reel():
    assert storage.slug_for("https://www.instagram.com/reel/C1a_B2c/") == "instagram-c1a-b2c"


def test_slug_unknown_url_uses_domain_and_hash():
    slug = storage.slug_for("https://example.com/some/video?x=1")
    assert slug.startswith("example-com-")
    assert slug == storage.slug_for("https://example.com/some/video?x=1")


def test_slug_local_file_deterministic_and_content_keyed(tmp_path):
    f = tmp_path / "My Raw Take 01.mp4"
    f.write_bytes(b"fake video bytes")
    slug = storage.slug_for(str(f))
    assert slug.startswith("my-raw-take-01-")
    assert slug == storage.slug_for(str(f))
    f.write_bytes(b"different bytes entirely")
    assert slug != storage.slug_for(str(f))


def test_slug_missing_file_still_deterministic(tmp_path):
    p = str(tmp_path / "ghost.mp4")
    assert storage.slug_for(p) == storage.slug_for(p)


# -- use_workspace (F-15) ----------------------------------------------------

def test_use_workspace_beats_env_and_restores(zing_workspace, tmp_path):
    other = tmp_path / "other-root"
    assert storage.workspace_root() == zing_workspace
    with storage.use_workspace(other):
        assert storage.workspace_root() == other
        with storage.use_workspace(tmp_path / "nested"):
            assert storage.workspace_root() == tmp_path / "nested"
        assert storage.workspace_root() == other
    assert storage.workspace_root() == zing_workspace


def test_use_workspace_is_thread_isolated(zing_workspace, tmp_path):
    import threading

    seen: dict[str, object] = {}
    ready = threading.Barrier(2, timeout=10)

    def worker(name: str, root):
        with storage.use_workspace(root):
            ready.wait()  # both threads inside their overrides at once
            seen[name] = storage.workspace_root()

    t1 = threading.Thread(target=worker, args=("a", tmp_path / "root-a"))
    t2 = threading.Thread(target=worker, args=("b", tmp_path / "root-b"))
    t1.start(); t2.start(); t1.join(10); t2.join(10)
    assert seen["a"] == tmp_path / "root-a"
    assert seen["b"] == tmp_path / "root-b"
    assert storage.workspace_root() == zing_workspace  # main thread untouched


# -- persistence -------------------------------------------------------------

def test_save_and_load_roundtrip(zing_workspace):
    b = make_breakdown()
    d = storage.save_breakdown(b, markdown="# hi\n")
    assert d == storage.breakdown_dir("tiktok-123")
    assert (d / "breakdown.md").read_text(encoding="utf-8") == "# hi\n"
    loaded = storage.load_breakdown("tiktok-123")
    assert loaded.to_dict() == b.to_dict()


def test_load_missing_slug_raises_with_path(zing_workspace):
    try:
        storage.load_breakdown("nope")
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError as e:
        assert "nope" in str(e) and "breakdown.json" in str(e)


def test_resave_keeps_bak_and_preserves_judgment(zing_workspace):
    b = make_breakdown()
    storage.save_breakdown(b)
    storage.save_judgment("tiktok-123", {"study": {"hook_type": "question"}})

    fresh = make_breakdown()  # re-study: no judgment on the new measurement
    d = storage.save_breakdown(fresh)
    assert (d / "breakdown.json.bak").exists()
    loaded = storage.load_breakdown("tiktok-123")
    assert loaded.judgment["study"]["hook_type"] == "question"


def test_save_judgment_replaces_section_wholesale(zing_workspace):
    storage.save_breakdown(make_breakdown())
    storage.save_judgment("tiktok-123", {"study": {"a": 1, "b": 2}, "notes": {"x": 1}})
    updated = storage.save_judgment("tiktok-123", {"study": {"c": 3}})
    assert updated.judgment["study"] == {"c": 3}  # no deep merge
    assert updated.judgment["notes"] == {"x": 1}  # untouched section survives


def test_save_judgment_rejects_non_dict(zing_workspace):
    storage.save_breakdown(make_breakdown())
    try:
        storage.save_judgment("tiktok-123", "great video")  # type: ignore[arg-type]
        raise AssertionError("expected TypeError")
    except TypeError as e:
        assert "dict" in str(e)


# -- F-02: slug validation (path traversal, SECURITY) -------------------------
# Regression tests for S1-FIXLIST F-02 / S1-REVIEW-lane-c finding 1:
# caller-supplied slugs must never resolve outside breakdowns_root().

TRAVERSAL_SLUGS = [
    "../../escape",              # POSIX relative traversal
    "..\\..\\escape",            # Windows relative traversal
    "../escape",
    "..",
    ".",
    "breakdowns/../../escape",   # traversal hidden behind a normal segment
    "/etc/passwd",               # POSIX absolute
    "/tmp/escape",
    "C:\\Windows\\escape",       # drive-letter absolute (backslashes)
    "C:/Windows/escape",         # drive-letter absolute (forward slashes)
    "c:evil",                    # drive-relative
    "\\\\server\\share\\escape", # UNC
    "nested/inside",             # embedded POSIX separator
    "nested\\inside",            # embedded Windows separator
    ".hidden",                   # dot segment
    "trailing.",
    "has.dot",
    "",                          # empty
    "   ",                       # whitespace-only
    "a" * 200,                   # oversize
    "UPPER-Case",                # outside the slug character contract
    "spaced slug",
]

_BOUNDARY_TRAVERSALS = [
    "../../escape", "..\\..\\escape", "/etc/passwd", "C:\\Windows\\escape",
]


@pytest.mark.parametrize("bad", TRAVERSAL_SLUGS)
def test_validate_slug_rejects_traversal_and_junk(zing_workspace, bad):
    with pytest.raises(storage.SlugError):
        storage.validate_slug(bad)


@pytest.mark.parametrize("bad", _BOUNDARY_TRAVERSALS)
def test_read_boundaries_reject_traversal(zing_workspace, bad):
    for fn in (
        storage.breakdown_dir,
        storage.load_breakdown,
        storage.find_media,
        storage.read_status,
    ):
        with pytest.raises(storage.SlugError):
            fn(bad)


@pytest.mark.parametrize("bad", _BOUNDARY_TRAVERSALS)
def test_write_boundaries_reject_traversal_and_touch_nothing(
    zing_workspace, tmp_path, bad
):
    # With ZING_HOME at tmp_path/"zing-home", breakdowns/../../escape
    # resolves to tmp_path/"escape" — the review's repro target.
    outside = tmp_path / "escape"

    with pytest.raises(storage.SlugError):
        storage.save_breakdown(make_breakdown(), slug=bad)
    with pytest.raises(storage.SlugError):
        storage.save_judgment(bad, {"study": {"hook_type": "question"}})
    with pytest.raises(storage.SlugError):
        storage.media_target(bad, "mp4")
    with pytest.raises(storage.SlugError):
        storage.write_status(bad, state="running")

    assert not outside.exists()  # nothing escaped the workspace
    root = storage.breakdowns_root()
    assert not root.exists() or list(root.iterdir()) == []  # no junk inside either


def test_validate_slug_accepts_everything_slug_for_produces(zing_workspace, tmp_path):
    sources = [
        "https://www.tiktok.com/@user/video/7301234567890123456",
        "https://vm.tiktok.com/ZMabc123/",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.instagram.com/reel/C1a_B2c/",
        "https://example.com/some/video?x=1",
        "https://x.com/creator/status/1234567890",
        "https://" + "a" * 300 + ".example.com/v/1",  # oversize host still caps
    ]
    f = tmp_path / "My Raw Take 01.mp4"
    f.write_bytes(b"fake video bytes")
    sources.append(str(f))
    sources.append(str(tmp_path / "Ghost Clip.mp4"))  # missing file form

    for src in sources:
        slug = storage.slug_for(src)
        assert storage.validate_slug(slug) == slug, src


def test_list_breakdowns_reports_invalid_dir_names_honestly(zing_workspace):
    root = storage.breakdowns_root()
    root.mkdir(parents=True)
    (root / "Weird Name.dir").mkdir()
    entries = storage.list_breakdowns()
    assert len(entries) == 1
    assert entries[0]["slug"] == "Weird Name.dir"
    assert "error" in entries[0]


# -- media -------------------------------------------------------------------

def test_media_target_and_find(zing_workspace):
    target = storage.media_target("tiktok-123", ".MP4")
    assert target.name == "media.mp4"
    assert storage.find_media("tiktok-123") is None
    target.write_bytes(b"x")
    assert storage.find_media("tiktok-123") == target


# -- index -------------------------------------------------------------------

def test_list_breakdowns_empty_workspace(zing_workspace):
    assert storage.list_breakdowns() == []


def test_list_breakdowns_index_and_honest_errors(zing_workspace):
    storage.save_breakdown(make_breakdown())
    storage.save_judgment("tiktok-123", {"study": {"ok": True}})
    bad = storage.breakdown_dir("broken-entry")
    bad.mkdir(parents=True)
    (bad / "breakdown.json").write_text("{not json", encoding="utf-8")

    index = storage.list_breakdowns()
    by_slug = {e["slug"]: e for e in index}
    good = by_slug["tiktok-123"]
    assert good["platform"] == "tiktok"
    assert good["shots"] == 1
    assert good["judgment_sections"] == ["study"]
    assert "error" in by_slug["broken-entry"]


def test_index_survives_extra_files(zing_workspace):
    storage.save_breakdown(make_breakdown())
    d = storage.breakdown_dir("tiktok-123")
    (d / "frames").mkdir()
    (d / "notes.txt").write_text("misc", encoding="utf-8")
    assert json.loads((d / "breakdown.json").read_text(encoding="utf-8"))
    assert storage.list_breakdowns()[0]["slug"] == "tiktok-123"
