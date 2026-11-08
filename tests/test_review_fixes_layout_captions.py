import hashlib

import pytest

from myzing import storage
from myzing.audio import AudioMap, Loudness, Tempo
from myzing.audio.structure import Structure
from myzing.captions.presets import apply_preset
from myzing.composition import (AssetRef, Composition, CompositionCaption, CompositionClip,
                               SourceRange, Transition, TransitionRecipe)
from myzing.layout.crop_planner import _vertical
from myzing.layout.debug import write_contact_sheet
from myzing.layout.delivery import adapt_plan
from myzing.layout.types import Box, FaceTrack, FrameDetections, Keyframe, LayoutPlan
from myzing.music.advice import rate
from myzing.schemas import Word
from myzing.study import api, source_map
from test_study_api import wire_stages


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr("subprocess.run", refuse)


@pytest.fixture
def study_steps(monkeypatch):
    from myzing.audio import tag_models, tagging
    wire_stages(monkeypatch, slug="local")
    monkeypatch.setattr(source_map, "build_source_map", lambda p, d, f, shots:
                        source_map.SourceMap(f, d, [s.start for s in shots[1:]]))
    monkeypatch.setattr(tag_models, "model_paths", lambda: {})
    monkeypatch.setattr(tagging, "tag_file", lambda *a, **k: tagging.AudioTags())
    ingest = api.ingest_mod.ingest

    def staged(source, **kwargs):
        result = ingest(source, **kwargs)
        result.media_path.write_bytes(b"staged analysis copy")
        return result
    monkeypatch.setattr(api.ingest_mod, "ingest", staged)


@pytest.mark.parametrize("selection", [{}, {"ref_start": 2, "ref_end": 4}, {"analysis_seconds": 4}])
def test_local_study_hashes_the_original_source(tmp_path, study_steps, selection):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original source before staging or trimming")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    workspace = tmp_path / "project"
    result = api.study(str(source), workspace=workspace, raw_mode=True, **selection)
    with storage.use_workspace(workspace):
        saved = storage.load_breakdown("local")
    assert result.provenance["source_sha256"] == expected
    assert saved.provenance["source_sha256"] == expected


def test_url_study_keeps_its_existing_provenance(tmp_path, study_steps):
    kept = tmp_path / "kept.mp4"
    kept.write_bytes(b"kept URL source")
    result = api.study("https://example.com/video", kept_media=kept)
    assert "source_sha256" not in result.provenance


def overlapping_plan():
    return Composition(assets=[AssetRef("source", "source.mp4", None, 2)],
        clips=[CompositionClip("source.mp4", 0, 2, start, id=name, asset_id="source")
               for name, start in (("A", 0), ("B", 1.5), ("C", 3.5))],
        transitions=[Transition("AB", "A", "B", 1.5, 2, TransitionRecipe("dissolve", .5, "test"),
                                SourceRange(1.5, 2), SourceRange(0, .5))], width=360, height=640)


@pytest.mark.parametrize("requested", ["auto", "reframe", "zoomfill"])
def test_delivery_splits_clips_outside_the_transition(requested, monkeypatch):
    monkeypatch.setattr("myzing.layout.borders.sample_border_bounds", lambda *a: None)
    plan = overlapping_plan()
    result = adapt_plan(plan, 360, 640, {"source": (360, 640)}, {},
                        requested=requested, cuts={"source": [1]})
    assert [(c.id, c.src_in, c.src_out, c.timeline_start) for c in result.clips] == [
        ("A", 0, 2, 0), ("B", 0, 2, 1.5),
        ("C-delivery-shot-1", 0, 1, 3.5), ("C-delivery-shot-2", 1, 2, 4.5)]
    assert result.transitions == plan.transitions
    assert [c.id for c in plan.clips] == ["A", "B", "C"]


@pytest.mark.parametrize("times", [(2, 3), (0, 1), (2,), (0,)])
def test_vertical_ignores_tracks_outside_the_shot(times):
    clip = CompositionClip("source.mp4", 1, 2, 0, id="shot", asset_id="source")
    face = FaceTrack("face-current", [Keyframe(t, Box(.4, .6, .1, .2)) for t in (1, 2)])
    other = FaceTrack("face-other", [Keyframe(t, Box(.4, .1, .1, .2)) for t in times])
    assert _vertical(clip, [face, other], 1000) == _vertical(clip, [face], 1000)


@pytest.mark.parametrize("times", [(1,), (1.5,), (.5, 1.1), (1.9, 3)])
def test_vertical_keeps_tracks_inside_the_shot(times):
    clip = CompositionClip("source.mp4", 1, 2, 0, id="shot", asset_id="source")
    face = FaceTrack("face", [Keyframe(t, Box(.4, .1, .1, .2)) for t in times])
    line, span = _vertical(clip, [face], 1000)
    assert line == pytest.approx(80)
    assert span == pytest.approx((100, 300))


@pytest.mark.parametrize("shape", [(1, 640, 3), (1000, 1, 3)])
def test_contact_sheet_handles_thin_frames(tmp_path, monkeypatch, shape):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    monkeypatch.setattr("myzing.layout.debug.read_image", lambda path: np.zeros(shape, dtype=np.uint8))
    output = tmp_path / "sheet.png"
    assert write_contact_sheet([(0, tmp_path / "frame.png")], [FrameDetections(0, [])],
                               LayoutPlan([], [], []), output) == output
    decoded = cv2.imdecode(np.frombuffer(output.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (490, 300, 3)


@pytest.mark.parametrize("name", ["clean", "punch", "box"])
def test_overlapping_clips_caption_each_word_once(name):
    plan = overlapping_plan()
    plan.captions = [CompositionCaption("Hello", 1.6, 1.8, id="words", words=[Word("Hello", 1.6, 1.8)])]
    apply_preset(plan, name, vad=False)
    assert len(plan.captions) == 1
    assert [w.text for w in plan.captions[0].words] == ["Hello"]
    assert plan.captions[0].id.startswith("A-")


@pytest.mark.parametrize("start,owner", [(1.5, "A"), (2, "B"), (3.5, "C")])
def test_caption_ownership_uses_half_open_clip_ranges(start, owner):
    plan = overlapping_plan()
    plan.captions = [CompositionCaption("Hello", start, start + .2, id="words",
                                       words=[Word("Hello", start, start + .2)])]
    apply_preset(plan, "clean", vad=False)
    assert len(plan.captions) == 1
    assert plan.captions[0].id.startswith(owner + "-")


@pytest.mark.parametrize("levels", [[-120] * 8, [-60] * 8, [-80] * 7 + [-20], []])
@pytest.mark.parametrize("context", [{"speech": True}, {"pace": .5}, {}])
def test_silent_excerpt_gets_no_energy_points(levels, context):
    energy = [{"time": i * .25, "rms_dbfs": level} for i, level in enumerate(levels)]
    audio = AudioMap("silent.wav", 2, 22050, 600, False, Tempo("steady", 120), [], [], [],
                     Loudness(None, None, None),
                     structure=Structure(energy=energy, vocals={"status": "not_detected"}))
    result = rate(audio, length=2, **context)
    reason = next(r for r in result.reasons if r["topic"] == "energy")
    assert result.measurements["scoring"]["points"]["energy"] == reason["points"] == 0
    # No energy rows is missing analysis, not measured silence.
    assert ("missing" if not levels else "silent") in reason["reason"].lower()


def test_quiet_audible_excerpt_keeps_speech_energy_points():
    energy = [{"time": i * .25, "rms_dbfs": -59} for i in range(8)]
    audio = AudioMap("quiet.wav", 2, 22050, 600, False, Tempo(), [], [], [], Loudness(-59, 0, -56),
                     structure=Structure(energy=energy, vocals={"status": "not_detected"}))
    result = rate(audio, length=2, speech=True)
    reason = next(r for r in result.reasons if r["topic"] == "energy")
    assert reason["points"] == reason["weight"] == 25
    assert "silent" not in reason["reason"].lower()
