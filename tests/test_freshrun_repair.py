"""Offline regressions for the final FRESHRUN repair review."""
import builtins
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.match import preflight


@pytest.fixture(autouse=True)
def isolated(zing_workspace, monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf/hub"))
    monkeypatch.setenv("ZING_WHISPER_MODEL", "skip")


def test_registry_import_without_tomllib(monkeypatch):
    from scripts import check_registry_server_json as registry
    imports = []
    original = builtins.__import__
    def fallback(name, *args, **kwargs):
        if name == "tomllib":
            raise ModuleNotFoundError(name)
        if name == "tomli":
            imports.append(name)
            return registry.tomllib
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fallback)
    loaded = runpy.run_path(str(Path(registry.__file__)))
    assert imports == ["tomli"]
    assert loaded["check"](registry.ROOT / "server.json") == []


def media_inputs(tmp_path, monkeypatch):
    from test_freshrun import inputs
    args = inputs(tmp_path, monkeypatch, audio=False)
    monkeypatch.setattr(preflight, "optional_warnings", lambda: [])
    return args


@pytest.mark.parametrize("suffix", [".wav", ".mp3", ".m4a"])
def test_audio_only_clip_is_warned_and_skipped(tmp_path, monkeypatch, suffix):
    args = media_inputs(tmp_path, monkeypatch)
    audio = Path(args[1]) / ("music" + suffix)
    audio.write_bytes(b"audio")
    monkeypatch.setattr(preflight, "probe", lambda p: SimpleNamespace(
        duration=10, has_audio=p == audio, flags=["no_video"] if p == audio else []))
    result = preflight.check(*args, answers={})
    assert result["problems"] == []
    assert result["speech_model"] is None  # skipped audio must not demand ASR
    assert len(result["warnings"]) == 1 and audio.name in result["warnings"][0]


def test_audio_only_folder_still_fails(tmp_path, monkeypatch):
    args = media_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(preflight, "probe", lambda p: SimpleNamespace(
        duration=10, has_audio=True, flags=["no_video"] if p.parent == Path(args[1]) else []))
    result = preflight.check(*args, answers={})
    assert len(result["problems"]) == 1 and "No readable video" in result["problems"][0]


def test_real_video_probe_failure_not_hidden_by_audio(tmp_path, monkeypatch):
    args = media_inputs(tmp_path, monkeypatch)
    def probe(p):
        if p.name == "take.mp4":
            raise ValueError("broken video")
        return SimpleNamespace(duration=10, has_audio=False, flags=[])
    monkeypatch.setattr(preflight, "probe", probe)
    assert any("broken video" in p for p in preflight.check(*args, answers={})["problems"])


def test_probe_returns_no_video_metadata(tmp_path, monkeypatch):
    path = tmp_path / "music.wav"
    path.write_bytes(b"audio")
    monkeypatch.setattr(preflight.proc, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(
        {"streams": [{"codec_type": "audio"}], "format": {"duration": "2"}})))
    assert "no_video" in preflight.probe(path).flags
    with pytest.raises(ValueError, match="no readable video"):
        preflight.check_reference(path)


@pytest.mark.parametrize("free,problem,tight", [(900_000_000, False, False), (40_000_000, False, True), (1_000_000, True, False)])
def test_space_estimate_allows_small_job_and_warns_when_tight(tmp_path, monkeypatch, free, problem, tight):
    args = media_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda p: SimpleNamespace(free=free))
    result = preflight.check(*args, answers={})
    assert bool(result["problems"]) == problem
    assert any("space is tight" in w for w in result["warnings"]) == tight


def test_space_estimate_scales_with_sources(tmp_path, monkeypatch):
    args = media_inputs(tmp_path, monkeypatch)
    with (Path(args[1]) / "take.mp4").open("wb") as stream:
        stream.truncate(100_000_000)
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda p: SimpleNamespace(free=200_000_000))
    result = preflight.check(*args, answers={})
    assert not result["problems"]
    assert any("464.0 MB" in w for w in result["warnings"])


@pytest.mark.parametrize("missing", [None, "color", "layout", "ocr_models", "fonts", "audio_tagging"])
def test_optional_warning_names_only_missing_capabilities(monkeypatch, missing):
    caps = dict(color=True, layout=True, ocr_models={"model": "hash"}, fonts=True,
                font_files=[{"available": True}], audio_tagging={"verified_assets": {"model": "path"}})
    if missing:
        caps[missing] = {} if missing == "audio_tagging" else False
    monkeypatch.setattr("myzing.match.api.capabilities", lambda: caps)
    monkeypatch.setattr(preflight.importlib.util, "find_spec", lambda name: object())
    warnings = preflight.optional_warnings()
    names = dict(color="color", layout="automatic face analysis", ocr_models="OCR", fonts="font matching", audio_tagging="audio tagging")
    assert warnings == ([] if missing is None else [f"Optional capabilities unavailable: {names[missing]}; using disclosed fallbacks."])


def test_studio_names_missing_configured_model(monkeypatch):
    from myzing.studio.evidence import speech_model_note
    monkeypatch.setattr("myzing.doctor.check_whisper", lambda: SimpleNamespace(data={"model": "large-v2", "cached": False}))
    note = speech_model_note()
    assert "large-v2" in note and "zing doctor --speech-model large-v2 --yes" in note
    assert "small.en" not in note


def test_doctor_warning_verdict_is_printed(monkeypatch, capsys):
    from myzing import doctor
    checks = [doctor.Check("yt-dlp", doctor.RECOMMENDED, True, "stale", mark="warning")]
    monkeypatch.setattr(doctor, "run_checks", lambda **k: checks)
    doctor.run([])
    text = capsys.readouterr().out
    assert "Verdict: ready, with warnings" in text
    assert "fully ready" not in text


@pytest.mark.parametrize("runtime", ["node", "deno"])
def test_custom_ytdlp_runtime_path_survives_parsing(monkeypatch, runtime):
    from myzing.study import downloader
    configured = {runtime: {"path": "C:/custom runtime/js.exe"}}
    observed = []
    class Download:
        def __init__(self, options): observed.append(options)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def download(self, urls): return 0
    monkeypatch.setattr(downloader.shutil, "which", lambda name: "/node")
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(
        parse_options=lambda args: SimpleNamespace(ydl_opts={"js_runtimes": configured}, urls=[]), YoutubeDL=Download))
    assert downloader.main([]) == 0
    assert observed[0]["js_runtimes"] == configured


@pytest.mark.parametrize("trigger", ["unsafe", "ink"])
@pytest.mark.parametrize("evidence", ["face", "clear", "missing", "mask"])
def test_both_ink_fallback_paths_preserve_overlap_evidence(tmp_path, monkeypatch, trigger, evidence):
    from myzing.composition import Composition, CompositionCaption, CaptionStyle
    from myzing.director.plans import attach_report
    from myzing.layout import Box, FaceTrack, Keyframe
    from myzing.layout.types import EventLayout, OverlapCheck, Mask
    from myzing.layout.caption_safety import remember
    from myzing.match import caption_fit
    c = CompositionCaption("Hello", 0, 1, id="c", word_timed=False, style=CaptionStyle(60))
    prior = OverlapCheck(False, ["original-face"])
    c.layout = EventLayout("c", 0, 1, "original", prior, box=Box(.1, .1, .1, .05), warnings=["original collision"])
    from myzing.composition import CompositionClip, AssetRef
    plan = Composition(captions=[c], assets=[AssetRef("a", "fixture.mp4", None, 1)],
                       clips=[CompositionClip("fixture.mp4", 0, 1, 0, id="clip", asset_id="a")])
    if trigger == "ink":
        plan.accepted_unsafe_layouts = ["c"]  # reach the second recovery call
    context = {}
    if evidence != "missing":
        box = Box(.2, .5, .2, .2) if evidence == "face" else Box(.2, .1, .2, .1)
        face = FaceTrack("measured-face", [Keyframe(0, box), Keyframe(1, box)])
        masks = [Mask("original-reserve", Box(0, .4, 1, .4))] if evidence == "mask" else []
        remember(context, c, [face], masks)
    # Verify the context survives the actual director serialization boundary.
    plan = attach_report(plan, {"warnings": [], "caption_safety": context})
    monkeypatch.setattr(caption_fit, "_measure", lambda c, s, *args: (0, 0, 300, 100))
    caption_fit.fit_captions(plan, tmp_path)
    c = plan.captions[0]
    from myzing.match.evidence import report
    from myzing.schemas import Breakdown, VideoMeta
    from myzing.style_recipe import build_style_recipe
    studied = Breakdown(VideoMeta("fixture", "file", duration=1, fps=30))
    reported = report(build_style_recipe(studied), studied, {}, None, {"full_decode": True}, plan)
    visible = [w for w in plan.warnings if w.startswith("Caption c:")]
    assert all(w in reported["warnings"] for w in visible)
    if evidence == "clear":
        assert not any(w.startswith("Caption c:") for w in reported["warnings"])
    assert c.layout.reason == "readable-placement-fallback"
    if evidence == "clear":
        assert c.layout.overlap.safe and not c.layout.warnings
        assert "c" not in plan.accepted_unsafe_layouts
        assert not any("overlaps" in w or "may cover" in w for w in plan.warnings)
    else:
        assert not c.layout.overlap.safe and "c" in plan.accepted_unsafe_layouts
        if evidence == "missing":
            assert c.layout.overlap.face_ids == ["original-face"]
            assert any("unmeasured" in w and "unavailable" in w for w in c.layout.warnings)
        elif evidence == "face":
            assert c.layout.overlap.face_ids == ["measured-face"]
            assert any("Caption c:" in w and "measured-face" in w and "(measured)" in w for w in plan.warnings)
        else:
            assert c.layout.overlap.mask_names == ["original-reserve"]
            assert not c.layout.overlap.face_ids


@pytest.mark.parametrize("preset", ["punch", "box", "clean"])
def test_body_does_not_block_band_and_faces_only_block_during_caption(preset):
    from copy import deepcopy
    from test_caption2 import plan
    from myzing.captions.presets import apply_preset
    from myzing.layout import Box, FaceTrack, Keyframe
    from myzing.layout.framing import place_captions
    p = plan("Here is my story and here is another story about going into space and finding a new way to understand the world around us")
    apply_preset(p, preset, vad=False)
    duration = p.clips[0].duration
    assert len(p.captions) >= 2
    baseline = deepcopy(p)
    place_captions(baseline, {}, {"a": (360, 640)})
    body = FaceTrack("person-body", [Keyframe(0, Box(0, 0, 1, 1)), Keyframe(duration, Box(0, 0, 1, 1))])
    first = p.captions[0]
    face = FaceTrack("face-speaking", [Keyframe(first.start, Box(0, 0, 1, 1)), Keyframe(first.end - .01, Box(0, 0, 1, 1))])
    place_captions(p, {"a": [body, face]}, {"a": (360, 640)})
    assert p.captions[0].layout.overlap.face_ids == ["face-speaking"]
    assert p.captions[0].id in p.accepted_unsafe_layouts
    for c in p.captions[1:]:
        assert c.layout.overlap.safe and c.id not in p.accepted_unsafe_layouts
        assert not any(w.startswith(f"Caption {c.id}:") for w in p.warnings)


def test_reference_placement_retains_exact_face_and_mask_context(monkeypatch):
    from test_caption2 import plan
    from myzing.layout import Box, FaceTrack, Keyframe
    from myzing.layout import framing
    from myzing.layout.caption_safety import restore
    from myzing.layout.chooser import check_overlap
    p = plan("Here is my story")
    body = FaceTrack("person-body", [Keyframe(0, Box(0, 0, 1, 1)), Keyframe(10, Box(0, 0, 1, 1))])
    context = {}
    monkeypatch.setattr(framing, "fit_measured_ink", lambda *a, **k: None)
    framing.place_captions(p, {"a": [body]}, {"a": (360, 640)}, safety_context=context)
    for c in p.captions:
        restored = restore(context, c)
        assert restored["obstacles"] == [] and restored["masks"]
        assert check_overlap(c.layout.as_path(), restored["obstacles"], restored["masks"]).safe


@pytest.mark.parametrize("long_word", [False, True])
def test_dense_timeline_elides_labels_and_publishes(tmp_path, monkeypatch, long_word):
    from myzing.inspect import timeline
    from myzing.schemas import Word
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fixture")
    class Decoder:
        def probe(self, video): return {"duration": 30, "fps": 30, "has_audio": False}
        def frame(self, video, t, w, h): return bytes(w * h * 3)
    words = [Word("W" * 500 if long_word else "conversation", i * .1, i * .1 + .09) for i in range(300)]
    monkeypatch.setattr(timeline, "Decoder", Decoder)
    monkeypatch.setattr(timeline, "_transcript", lambda *args: (words, "study", []))
    output = tmp_path / "timeline.png"
    result = timeline.inspect_timeline(video, output, start=0, end=30)
    assert output.is_file() and result.rows[0]["elided_word_labels"] > 0
    assert any("transcript labels omitted" in w for w in result.warnings)
    assert bool(result.rows[0]["truncated_word_labels"]) == long_word
    assert 0 < len(result.rows[0]["words"]) < len(words)


def test_inspection_failure_cannot_kill_rendered_draft(tmp_path, monkeypatch):
    from myzing.match import api
    from myzing.inspect import InspectionError
    def fail(*args): raise InspectionError("fixture decoder failed")
    monkeypatch.setattr(api, "_inspect_impl", fail)
    video = tmp_path / "rendered.mp4"
    video.write_bytes(b"rendered")
    result = api._inspect(video, tmp_path / "timeline.png", {}, tmp_path, 30)
    assert video.read_bytes() == b"rendered"
    assert result["outputs"] == [] and result["inspection"] is None
    assert "Rendered video retained" in result["warnings"][0]
