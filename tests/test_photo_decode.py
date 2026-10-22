"""POLISH1 item 2: HEIC through FFmpeg, bounded decoding of very large photos."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from myzing import cli  # noqa: E402
from myzing.memes import MemeError, photo  # noqa: E402
from myzing.memes.render import render_meme  # noqa: E402
from myzing.still.api import create_stills  # noqa: E402
from myzing.still.inventory import describe_photo  # noqa: E402


@pytest.fixture(scope="module")
def large_jpeg(tmp_path_factory):
    """A synthetic 50 MP JPEG (8660x5774) stored rotated, EXIF orientation 6."""
    folder = tmp_path_factory.mktemp("large")
    image = Image.new("RGB", (8660, 5774), (40, 90, 150))
    # A bright marker in the stored top-left corner; orientation 6 (rotate
    # 90 degrees clockwise to display) moves it to the displayed top-right.
    image.paste((250, 240, 30), (0, 0, 1200, 1200))
    exif = Image.Exif()
    exif[0x0112] = 6
    path = folder / "phone-50mp.jpg"
    image.save(path, quality=70, exif=exif)
    return path


def test_large_jpeg_decodes_to_an_oriented_bounded_working_copy(large_jpeg):
    image, source = photo.load_photo(large_jpeg)
    assert source.original == (5774, 8660)  # display orientation
    assert max(image.size) == photo.WORKING_MAX_SIDE
    assert image.size == source.working == (2731, 4096)
    assert source.decoder == "pillow" and source.orientation == "exif" and source.downscaled
    # Marker moved to the displayed top-right corner.
    assert image.getpixel((image.width - 20, 20))[0] > 200
    assert image.getpixel((20, 20))[2] > 120
    report = source.to_dict()
    assert report["megapixels"] == 50.0 and report["original"] == [5774, 8660]
    assert "50.0 MP" in source.note() and "2731x4096 working copy" in source.note()


def test_large_photo_meme_and_still_report_original_and_working_sizes(large_jpeg, tmp_path, zing_workspace):
    result = render_meme(["one quick fix", "six hours later"], image=str(large_jpeg), aspect="4:5",
                         fit="blur", out=str(tmp_path / "meme.png"))
    assert result["source"]["original"] == [5774, 8660] and result["source"]["working"] == [2731, 4096]
    assert any("50.0 MP" in w for w in result["warnings"])
    with Image.open(result["path"]) as rendered:
        assert rendered.size == (1080, 1350)
    folder = tmp_path / "photos"
    folder.mkdir()
    shutil.copy(large_jpeg, folder / large_jpeg.name)
    record = describe_photo(folder / large_jpeg.name)
    assert (record.width, record.height) == (2731, 4096)
    assert record.source["original"] == [5774, 8660]
    assert "5774 by 8660 pixels (2731 by 4096 working copy)" in record.description
    stills = create_stills(folder, "one quick fix", tmp_path / "stills", n=1, aspect="4:5")
    assert stills["count"] == 1
    index = json.loads(Path(stills["index_path"]).read_text(encoding="utf-8"))
    assert index["photos"][0]["source"]["downscaled"] is True


def test_decode_bound_is_explicit_and_replaces_pillow_bomb_warning(tmp_path, monkeypatch):
    path = tmp_path / "wide.png"
    Image.new("RGB", (3000, 2000), "white").save(path)
    # Pillow would warn above 4 MP here; Zing's own bound (8 MP) applies instead.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 4_000_000)
    monkeypatch.setattr(photo, "MAX_SOURCE_PIXELS", 8_000_000)
    image, source = photo.load_photo(path)
    assert source.original == (3000, 2000) and image.size == (3000, 2000)
    monkeypatch.setattr(photo, "MAX_SOURCE_PIXELS", 5_000_000)
    with pytest.raises(MemeError, match=r"6 MP\), above Zing's 5 MP / 16384 px decode limit: wide.png; resize it first"):
        photo.load_photo(path)
    # Above twice Pillow's limit its hard error is translated, never a traceback.
    monkeypatch.setattr(photo, "MAX_SOURCE_PIXELS", 80_000_000)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 2_000_000)
    with pytest.raises(MemeError, match="decode limit: wide.png"):
        photo.load_photo(path)


def test_heif_sniffing_uses_extension_or_ftyp_brand(tmp_path):
    renamed = tmp_path / "IMG_0001.jpg"
    renamed.write_bytes(photo._probe_container())
    assert photo.is_heif(renamed)
    jpeg = tmp_path / "plain.jpg"
    Image.new("RGB", (8, 8)).save(jpeg)
    assert not photo.is_heif(jpeg)
    assert photo.is_heif(tmp_path / "missing.HEIC")


@pytest.mark.ffmpeg
def test_heic_support_matches_the_ffmpeg_demuxer_and_failures_are_actionable(tmp_path):
    """Never skips: FFmpeg 8.x reads HEIF items, 6.1 refuses with a remedy."""
    supported, detail = photo.heif_support()
    sample = tmp_path / "probe.heic"
    sample.write_bytes(photo._probe_container())
    probe = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "stream=codec_name", "-of", "json",
                            str(sample)], capture_output=True, text=True, check=False)
    demuxed = probe.returncode == 0 and "hevc" in probe.stdout
    assert supported == demuxed, detail
    version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=False).stdout
    if version.startswith("ffmpeg version 6."):
        assert not supported and "cannot read HEIF image items" in detail
    if version.startswith("ffmpeg version 8."):
        assert supported and "reads HEIF image items" in detail
    # A HEIF header without picture data never yields a silent or blank photo.
    with pytest.raises(MemeError) as error:
        photo.load_photo(sample)
    message = str(error.value)
    assert "HEIC/HEIF" in message and "Convert the photo to JPEG or PNG" in message
    if not supported:
        assert "cannot read HEIC/HEIF photo probe.heic" in message


def test_doctor_reports_heic_support(capsys):
    from myzing import doctor

    check = doctor.check_heic()
    assert check.name == "heic" and check.tier == doctor.OPTIONAL
    assert "HEIC/HEIF photos" in check.detail
    assert check.ok or "Zing bundles no HEIC decoder" in check.fix


@pytest.fixture(scope="module")
def heic_files(tmp_path_factory):
    """Real HEIC photos encoded by the local FFmpeg; skip when it cannot."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg is not on PATH")
    from heif_fixture import HeifUnavailable, make_heic

    folder = tmp_path_factory.mktemp("heic")
    source = folder / "source.png"
    image = Image.new("RGB", (640, 480), (30, 60, 200))
    image.paste((240, 230, 20), (0, 0, 160, 120))  # top-left marker
    image.save(source)
    try:
        files = {"single": make_heic(folder / "single.heic", source),
                 "grid": make_heic(folder / "grid.heic", source, grid=(2, 2)),
                 "rotated": make_heic(folder / "rotated.heic", source, rotation=1)}
    except HeifUnavailable as exc:
        pytest.skip(f"local FFmpeg cannot encode a HEIC test photo: {exc}")
    return files


def test_real_heic_single_grid_and_rotated(heic_files, tmp_path, zing_workspace):
    supported, _ = photo.heif_support()
    if not supported:
        for path in heic_files.values():
            with pytest.raises(MemeError, match="cannot read HEIC/HEIF photo.*Convert the photo to JPEG"):
                photo.load_photo(path)
        return
    for name in ("single", "grid"):
        image, source = photo.load_photo(heic_files[name])
        assert image.size == (640, 480) and source.decoder == "ffmpeg-heif" and not source.downscaled
        assert image.getpixel((20, 20))[0] > 200 and image.getpixel((600, 400))[2] > 150
    rotated, source = photo.load_photo(heic_files["rotated"])
    # irot 1 = 90 degrees anticlockwise: the top-left marker moves to bottom-left.
    assert rotated.size == (480, 640) and source.original == (480, 640)
    assert rotated.getpixel((20, 620))[0] > 200 and rotated.getpixel((20, 20))[0] < 100
    result = render_meme(["one quick fix"], image=str(heic_files["grid"]), out=str(tmp_path / "m.png"), fit="blur")
    assert result["source"]["decoder"] == "ffmpeg-heif"
    folder = tmp_path / "photos"
    folder.mkdir()
    shutil.copy(heic_files["rotated"], folder / "IMG_0042.HEIC")
    assert cli.main(["still", "--photos", str(folder), "--topic", "monday standup",
                     "--out", str(tmp_path / "stills"), "--n", "1", "--json"]) == 0
    index = json.loads((tmp_path / "stills" / "index.json").read_text(encoding="utf-8"))
    assert index["photos"][0]["source"]["decoder"] == "ffmpeg-heif"
    assert (index["photos"][0]["width"], index["photos"][0]["height"]) == (480, 640)
