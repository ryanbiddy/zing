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
import re
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

def inside(rect, box, w, h, margin=0.):
    """The normalized source ``box`` (grown by ``margin`` of the photo) maps
    entirely inside the w x h output through the framing ``rect``."""
    left = rect.x + (box[0] - margin) * rect.width
    top = rect.y + (box[1] - margin) * rect.height
    right = rect.x + (box[0] + box[2] + margin) * rect.width
    bottom = rect.y + (box[1] + box[3] + margin) * rect.height
    return left >= -.5 and top >= -.5 and right <= w + .5 and bottom <= h + .5


def portrait_face_near_top(path):
    """Official-portrait shape with the face close to the top edge."""
    image = Image.new("RGB", (600, 900), (40, 70, 120))
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 200, 480, 900), fill=(30, 60, 160))
    draw.ellipse((240, 30, 360, 150), fill=SKIN)
    image.save(path)
    return path


FACE_TOP = (.4, 30 / 900, .2, 120 / 900)


def subject_photo(path):
    """No face; one distinct off-center subject on a plain field."""
    image = Image.new("RGB", (800, 600), (85, 119, 85))
    ImageDraw.Draw(image).rectangle((420, 180, 560, 320), fill=(255, 140, 20))
    image.save(path)
    return path


SUBJECT = (420 / 800, 180 / 600, 140 / 800, 140 / 600)


@pytest.mark.parametrize("aspect", list(ASPECTS))
def test_evidence_based_crop_keeps_detected_faces_with_margin(tmp_path, monkeypatch, aspect):
    faces_at(monkeypatch, [FACE])
    source = portrait(tmp_path / "portrait.png")
    result = render_meme(["top"], image=str(source), aspect=aspect, out=str(tmp_path / "out.png"))
    assert result["fit"] == "fill" and result["focus_basis"] == "faces"
    w, h = ASPECTS[aspect]
    rect = fit_rect((600, 900), Rect(0, 0, w, h), "fill", result["focus"])
    assert inside(rect, framing.head_box(list(FACE)), w, h, framing.MARGIN - 1e-9)
    center = (rect.x + .5 * rect.width, rect.y + (FACE[1] + FACE[3] / 2) * rect.height)
    with Image.open(result["path"]) as image:
        assert near(image.getpixel((round(center[0]), round(center[1]))), SKIN)
        for corner in ((1, 1), (w - 2, h - 2)):
            assert image.getpixel(corner) != LETTERBOX


@pytest.mark.parametrize("detector", [False, True])
@pytest.mark.parametrize("aspect", list(ASPECTS))
def test_face_near_the_top_is_never_cut(tmp_path, monkeypatch, aspect, detector):
    # With the detector the face is evidence; without it auto never crops.
    if detector:
        faces_at(monkeypatch, [FACE_TOP])
    source = portrait_face_near_top(tmp_path / "portrait.png")
    result = render_meme(["top"], image=str(source), aspect=aspect, out=str(tmp_path / "out.png"))
    w, h = ASPECTS[aspect]
    rect = fit_rect((600, 900), Rect(0, 0, w, h), result["fit"], result["focus"])
    assert inside(rect, FACE_TOP, w, h)
    if detector:
        assert result["fit"] == "fill" and result["focus_basis"] == "faces"
    else:
        # POLISH1: without a detector the face-like region is still the
        # estimated subject, so the default classic text moves to a caption bar.
        assert result["fit"] == "blur" and framing.BLUR_NO_DETECTOR in result["warnings"]
        assert result["protection"]["text_clear"] and result["layout"] == "caption"


def face_beside_subject(path):
    """Grok's repro: a face at the top and a salient orange body well below it,
    so the measured subject excludes the face."""
    image = Image.new("RGB", (600, 900), (40, 70, 120))
    draw = ImageDraw.Draw(image)
    draw.ellipse((250, 20, 350, 120), fill=(195, 165, 140))
    draw.rectangle((130, 460, 470, 740), fill=(255, 140, 20))
    image.save(path)
    return path


FACE_ABOVE = (250 / 600, 20 / 900, 100 / 600, 100 / 900)


@pytest.mark.parametrize("aspect", list(ASPECTS))
def test_no_detector_never_crops_on_a_subject_beside_a_face(tmp_path, aspect):
    source = face_beside_subject(tmp_path / "photo.png")
    with Image.open(source) as image:
        subject = framing.saliency_box(image)
    # Precondition: the measured subject fits a 1:1 crop but leaves the face out.
    assert subject is not None and subject[1] > FACE_ABOVE[1] + FACE_ABOVE[3]
    kept, basis = framing.focus_box([], "yunet", subject)
    assert basis == "subject" and framing.fits_window(framing.with_margin(kept), (600, 900), (1080, 1080))
    w, h = ASPECTS[aspect]
    result = render_meme(["top"], image=str(source), aspect=aspect, out=str(tmp_path / "out.png"))
    assert result["fit"] == "blur" and result["focus_basis"] == "no_detector"
    assert result["warnings"] == [framing.BLUR_NO_DETECTOR]
    assert inside(fit_rect((600, 900), Rect(0, 0, w, h), "blur", None), FACE_ABOVE, w, h)
    # The still workflow (photo.subject recorded at inventory) behaves the same.
    folder = tmp_path / "photos"
    folder.mkdir()
    face_beside_subject(folder / "photo.png")
    api.create_stills(folder, "release day", tmp_path / "still", n=2, aspect=aspect)
    index = StillIndex.from_dict(json.loads((tmp_path / "still" / "index.json").read_text(encoding="utf-8")))
    assert index.photos[0].subject is not None
    for concept in index.concepts:
        assert concept.fit == "blur" and framing.BLUR_NO_DETECTOR in concept.warnings


def test_no_detector_and_no_subject_never_crops(tmp_path):
    path = tmp_path / "flat.png"
    Image.new("RGB", (640, 480), (63, 97, 122)).save(path)
    for aspect in ASPECTS:
        result = render_meme(["a"], image=str(path), aspect=aspect,
                             out=str(tmp_path / (aspect.replace(":", "x") + ".png")))
        assert result["fit"] == "blur" and result["focus"] is None and result["focus_basis"] == "no_detector"
        assert result["warnings"] == [framing.BLUR_NO_DETECTOR]
    # The face-blind centered crop is only ever an explicit request.
    cover = render_meme(["a"], image=str(path), fit="cover", out=str(tmp_path / "cover.png"))
    assert cover["fit"] == "cover" and cover["warnings"] == []
    explicit = render_meme(["a"], image=str(path), fit="fill", out=str(tmp_path / "fill.png"))
    assert explicit["fit"] == "cover" and "may cut faces" in explicit["warnings"][0]


def test_detector_with_no_faces_crops_only_on_a_large_measured_subject(tmp_path, monkeypatch):
    faces_at(monkeypatch, [])
    flat = tmp_path / "flat.png"
    Image.new("RGB", (640, 480), (63, 97, 122)).save(flat)
    blurred = render_meme(["a"], image=str(flat), out=str(tmp_path / "flat-out.png"))
    assert blurred["fit"] == "blur" and blurred["warnings"] == [framing.BLUR_NO_EVIDENCE]
    # 4:3 into 1:1 keeps 75% of the photo: a subject crop is allowed, with a caveat.
    source = subject_photo(tmp_path / "subject.png")
    filled = render_meme(["a"], image=str(source), aspect="1:1", out=str(tmp_path / "subject-out.png"))
    assert filled["fit"] == "fill" and filled["focus_basis"] == "subject"
    assert "keeps 75% of the photo" in filled["warnings"][0] and "missed" in filled["warnings"][0]
    rect = fit_rect((800, 600), Rect(0, 0, 1080, 1080), "fill", filled["focus"])
    assert inside(rect, SUBJECT, 1080, 1080, framing.MARGIN - 1e-9)
    # 4:5 and 9:16 would drop more than 25% of the photo: blur, and say why.
    for aspect in ("4:5", "9:16"):
        tall = render_meme(["a"], image=str(source), aspect=aspect,
                           out=str(tmp_path / (aspect.replace(":", "x") + ".png")))
        assert tall["fit"] == "blur" and any("more than 25%" in n for n in tall["warnings"])
    # A face the detector missed beside a salient subject: every crop that would
    # drop more than 25% of the photo blurs instead and keeps the face; the mild
    # crops that remain (4:5 and 9:16 of a 2:3 photo) carry the caveat.
    missed = face_beside_subject(tmp_path / "missed.png")
    for aspect in ASPECTS:
        result = render_meme(["a"], image=str(missed), aspect=aspect,
                             out=str(tmp_path / ("missed-" + aspect.replace(":", "x") + ".png")))
        w, h = ASPECTS[aspect]
        width, height = framing.crop_window((600, 900), (w, h))
        if width * height < framing.MIN_SCENERY_AREA:
            rect = fit_rect((600, 900), Rect(0, 0, w, h), result["fit"], result["focus"])
            assert result["fit"] == "blur" and inside(rect, FACE_ABOVE, w, h), aspect
        else:
            assert result["fit"] == "fill" and "missed" in result["warnings"][0], aspect
    explicit = render_meme(["a"], image=str(flat), fit="fill", out=str(tmp_path / "explicit.png"))
    assert explicit["fit"] == "cover" and "centered crop" in explicit["warnings"][0]


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


def test_saliency_finds_an_off_center_subject_and_ignores_flat_photos():
    image = Image.new("RGB", (400, 300), (85, 119, 85))
    ImageDraw.Draw(image).rectangle((260, 60, 340, 140), fill=(255, 140, 20))
    x, y, w, h = framing.saliency_box(image)
    assert x <= 300 / 400 <= x + w and y <= 100 / 300 <= y + h
    assert framing.saliency_box(Image.new("RGB", (400, 300), (85, 119, 85))) is None


def test_background_faces_do_not_steer_the_crop():
    tiny = [.01, .7, .01, .02]
    assert framing.prominent_faces([[.4, .1, .2, .2], tiny]) == [[.4, .1, .2, .2]]
    # A street scene whose largest face is a 2.8%-tall passer-by has no subject face.
    assert framing.prominent_faces([[.006, .684, .011, .028], [.3, .66, .01, .017]]) == []
    box, basis = framing.focus_box([tiny], "yunet", [.3, .3, .2, .2])
    assert basis == "subject" and box == pytest.approx([.27, .27, .26, .26])  # grown 15% per side


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
    # Explicit layout: render-video does not run subject protection, so a
    # defaulted still layout could move to a caption bar (POLISH1).
    still = render_meme(["top"], image=str(source), aspect="16:9", fit=fit, focus=focus,
                        layout="classic", out=str(tmp_path / "still.png"))
    motion = render_meme_video(["top"], image=str(source), aspect="16:9", fit=fit, focus=focus,
                               duration=1, fps=10, gif=True, out=str(tmp_path / "motion.mp4"))
    assert motion["fit"] == still["fit"] == fit
    with Image.open(motion["gif"]["path"]) as gif:
        assert gif.is_animated
        gif.seek(gif.n_frames // 2)
        frame_gif = gif.convert("RGB")
        k = frame_gif.width / 1200
        rect = fit_rect((600, 900), Rect(0, 0, 1200, 675), fit, focus)
        face = (rect.x + .5 * rect.width, rect.y + (FACE[1] + FACE[3] / 2) * rect.height)
        assert near(frame_gif.getpixel((round(face[0] * k), round(face[1] * k))), SKIN, 40)
        corner = frame_gif.getpixel((round(10 * k), round(600 * k)))
        assert corner != LETTERBOX and max(corner) > 30  # the GIF keeps the framing too
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


# (topic as typed, expected shape, expected topic text inside the lines)
TOPICS = [
    # situations: the subject is kept after "when"
    ("when you commit", "situation", "you commit"),
    ("when the build finally passes", "situation", "the build finally passes"),
    ("me when prod goes down", "situation", "prod goes down"),
    ("that feeling when the tests pass", "situation", "the tests pass"),
    ("pov: you open the legacy code", "situation", "you open the legacy code"),
    ("when Kevin replied all", "situation", "Kevin replied all"),
    # past tense, present tense, acronyms
    ("the deploy failed", "situation", "the deploy failed"),
    ("prod went down again", "situation", "prod went down again"),
    ("the intern pushed to main", "situation", "the intern pushed to main"),
    ("the tests pass", "situation", "the tests pass"),
    ("AWS goes down", "situation", "AWS goes down"),
    ("CI is red", "situation", "CI is red"),
    # wh-clauses are nouns, never prefixed with "when"
    ("how it works", "wh", "how it works"),
    ("when how it works", "wh", "how it works"),
    ("why the build broke", "wh", "why the build broke"),
    ("what the PM actually wants", "wh", "what the PM actually wants"),
    # verb phrases and "how to" become correctly spelled gerunds
    ("how to exit vim", "thing", "exiting vim"),
    ("trying to commit before the deadline", "thing", "committing before the deadline"),
    ("fix the flaky test", "thing", "fixing the flaky test"),
    ("format the codebase", "thing", "formatting the codebase"),
    ("ship it on a friday", "thing", "shipping it on a friday"),
    ("be on call", "thing", "being on call"),
    ("write the docs", "thing", "writing the docs"),
    ("debug in production", "thing", "debugging in production"),
    ("submit the PR", "thing", "submitting the PR"),
    ("run the migrations", "thing", "running the migrations"),
    ("fix bugs", "thing", "fixing bugs"),
    # noun phrases (and nouns that look like verbs) stay as typed
    ("monday standup energy", "thing", "monday standup energy"),
    ("release day", "thing", "release day"),
    ("merge conflicts", "thing", "merge conflicts"),
    ("Kevin from accounting", "thing", "Kevin from accounting"),
    ("PR reviews", "thing", "PR reviews"),
    ("a failed deploy", "thing", "a failed deploy"),
    ("the meeting that ran long", "thing", "the meeting that ran long"),
    ("deploying on a friday", "thing", "deploying on a friday"),
]
BARE_VERBS = {"commit", "fix", "format", "ship", "be", "write", "debug", "submit", "run", "exit",
              "open", "push", "merge", "deploy", "test", "make", "go", "do", "get"}
MISSPELT = {"commiting", "formating", "bing", "submiting", "shiping", "runing", "debuging",
            "exitting", "beeing", "writeing", "makeing", "planing", "forgeting", "begining"}


@pytest.mark.parametrize("topic,shape,text", TOPICS, ids=[t[0] for t in TOPICS])
def test_topic_table_lines_are_grammatical(topic, shape, text):
    from myzing.memes.ideas import _topic

    assert _topic(topic) == (shape, text)
    ideas = generate_ideas(topic, n=8)
    assert len({tuple(idea["texts"]) for idea in ideas}) == 8
    for idea in ideas:
        assert idea["validation"]["valid"], idea
        for line in idea["texts"]:
            lowered = line.casefold()
            words = re.findall(r"[a-z']+", lowered)
            assert "…" not in line
            assert not re.search(r"\bwhen (when|how|why|what|where|who|which)\b", lowered), line
            assert not re.search(r"\bwhy (how|why|what|where|who)\b", lowered), line
            # a bare verb right after "when", "why", "of", "how's" or "can" means a
            # dropped subject (a typed noun like "merge conflicts" is not one)
            for lead in ("when", "why", "of", "how's", "can"):
                for match in re.finditer(rf"\b{re.escape(lead)} (\w+)", lowered):
                    noun = shape == "thing" and lowered[match.start(1):].startswith(text.casefold())
                    assert noun or match.group(1) not in BARE_VERBS, (line, lead)
            assert not set(words) & MISSPELT, line
            # capitals only where the user typed them (names, acronyms); no Title Case
            for word in re.findall(r"\b\w*[A-Z]\w*\b", line):
                assert word in topic, (line, word)
        if shape != "thing":
            assert any(text in line for line in idea["texts"]) or len(text) > 40


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
    assert all(entry["label_lines"] == ["caption | blur | desk.png"] or "desk.png" in entry["label_lines"][-1]
               for entry in sheet["entries"])


def test_contact_sheet_labels_wrap_instead_of_truncating(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    name = "a-very-long-photo-filename-from-the-camera-roll-2026-10-22-0001.png"
    Image.new("RGB", (640, 480), (63, 97, 122)).save(folder / name)
    api.create_stills(folder, "release day", tmp_path / "out", n=1)
    sheet = json.loads((tmp_path / "out" / "index.json").read_text(encoding="utf-8"))["contact_sheet"]
    lines = sheet["entries"][0]["label_lines"]
    assert len(lines) >= 2 and "…" not in "".join(lines)
    assert "".join(lines).replace(" ", "").endswith(name)  # the whole filename is shown
    assert sheet["height"] == 334 + 44 + 22 * len(lines)  # the band grows with the lines
