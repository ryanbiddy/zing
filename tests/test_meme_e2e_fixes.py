"""Regressions for the first real meme E2E pass, on generated images only.

1. Framing: subject-aware fill and blur-fill instead of letterboxing.
2. Offline copy: situation topics, no ellipsis cuts, no Title Case.
3. Outline weight follows the font size (legible on bright photos).
4. Text boxes fit their text: shared caption size, bar height, edge-hugging
   classic text, balanced line breaks.
5. Contact sheet cells follow the aspect and name the framing.
"""

from __future__ import annotations

import io
import json
import subprocess

import pytest

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # the memes extra is optional
    Image = ImageDraw = ImageFont = None

pytestmark = pytest.mark.skipif(Image is None, reason="install myzing[memes] for render tests")

from myzing.layout import detector as yunet
from myzing.layout.detector import LayoutError
from myzing.layout.types import Box
from myzing.memes import framing
from myzing.memes.ideas import generate_ideas
from myzing.memes.render import (ASPECTS, DANGLING, Rect, balanced_wrap, caption_geometry,
                                 fit_rect, render_meme, resolve_font, stroke_px)
from myzing.still import api, inventory as inv
from myzing.still.models import StillIndex
from myzing.still.placement import output_faces

LETTERBOX = (24, 24, 24)
SKIN = (240, 190, 140)
FACE = (.4, .1333, .2, .1333)  # normalized, on the 600x900 portrait


@pytest.fixture(autouse=True)
def no_detector(monkeypatch, zing_workspace):
    def absent(*args, **kwargs):
        raise LayoutError("test: detector unavailable")

    monkeypatch.setattr(yunet, "YuNetDetector", absent)
    monkeypatch.setattr(inv, "YuNetDetector", absent)


def faces_at(monkeypatch, boxes):
    """Pretend local YuNet found these normalized faces (render and still)."""
    class Detector:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(yunet, "YuNetDetector", Detector)
    monkeypatch.setattr(framing, "detect_faces", lambda image, detector: [list(b) for b in boxes])
    monkeypatch.setattr(inv, "YuNetDetector", Detector)
    monkeypatch.setattr(inv, "detect_faces", lambda image, detector: [Box(*b).to_dict() for b in boxes])


def portrait(path):
    """A tall photo with a face disk near the top (like an official portrait)."""
    image = Image.new("RGB", (600, 900), (40, 70, 120))
    draw = ImageDraw.Draw(image)
    draw.rectangle((150, 300, 450, 900), fill=(30, 60, 160))  # shoulders
    draw.ellipse((240, 120, 360, 240), fill=SKIN)
    image.save(path)
    return path


def group(path):
    """A wide photo with three faces spread edge to edge."""
    image = Image.new("RGB", (900, 600), (60, 90, 70))
    draw = ImageDraw.Draw(image)
    for x, color in ((60, (250, 80, 80)), (420, (80, 250, 80)), (780, (80, 80, 250))):
        draw.ellipse((x - 40, 200, x + 40, 280), fill=color)
    image.save(path)
    return path


def near(a, b, tolerance=24):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


# 1. Framing ---------------------------------------------------------------

@pytest.mark.parametrize("aspect", list(ASPECTS))
def test_auto_fill_keeps_the_face_and_fills_every_aspect(tmp_path, monkeypatch, aspect):
    faces_at(monkeypatch, [FACE])
    source = portrait(tmp_path / "portrait.png")
    result = render_meme(["top"], image=str(source), aspect=aspect, out=str(tmp_path / "out.png"))
    assert result["fit"] == "fill" and result["focus_basis"] == "faces"
    w, h = ASPECTS[aspect]
    rect = fit_rect((600, 900), Rect(0, 0, w, h), "fill", result["focus"])
    center = (rect.x + .5 * rect.width, rect.y + (FACE[1] + FACE[3] / 2) * rect.height)
    assert 0 <= center[0] < w and 0 <= center[1] < h
    with Image.open(result["path"]) as image:
        assert near(image.getpixel((round(center[0]), round(center[1]))), SKIN)
        for corner in ((1, 1), (w - 2, h - 2)):
            assert image.getpixel(corner) != LETTERBOX


def test_legacy_center_crop_cut_the_face_that_fill_keeps(tmp_path, monkeypatch):
    faces_at(monkeypatch, [FACE])
    source = portrait(tmp_path / "portrait.png")
    rect = fit_rect((600, 900), Rect(0, 0, 1200, 675), "cover")
    assert rect.y + (FACE[1] + FACE[3]) * rect.height < 0  # the whole face is above the frame
    result = render_meme(["top"], image=str(source), aspect="16:9", out=str(tmp_path / "fill.png"))
    filled = fit_rect((600, 900), Rect(0, 0, 1200, 675), "fill", result["focus"])
    assert filled.y + FACE[1] * filled.height >= 0


def test_auto_blur_fills_when_a_crop_would_cut_faces_and_contain_remains(tmp_path, monkeypatch):
    faces = [(.0222, .333, .0889, .1333), (.4222, .333, .0889, .1333), (.8222, .333, .0889, .1333)]
    faces_at(monkeypatch, faces)
    source = group(tmp_path / "group.png")
    blurred = render_meme(["top"], image=str(source), aspect="9:16", out=str(tmp_path / "blur.png"))
    assert blurred["fit"] == "blur" and blurred["focus"] is None
    contained = render_meme(["top"], image=str(source), aspect="9:16", fit="contain",
                            out=str(tmp_path / "contain.png"))
    rect = fit_rect((900, 600), Rect(0, 0, 1080, 1920), "contain")
    with Image.open(blurred["path"]) as image, Image.open(contained["path"]) as letterboxed:
        corner = image.getpixel((5, 5))
        assert corner != LETTERBOX and max(corner) > 30  # a darkened copy of the photo
        assert letterboxed.getpixel((5, 5)) == LETTERBOX
        for x in (60, 420, 780):  # every face stays in the contained photo
            point = (round(rect.x + x / 900 * rect.width), round(rect.y + 240 / 600 * rect.height))
            assert image.getpixel(point) == letterboxed.getpixel(point)


def test_centered_focus_is_byte_identical_to_cover(tmp_path):
    assert fit_rect((640, 480), Rect(0, 0, 1080, 1080), "fill", [.2, .2, .6, .6]) == \
        fit_rect((640, 480), Rect(0, 0, 1080, 1080), "cover")
    path = tmp_path / "flat.png"
    Image.new("RGB", (640, 480), (63, 97, 122)).save(path)
    auto = render_meme(["a"], image=str(path), out=str(tmp_path / "auto.png"))
    cover = render_meme(["a"], image=str(path), fit="cover", out=str(tmp_path / "cover.png"))
    # No detector: the documented central-60% region is the focus; it is
    # centered, so the fill is exactly the legacy centered cover.
    assert auto["fit"] == "fill" and auto["focus_basis"] == "center_heuristic"
    assert any("fetch-model" in w for w in auto["warnings"])
    assert (tmp_path / "auto.png").read_bytes() == (tmp_path / "cover.png").read_bytes()


def test_saliency_finds_an_off_center_subject_and_ignores_flat_photos():
    image = Image.new("RGB", (400, 300), (85, 119, 85))
    ImageDraw.Draw(image).rectangle((260, 60, 340, 140), fill=(255, 140, 20))
    x, y, w, h = framing.saliency_box(image)
    assert x <= 300 / 400 <= x + w and y <= 100 / 300 <= y + h
    assert framing.saliency_box(Image.new("RGB", (400, 300), (85, 119, 85))) is None


def test_background_faces_do_not_steer_the_crop():
    tiny = [.01, .7, .01, .02]
    assert framing.prominent_faces([[.4, .1, .2, .2], tiny]) == [[.4, .1, .2, .2]]
    assert framing.focus_box([tiny], "yunet", [.3, .3, .2, .2]) == ([.3, .3, .2, .2], "subject")


@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_still_concepts_fill_and_keep_text_off_faces(tmp_path, monkeypatch, aspect):
    faces_at(monkeypatch, [FACE])
    folder = tmp_path / "photos"
    folder.mkdir()
    portrait(folder / "portrait.png")
    output = tmp_path / "out"
    api.create_stills(folder, "when the build finally passes", output, n=3, aspect=aspect)
    index = StillIndex.from_dict(json.loads((output / "index.json").read_text(encoding="utf-8")))
    photo = index.photos[0]
    w, h = ASPECTS[aspect]
    for concept in index.concepts:
        assert concept.fit in ("fill", "blur")
        picked = api.pick_still(output, concept.id)
        with Image.open(picked["path"]) as image:
            assert image.getpixel((w - 2, h - 2)) != LETTERBOX
        faces = output_faces(photo, aspect, concept.layout, fit=concept.fit, focus=concept.focus,
                             texts=concept.texts)
        assert faces
        for face in faces:
            for text in picked["boxes"]:
                x0, y0, x1, y1 = text["box"]
                assert x1 <= face.x * w or x0 >= face.right * w or y1 <= face.y * h or y0 >= face.bottom * h


def test_indexes_written_before_framing_still_pick_with_contain(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (640, 480), (63, 97, 122)).save(folder / "desk.png")
    output = tmp_path / "out"
    made = api.create_stills(folder, "bugs", output, n=1, fit="contain")
    data = json.loads((output / "index.json").read_text(encoding="utf-8"))
    for concept in data["concepts"]:
        assert concept.pop("fit") == "contain" and concept.pop("focus") is None
    for photo in data["photos"]:
        photo.pop("subject")
    (output / "index.json").write_text(json.dumps(data), encoding="utf-8")
    picked = api.pick_still(output, made["summary"][0]["id"])
    with Image.open(picked["path"]) as image:
        assert image.getpixel((540, 20)) == LETTERBOX


@pytest.mark.ffmpeg
@pytest.mark.parametrize("fit", ["fill", "blur"])
def test_animated_export_uses_the_still_framing(tmp_path, fit):
    from myzing.memes.video import render_meme_video

    source = portrait(tmp_path / "portrait.png")
    focus = framing.head_box(list(FACE)) if fit == "fill" else None
    still = render_meme(["top"], image=str(source), aspect="16:9", fit=fit, focus=focus,
                        out=str(tmp_path / "still.png"))
    motion = render_meme_video(["top"], image=str(source), aspect="16:9", fit=fit, focus=focus,
                               duration=1, fps=10, out=str(tmp_path / "motion.mp4"))
    assert motion["fit"] == still["fit"] == fit
    frame = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", motion["path"], "-frames:v", "1",
                            "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True, check=True,
                           timeout=60).stdout
    with Image.open(io.BytesIO(frame)) as video, Image.open(still["path"]) as image:
        video = video.convert("RGB")
        rect = fit_rect((600, 900), Rect(0, 0, 1200, 675), fit, focus)
        face = (round(rect.x + .5 * rect.width), round(rect.y + (FACE[1] + FACE[3] / 2) * rect.height))
        assert near(video.getpixel(face), image.getpixel(face), 30)
        assert near(video.getpixel(face), SKIN, 30)
        corner = video.getpixel((10, 600))
        assert corner != LETTERBOX and max(corner) > 30  # filled frame, not padding
        if fit == "blur":
            assert near(corner, image.getpixel((10, 600)), 30)


# 2. Offline copy ----------------------------------------------------------

def test_situation_topics_read_as_sentences():
    ideas = generate_ideas("when the build finally passes", n=8)
    texts = [text for idea in ideas for text in idea["texts"]]
    assert all(idea["validation"]["valid"] for idea in ideas)
    for broken in ("passes finally works", "how's when", "just do when", "quick when", "day 1 of when"):
        assert not any(broken in text for text in texts), broken
    assert ["when the build finally passes"] in [idea["texts"] for idea in ideas]
    assert len({idea["texts"][0] for idea in ideas}) >= 4  # varied setups, not one setup x8


def test_long_topics_are_cut_at_a_clause_without_an_ellipsis():
    for topic, kept in (("touching grass after the release", "touching grass after the release"),
                        ("pov: the meeting runs long and everyone is still talking about it",
                         "the meeting runs long")):
        ideas = generate_ideas(topic, n=8)
        texts = " | ".join(text for idea in ideas for text in idea["texts"])
        assert "…" not in texts and kept in texts
        assert all(idea["validation"]["valid"] for idea in ideas)


def test_no_title_case_and_tasks_become_gerunds():
    ideas = generate_ideas("fix the flaky test", n=8)
    texts = [text for idea in ideas for text in idea["texts"]]
    assert all(text == text.lower() for text in texts)
    assert any("fixing the flaky test" in text for text in texts)
    assert not any("quick fix the" in text or "day 1 of fix " in text for text in texts)


# 3. Outline weight --------------------------------------------------------

def test_outline_follows_font_size_and_survives_a_white_photo(tmp_path):
    assert stroke_px(1080, 73, .5) >= 6 > round(1080 * .5 / 200)
    assert stroke_px(1080, 20, .5) == 3 and stroke_px(1080, 73, 0) == 0
    path = tmp_path / "white.png"
    Image.new("RGB", (1080, 1080), "white").save(path)
    result = render_meme(["IT'S FINE"], image=str(path), fit="cover", out=str(tmp_path / "out.png"))
    with Image.open(result["path"]) as image:
        ink = image.crop(tuple(result["boxes"][0]["text_bbox"]))
        dark = sum(n for n, rgb in ink.getcolors(ink.width * ink.height) if max(rgb) < 80)
        assert dark / (ink.width * ink.height) > .22


# 4. Text boxes fit their text --------------------------------------------

def test_caption_beats_share_one_size_and_the_bar_fits_the_text(tmp_path):
    texts = ["monday standup", "nobody has updates, everyone has opinions"]
    bar, boxes, size = caption_geometry(texts, (1080, 1920), "sans")
    assert bar < round(1920 * .26)
    path = tmp_path / "photo.png"
    Image.new("RGB", (640, 480), (63, 97, 122)).save(path)
    result = render_meme(texts, image=str(path), layout="caption", aspect="9:16", fit="contain",
                         out=str(tmp_path / "caption.png"))
    assert len({box["font_size"] for box in result["boxes"]}) == 1
    with Image.open(result["path"]) as image:
        assert image.getpixel((540, bar - 1)) == (255, 255, 255)
        assert image.getpixel((540, bar + 1)) != (255, 255, 255)


def test_balanced_lines_avoid_widows_and_dangling_words():
    font = ImageFont.truetype(resolve_font("sans"), 73)
    lines = balanced_wrap("me at standup hearing the same blocker for the 4th week", font, 960)
    assert len(lines) >= 2 and len(lines[-1].split()) > 1
    assert all(line.split()[-1].casefold() not in DANGLING for line in lines[:-1])
    widths = [font.getlength(line) for line in lines]
    assert max(widths) - min(widths) < .35 * max(widths)


def test_classic_text_hugs_the_top_and_bottom_edges(tmp_path):
    path = tmp_path / "photo.png"
    Image.new("RGB", (640, 480), (63, 97, 122)).save(path)
    result = render_meme(["one quick fix", "six hours later"], image=str(path), fit="cover",
                         out=str(tmp_path / "classic.png"))
    top, bottom = (box["box"] for box in result["boxes"])
    assert top[1] == round(1080 * .03) and top[3] - top[1] < 1080 * .15
    assert bottom[3] == round(1080 * .97) and bottom[3] - bottom[1] < 1080 * .15


# 5. Contact sheet ---------------------------------------------------------

def test_landscape_contact_sheet_has_no_gap_and_names_the_framing(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (640, 480), (63, 97, 122)).save(folder / "desk.png")
    result = api.create_stills(folder, "release day", tmp_path / "out", n=3, aspect="16:9")
    index = json.loads((tmp_path / "out" / "index.json").read_text(encoding="utf-8"))
    sheet = index["contact_sheet"]
    assert sheet["height"] == 189 + 66  # one row: a 16:9 thumbnail plus the label band
    with Image.open(result["contact_sheet"]) as image:
        label_band = image.crop((0, 189 + 10, image.width, image.height))
        assert label_band.getbbox()  # IDs sit right under the thumbnails
