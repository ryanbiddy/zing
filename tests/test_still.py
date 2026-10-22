"""Generated-photo acceptance tests. Every still operation is socket-blocked."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = ImageDraw = None

from myzing import cli, mcp_server
from myzing.layout.detector import LayoutError
from myzing.layout.types import Box, Detection
from myzing.memes import MemeError
from myzing.memes.render import ASPECTS
from myzing.memes.validate import check_texts
from myzing.still import api, inventory as inv
from myzing.still.models import StillIndex
from myzing.still.placement import output_faces, place

pytestmark = pytest.mark.skipif(Image is None, reason="install myzing[memes] for render tests")


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def blocked(*args, **kwargs):
        raise AssertionError("still workflow attempted network access")

    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, blocked)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, blocked)

    def absent(*args, **kwargs):
        raise LayoutError("test: detector unavailable")

    monkeypatch.setattr(inv, "YuNetDetector", absent)


@pytest.fixture
def photos(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    for name, size, color in [("desk.png", (640, 480), "#426980"),
                               ("portrait.jpg", (300, 600), "#cd9845")]:
        image = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((size[0] * .3, size[1] * .4, size[0] * .7, size[1] * .7), fill="#eee5d4")
        image.save(folder / name)
    (folder / "ignore.txt").write_text("unsupported")
    return folder


def read_index(folder):
    return json.loads((folder / "index.json").read_text(encoding="utf-8"))


def test_distinct_deterministic_full_inventory_and_contact_sheet(photos, tmp_path):
    results = [api.create_stills(photos, "one quick bug fix", tmp_path / name, n=8)
               for name in ("a", "b")]
    a, b = (read_index(tmp_path / name) for name in ("a", "b"))
    assert a == b
    assert StillIndex.from_dict(a).to_dict() == a
    assert len(a["photos"]) == 2
    assert len(a["concepts"]) == results[0]["count"] == 8
    assert len({tuple(c["texts"]) for c in a["concepts"]}) == 8
    assert len({c["photo"] for c in a["concepts"]}) == 2
    assert all(check_texts(c["texts"])["valid"] for c in a["concepts"])
    assert {c["id"] for c in a["concepts"]} == {e["id"] for e in a["contact_sheet"]["entries"]}
    assert "one quick bug fix" in results[0]["prompt"]
    assert '"face_count": null' in results[0]["prompt"]
    assert "#" in results[0]["prompt"] and "Subject details" in results[0]["prompt"]
    assert all(p["face_method"] == "center_heuristic" for p in a["photos"])
    assert any("central 60%" in w for w in results[0]["warnings"])
    with Image.open(results[0]["contact_sheet"]) as sheet:
        assert sheet.size == (1080, 1200)
        assert all(sheet.crop(e["box"]).getbbox() for e in a["contact_sheet"]["entries"])
    for concept in a["concepts"]:
        assert (tmp_path / "a" / concept["path"]).is_file()
        assert (tmp_path / "a" / concept["path"]).read_bytes() == (tmp_path / "b" / concept["path"]).read_bytes()
        assert "Caption text:" in concept["alt_text"]
        assert "Subject details have not been identified" in concept["alt_text"]


@pytest.mark.parametrize("aspect", list(ASPECTS))
@pytest.mark.parametrize("layout", ["auto", "classic", "caption", "labels"])
def test_dimensions_and_supplied_face_never_overlaps_text(photos, tmp_path, monkeypatch, aspect, layout):
    # The entire image is a synthetic face. Every overlay must move outside it.
    monkeypatch.setattr(inv, "YuNetDetector", lambda **kw: object())
    monkeypatch.setattr(inv, "detect_faces", lambda *args: [Box(0, 0, 1, 1).to_dict()])
    output = tmp_path / "result"
    api.create_stills(photos, "lunch", output, n=1, aspect=aspect, layout=layout)
    index = StillIndex.from_dict(read_index(output))
    concept = index.concepts[0]
    photo = next(p for p in index.photos if p.id == concept.photo)
    assert photo.face_method == "yunet"
    assert concept.layout == "caption"
    selected = api.pick_still(output, concept.id)
    assert selected["alt_text"] == concept.alt_text
    w, h = ASPECTS[aspect]
    with Image.open(selected["path"]) as image:
        assert image.size == (w, h)
    # Framing (fill/blur) and the text-fitted caption bar both move the
    # photo, so map faces with the concept's own framing and texts.
    for face in output_faces(photo, aspect, concept.layout, fit=concept.fit, focus=concept.focus,
                             texts=concept.texts):
        for text in selected["boxes"]:
            x0, y0, x1, y1 = text["box"]
            assert (x1 <= face.x * w or x0 >= face.right * w or
                    y1 <= face.y * h or y0 >= face.bottom * h)
            assert text["text_bbox"][3] <= y1
    stored = read_index(output)
    assert stored["selected"] == concept.id
    assert stored["concepts"][0]["outputs"][0]["alt_text"] == concept.alt_text
    assert api.pick_still(output, concept.id)["path"] == selected["path"]


def test_auto_classic_busy_caption_and_region_labels(photos, tmp_path):
    photo = inv.describe_photo(photos / "desk.png")
    photo.face_method, photo.faces = "supplied", []
    photo.edge_density = photo.band_density = 0
    assert place(photo, ["a", "b"], "1:1")[0] == "classic"
    photo.edge_density = .3
    assert place(photo, ["a", "b"], "1:1")[0] == "caption"
    photo.faces = [Box(.2, .2, .6, .6).to_dict()]
    chosen, regions, notes = place(photo, ["a"], "1:1", regions=[[.3, .4, .3, .15]])
    assert chosen == "labels" and regions != [[.3, .4, .3, .15]] and notes
    photo.faces = [Box(0, 0, 1, 1).to_dict()]
    with pytest.raises(MemeError, match="at most three"):
        place(photo, ["a", "b", "c", "d"], "1:1", "labels")


def test_locally_measured_busy_photo_uses_caption(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    image = Image.new("RGB", (256, 256))
    draw = ImageDraw.Draw(image)
    for y in range(0, 256, 4):
        for x in range(0, 256, 4):
            draw.rectangle((x, y, x + 3, y + 3), fill="white" if (x + y) % 8 else "black")
    image.save(folder / "busy.png")
    result = api.create_stills(folder, "busy", tmp_path / "out", n=1)
    assert result["summary"][0]["layout"] == "caption"


def test_lines_cli_and_mcp_render_same_validation(photos, tmp_path, capsys):
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps({"ideas": [
        {"photo": "desk.png", "texts": ["one quick fix", "the sun came up"], "title": "Scope creep"},
        {"photo": "portrait.jpg", "texts": ["the bug has tenure now"]},
    ]}), encoding="utf-8")
    output = tmp_path / "out"
    assert cli.main(["still", "--photos", str(photos), "--topic", "bugs", "--out", str(output),
                     "--lines", str(lines), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["count"] == 2
    assert result["summary"][0]["texts"] == ["one quick fix", "the sun came up"]
    concept_id = result["summary"][0]["id"]
    selected = mcp_server.h_still_render(str(output), concept_id)
    assert selected["ok"] and Path(selected["path"]).is_file()
    assert cli.main(["still", "pick", str(output), "--id", concept_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == concept_id
    via_mcp = mcp_server.h_still_concepts(str(photos), "bugs", str(tmp_path / "mcp"), lines=str(lines))
    assert via_mcp["ok"] and via_mcp["summary"] == result["summary"]


@pytest.mark.parametrize("ideas,match", [
    ([{"texts": ["x" * 71]}], "70"),
    ([{"texts": ["x" * 60, "y" * 60]}], "110"),
    ([{"texts": ["a", "b", "c", "d"]}], "1-3"),
    ([{"texts": [""]}], "non-empty"),
    ([{"texts": ["Nobody: coding"]}], "filler"),
    ([{"texts": ["same"]}, {"texts": [" SAME "]}], "Duplicate"),
    ([{"texts": "not an array"}], "list of strings"),
    ([{"texts": ["a"], "photo": "missing.png"}], "Unknown photo"),
    ([{"texts": ["a"], "regions": "bad"}], "regions"),
    ([{"texts": ["a"], "regions": [[0, 0, 2, 1]]}], "normalized"),
])
def test_bad_lines_rejected_before_output(photos, tmp_path, ideas, match):
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps(ideas), encoding="utf-8")
    output = tmp_path / "bad"
    with pytest.raises(MemeError, match=match):
        api.create_stills(photos, "bugs", output, lines=lines)
    assert not output.exists()


def test_template_metadata_is_offline_and_does_not_fetch_blank(photos, tmp_path):
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps([{"photo": "desk.png", "template": "drake", "texts": ["planning", "doing"]}]))
    result = api.create_stills(photos, "bugs", tmp_path / "out", lines=lines)
    assert result["count"] == 1
    assert read_index(tmp_path / "out")["concepts"][0]["render"]["source_path"] == str(photos / "desk.png")


def test_inventory_limits_formats_exif_and_duplicate_bytes(photos, tmp_path, monkeypatch):
    (photos / "duplicate.png").write_bytes((photos / "desk.png").read_bytes())
    listed, notes = inv.inventory(photos)
    assert len(listed) == 2 and "byte-identical" in notes[0]
    monkeypatch.setattr(inv, "MAX_PHOTOS", 2)
    with pytest.raises(MemeError, match="64 files"):
        inv.inventory(photos)
    monkeypatch.setattr(inv, "MAX_PHOTOS", 64)
    monkeypatch.setattr(inv, "MAX_BYTES", 4)
    with pytest.raises(MemeError, match="20 MiB"):
        inv.inventory(photos)
    monkeypatch.setattr(inv, "MAX_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr(inv, "MAX_ENTRIES", 1)
    with pytest.raises(MemeError, match="4096"):
        inv.inventory(photos)
    monkeypatch.setattr(inv, "MAX_ENTRIES", 4096)
    monkeypatch.setattr(inv, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(MemeError, match="256 MiB"):
        inv.inventory(photos)
    image = Image.new("RGB", (30, 60), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(tmp_path / "rotated.jpg", exif=exif)
    measured = inv.describe_photo(tmp_path / "rotated.jpg")
    assert (measured.width, measured.height, measured.orientation) == (60, 30, "landscape")


def test_invalid_inputs_and_changed_photo_fail_honestly(photos, tmp_path, capsys):
    output = tmp_path / "out"
    made = api.create_stills(photos, "bugs", output, n=1)
    with pytest.raises(MemeError, match="empty output"):
        api.create_stills(photos, "bugs", output)
    concept_id = made["summary"][0]["id"]
    index = read_index(output)
    photo = next(p for p in index["photos"] if p["id"] == index["concepts"][0]["photo"])
    Image.new("RGB", (40, 40), "red").save(photo["path"])
    result = mcp_server.h_still_render(str(output), concept_id)
    assert not result["ok"] and "changed" in result["error"]
    assert not mcp_server.h_still_render(str(output), "../../escape")["ok"]
    assert cli.main(["still", "--photos", str(photos), "--topic", "bugs", "--out", str(tmp_path / "bad"),
                     "--n", "0", "--json"]) == 1
    assert not json.loads(capsys.readouterr().out)["ok"]
    for path in ("https://example.com/photos", "//server/share", "\\\\server\\share"):
        with pytest.raises(MemeError, match="local path"):
            inv.local_path(path)


def test_unreadable_and_animated_photo_refused(photos):
    (photos / "broken.png").write_bytes(b"not an image")
    with pytest.raises(MemeError, match="Cannot read photo"):
        inv.inventory(photos)
    (photos / "broken.png").unlink()
    frames = [Image.new("RGB", (40, 40), color) for color in ("red", "blue")]
    frames[0].save(photos / "animated.png", save_all=True, append_images=frames[1:], duration=100)
    with pytest.raises(MemeError, match="single-frame"):
        inv.inventory(photos)


def test_core_without_pillow_has_install_hint(tmp_path):
    code = """
from myzing.mcp_server import h_still_concepts
r = h_still_concepts('.', 'bugs', 'new-output')
assert not r['ok'] and 'myzing[memes]' in r['error'], r
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    process = subprocess.run([sys.executable, "-S", "-c", code], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr


def test_encoder_failure_preserves_selection_and_all_exports(photos, tmp_path, monkeypatch):
    from myzing.memes import video

    output = tmp_path / "out"
    made = api.create_stills(photos, "bugs", output, n=1)
    concept_id = made["summary"][0]["id"]
    selected = api.pick_still(output, concept_id)
    old_index = (output / "index.json").read_bytes()
    old_image = Path(selected["path"]).read_bytes()

    def failed(*args, **kwargs):
        raise MemeError("test encoder failure")

    monkeypatch.setattr(video, "render_meme_video", failed)
    with pytest.raises(MemeError, match="encoder failure"):
        api.pick_still(output, concept_id, gif=True)
    assert (output / "index.json").read_bytes() == old_index
    assert Path(selected["path"]).read_bytes() == old_image
    assert not list(output.glob(".pick-*")) and not list(output.glob("*.mp4"))
    Path(selected["path"]).write_bytes(b"user edited this output")
    with pytest.raises(MemeError, match="already exists or changed"):
        api.pick_still(output, concept_id)
    changed = read_index(output)
    changed["concepts"][0]["texts"] = ["edited text with stale alt text"]
    (output / "index.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(MemeError, match="Saved concept changed"):
        api.pick_still(output, concept_id)


def test_detector_adapter_uses_display_orientation_and_no_download(photos, monkeypatch):
    pytest.importorskip("numpy")
    calls = []

    class Detector:
        def __init__(self, *, download):
            assert download is False

        def detect(self, bgr):
            calls.append(bgr.shape)
            assert bgr.shape[2] == 3
            return [Detection(Box(.1, .1, .2, .2), .9)]

    monkeypatch.setattr(inv, "YuNetDetector", Detector)
    listed, _ = inv.inventory(photos)
    assert sorted(calls) == [(480, 640, 3), (600, 300, 3)]
    assert all(p.face_method == "yunet" and len(p.faces) == 1 for p in listed)
    assert all("1 face candidates" in p.description for p in listed)


@pytest.mark.ffmpeg
def test_pick_real_video_and_gif_offline(photos, tmp_path):
    # BMP is supported by still inventory but deliberately not FFmpeg's input
    # demuxer whitelist: pick must normalize it locally before animation.
    motion_photos = tmp_path / "motion-photos"
    motion_photos.mkdir()
    with Image.open(photos / "desk.png") as source:
        source.save(motion_photos / "desk.bmp")
    output = tmp_path / "out"
    made = api.create_stills(motion_photos, "bugs", output, n=1, aspect="16:9")
    selected = api.pick_still(output, made["summary"][0]["id"], gif=True)
    assert (selected["width"], selected["height"]) == (1200, 675)
    assert (selected["video"]["width"], selected["video"]["height"]) == (1200, 676)
    process = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json",
                              selected["video"]["path"]], capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["streams"][0]["sample_aspect_ratio"] == "1:1"
    for key in ("video", "gif"):
        assert Path(selected[key]["path"]).stat().st_size > 0
        assert selected[key]["alt_text"] == selected["alt_text"]
    with Image.open(selected["gif"]["path"]) as image:
        assert image.is_animated and image.width == 640
    exports = read_index(output)["concepts"][0]["outputs"]
    assert {Path(e["path"]).suffix for e in exports} == {".png", ".mp4", ".gif"}
    assert all(e["sha256"] and e["alt_text"] for e in exports)
    assert not (output / "source.png").exists()
    assert selected["video"]["source_path"].endswith("desk.bmp")
