"""Phone post kits with local files and no external calls."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from myzing.channels import command, kit, queue, registry, tick
from myzing.factory import pipeline

from test_channels_review_fixes import NOW, channel, episode, offline


@pytest.fixture
def phone(channel, tmp_path):
    channel["phone_folder"] = str(tmp_path / "phone")
    registry.save(channel)
    return tmp_path / "phone" / f"{channel['slug']}-kits"


@pytest.fixture
def queued(channel):
    project = episode(channel)
    assert queue.build(channel["slug"], NOW)["added"] == 1
    return project


def test_phone_kit_has_all_files_marker_and_relative_video(channel, phone, queued, tmp_path):
    result = kit.kit(channel["slug"], tmp_path / "custom")
    source = Path(result["kits"][0])
    folder = phone / source.name
    assert result["phone"] == str(phone / "index.html") and not result["warnings"]
    assert {p.name for p in folder.iterdir()} == {"video.mp4", "post.json", ".zing-kit",
                                               *[f"{field}.txt" for field in kit.TEXTS]}
    for path in source.iterdir():
        assert (folder / path.name).read_bytes() == path.read_bytes()
    marker = pipeline._read(folder / ".zing-kit")
    for name in ("video.mp4", "post.json"):
        stat = (source / name).stat()
        assert marker[name] == {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    page = (phone / "index.html").read_text(encoding="utf-8")
    assert page.count("<video ") == 1 and f'src="{folder.name}/video.mp4"' in page
    assert "Upload these files yourself." in page and page.count("data-copy=") == 6
    assert str(source) not in page and source.as_uri() not in page
    assert queue.read(channel["slug"])[0]["status"] == "kit"


def test_unchanged_phone_kit_is_not_copied(channel, phone, queued, monkeypatch):
    result = kit.kit(channel["slug"])
    folder = phone / Path(result["kits"][0]).name
    video = folder / "video.mp4"
    stat = video.stat()
    os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns - 10_000_000_000))
    before = {p.name: p.stat().st_mtime_ns for p in folder.iterdir()}
    monkeypatch.setattr(shutil, "copyfile", lambda *a, **kw: pytest.fail("unchanged kit was copied"))
    result = kit.kit(channel["slug"])
    assert result["made"] == 0 and not result["warnings"]
    assert result["phone"] == str(phone / "index.html")
    assert {p.name: p.stat().st_mtime_ns for p in folder.iterdir()} == before


@pytest.mark.parametrize("name", ["video.mp4", "post.json"])
@pytest.mark.parametrize("change", ["size", "mtime"])
def test_changed_source_kit_is_copied(channel, phone, queued, name, change):
    result = kit.kit(channel["slug"])
    source = Path(result["kits"][0])
    folder = phone / source.name
    video = folder / "video.mp4"
    stat = video.stat()
    os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns - 10_000_000_000))
    before = video.stat().st_mtime_ns
    path = source / name
    stat = path.stat()
    if change == "size":
        path.write_bytes(path.read_bytes() + b" ")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    else:
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
    result = kit.kit(channel["slug"])
    assert result["made"] == 0 and not result["warnings"]
    assert video.stat().st_mtime_ns != before
    assert (folder / name).read_bytes() == path.read_bytes()
    stat = path.stat()
    assert pipeline._read(folder / ".zing-kit")[name] == {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


@pytest.mark.parametrize("status", ["posted", "skipped", "gone"])
def test_finished_phone_kits_are_removed(channel, phone, queued, status):
    result = kit.kit(channel["slug"])
    source = Path(result["kits"][0])
    row, = queue.read(channel["slug"])
    if status == "gone":
        queue.write(channel["slug"], [])
    else:
        queue.mark(channel["slug"], row["id"], status)
    result = kit.kit(channel["slug"])
    assert result["phone"] == str(phone / "index.html") and not result["warnings"]
    assert not (phone / source.name).exists() and source.is_dir()
    assert "<video " not in (phone / "index.html").read_text(encoding="utf-8")


def test_unapproved_queued_clip_has_no_phone_kit(channel, phone, queued):
    pipeline._write(queued / "ratings.json", {"clip01": {"v": "no"}})
    result = kit.kit(channel["slug"])
    assert result["made"] == 0 and "episode/clip01" in result["blocked"]
    assert not result["warnings"] and result["phone"] == str(phone / "index.html")
    assert {p.name for p in phone.iterdir()} == {"index.html"}


def test_unmarked_folder_and_file_are_left_alone(channel, phone, queued):
    result = kit.kit(channel["slug"])
    kept = phone / "keep"
    kept.mkdir()
    (kept / "video.mp4").write_bytes(b"personal video")
    (phone / "notes.txt").write_text("Keep this", encoding="utf-8")
    queue.mark(channel["slug"], "episode/clip01", "skipped")
    assert not kit.kit(channel["slug"])["warnings"]
    assert not (phone / Path(result["kits"][0]).name).exists()
    assert {p.name for p in kept.iterdir()} == {"video.mp4"}
    assert (kept / "video.mp4").read_bytes() == b"personal video"
    assert (phone / "notes.txt").read_text(encoding="utf-8") == "Keep this"


def test_unmarked_kit_is_not_replaced(channel, phone, queued):
    source = Path(kit.kit(channel["slug"])["kits"][0])
    folder = phone / source.name
    (folder / ".zing-kit").unlink()
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    (source / "video.mp4").write_bytes(b"new video")
    result = kit.kit(channel["slug"])
    assert result["phone"] is None and ".zing-kit" in result["warnings"][0]
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["copy", "rename"])
def test_failed_mirror_keeps_old_kit_and_retries(channel, phone, queued, monkeypatch, existing, failure):
    before = None
    if existing:
        source = Path(kit.kit(channel["slug"])["kits"][0])
        before = {p.name: p.read_bytes() for p in (phone / source.name).iterdir()}
        (source / "video.mp4").write_bytes(b"new video")
    copy, rename = shutil.copyfile, Path.rename

    def copyfile(src, dest, *args, **kwargs):
        if failure == "copy" and phone in Path(dest).parents and Path(dest).name == "instagram.txt":
            Path(dest).write_bytes(b"partial")
            raise OSError("copy failed")
        return copy(src, dest, *args, **kwargs)

    def move(src, dest):
        if src.name == "ready" and src.parent.parent == phone:
            assert {p.name for p in src.iterdir()} == {"video.mp4", "post.json", ".zing-kit",
                                                     *[f"{field}.txt" for field in kit.TEXTS]}
            if failure == "rename":
                raise OSError("rename failed")
        return rename(src, dest)

    monkeypatch.setattr(shutil, "copyfile", copyfile)
    monkeypatch.setattr(Path, "rename", move)
    result = kit.kit(channel["slug"])
    row, = queue.read(channel["slug"])
    folder = phone / Path(row["kit"]).name
    assert row["status"] == "kit" and result["phone"] is None
    assert result["warnings"] == [f"phone_folder {failure} failed"]
    assert not list(phone.glob(".kit-*"))
    if existing:
        assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    else:
        assert not folder.exists()
    monkeypatch.setattr(shutil, "copyfile", copy)
    monkeypatch.setattr(Path, "rename", rename)
    result = kit.kit(channel["slug"])
    assert result["phone"] == str(phone / "index.html") and not result["warnings"]
    assert (folder / "video.mp4").read_bytes() == (Path(row["kit"]) / "video.mp4").read_bytes()


def test_unwritable_phone_folder_warns_without_failing_tick(channel, phone, queued, monkeypatch):
    mkdir = Path.mkdir

    def denied(path, *args, **kwargs):
        if path == phone:
            raise PermissionError("phone folder is read only")
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", denied)
    result = kit.kit(channel["slug"])
    assert result["made"] == 1 and result["phone"] is None and not result["blocked"]
    assert result["warnings"] == ["phone_folder phone folder is read only"]
    assert Path(result["index"]).is_file()
    pipeline._write(queued / "status.json", {"state": "done"})
    channel["publish"]["youtube"] = "off"
    channel.pop("youtube")
    registry.save(channel)
    result = tick.run([channel["slug"]], now=NOW, watch_fn=lambda *a, **kw: {"found": 0, "started": 0})
    assert result["exit_code"] == 0 and not result["channels"][channel["slug"]]["errors"]


def test_kit_command_prints_phone_index(channel, phone, queued, capsys):
    assert command.run(["kit", channel["slug"]]) == 0
    assert json.loads(capsys.readouterr().out)["phone"] == str(phone / "index.html")


def test_without_phone_folder_has_no_mirror(channel, queued, tmp_path):
    result = kit.kit(channel["slug"])
    assert result["made"] == 1 and result["phone"] is None and not result["warnings"]
    assert not list(tmp_path.rglob(f"{channel['slug']}-kits"))
