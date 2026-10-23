"""Generated-media pixel, framing, phone and delivery-budget acceptance."""

import json
import subprocess
import sys
from dataclasses import replace

import pytest

from myzing.brief.models import Brief
from myzing.composition import AssetRef, CaptionStyle, Composition, CompositionCaption, CompositionClip
from myzing.composition.encoding import DeliveryEncoding
from myzing.layout.types import Box, EventLayout, OverlapCheck
from myzing.render.composition import render_composition
from myzing.schemas import Word

pytestmark = pytest.mark.ffmpeg


def ff(*args):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], capture_output=True, timeout=180)
    assert r.returncode == 0, r.stderr.decode(errors="replace")
    return r.stdout


def source(root, duration=3, width=640, height=360):
    path = root / "generated.mp4"
    ff("-f", "lavfi", "-i", f"testsrc2=s={width}x{height}:r=30:d={duration}", "-c:v", "libx264", "-crf", "16", path)
    return path


def plan(path, duration=3, width=640, height=360):
    return Composition(assets=[AssetRef("v", str(path), None, duration)],
        clips=[CompositionClip(str(path), 0, duration, 0, id="c", asset_id="v")], width=width, height=height)


def frame(path, time, w, h):
    np = pytest.importorskip("numpy")
    return np.frombuffer(ff("-ss", time, "-i", path, "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"), dtype=np.uint8).reshape(h, w, 3)


@pytest.mark.parametrize("opacity,radius", [(1, 0), (.85, 6)])
def test_active_box_pixels_follow_words_and_hold_through_pauses(tmp_path, opacity, radius):
    np = pytest.importorskip("numpy")
    path = source(tmp_path)
    p = plan(path)
    # Dark full phrase plate makes the pixel oracle independent of busy testsrc.
    style = CaptionStyle(40, highlight="#000000", outline_width=0, box_color="#101010",
        highlight_box_color="#FF00FF", highlight_box_padding=7, highlight_box_radius=radius,
        highlight_box_opacity=opacity, before_color="#FFFFFF", after_color="#00FF00")
    p.captions = [CompositionCaption("ONE TWO", .1, 2.5, words=[Word("ONE", .3, .8), Word("TWO", 1.3, 1.8)],
        id="words", word_timed=True, all_caps=False, style=style,
        layout=EventLayout("words", .1, 2.5, "test", OverlapCheck(True), box=Box(.1, .3, .8, .35)))]
    output = tmp_path / "highlight.mp4"
    render_composition(p, output, work_dir=tmp_path / "work")

    def plate(time):
        pixels = frame(output, time, 640, 360)[120:210, 64:576]
        mask = (pixels[:, :, 0] > 160) & (pixels[:, :, 2] > 160) & (pixels[:, :, 1] < 60)
        return pixels, mask

    centers = []
    for time in (.4, 1.4):
        pixels, mask = plate(time)
        ys, xs = np.nonzero(mask)
        assert len(xs) > 500
        centers.append(xs.mean())
        # Ink is above the plate, with black glyph pixels within its bounds.
        assert (pixels[ys.min():ys.max(), xs.min():xs.max()].max(axis=2) < 55).sum() > 100
    assert centers[1] > centers[0] + 50
    pixels, mask = plate(.2)  # Before the first word: no plate, before-color ink.
    assert mask.sum() < 20 and (pixels.min(axis=2) > 200).sum() > 100
    # The plate holds through the pause and after the last word: no blink.
    for time, center in ((.8, centers[0]), (1.0, centers[0]), (1.3 - 1/30, centers[0]), (1.3, centers[1]),
                         (1.8, centers[1]), (2.1, centers[1])):
        pixels, mask = plate(time)
        assert mask.sum() > 500 and abs(np.nonzero(mask)[1].mean() - center) < 8, time
    pixels, _ = plate(2.1)  # The finished first word shows the after color.
    assert ((pixels[:, :, 1] > 180) & (pixels[:, :, 0] < 70) & (pixels[:, :, 2] < 70)).sum() > 200
    for time, expected in ((.3 - 1/30, False), (.3, True)):
        assert bool(plate(time)[1].sum() > 500) == expected, time


@pytest.mark.parametrize("w,h", [(640, 360), (360, 360), (360, 640)])
def test_phone_caption_rule_has_rendered_ink(tmp_path, w, h):
    from myzing.layout.framing import place_captions
    from myzing.layout.readability import phone_size
    path = source(tmp_path)
    p = plan(path, width=w, height=h)
    p.brief = Brief(caption_mode="phone")
    p.captions = [CompositionCaption("PHONE SIZE", 0, 2, id="phone", word_timed=False,
                                    style=CaptionStyle(10, outline_width=2, box_color="#111111"))]
    place_captions(p, {}, {"v": (640, 360)})
    assert p.captions[0].style.size >= phone_size(w, h) - .01
    output = tmp_path / "phone.mp4"
    render_composition(p, output)
    pixels = frame(output, .5, w, h)
    b = p.captions[0].layout.box
    ink = pixels[int(b.y*h):int(b.bottom*h), int(b.x*w):int(b.right*w)].min(axis=2) > 200
    assert ink.sum() > 50


def test_generated_broadcast_frame_crops_chrome_through_cli(tmp_path):
    from myzing.layout.picture import analyze_picture
    live = source(tmp_path, 3, 640, 360)
    framed = tmp_path / "broadcast.mp4"
    ff("-i", live, "-vf", "lutyuv=y='100+val*0.4',pad=640:480:0:40:color=0x020210,drawbox=x=20:y=425:w=280:h=25:color=0x1020a0:t=fill",
       "-c:v", "libx264", "-crf", "12", framed)
    evidence = analyze_picture(framed, [(0, 3)], (640, 480))
    assert evidence["confident"], evidence
    assert evidence["bounds_pixels"] == pytest.approx([0, 40, 640, 360], abs=4)
    p = plan(framed, width=640, height=480)
    document = tmp_path / "plan.json"
    document.write_text(p.to_json(), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "myzing.cli", "render", str(document), "-o", str(tmp_path / "delivery.mp4"),
         "--aspect", "1:1,9:16", "--short-side", "360", "--picture-crop", "on", "--framing", "fill"],
         capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    for aspect, height in (("1x1", 360), ("9x16", 640)):
        saved = json.loads((tmp_path / f"delivery.{aspect}.json").read_text())
        assert saved["clips"][0]["framing"]["picture"]["confident"]
        pixels = frame(tmp_path / f"delivery.{aspect}.mp4", 1, 360, height)
        assert pixels[:5].mean() > 45 and pixels[-5:].mean() > 45


def test_two_pass_2_5_mb_target_within_ten_percent(tmp_path):
    path = source(tmp_path, 8, 960, 540)
    p = plan(path, 8, 960, 540)
    p.delivery = DeliveryEncoding(target_mb=2.5)
    result = render_composition(p, tmp_path / "budget.mp4", work_dir=tmp_path / "work")
    receipt = result.delivery_measurements
    assert abs(receipt["relative_size_error"]) <= .10, receipt
    assert receipt["quality"]["mean_encoder_qp"] is not None
    assert "-crf" not in result.command and "-pass" in result.command
    assert (tmp_path / "budget.encoding.json").is_file()


def test_tight_budget_warns_of_quality_loss(tmp_path):
    path = source(tmp_path, 3)
    p = plan(path)
    p.delivery = DeliveryEncoding(video_bitrate_kbps=40)
    result = render_composition(p, tmp_path / "low.mp4")
    assert any("visible quality loss" in w for w in result.warnings)


def gray_live(root, duration=3, size="640x352"):
    """Neutral-chroma moving picture: any saturated output pixel is chrome."""
    path = root / "live.mp4"
    ff("-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={duration}", "-vf",
       "noise=alls=24:allf=t,lutyuv=y='100+val*0.4':u=128:v=128", "-c:v", "libx264", "-crf", "14", path)
    return path


def saturated(pixels):
    return (pixels.max(axis=-1).astype(int) - pixels.min(axis=-1).astype(int)) > 70


def test_off_grid_chrome_never_reaches_the_crop_or_the_blur_fill(tmp_path):
    np = pytest.importorskip("numpy")
    from myzing.layout.picture import analyze_picture
    framed = tmp_path / "broadcast.mp4"
    # Picture rows 43..395: both borders fall inside a 2-row analysis sample.
    ff("-i", gray_live(tmp_path), "-vf", "pad=640:480:0:43:color=0x05091a,"
       "drawbox=x=0:y=420:w=640:h=34:color=0xFF00FF:t=fill,drawbox=x=12:y=8:w=150:h=22:color=0xFF00FF:t=fill",
       "-c:v", "libx264", "-crf", "12", framed)
    evidence = analyze_picture(framed, [(0, 3)], (640, 480))
    assert evidence["confident"] and evidence["surround"]["kind"] == "chrome", evidence
    x, y, w, h = evidence["bounds_pixels"]
    assert y >= 43 and y + h <= 395 and (x, w) == (0, 640)
    p = plan(framed, width=640, height=480)
    document = tmp_path / "plan.json"
    document.write_text(p.to_json(), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "myzing.cli", "render", str(document), "-o", str(tmp_path / "d.mp4"),
                        "--aspect", "1:1,9:16", "--short-side", "360", "--picture-crop", "on", "--framing", "blurfill"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    for aspect, height in (("1x1", 360), ("9x16", 640)):
        saved = json.loads((tmp_path / f"d.{aspect}.json").read_text())
        assert saved["clips"][0]["framing"]["mode"] == "blurfill"
        for time in (.5, 1.5, 2.5):
            assert saturated(frame(tmp_path / f"d.{aspect}.mp4", time, 360, height)).sum() == 0


def test_letterbox_matte_keeps_the_full_frame(tmp_path):
    from myzing.layout.picture import analyze_picture
    letterboxed = tmp_path / "letterbox.mp4"
    ff("-i", gray_live(tmp_path, size="640x268"), "-vf", "pad=640:360:0:46:color=black", "-c:v", "libx264", "-crf", "12",
       letterboxed)
    evidence = analyze_picture(letterboxed, [(0, 3)], (640, 360))
    assert not evidence["confident"]
    assert evidence["ranges"][0]["surround"]["kind"] == "matte"
    p = plan(letterboxed)
    document = tmp_path / "plan.json"
    document.write_text(p.to_json(), encoding="utf-8")
    base = [sys.executable, "-m", "myzing.cli", "render", str(document), "--aspect", "9:16", "--short-side", "360"]
    r = subprocess.run([*base, "-o", str(tmp_path / "auto.mp4"), "--picture-crop", "auto"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "picture" not in json.loads((tmp_path / "auto.9x16.json").read_text())["clips"][0]["framing"]
    r = subprocess.run([*base, "-o", str(tmp_path / "on.mp4"), "--picture-crop", "on"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode != 0 and "letterbox" in (r.stderr + r.stdout)


def test_short_clip_size_target_is_a_cap(tmp_path):
    path = tmp_path / "short.mp4"
    ff("-f", "lavfi", "-i", "mandelbrot=s=640x360:r=30", "-f", "lavfi", "-i", "sine=d=1", "-t", "1",
       "-c:v", "libx264", "-crf", "12", "-c:a", "aac", path)
    p = plan(path, 1)
    p.delivery = DeliveryEncoding(target_mb=.1)
    result = render_composition(p, tmp_path / "cap.mp4", work_dir=tmp_path / "work")
    receipt = result.delivery_measurements
    assert receipt["achieved_bytes"] <= 100_000, receipt
    assert receipt["achieved_bytes"] == (tmp_path / "cap.mp4").stat().st_size
    assert receipt["audio_bytes"] > 0 and not any("over the" in w for w in result.warnings)


def test_vertical_phone_captions_sit_in_the_raised_lower_band(tmp_path):
    np = pytest.importorskip("numpy")
    from myzing.layout.framing import place_captions, select_framing, visible_content
    live = gray_live(tmp_path, size="1280x560")
    p = plan(live, width=720, height=1280)
    p.clips[0].framing = select_framing("zoomfill", 1280, 560, 720, 1280, p.clips[0], [])
    p.brief = Brief(caption_mode="phone")
    words = [Word("ALPHA", .2, .4), Word("BRAVO", .4, .6), Word("CHARLIE", .6, .8), Word("DELTA", .8, 1.0),
             Word("ECHO", 1.2, 1.6), Word("FOXTROT", 1.6, 2.4)]
    style = CaptionStyle(60, outline_width=0, box_color="#00FF00")
    p.captions = [CompositionCaption("ALPHA BRAVO CHARLIE DELTA", .2, 1.0, words=words[:4], id="a", word_timed=True,
                                     style=style),
                  CompositionCaption("ECHO FOXTROT", 1.2, 2.4, words=words[4:], id="b", word_timed=True, style=style)]
    place_captions(p, {}, {"v": (1280, 560)})
    picture = visible_content(p.clips[0].framing, 720, 1280)
    assert p.clips[0].framing.foreground_top is not None
    assert {c.layout.box.y for c in p.captions} == {picture.bottom}
    output = tmp_path / "band.mp4"
    render_composition(p, output)
    for time in (.5, 1.8):
        pixels = frame(output, time, 720, 1280)
        rows = np.nonzero((saturated(pixels) & (pixels[:, :, 1] > 150)).any(axis=1))[0]
        assert len(rows) and rows.min() >= picture.bottom * 1280 - 1 and rows.max() < .8 * 1280
        # The sharp (noisy) picture starts where the plan says; blur is above it.
        top = round(picture.y * 1280)
        detail = [np.abs(np.diff(pixels[row, :, 1].astype(int))).mean() for row in (top - 4, top + 4)]
        assert detail[1] > 3 * detail[0], detail


@pytest.mark.parametrize("text", ["WIDE WWW ill", "WIDE WWW\nill"])
def test_highlight_states_never_move_glyphs(tmp_path, text):
    """The plate is drawn behind the phrase; word states only recolor glyphs."""
    np = pytest.importorskip("numpy")
    path = tmp_path / "flat.mp4"
    ff("-f", "lavfi", "-i", "color=0x404040:s=640x360:r=30:d=3", "-c:v", "libx264", "-qp", "0", path)
    p = plan(path)
    words = [Word("WIDE", .2, .6), Word("WWW", .8, 1.2), Word("ill", 1.4, 1.8)]
    style = CaptionStyle(44, color="#FFFFFF", highlight="#FFFFFF", outline_width=0, highlight_box_color="#FF00FF",
                         highlight_box_padding=9, highlight_box_radius=5)
    p.captions = [CompositionCaption(text, .1, 2.5, words=words, id="c", word_timed=True, all_caps=False, style=style,
                                     layout=EventLayout("c", .1, 2.5, "test", OverlapCheck(True), box=Box(.1, .25, .8, .5)))]
    output = tmp_path / "states.mp4"
    render_composition(p, output)
    ink = [frame(output, t, 640, 360).min(axis=2) > 200 for t in (.15, .4, 1.0, 1.6, 2.2)]
    plates = [saturated(frame(output, t, 640, 360)).sum() for t in (.15, .4, 1.0, 1.6, 2.2)]
    # No plate before the first word; afterwards it holds, without a blink.
    assert plates[0] == 0 and min(plates[1:]) > 300
    reference = ink[0].sum(axis=0).astype(float)
    for mask in ink[1:]:
        ys, xs = np.nonzero(mask)
        ys0, xs0 = np.nonzero(ink[0])
        assert abs(xs.min() - xs0.min()) <= 1 and abs(xs.max() - xs0.max()) <= 1
        assert abs(ys.min() - ys0.min()) <= 1 and abs(ys.max() - ys0.max()) <= 1
        profile = mask.sum(axis=0).astype(float)
        assert max(range(-6, 7), key=lambda s: float((np.roll(profile, s) * reference).sum())) == 0
