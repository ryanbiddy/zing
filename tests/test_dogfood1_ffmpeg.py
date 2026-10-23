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
def test_active_box_pixels_follow_words_and_leave_gaps(tmp_path, opacity, radius):
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
    centers = []
    for time in (.4, 1.4):
        pixels = frame(output, time, 640, 360)[120:210, 64:576]
        mask = (pixels[:, :, 0] > 160) & (pixels[:, :, 2] > 160) & (pixels[:, :, 1] < 60)
        ys, xs = np.nonzero(mask)
        assert len(xs) > 500
        centers.append(xs.mean())
        # Ink is above the plate, with black glyph pixels within its bounds.
        assert (pixels[ys.min():ys.max(), xs.min():xs.max()].max(axis=2) < 55).sum() > 100
    assert centers[1] > centers[0] + 50
    for time in (.2, 1.0, 2.1):
        pixels = frame(output, time, 640, 360)[120:210, 64:576]
        assert ((pixels[:, :, 0] > 160) & (pixels[:, :, 2] > 160) & (pixels[:, :, 1] < 60)).sum() < 20
        if time == .2:
            assert (pixels.min(axis=2) > 200).sum() > 100
        if time == 2.1:
            assert ((pixels[:, :, 1] > 180) & (pixels[:, :, 0] < 70) & (pixels[:, :, 2] < 70)).sum() > 200
    for time, expected in ((.3-1/30, False), (.3, True), (.8, False), (1.3, True), (1.8, False)):
        pixels = frame(output, time, 640, 360)[120:210, 64:576]
        present = ((pixels[:, :, 0] > 160) & (pixels[:, :, 2] > 160) & (pixels[:, :, 1] < 60)).sum() > 500
        assert bool(present) == expected


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
