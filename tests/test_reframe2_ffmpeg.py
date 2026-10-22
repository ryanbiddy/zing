"""Raster acceptance for intermediate coverage, dialogue moves and phone captions."""

import subprocess

import pytest

from myzing.composition import AssetRef, Composition, CompositionClip, CompositionCaption
from myzing.composition.aspects import dimensions
from myzing.composition.speakers import SpeechWord
from myzing.layout.framing import select_framing, visible_content, place_captions
from myzing.layout.types import Box, FaceTrack, Keyframe
from myzing.render.composition import render_composition

pytestmark = pytest.mark.ffmpeg


def ffmpeg(*args):
    result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', *map(str, args)],
                            capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    return result.stdout


def pixels(path, width, height):
    np = pytest.importorskip('numpy')
    return np.frombuffer(ffmpeg('-i', path, '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'),
                         dtype=np.uint8).reshape(-1, height, width, 3)


def plan_for(source, width, height, duration=1):
    c = CompositionClip(str(source), 0, duration, 0, id='clip', asset_id='s')
    return Composition(assets=[AssetRef('s', str(source), None)], clips=[c], width=width, height=height)


@pytest.mark.parametrize('aspect', ['16:9', '1:1', '9:16'])
def test_zoomfill_sharp_coverage_and_enlargement_match_rendered_pixels(tmp_path, aspect):
    source = tmp_path / 'gray.mkv'
    ffmpeg('-f', 'lavfi', '-i', 'color=c=0x999999:s=640x360:r=30:d=1', '-c:v', 'ffv1', source)
    width, height = dimensions(aspect, 180)
    plan = plan_for(source, width, height)
    f = select_framing('zoomfill', 640, 360, width, height, plan.clips[0], [])
    plan.clips[0].framing = f
    output = tmp_path / 'output.mp4'
    render_composition(plan, output)
    frames = pixels(output, width, height)
    assert len(frames) == 30
    content = visible_content(f, width, height)
    # Flat source makes the sharp/55%-luma background boundary measurable.
    row_luma = frames[10].mean(axis=(1, 2))
    sharp = (row_luma > 135).nonzero()[0]
    assert len(sharp) == pytest.approx(content.height * height, abs=2)
    assert sharp[0] == pytest.approx(content.y * height, abs=2)
    assert f.assessments[-1].enlargement <= 2.5


@pytest.mark.parametrize('mode', ['reframe', 'zoomfill'])
def test_two_generated_faces_follow_timed_speakers_without_midword_pan(tmp_path, mode):
    np = pytest.importorskip('numpy')
    source = tmp_path / 'dialogue.mkv'
    # Colored face stand-ins and two timed tone bursts; identity labels are
    # supplied evidence, not a claim that a rectangle detector understands speech.
    ffmpeg('-f', 'lavfi', '-i',
           'color=c=0x303030:s=640x360:r=30:d=6,drawbox=x=192:y=72:w=64:h=90:color=red:t=fill,'
           'drawbox=x=384:y=72:w=64:h=90:color=lime:t=fill',
           '-f', 'lavfi', '-i', r"aevalsrc=if(between(t\,0.2\,0.8)+between(t\,5\,5.8)\,0.1*sin(2*PI*440*t)\,0):s=48000:d=6",
           '-c:v', 'ffv1', '-c:a', 'pcm_s16le', source)
    tracks = [FaceTrack(name, [Keyframe(0, Box(x, .2, .1, .25)), Keyframe(6, Box(x, .2, .1, .25))])
              for name, x in [('left', .3), ('right', .6)]]
    words = [SpeechWord('s', 'One', .2, .8, 'A', 'left'), SpeechWord('s', 'Two', 5, 5.8, 'B', 'right')]
    plan = plan_for(source, 180, 320, 6)
    plan.speech_words = words
    f = select_framing(mode, 640, 360, 180, 320, plan.clips[0], tracks, speech_words=words)
    assert f.mode == mode and [t.face_track_id for t in f.speaker_turns] == ['left', 'right']
    plan.clips[0].framing = f
    output = tmp_path / 'output.mp4'
    render_composition(plan, output)
    frames = pixels(output, 180, 320)
    assert len(frames) == 180
    content = visible_content(f, 180, 320)
    for word, channel in zip(words, [0, 1]):
        centers = []
        for frame in frames[round(word.start * 30):round(word.end * 30)]:
            mask = (frame[:, :, channel] > 180) & (frame[:, :, 2] < 90)
            mask[:round(content.y * 320) + 2] = False
            mask[round(content.bottom * 320) - 2:] = False
            ys, xs = np.nonzero(mask)
            assert len(xs) > 100
            centers.append((xs.min() + xs.max()) / 2)
        assert max(abs(x - 90) for x in centers) <= 3
        assert max(centers) - min(centers) <= 1


def test_generated_rocket_top_survives_forced_crop(tmp_path):
    source = tmp_path / 'rocket.mkv'
    ffmpeg('-f', 'lavfi', '-i', 'color=c=0x303030:s=640x360:r=30:d=1,'
           'drawbox=x=300:y=0:w=40:h=320:color=white:t=fill,drawbox=x=300:y=0:w=40:h=4:color=red:t=fill',
           '-c:v', 'ffv1', source)
    rocket = FaceTrack('saliency-rocket', [Keyframe(0, Box(300/640, 0, 40/640, 320/360)),
                                          Keyframe(1, Box(300/640, 0, 40/640, 320/360))])
    plan = plan_for(source, 180, 320)
    plan.clips[0].framing = select_framing('reframe', 640, 360, 180, 320, plan.clips[0], [rocket])
    output = tmp_path / 'output.mp4'
    render_composition(plan, output)
    frames = pixels(output, 180, 320)
    red_top = frames[:, :3, 80:100, 0].mean(axis=(1,2))
    assert (red_top > 180).all()
    # An untracked diagonal nose can exit through the right edge rather than
    # the top. Forced reframe must not blindly crop it away when evidence fails.
    blind = tmp_path / 'untracked.mkv'
    ffmpeg('-f', 'lavfi', '-i', 'color=c=0x303030:s=640x360:r=30:d=1,'
           'drawbox=x=320:y=100:w=170:h=20:color=white:t=fill,drawbox=x=490:y=100:w=6:h=20:color=red:t=fill',
           '-c:v', 'ffv1', blind)
    plan = plan_for(blind, 180, 320)
    plan.clips[0].framing = select_framing('reframe', 640, 360, 180, 320, plan.clips[0], [])
    assert plan.clips[0].framing.mode == 'zoomfill'
    output = tmp_path / 'untracked-safe.mp4'
    render_composition(plan, output)
    frames = pixels(output, 180, 320)
    red = (frames[:, :, :, 0] > 140) & (frames[:, :, :, 1] < 90)
    assert (red.sum(axis=(1, 2)) > 10).all()


@pytest.mark.parametrize('aspect', ['16:9', '1:1', '9:16'])
def test_caption_contrast_and_ui_clearance_on_busy_generated_background(tmp_path, aspect):
    source = tmp_path / 'busy.mkv'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=30:d=1', '-c:v', 'ffv1', source)
    width, height = dimensions(aspect, 360)
    plan = plan_for(source, width, height)
    plan.clips[0].framing = select_framing('zoomfill', 640, 360, width, height, plan.clips[0], [])
    cap = CompositionCaption(id='cap', text='PHONE CLEAR', start=.1, end=.9, word_timed=False)
    plan.captions = [cap]
    place_captions(plan, {})
    assert cap.layout.overlap.safe
    output = tmp_path / 'output.mp4'
    render_composition(plan, output)
    frame = pixels(output, width, height)[15]
    box = cap.layout.box
    region = frame[round(box.y * height)+2:round(box.bottom * height)-2,
                   round(box.x * width)+2:round(box.right * width)-2]
    assert (region.min(axis=2) > 200).sum() > 25
    if aspect == '9:16':
        assert cap.style.outline_width >= 360 / 270 and cap.style.box_color == '#111111'
        assert ((region.max(axis=2) < 45).sum() / (region.shape[0] * region.shape[1])) > .35
        # Bright glyphs and a dark plate remain distinct on a ~400 px phone.
        assert region.min(axis=2).max() > 225
        assert .06 <= box.x and box.right <= .84 and .08 <= box.y and box.bottom <= .8
