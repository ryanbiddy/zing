"""R9 pixel acceptance. All media is generated; fonts are the bundled OFL files."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import struct
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from myzing.composition import AssetRef, CaptionStyle, Composition, CompositionClip, LoudnessTarget
from myzing.layout.types import Box, EventLayout, Keyframe, OverlapCheck, box_at
from myzing.project.models import Rational
from myzing.render import render_composition
from myzing.render import pipeline
from myzing.render.validation import EDLValidationError
from myzing.schemas import Word
from test_positioned_caption_timing import RATES, SHORT_WORDS, WORD_FRAMES
from test_render_composition import ROOT, caption, font_ref

pytestmark = pytest.mark.ffmpeg


def ffmpeg(*args, cwd=None):
    result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
                            cwd=cwd, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    root = tmp_path_factory.mktemp("r9-source")
    source = root / "generated black.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=black:s=640x360:r=30:d=3", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", source)
    return source


def composition(source, events, fps=Rational(30, 1)):
    return Composition(assets=[AssetRef("video", str(source), hashlib.sha256(source.read_bytes()).hexdigest(), aliases=["source-id"])],
                       clips=[CompositionClip("source-id", 0, 3, 0, id="clip", asset_id="video")],
                       captions=events, width=640, height=360, fps=fps)


def frames(path):
    np = pytest.importorskip("numpy")
    raw = ffmpeg("-i", path, "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 360, 640, 3)


def bounds(mask):
    np = pytest.importorskip("numpy")
    ys, xs = np.nonzero(mask)
    assert len(xs), "no text pixels found"
    return tuple(float(v) for v in (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def center(mask):
    l, t, r, b = bounds(mask)
    return (l + r) / 2 / 640, (t + b) / 2 / 360


def render(tmp_path, c, name="output"):
    output = tmp_path / f"{name}.mp4"
    return render_composition(c, output, work_dir=tmp_path / f"{name}-work")


@pytest.mark.parametrize("fps", [Rational(30, 1), Rational(30000, 1001), Rational(60, 1), Rational(100, 1)])
def test_each_word_highlight_switches_within_one_output_frame(tmp_path, source, fps):
    np = pytest.importorskip("numpy")
    words = [Word("ONE", .217, .617), Word("TWO", .743, 1.123, timing={
        "version": 1, "status": "corrected", "method": "user_correction",
        "original": {"start": .743, "end": .743}, "adjustments": []}), Word("THREE", 1.267, 1.783)]
    c = composition(source, [caption(text="ONE TWO THREE", words=words, word_timed=True)], fps)
    before = c.to_json()
    result = render(tmp_path, c)
    decoded = frames(result.output_path)
    rate = fps.numerator / fps.denominator
    yellow = (decoded[:, :, :, 0] > 160) & (decoded[:, :, :, 1] > 160) & (decoded[:, :, :, 2] < 100)
    centroids = [center(yellow[round((w.start + w.end) / 2 * rate)])[0] for w in words]
    assert centroids[0] < centroids[1] < centroids[2]
    for i, word in enumerate(words):
        selected = [n for n, mask in enumerate(yellow) if mask.sum() > 10
                    and abs(center(mask)[0] - centroids[i]) < .03]
        assert selected
        assert abs(selected[0] / rate - word.start) <= 1 / rate + 1e-6
        assert abs((selected[-1] + 1) / rate - word.end) <= 1 / rate + 1e-6
        assert selected == list(range(selected[0], selected[-1] + 1))
    assert not yellow[0].any() and not yellow[math.ceil(2 * rate)].any()
    assert c.to_json() == before  # Measured/corrected provenance survives unchanged.
    metadata = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate", "-of", "json", str(result.output_path)], capture_output=True, check=True).stdout)
    assert metadata["streams"][0]["r_frame_rate"] == f"{fps.numerator}/{fps.denominator}"


@pytest.mark.parametrize("alignment", ["left", "center", "right"])
def test_static_multiline_ink_position_and_alignment(tmp_path, source, alignment):
    np = pytest.importorskip("numpy")
    box = Box(.23, .27, .55, .4)
    e = caption(text="WIDE CAPTION\nSHORT", alignment=alignment, style=CaptionStyle(36, outline_width=0))
    e.layout = replace(e.layout, box=box)
    image = frames(render(tmp_path, composition(source, [e])).output_path)[15]
    mask = image.min(axis=2) > 150
    l, t, r, b = bounds(mask)
    actual_x = {"left": l / 640, "center": (l + r) / 2 / 640, "right": r / 640}[alignment]
    expected_x = {"left": box.x, "center": box.center[0], "right": box.right}[alignment]
    assert abs(actual_x - expected_x) <= .02
    assert abs((t + b) / 2 / 360 - box.center[1]) <= .02
    rows = np.flatnonzero(mask.any(axis=1))
    split = next((int(a + b) // 2 for a, b in zip(rows, rows[1:]) if b - a > 3), None)
    assert split is not None, "explicit newline must produce two separated lines"
    first, second = bounds(mask[:split]), bounds(mask[split:])
    x = {"left": lambda b: b[0], "center": lambda b: (b[0] + b[2]) / 2, "right": lambda b: b[2]}[alignment]
    assert abs(x(first) - x(second)) <= 3


@pytest.mark.parametrize("key_count", [2, 4])
def test_caption_center_follows_piecewise_path(tmp_path, source, key_count):
    keys = [Keyframe(.1, Box(.08, .14, .4, .2)), Keyframe(1, Box(.48, .2, .4, .2)),
            Keyframe(1.9, Box(.3, .65, .4, .2)), Keyframe(2.9, Box(.06, .45, .4, .2))]
    if key_count == 2:
        keys = [keys[0], keys[-1]]
    e = caption(text="MOVE WITH ME", start=.1, end=2.9, word_timed=True,
                words=[Word("MOVE", .1, 1), Word("WITH", 1, 1.9), Word("ME", 1.9, 2.9)],
                layout=EventLayout("caption", .1, 2.9, "explicit-path", OverlapCheck(True), path=keys))
    result = render(tmp_path, composition(source, [e]))
    decoded = frames(result.output_path)
    for index in [3, 13, 29, 30, 39, 56, 57, 70, 86]:
        expected = box_at(keys, index / 30).center
        actual = center(decoded[index].max(axis=2) > 150)
        assert all(abs(a - b) <= .02 for a, b in zip(actual, expected)), (index, actual, expected)
    ass = (result.work_dir / "captions.ass").read_text(encoding="utf-8")
    assert r"\move(" in ass


def drawtext_mask(tmp_path, text, font, size):
    np = pytest.importorskip("numpy")
    (tmp_path / "literal.txt").write_text(text, encoding="utf-8", newline="\n")
    # Stage the exact original face, using simple filter-local paths on Windows.
    (tmp_path / "original.ttf").write_bytes(Path(font.path).read_bytes())
    raw = ffmpeg("-f", "lavfi", "-i", "color=black:s=640x360:r=1:d=1", "-vf",
                  f"drawtext=fontfile='original.ttf':textfile='literal.txt':expansion=none:fontsize={size}:fontcolor=white:x=10:y=10",
                  "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1", cwd=tmp_path)
    return np.frombuffer(raw, dtype=np.uint8).reshape(360, 640, 3).min(axis=2) > 150


def crop(mask):
    l, t, r, b = map(int, bounds(mask))
    return mask[t:b, l:r]


def test_ass_special_characters_are_literal_like_independent_drawtext(tmp_path, source):
    np = pytest.importorskip("numpy")
    text = "{} \\N \\n \\h {\\pos(0,0)}\nEND \\\\"
    e = caption(text=text, all_caps=False, style=CaptionStyle(28, outline_width=0),
                layout=EventLayout("caption", 0, 2, "fixture", OverlapCheck(True), box=Box(.05, .15, .9, .7)))
    actual = crop(frames(render(tmp_path, composition(source, [e])).output_path)[15].min(axis=2) > 150)
    expected = crop(drawtext_mask(tmp_path, text, e.font, 28))
    # Compare each line separately: drawtext and ASS use different line gaps.
    def lines(mask):
        rows = np.flatnonzero(mask.any(axis=1))
        breaks = np.where(np.diff(rows) > 3)[0]
        return [crop(mask[part[0]:part[-1] + 1]) for part in np.split(rows, breaks + 1)]
    a_lines, b_lines = lines(actual), lines(expected)
    assert len(a_lines) == len(b_lines) == 2
    for a, b in zip(a_lines, b_lines):
        assert abs(a.shape[0] - b.shape[0]) <= 2 and abs(a.shape[1] - b.shape[1]) <= 3
        # Align within raster rounding, then compare actual glyph pixels.
        score = 0
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                canvas_a = np.zeros((max(a.shape[0], b.shape[0]) + 8, max(a.shape[1], b.shape[1]) + 8), dtype=bool)
                canvas_b = canvas_a.copy()
                canvas_a[4:4 + a.shape[0], 4:4 + a.shape[1]] = a
                canvas_b[4 + dy:4 + dy + b.shape[0], 4 + dx:4 + dx + b.shape[1]] = b
                score = max(score, (canvas_a & canvas_b).sum() / (canvas_a | canvas_b).sum())
        assert score >= .65, score


def test_exact_font_files_and_output_pixel_size(tmp_path, source):
    np = pytest.importorskip("numpy")
    events = []
    for i, name in enumerate(["Anton-Regular.ttf", "IBMPlexSans.ttf"]):
        events.append(caption(text="GLYPH TEST", id=f"font-{i}", start=i, end=i + 1,
            font=font_ref(name), style=CaptionStyle(42, outline_width=0),
            layout=EventLayout(f"font-{i}", i, i + 1, "fixture", OverlapCheck(True), box=Box(.1, .2, .8, .5))))
    # Same OFL outlines, light weight metadata: normal ASS \b0 would synthesize
    # bold and alter this face. Rebuild checksums through the font registrar.
    from myzing.composition import FontAsset
    from myzing.render.font_files import private_font
    light = bytearray(Path(events[0].font.path).read_bytes())
    for i in range(struct.unpack_from(">H", light, 4)[0]):
        tag, _, offset, _ = struct.unpack_from(">4sIII", light, 12 + i * 16)
        if tag == b"OS/2":
            struct.pack_into(">H", light, offset + 4, 100)
    light_path = tmp_path / "generated-light-font.ttf"
    light_path.write_bytes(private_font(bytes(light))[1])
    events.append(replace(events[0], id="font-light", start=2, end=3,
        font=FontAsset(str(light_path), hashlib.sha256(light_path.read_bytes()).hexdigest(), "OFL-1.1"),
        layout=replace(events[0].layout, id="font-light", start=2, end=3)))
    result = render(tmp_path, composition(source, events))
    decoded = frames(result.output_path)
    masks = [decoded[15 + i * 30].min(axis=2) > 150 for i in range(3)]
    assert np.count_nonzero(masks[0] ^ masks[1]) > 800
    assert np.count_nonzero(masks[0] ^ masks[2]) / masks[0].sum() < .03
    for event, mask in zip(events, masks):
        expected = crop(drawtext_mask(tmp_path, event.text, event.font, 42))
        actual = crop(mask)
        assert abs(actual.shape[0] / expected.shape[0] - 1) <= .10
        assert abs(actual.shape[1] / expected.shape[1] - 1) <= .10
        # Bounding-box IoU after aligning centers, independently sized by drawtext.
        intersection = min(actual.shape[0], expected.shape[0]) * min(actual.shape[1], expected.shape[1])
        union = actual.size + expected.size - intersection
        assert intersection / union >= .8
    registered = json.loads((result.work_dir / "caption-fonts.json").read_text())
    assert len({f["registered_family"] for f in registered}) == 3
    assert all(Path(e.font.path).read_bytes() for e in events)


def test_plate_outline_colors_and_layout_scale(tmp_path, source):
    e = caption(text="COLOR", style=CaptionStyle(60, color="#00FFFF", outline_color="#00FF00", outline_width=4, box_color="#FF00FF"))
    e.layout = replace(e.layout, scale=.7, box=Box(.3, .3, .4, .3), fallback="smaller-box")
    result = render(tmp_path, composition(source, [e]))
    image = frames(result.output_path)[15]
    red, green, blue = [image[:, :, i] for i in range(3)]
    plate = (red > 150) & (blue > 150) & (green < 100)
    outline = (green > 130) & (red < 100) & (blue < 100)
    fill = (green > 150) & (blue > 150) & (red < 100)
    assert plate.sum() > 10000 and outline.sum() > 200 and fill.sum() > 400
    l, t, r, b = bounds(plate)
    assert max(abs(l / 640 - .3), abs(t / 360 - .3), abs(r / 640 - .7), abs(b / 360 - .6)) <= .02
    reference = crop(drawtext_mask(tmp_path, "COLOR", e.font, 42))
    assert abs(crop(fill).shape[0] / reference.shape[0] - 1) <= .10


def test_unsafe_layout_requires_explicit_acceptance_even_with_real_media(tmp_path, source):
    e = caption()
    e.layout = replace(e.layout, overlap=OverlapCheck(False, mask_names=["ui"]), reason="infeasible", warnings=["infeasible: no safe box"])
    c = composition(source, [e])
    with pytest.raises(EDLValidationError, match="caption caption: unsafe"):
        render(tmp_path, c)
    assert not (tmp_path / "output-work").exists()
    c.accepted_unsafe_layouts = ["caption"]
    result = render(tmp_path, c)
    assert (frames(result.output_path)[15].max(axis=2) > 150).any()
    assert any("explicitly accepted" in w for w in result.warnings)


def test_unsupported_feature_fails_before_rendering_real_media(tmp_path, source, monkeypatch):
    c = composition(source, [caption()])
    c.loudness_target = LoudnessTarget(-16, -1)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("FFmpeg/ffprobe started"))
    with pytest.raises(EDLValidationError, match="not yet supported in this renderer: loudness targets"):
        render(tmp_path, c)
    assert not (tmp_path / "output-work").exists()


@pytest.mark.parametrize("kind", ["media", "font"])
def test_sha256_mismatch_stops_before_any_render_work(tmp_path, source, monkeypatch, kind):
    c = composition(source, [caption()])
    if kind == "media":
        c.assets[0].sha256 = "0" * 64
    else:
        c.captions[0].font.sha256 = "0" * 64
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("FFmpeg/ffprobe started"))
    with pytest.raises(EDLValidationError, match="SHA-256 mismatch"):
        render(tmp_path, c)
    assert not (tmp_path / "output-work").exists()


def test_cli_v2_resolves_relative_assets_fonts_and_hard_cuts(tmp_path, source):
    from myzing.composition import CompositionAudio, Transition, TransitionRecipe
    project = tmp_path / "moved project's directory"
    project.mkdir()
    (project / "source.mp4").write_bytes(source.read_bytes())
    c = composition(project / "source.mp4", [caption()])
    c.assets[0].path = "source.mp4"
    c.clips[0].src_out = 1
    c.clips.append(CompositionClip("source-id", 1, 3, 1, id="clip-2", asset_id="video"))
    c.transitions = [Transition("cut", "clip", "clip-2", 1, 1, TransitionRecipe("hard_cut", 0, "fixture cut"))]
    (project / "font.ttf").write_bytes(Path(c.captions[0].font.path).read_bytes())
    c.captions[0].font.path = "font.ttf"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=800:duration=3", project / "voice.wav")
    c.assets.append(AssetRef("voice", "voice.wav", hashlib.sha256((project / "voice.wav").read_bytes()).hexdigest()))
    c.audio.append(CompositionAudio("voice.wav", "voiceover", id="voice", asset_id="voice", role="voiceover"))
    file = project / "edit.json"
    file.write_text(c.to_json(), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "myzing.cli", "render", str(file), "--keep-work", str(project / "work")],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    output = file.with_suffix(".mp4")
    assert len(frames(output)) == 90
    raw = ffmpeg("-i", output, "-map", "0:a:0", "-f", "s16le", "pipe:1")
    assert max(abs(v[0]) for v in __import__("struct").iter_unpack("<h", raw)) > 1000


def test_overflow_fails_without_publishing_or_silently_wrapping(tmp_path, source):
    e = caption(text="THIS PHRASE CANNOT FIT", style=CaptionStyle(80))
    e.layout = replace(e.layout, box=Box(.4, .4, .1, .1))
    with pytest.raises(EDLValidationError, match="caption caption: text/outline/plate exceeds its layout box"):
        render(tmp_path, composition(source, [e]))
    assert not (tmp_path / "output.mp4").exists()


def test_missing_glyph_fails_instead_of_using_system_font(tmp_path, source):
    with pytest.raises(EDLValidationError, match="without font substitution"):
        render(tmp_path, composition(source, [caption(text="HI \U0001f680")]))
    assert not (tmp_path / "output.mp4").exists()


def test_real_v1_render_keeps_pre_r9_command_graph_and_ass_bytes(tmp_path, source):
    from myzing.schemas import EDL

    baseline = json.loads((ROOT / "tests/fixtures/render-v1-baseline.json").read_text(encoding="utf-8"))
    edl = EDL.from_dict(baseline["edl"])
    edl.clips[0].src = str(source)
    result = pipeline.render_edl(edl, tmp_path / "legacy.mp4", work_dir=tmp_path / "legacy-work")
    major = pipeline.ffmpeg_major_version("ffmpeg")
    expected = baseline["commands"]["6" if major is not None and major < 7 else "9"]
    paths = {"source.mp4": str(source), "graph.txt": str(result.work_dir / "filter graph.txt"),
             "output.mp4": str(result.work_dir / "rendered.mp4")}
    assert list(result.command) == [paths.get(arg, arg) for arg in expected]
    assert result.filtergraph.encode() == baseline["graph"].encode()
    assert hashlib.sha256((result.work_dir / "captions.ass").read_bytes()).hexdigest() == baseline["ass_sha256"][os.name]
    decoded = frames(result.output_path)
    assert len(decoded) == 60 and (decoded[15].max(axis=2) > 150).any()


@pytest.mark.parametrize(("fps", "expected"), list(zip(RATES, WORD_FRAMES)))
def test_subframe_words_highlight_on_exact_frames_without_overlap(tmp_path, source, fps, expected):
    np = pytest.importorskip("numpy")
    e = caption(text="A B C D E F G H", end=2.911, words=SHORT_WORDS, word_timed=True,
                style=CaptionStyle(42, outline_width=0),
                layout=EventLayout("caption", 0, 2.911, "fixture", OverlapCheck(True), box=Box(.1, .3, .8, .3)))
    c = composition(source, [e], fps)
    before = c.to_json()
    result = render(tmp_path, c)
    decoded = frames(result.output_path)
    # Locate each glyph independently from the unhighlighted phrase. Each
    # one-letter word has a separate horizontal ink span, in transcript order.
    columns = np.flatnonzero((decoded[0].min(axis=2) > 150).any(axis=0))
    spans = np.split(columns, np.where(np.diff(columns) > 1)[0] + 1)
    assert len(spans) == len(SHORT_WORDS)
    for index, image in enumerate(decoded):
        yellow = (image[:, :, 0] > 160) & (image[:, :, 1] > 160) & (image[:, :, 2] < 100)
        actual = [i for i, span in enumerate(spans) if yellow[:, span].sum() > 10]
        wanted = [i for i, (start, end) in enumerate(expected) if start <= index < end]
        assert actual == wanted, (fps, index, actual, wanted)
    assert c.to_json() == before
    assert any("word 1 'A' render timing" in w for w in result.warnings)
    if fps.numerator != 100:
        assert any("render window" in w for w in result.warnings)


@pytest.mark.parametrize("fps", RATES[:5])
@pytest.mark.parametrize("plate", [False, True])
def test_fast_multi_keyframe_path_matches_plan_on_every_output_frame(tmp_path, source, fps, plate):
    from fractions import Fraction

    a, b, c = Box(.05, .15, .22, .18), Box(.68, .15, .25, .22), Box(.34, .65, .3, .25)
    keys = [Keyframe(t, box) for t, box in [
        (.1, a), (.201, a), (.208, b), (.219, c), (.225, a),
        (.501, b), (.505, a), (.511, c), (.521, b),
        (1.01, a), (1.02, c), (1.03, b),
        (1.801, c), (1.807, b), (1.819, a), (2.9, c),
    ]]
    e = caption(text="ZIP", start=.1, end=2.9, style=CaptionStyle(
        26, outline_width=0, box_color="#FF00FF" if plate else None),
        layout=EventLayout("caption", .1, 2.9, "explicit-path", OverlapCheck(True), path=keys))
    result = render(tmp_path, composition(source, [e], fps))
    for index, image in enumerate(frames(result.output_path)):
        time = Fraction(index * fps.denominator, fps.numerator)
        ink = image.min(axis=2) > 150
        if not Fraction("0.1") <= time < Fraction("2.9"):
            assert not ink.any(), (fps, index)
            continue
        expected = box_at(keys, time)
        actual = center(ink)
        assert all(abs(a - b) <= .02 for a, b in zip(actual, expected.center)), (fps, index, actual, expected)
        if plate:
            magenta = (image[:, :, 0] > 150) & (image[:, :, 1] < 100) & (image[:, :, 2] > 150)
            l, t, r, b = bounds(magenta)
            assert max(abs(l / 640 - expected.x), abs(t / 360 - expected.y),
                       abs(r / 640 - expected.right), abs(b / 360 - expected.bottom)) <= .02, (fps, index)


@pytest.mark.parametrize("fps", RATES)
def test_one_frame_events_switch_exactly_on_every_frame_across_a_cut(tmp_path, source, fps):
    from fractions import Fraction

    count = int(Fraction(28, 10) * fps.numerator / fps.denominator)
    events = []
    for index in range(count):
        time = Fraction(index * fps.denominator, fps.numerator)
        start, end = float(max(0, time - Fraction(1, 1000))), float(time + Fraction(1, 1000))
        events.append(caption(id=f"frame-{index}", text="I", start=start, end=end,
            word_timed=True, words=[Word("I", start, end)],
            style=CaptionStyle(42, outline_width=0, highlight="#00FFFF" if index % 2 else "#FFFF00"),
            layout=EventLayout(f"frame-{index}", start, end, "fixture", OverlapCheck(True), box=Box(.2, .3, .6, .3))))
    c = composition(source, events, fps)
    c.clips[0].src_out = 1
    c.clips.append(CompositionClip("source-id", 1, 3, 1, id="clip-2", asset_id="video"))
    result = render(tmp_path, c)
    for index, image in enumerate(frames(result.output_path)):
        yellow = ((image[:, :, 0] > 160) & (image[:, :, 1] > 160) & (image[:, :, 2] < 100)).sum() > 10
        cyan = ((image[:, :, 0] < 100) & (image[:, :, 1] > 160) & (image[:, :, 2] > 160)).sum() > 10
        assert (bool(yellow), bool(cyan)) == (
            index < count and index % 2 == 0, index < count and index % 2 == 1,
        ), (fps, index, yellow, cyan)
