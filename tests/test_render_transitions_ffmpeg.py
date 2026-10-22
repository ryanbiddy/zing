"""R15 decoded-pixel, frame, audio and detector oracles on generated media."""

import hashlib
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="install myzing[color] for transition pixel oracles")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from myzing.composition import ColorTransform, CompositionClip, SourceRange, Transition, TransitionRecipe
from myzing.project.models import Rational
from myzing.render import pipeline, render_composition
from myzing.render.validation import EDLValidationError
from myzing.study.transitions import detect_transition_signatures
from tools.eval.render_transition_fixture import RECIPES, make_sources, pair_plan, run

pytestmark = pytest.mark.ffmpeg


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    return make_sources(tmp_path_factory.mktemp("r15 source's [paths],"))


@pytest.fixture(scope="module")
def textures(tmp_path_factory):
    return make_sources(tmp_path_factory.mktemp("r15 textures"), textures=True)


def decode(path, *, gray=False):
    data = run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "rawvideo",
                "-pix_fmt", "gray" if gray else "rgb24", "-"])
    return np.frombuffer(data, dtype=np.uint8).reshape((-1, 160, 160) if gray else (-1, 160, 160, 3)).astype(float)


def audio(path):
    data = run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ar", "48000",
                "-ac", "1", "-f", "f32le", "-"])
    return np.frombuffer(data, dtype="<f4")


def render(tmp_path, c, name="render"):
    return render_composition(c, tmp_path / f"{name}.mp4", work_dir=tmp_path / f"{name}-work")


@pytest.mark.parametrize("kind,direction", RECIPES, ids=[k + (f"-{d}" if d else "") for k, d in RECIPES])
def test_supported_transition_pixels_frames_duration_audio(tmp_path, sources, kind, direction):
    c = pair_plan(sources, kind, direction)
    result = render(tmp_path, c)
    frames = decode(result.output_path)
    d = c.transitions[0].recipe.duration_seconds
    start, end = round((2 - d) * 30), 60
    assert len(frames) == round((4 - d) * 30)
    assert abs(pipeline.probe_media(result.output_path).duration - (4 - d)) <= 1 / 30
    # Ignore the counter strip for the color oracle. All pre/post frames must
    # be the correct scene, catching early/late switches and blank frames.
    colors = np.median(frames[:, 16:140, 16:140], axis=(1, 2))
    red, blue = colors[5], colors[-5]
    assert np.max(np.abs(colors[:start] - red)) < 5
    assert np.max(np.abs(colors[end:] - blue)) < 5
    if kind == "dissolve":
        for i in range(start, end + 1):
            progress = (i - start) / (end - start)
            assert np.max(np.abs(colors[i] - ((1 - progress) * red + progress * blue))) < 7
    elif kind == "wipe":
        for fraction in (.25, .5, .75):
            i = start + round((end - start) * fraction)
            p = (i - start) / (end - start)
            frame = frames[i]
            # Blue pixels advance in the direction named by the recipe.
            blue_mask = frame[:, :, 2] > frame[:, :, 0] + 40
            expected = np.zeros((160, 160), dtype=bool)
            edge = round(160 * (1 - p if direction in {"left", "up"} else p))
            if direction == "left": expected[:, edge:] = True
            if direction == "right": expected[:, :edge] = True
            if direction == "up": expected[edge:, :] = True
            if direction == "down": expected[:edge, :] = True
            assert np.mean(blue_mask[16:] != expected[16:]) <= .025
    elif kind.startswith("dip_to_"):
        # Check native xfade's dip profile in planar YUV. FFmpeg uses a
        # full-range background even on limited-range inputs, so RGB center
        # values alone are not a valid linear interpolation oracle.
        raw = run(["ffmpeg", "-v", "error", "-i", str(result.output_path), "-pix_fmt", "yuv444p", "-f", "rawvideo", "-"])
        yuv = np.frombuffer(raw, dtype="uint8").reshape(-1, 3, 160, 160)[:, :, 60, 60].astype(float)
        background = np.array([0 if kind == "dip_to_black" else 255, 128, 128])
        def smooth(low, high, x):
            t = np.clip((x - low) / (high - low), 0, 1)
            return t * t * (3 - 2 * t)
        for i in range(start, end + 1):
            p = 1 - (i - start) / (end - start)
            a = yuv[5] * smooth(.8, 1, p) + background * (1 - smooth(.8, 1, p))
            b = background * smooth(.2, 1, p) + yuv[-5] * (1 - smooth(.2, 1, p))
            assert np.max(abs(yuv[i] - (p * a + (1 - p) * b))) < 4
        assert np.max(np.abs(colors[start] - red)) < 5
    if kind != "dip_to_black":
        assert np.min(np.max(colors, axis=1)) > 65  # No unexpected blank frame.
    # Compare each counter-strip frame outside the effect against its source
    # frame. A hold or duplicate at the transition end shifts this sequence.
    gray = decode(result.output_path, gray=True)
    def counters(video):
        return sum((video[:, 3:12, bit * 20 + 4:bit * 20 + 16].mean((1, 2)) > 128).astype(int) * 2 ** bit
                   for bit in range(8))
    assert np.array_equal(counters(gray[:start]), np.arange(15, 15 + start))
    incoming_index = 15 + round(d * 30)
    assert np.array_equal(counters(gray[end:]), np.arange(incoming_index, 75))
    samples = audio(result.output_path)
    if d:
        # Independent tones make equal power measurable: RMS should remain
        # constant, not dip as it would with a linear crossfade or audio gap.
        windows = [samples[round(t * 48000):round((t + .02) * 48000)]
                   for t in np.arange(2 - d - .08, 2.06, .02)]
        rms = np.array([np.sqrt(np.mean(w * w)) for w in windows])
        assert rms.min() > .075 and rms.max() < .1, rms
        segment = samples[round((2 - d - .05) * 48000):round(2.05 * 48000)]
        assert np.max(np.abs(np.diff(segment))) < .025  # No discontinuity click.
        assert f"acrossfade=ns={round(d * 48000)}:c1=qsin:c2=qsin" in result.filtergraph


@pytest.mark.parametrize("kind,direction", [("dissolve", None), *(("wipe", d) for d in ("left", "right", "up", "down"))])
def test_detector_v5_reads_rendered_corpus_textures(tmp_path, textures, kind, direction):
    result = render(tmp_path, pair_plan(textures, kind, direction))
    reading = detect_transition_signatures(result.output_path)
    assert reading["predicted"] == [kind], reading["events"]
    event, = reading["events"]
    assert event["detector_version"] == 5
    assert event["direction"] == direction
    assert abs(event["start_seconds"] - 1.4) <= 1 / 30
    assert abs(event["end_seconds"] - 2) <= 1 / 30


def test_zoom_punch_magnifies_outgoing_edge(tmp_path, textures):
    plain = decode(render(tmp_path, pair_plan(textures, "dissolve"), "plain").output_path, gray=True)
    zoomed = decode(render(tmp_path, pair_plan(textures, "zoom_punch"), "zoom").output_path, gray=True)
    assert np.mean(abs(plain[20] - zoomed[20])) < 1
    assert np.mean(abs(plain[50] - zoomed[50])) > 4
    assert np.mean(abs(plain[65] - zoomed[65])) < 2  # Independent H.264 prediction histories.
    # Independently crop/scale the actual outgoing source at p=1/3 and blend
    # with the incoming scene. This checks magnification, not just difference.
    a, b = (decode(p, gray=True) for p in textures)
    from PIL import Image
    p, z = 1 / 3, 1 + .35 / 3
    side = int(160 / z)
    left = int(80 - side / 2)
    crop = Image.fromarray(a[15].astype("uint8")).crop((left, left, left + side, left + side)).resize((160, 160), Image.Resampling.BICUBIC)
    expected = np.array(crop) * (1 - p) + b[15] * p
    assert np.mean(abs(zoomed[48] - expected)) < 6


def test_luts_precede_overlap_and_captions_follow_it(tmp_path, sources):
    from test_render_composition import caption
    c = pair_plan(sources, "dissolve")
    # Two constant LUTs make ordering unambiguous: red -> green, blue -> yellow.
    for clip, rgb in zip(c.clips, ((0, 1, 0), (1, 1, 0))):
        path = tmp_path / f"{clip.id}.cube"
        path.write_text("LUT_3D_SIZE 2\n" + (" ".join(map(str, rgb)) + "\n") * 8, encoding="utf-8")
        clip.color = ColorTransform(str(path), hashlib.sha256(path.read_bytes()).hexdigest(), 1, "Rec.709")
    from myzing.composition import CaptionStyle
    c.captions = [caption(text="HI", start=0, end=3, layout=None, style=CaptionStyle(size=30, outline_width=0))]
    result = render(tmp_path, c)
    frames = decode(result.output_path)
    assert np.max(abs(frames[51, 20, 20] - np.array([127, 255, 0]))) < 8
    for i in (20, 51, 75):
        assert np.count_nonzero(np.all(frames[i] > 240, axis=-1)) > 80  # White caption survives both LUTs.
    graph = result.filtergraph
    assert graph.rindex("lut3d=") < graph.index("xfade=") < graph.index("filename='captions.ass'")


def test_mixed_chain_normalizes_inputs_and_keeps_fractional_audio_placement(tmp_path, sources):
    # Different fps, size, SAR and pixel format on B must still join. A cut
    # before and after an overlap also exercises concat's timebase reset.
    odd = tmp_path / "different.mkv"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(sources[1]), "-vf", "scale=192:192,fps=24,setsar=4/3,format=yuv444p",
         "-c:v", "ffv1", "-c:a", "pcm_s16le", str(odd)])
    c = pair_plan((sources[0], odd), "dissolve", duration=.50037, fps=Rational(30000, 1001))
    # Move the pair after a normal cut, then follow it with another normal cut.
    for clip in c.clips: clip.timeline_start += .70037
    for t in c.transitions: t.start += .70037; t.end += .70037
    c.clips.insert(0, CompositionClip(str(sources[0]), .5, 1.20037, 0, id="intro", asset_id="asset-0"))
    ending = max(x.timeline_end for x in c.clips)
    c.clips.append(CompositionClip(str(sources[0]), .5, 1.20037, ending, id="outro", asset_id="asset-0"))
    result = render(tmp_path, c)
    frames = decode(result.output_path)
    expected = max(x.timeline_end for x in c.clips)
    assert abs(len(frames) / (30000 / 1001) - expected) < 1 / (30000 / 1001)
    assert np.min(np.max(frames[:, 20:140, 20:140].mean((1, 2)), axis=1)) > 90
    # Render the compiled audio bus to PCM to remove AAC encoder delay/padding.
    command = ["ffmpeg", "-v", "error"]
    for clip in sorted(c.clips, key=lambda x: x.timeline_start):
        command += ["-i", str(c.assets[0 if clip.asset_id == "asset-0" else 1].path)]
    graph = result.filtergraph.replace("[video_out]", "[unused_video]") + ";[unused_video]nullsink"
    command += ["-filter_complex", graph, "-map", "[audio_out]", "-ac", "1", "-f", "f32le", "-"]
    pcm = np.frombuffer(run(command), dtype="<f4")
    assert len(pcm) == round(expected * 48000)


def test_insufficient_probed_source_handle_fails_before_work(tmp_path, sources, monkeypatch):
    c = pair_plan(sources, "dissolve")
    # The document's handle is valid; the real file has been shortened.
    c.clips[0].src_out = 3.5
    c.clips[1].timeline_start = 2.4
    c.transitions[0].start, c.transitions[0].end = 2.4, 3
    c.transitions[0].outgoing_handle = SourceRange(2.9, 3.5)
    monkeypatch.setattr(pipeline, "_render_in_directory", lambda *a, **k: pytest.fail("render started"))
    with pytest.raises(EDLValidationError, match=r"clip-0.*missing 0.500000s"):
        render(tmp_path, c)
    assert not (tmp_path / "render-work").exists()


@pytest.mark.parametrize("kind", ["whip", "whip_pan", "flash", "shader_spin"])
def test_unsupported_transition_fails_by_name_before_probe(tmp_path, sources, monkeypatch, kind):
    c = pair_plan(sources, "dissolve")
    c.transitions[0].recipe.kind = kind
    monkeypatch.setattr(pipeline, "probe_media", lambda *a, **k: pytest.fail("probe started"))
    with pytest.raises(EDLValidationError, match=kind):
        render(tmp_path, c)
    assert not (tmp_path / "render-work").exists()


@pytest.mark.parametrize("handle", [None, SourceRange(2.1, 2.5)])
def test_short_or_missing_handle_reports_clip_ids_and_seconds(tmp_path, sources, monkeypatch, handle):
    c = pair_plan(sources, "dissolve")
    c.transitions[0].outgoing_handle = handle
    monkeypatch.setattr(pipeline, "probe_media", lambda *a, **k: pytest.fail("probe started"))
    with pytest.raises(EDLValidationError) as error:
        render(tmp_path, c)
    assert "clip-0 -> clip-1" in str(error.value)
    assert ("0.600000s" if handle is None else "0.200000s") in str(error.value)
    assert not (tmp_path / "render-work").exists()


def test_missing_clip_audio_fades_silence_without_shifting_music(tmp_path, sources):
    from myzing.composition import AssetRef, CompositionAudio
    silent = tmp_path / "silent.mkv"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(sources[0]), "-an", "-c:v", "copy", str(silent)])
    c = pair_plan((silent, sources[1]), "dissolve")
    # An impulse at a fractional millisecond checks MR1 placement through the
    # transition graph independently of the source crossfade.
    import wave
    pulse = tmp_path / "pulse.wav"
    with wave.open(str(pulse), "wb") as w:
        w.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        w.writeframes(np.array([20000] + [0] * 4800, dtype="<i2").tobytes())
    c.assets.append(AssetRef("pulse", str(pulse), None))
    c.audio = [CompositionAudio(str(pulse), "music", .70037, id="pulse", asset_id="pulse", role="music")]
    result = render(tmp_path, c)
    command = ["ffmpeg", "-v", "error", "-i", str(silent), "-i", str(sources[1]), "-i", str(pulse),
               "-filter_complex", result.filtergraph + ";[video_out]nullsink", "-map", "[audio_out]", "-ac", "1", "-f", "f32le", "-"]
    pcm = np.frombuffer(run(command), dtype="<f4")
    assert np.argmax(np.abs(pcm[:48000])) == round(.70037 * 48000)
    assert np.count_nonzero(pcm[:30000]) == 0
    rms = [np.sqrt(np.mean(pcm[round(t * 48000):round((t + .02) * 48000)] ** 2)) for t in (1.41, 1.7, 2.01)]
    assert rms[0] < rms[1] < rms[2]
    assert rms[2] > .08


def test_consecutive_overlaps_do_not_accumulate_frame_or_sample_drift(tmp_path, sources):
    from tools.eval.render_transition_fixture import chain_plan
    c = chain_plan(sources)
    # Reordering the serialized arrays must not reorder the timeline or LUTs.
    c.clips.reverse()
    c.transitions.reverse()
    result = render(tmp_path, c)
    frames = decode(result.output_path)
    assert len(frames) == 456  # 10 * 2s - 8 * .6s = 15.2s.
    assert result.duration == pytest.approx(15.2)
    for transition in c.transitions:
        end_frame = round(transition.end * 30)
        incoming = next(x for x in c.clips if x.id == transition.incoming_clip)
        is_blue = int(incoming.asset_id[-1]) == 1
        color = np.median(frames[end_frame, 20:140, 20:140], axis=(0, 1))
        assert color[2 if is_blue else 0] > 240
    pcm = audio(result.output_path)
    for transition in c.transitions:
        if transition.recipe.duration_seconds:
            segment = pcm[round(transition.start * 48000):round(transition.end * 48000)]
            assert np.sqrt(np.mean(segment ** 2)) > .08
            assert np.max(abs(np.diff(segment))) < .025


def test_longer_audio_cannot_hide_missing_video_handle(tmp_path, sources, monkeypatch):
    short = tmp_path / "short-video.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(sources[0]), "-filter_complex", "[0:v]trim=duration=2[v]",
         "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-c:a", "aac", str(short)])
    c = pair_plan((short, sources[1]), "dissolve")
    monkeypatch.setattr(pipeline, "_render_in_directory", lambda *a, **k: pytest.fail("render started"))
    with pytest.raises(EDLValidationError, match=r"clip-0 -> clip-1.*missing 0.500000s"):
        render(tmp_path, c)
