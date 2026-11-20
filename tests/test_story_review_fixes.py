"""Regressions from the review of story preparation, checks and rendering."""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from myzing.story import StoryError, command, contract, heads, images, jobs, layout, outro, receipt, render
from test_story_audio import tone
from test_story_command import line_files
from test_story_contract import story, timings
from test_story_render import story_folder


def save(directory, filename, data):
    (directory / filename).write_text(json.dumps(data), encoding="utf-8")


def photo(directory, name="source.ppm"):
    (directory / name).write_bytes(b"P6\n2 2\n255\n" + b"abc" * 4)
    return {"path": name, "source_url": "https://example.test/photo", "credit": "Test artist", "license": "CC0"}


def copy_pixels(source, output, **kwargs):
    output.parent.mkdir(exist_ok=True)
    shutil.copyfile(source, output)


def capture_one(data, scratch, frames):
    frames.mkdir()
    (frames / "00001.jpg").write_bytes(b"captured")


@pytest.mark.parametrize("element", ["card", "head"])
def test_comic_checks_screen_caption_band(element):
    value = story()
    panel = value["panels"][0]
    panel.update(cards=[], actors=[])
    if element == "card":
        panel["cards"] = [{"kind": "tag", "text": "Ink", "x": 150, "y": 1745, "at": "hook"}]
    else:
        panel["actors"] = [{"who": "ada", "x": 150, "y": 1900, "scale": .19}]
    assert contract.check(value, look="cutout") == []
    assert any("caption band" in error for error in contract.check(value, look="comic"))


@pytest.mark.parametrize("asset,change", [
    ("heads", "order"), ("portraits", "content"), ("heads", "face"),
    ("images", "path"), ("images", "content"), ("images", "box"),
])
def test_stale_prepared_asset_names_command(tmp_path, monkeypatch, asset, change):
    from myzing.story import portraits

    value = story()
    first, second = photo(tmp_path), photo(tmp_path, "second.ppm")
    if asset == "images":
        value["images"] = {"poster": {**first, "cut": "sticker"}}
        monkeypatch.setattr(images, "cut_sticker", copy_pixels)
        images.generate(tmp_path, value)
    else:
        value["cast"]["ada"]["photos"] = [first, second]
        value["look"] = "headline" if asset == "portraits" else "cutout"
        monkeypatch.setattr(heads, "cut_head", copy_pixels)
        monkeypatch.setattr(portraits, "crop_portrait", copy_pixels)
        heads.generate(tmp_path, value)
    save(tmp_path, "timings.json", {**timings(), "synthetic": False})
    save(tmp_path, "story.json", value)
    monkeypatch.setattr(render, "capture", capture_one)
    assert render.render(tmp_path, stills=[1])[0].is_file()
    if change == "content":
        (tmp_path / first["path"]).write_bytes(b"replacement bytes")
    elif change == "order":
        value["cast"]["ada"]["photos"].reverse()
    elif change == "face":
        first["face"] = [0, 0, 1, 1]
    elif change == "path":
        value["images"]["poster"].update(second, credit="Second artist")
    else:
        value["images"]["poster"]["box"] = [0, 0, 1, 1]
    save(tmp_path, "story.json", value)
    step = "images" if asset == "images" else "heads"
    with pytest.raises(StoryError, match=f"zing story {step}"):
        render.render(tmp_path, stills=[1])


@pytest.mark.parametrize("look,filename", [("cutout", "ada-0.png"), ("headline", "ada-0-portrait.jpg")])
def test_prepared_cast_path_is_checked_before_capture(tmp_path, monkeypatch, look, filename):
    from myzing.story import portraits

    value = story()
    value["cast"]["ada"]["photos"] = [photo(tmp_path)]
    value["look"] = look
    monkeypatch.setattr(heads, "cut_head", copy_pixels)
    monkeypatch.setattr(portraits, "crop_portrait", copy_pixels)
    heads.generate(tmp_path, value)
    save(tmp_path, "story.json", value)
    save(tmp_path, "timings.json", {**timings(), "synthetic": False})
    # Model a path refused by the resolver, using only files inside the fixture.
    prepared = tmp_path / "heads" / filename
    original = Path.resolve

    def refuse(path, *args, **kwargs):
        if path == prepared:
            raise StoryError("prepared path refused")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", refuse)
    monkeypatch.setattr(render, "capture", capture_one)
    with pytest.raises(StoryError, match="prepared path refused"):
        render.render(tmp_path, stills=[1])
    if look == "cutout":
        with pytest.raises(StoryError, match="prepared path refused"):
            layout._aspects(value["cast"]["ada"], "ada", tmp_path)


@pytest.mark.parametrize("entry", ["voice", "build", "job"])
def test_voice_can_resolve_mixed_cues(tmp_path, monkeypatch, entry):
    value = story()
    value["beats"][0]["lines"].append({"text": "The next line."})
    early = {"kind": "tag", "text": "One", "x": 50, "y": 200, "at": "hook", "until": "hook+1.5"}
    value["panels"][0].update(actors=[], cards=[early, {**early, "at": "hook:1", "until": "first-job"}])
    save(tmp_path, "story.json", value)
    lines = line_files(tmp_path, value)
    tone(lines / "hook-0.wav", duration=2.5, rate=1000)
    if entry == "voice":
        assert command.run(["voice", str(tmp_path), "--lines-dir", str(lines)]) == 0
    else:
        def finish(directory, **kwargs):
            contract.load(directory)
            output = directory / "story.mp4"
            output.touch()
            return output

        monkeypatch.setattr(render, "render", finish)
        if entry == "build":
            command.build(tmp_path, lines_dir=lines)
        else:
            started = []
            start_thread = threading.Thread.start

            def start(thread):
                started.append(thread)
                start_thread(thread)

            monkeypatch.setattr(threading.Thread, "start", start)
            assert jobs.start(tmp_path, lines_dir=lines)["status"] == "started"
            started[0].join(timeout=5)
            assert jobs.status(tmp_path)["state"] == "done"
    assert (tmp_path / "timings.json").is_file()
    assert command.check(tmp_path) == []
    early["until"] = "hook+3"
    save(tmp_path, "story.json", value)
    assert any("covers" in error for error in command.check(tmp_path))


def test_locked_browser_cleanup_preserves_render(tmp_path, monkeypatch):
    story_folder(tmp_path)
    original = tempfile.TemporaryDirectory._rmtree

    def cleanup(name, ignore_errors=False, **kwargs):
        original(name, ignore_errors=ignore_errors, **kwargs)
        if Path(name).name.startswith(".story-render-") and not ignore_errors:
            raise PermissionError("browser profile still open")

    monkeypatch.setattr(tempfile.TemporaryDirectory, "_rmtree", staticmethod(cleanup))
    monkeypatch.setattr(render, "capture", capture_one)
    assert render.render(tmp_path, stills=[.3])[0].read_bytes() == b"captured"


def test_status_reader_cannot_turn_done_into_failed(tmp_path, monkeypatch):
    (tmp_path / "story.json").touch()
    monkeypatch.setattr(command, "build", lambda *a, **kw: {"rendered": "story.mp4"})
    replace = os.replace

    def windows_replace(source, target):
        # A polling thread can open the status file only if it can take _LOCK.
        if Path(target).name == jobs.STATUS_FILE:
            def poll():
                if jobs._LOCK.acquire(blocking=False):
                    reader_open.set()
                    jobs._LOCK.release()

            reader_open = threading.Event()
            thread = threading.Thread(target=poll)
            thread.start()
            thread.join()
            if reader_open.is_set():
                raise PermissionError("sharing violation")
        return replace(source, target)

    monkeypatch.setattr(os, "replace", windows_replace)
    jobs._run(tmp_path, {})
    assert jobs.status(tmp_path)["state"] == "done"


@pytest.mark.parametrize("flag", ["missing", None, "true"])
def test_only_declared_human_lines_drop_ai_credit(tmp_path, flag):
    value, timing = story(), timings()
    timing.pop("synthetic", None)
    if flag != "missing":
        timing["synthetic"] = flag
    assert any("synthetic" in message for message in contract.check_timings(value, timing))
    assert "narration is an AI voice" in outro.credit_lines(value, timing)
    save(tmp_path, "story.json", value)
    save(tmp_path, "timings.json", timing)
    output = tmp_path / "story.mp4"
    output.touch()
    result = receipt.write(tmp_path, output)
    assert json.loads(result.read_text(encoding="utf-8"))["voice"]["synthetic"] is True


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
@pytest.mark.parametrize("directory,name,orientation", [
    ("plain", "phone.jpg", 6), ("plain", "phone.jpg", 8),
    ("100% done", "50%20off.jpg", 1), ("take%03d", "take%03d.jpg", 1),
])
def test_prepare_literal_phone_photo(tmp_path, directory, name, orientation):
    Image = pytest.importorskip("PIL.Image")
    folder = tmp_path / directory
    folder.mkdir()
    source, target = folder / name, folder / "prepared.png"
    original = Image.new("RGB", (40, 20), "red")
    original.paste("blue", (20, 0, 40, 20))
    exif = original.getexif()
    exif[274] = orientation
    original.save(source, exif=exif)
    images._photo(source, target)
    with Image.open(target) as prepared:
        assert prepared.size == ((20, 40) if orientation in (6, 8) else (40, 20))
        red, _, blue = prepared.convert("RGB").getpixel((5, 5))
        assert (red > blue) == (orientation != 8)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
def test_story_encodes_in_percent_folder(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    folder = tmp_path / "100% done"
    folder.mkdir()
    story_folder(folder)

    def frames_for_encoder(data, scratch, frames):
        frames.mkdir()
        frame = Image.new("RGB", (32, 32), "blue")
        for i in range(math.ceil(data["timings"]["duration"] * render.FPS)):
            frame.save(frames / f"{i + 1:05d}.jpg")

    monkeypatch.setattr(render, "capture", frames_for_encoder)
    assert render.render(folder, no_sfx=True).stat().st_size > 0


@pytest.mark.parametrize("element", ["card", "head"])
def test_cutout_outro_checks_art_visible_before_speech_ends(element):
    value, timing = story(), timings()
    timing["synthetic"] = False
    last = timing["beats"][-1]
    last["lines"][0]["end"] = last["end"] = timing["outro_start"] - .05
    panel = {"from": "outro"}
    if element == "card":
        panel["cards"] = [{"kind": "tag", "text": "Credits", "x": 20, "y": 1580, "at": "outro-0.3"}]
    else:
        panel["actors"] = [{"who": "ada", "x": 40, "y": 1900, "scale": .4}]
    value["panels"].append(panel)
    assert any("caption band" in error for error in contract.check(value, timings=timing))
    if element == "card":
        panel["cards"][0]["at"] = "outro+0.1"
    else:
        panel["actors"][0]["enter"] = "outro+0.1"
    assert contract.check(value, timings=timing) == []


@pytest.mark.parametrize("source", ["heads/ada-0.png", "heads/ada-0-portrait.jpg", "heads/sheet.png", "missing.ppm"])
def test_heads_preflight_preserves_originals(tmp_path, monkeypatch, source):
    from myzing.story import portraits

    (tmp_path / "heads").mkdir()
    first = photo(tmp_path)
    second = {**first, "path": source}
    original = tmp_path / source
    if source != "missing.ppm":
        original.write_bytes(b"original")
    calls = []
    monkeypatch.setattr(heads, "cut_head", lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(portraits, "crop_portrait", lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(heads, "_write_sheet", lambda *a, **kw: calls.append(a))
    with pytest.raises(StoryError, match="original|missing"):
        heads.generate(tmp_path, {"cast": {"ada": {"photos": [first, second]}}}, sheet=True)
    assert calls == []
    if source != "missing.ppm":
        assert original.read_bytes() == b"original"


@pytest.mark.parametrize("step", ["images", "voice"])
def test_preparation_accepts_headline_override(tmp_path, step):
    value = story()
    del value["panels"]
    save(tmp_path, "story.json", value)
    options = ["--lines-dir", str(line_files(tmp_path, value))] if step == "voice" else []
    assert command.run([step, str(tmp_path), "--look", "headline", *options]) == 0
    assert json.loads((tmp_path / "story.json").read_text(encoding="utf-8")) == value


def test_thin_sticker_has_actionable_error():
    cv2, np = pytest.importorskip("cv2"), pytest.importorskip("numpy")
    alpha = np.full((heads.HEAD_SIZE, 1), 255, dtype=np.uint8)
    with pytest.raises(StoryError, match="subject|foreground"):
        heads._paper_sticker(np.zeros((*alpha.shape, 3), np.uint8), alpha, cv2, np)
