"""Storage: slugs, workspace layout, persistence, judgment preservation."""

from __future__ import annotations

import json

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
