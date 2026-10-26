"""Fresh-install regressions; model and media probes are offline fixtures."""
import hashlib
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.study import speech_models as speech
from myzing.match import preflight


@pytest.fixture(autouse=True)
def isolate(zing_workspace, monkeypatch, tmp_path):
    monkeypatch.delenv("ZING_WHISPER_MODEL", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf/hub"))


def cached(name):
    path = speech.hub_cache() / f"models--Systran--faster-whisper-{name}/snapshots/test"
    path.mkdir(parents=True)
    for file in ("model.bin", "config.json", "tokenizer.json"):
        (path / file).write_bytes(b"fixture")
    return path


@pytest.mark.parametrize("env,saved,models,expected", [
    ("small.en", "large-v2", ["small.en", "large-v2"], "small.en"),
    (None, "small.en", ["small.en", "large-v2"], "small.en"),
    (None, None, ["small.en", "large-v2"], "large-v2"),
    (None, None, ["small.en"], "small.en"),
    (None, "skip", [], "skip"),
    ("skip", "small.en", [], "skip"),
])
def test_resolution(env, saved, models, expected, monkeypatch):
    for name in models:
        cached(name)
    if saved:
        speech.save_choice(saved)
    if env:
        monkeypatch.setenv("ZING_WHISPER_MODEL", env)
    assert speech.resolve_name() == expected
    assert speech.recommendation()[0] == expected


@pytest.mark.parametrize("env,saved,missing", [(None, None, "large-v2"), (None, "large-v2", "large-v2"), ("large-v2", "small.en", "large-v2")])
def test_missing_choice_does_not_silently_switch(env, saved, missing, monkeypatch):
    if saved:
        speech.save_choice(saved)
        cached("small.en")
    if env:
        monkeypatch.setenv("ZING_WHISPER_MODEL", env)
    with pytest.raises(FileNotFoundError, match=f"--speech-model {missing} --yes"):
        speech.resolve_name()


def test_local_model_env_and_failed_setup_preserve_choice(monkeypatch):
    folder = cached("custom")
    speech.save_choice("skip")
    monkeypatch.setenv("ZING_WHISPER_MODEL", str(folder))
    assert speech.resolve_name() == str(folder)
    monkeypatch.delenv("ZING_WHISPER_MODEL")
    with pytest.raises(ValueError, match="explicit"):
        speech.setup("small.en", json_mode=True)
    assert speech.resolve_name() == "skip"


def inputs(tmp_path, monkeypatch, *, audio=True):
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"fixture")
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "take.mp4").write_bytes(b"fixture")
    monkeypatch.setattr(preflight, "probe", lambda p: SimpleNamespace(duration=10, has_audio=audio))
    monkeypatch.setattr(preflight.shutil, "which", lambda name: name)
    return str(reference), str(clips), str(tmp_path / "out")


def test_missing_speech_stops_match_before_study_in_seconds(tmp_path, monkeypatch):
    from myzing.match import api
    args = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "_study", lambda *a, **k: pytest.fail("heavy study began"))
    start = time.monotonic()
    result = api.match(*args, answers={})
    assert time.monotonic() - start < 3
    assert result["status"] == "shortage"
    assert len(result["shortages"]) == 1
    assert result["failures"] == []
    assert "--speech-model large-v2 --yes" in result["error"]
    assert not (Path(args[2]) / "project.json").exists()


def test_preflight_aggregates_and_names_fixes(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None if name == "ffmpeg" else name)
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda p: SimpleNamespace(free=1))
    monkeypatch.setattr("myzing.layout.detector.verified_model", lambda p: False)
    result = preflight.check(*args, answers={"framing": "reframe"})
    text = "\n".join(result["problems"])
    for fragment in ("ffmpeg", "speech-model", "layout fetch-model", "Free space"):
        assert fragment in text
    assert any("automatic face analysis" in w for w in result["warnings"])


@pytest.mark.parametrize("audio,choice", [(False, None), (True, "skip")])
def test_silent_or_explicit_skip_needs_no_speech_model(tmp_path, monkeypatch, audio, choice):
    args = inputs(tmp_path, monkeypatch, audio=audio)
    if choice:
        speech.setup(choice)
    assert not preflight.check(*args, answers={})["problems"]


def test_invalid_target_and_unreadable_media_aggregate(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(preflight, "probe", lambda p: (_ for _ in ()).throw(ValueError("broken container")))
    result = preflight.check(*args, answers={"target_length_seconds": -1})
    assert any("Brief/target invalid" in p for p in result["problems"])
    assert sum("broken container" in p for p in result["problems"]) == 2


def test_doctor_download_small_then_next_match_uses_small(tmp_path, monkeypatch):
    from myzing import doctor, model_fetch
    from myzing.match import api
    from myzing.study import transcribe
    payload = b"fixture weights"
    pin = {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    monkeypatch.setattr(speech, "MODELS", {"small.en": {"revision": "a" * 40,
        "files": {n: pin for n in ("model.bin", "config.json", "tokenizer.json")}}})
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: io.BytesIO(payload))
    monkeypatch.setattr(doctor, "run_checks", lambda **k: [])
    assert doctor.run(["--speech-model", "small.en", "--yes"]) == 0
    args = inputs(tmp_path, monkeypatch)
    # Stop at the first study after observing the actual transcribe resolver.
    seen = []
    monkeypatch.setattr(transcribe, "_load_model", lambda name, **kw: (seen.append(name) or object(), "cpu", "int8", "test"))
    monkeypatch.setattr(transcribe, "_run_model", lambda *a, **k: ([], "en", 1.))
    def study(*args, **kwargs):
        transcribe.transcribe(Path(args[0]))
        raise RuntimeError("fixture ends at speech")
    monkeypatch.setattr(api, "_study", study)
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: __import__('myzing.project.probe', fromlist=['parse_probe']).parse_probe({"streams": [{"codec_type": "video", "width": 640, "height": 360, "avg_frame_rate": "30/1", "duration": "10"}], "format": {"duration": "10"}}))
    monkeypatch.setattr("myzing.project.api.probe_file", __import__("myzing.project.probe", fromlist=["probe_file"]).probe_file)
    monkeypatch.setattr(api, "capabilities", lambda: {"fonts": False, "layout": False})
    api.match(*args, answers={})
    assert seen == ["small.en"]
    assert speech.resolve_name() == "small.en"


def test_node_python_option_and_staleness(monkeypatch):
    from datetime import date
    import sys
    from myzing import doctor
    from myzing.study import downloader
    monkeypatch.setattr(downloader.shutil, "which", lambda name: "/node" if name == "node" else None)
    assert downloader.runtime_options() == {"js_runtimes": {"node": {}}}
    calls = []
    class Download:
        def __init__(self, options): calls.append(options)
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def download(self, urls): calls.append(urls); return 0
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(parse_options=lambda args: SimpleNamespace(ydl_opts={"noplaylist": True}, urls=["https://example.test"]), YoutubeDL=Download))
    assert downloader.main([]) == 0
    assert calls[0]["js_runtimes"] == {"node": {}} and calls[0]["noplaylist"]
    monkeypatch.setattr(doctor, "_which", lambda name: "/"+name if name in ("node", "yt-dlp") else None)
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(doctor, "_run_version", lambda argv: "2026.01.01")
    result = doctor.check_ytdlp(today=date(2026, 10, 26))
    assert result.ok and result.mark == "warning" and not result.degraded_mode
    assert '"yt-dlp[default]"' in result.fix


def test_ink_fit_tests_floor_before_refusing(tmp_path, monkeypatch):
    from myzing.match import caption_fit
    from myzing.composition import Composition, CompositionCaption, CaptionStyle
    caption = CompositionCaption("Test", 0, 1, id="c", word_timed=False)
    monkeypatch.setattr(caption_fit, "_measure", lambda c, s, *a: (0, 0, s.size * 10, 20))
    style, failure = caption_fit._fit(caption, CaptionStyle(25), 1., 240, 50, "Arial", 1., Composition(), tmp_path)
    assert failure is None and style.size == 24


def test_unreadable_text_names_actual_floor_and_box(tmp_path, monkeypatch):
    from myzing.match import caption_fit
    from myzing.composition import Composition, CompositionCaption
    p = Composition()
    p.captions = [CompositionCaption("x" * 500, 0, 1, id="oversize", word_timed=False)]
    monkeypatch.setattr(caption_fit, "_measure", lambda c, s, *a: (0, 0, 500*s.size, 30))
    with pytest.raises(ValueError, match="oversize.*measured ink.*24.0px readability floor"):
        caption_fit.fit_captions(p, tmp_path)


@pytest.mark.parametrize("preset", ["punch", "box", "clean"])
def test_preset_subject_overlap_is_disclosed_not_a_render_veto(preset):
    from test_caption2 import plan
    from myzing.captions.presets import apply_preset
    from myzing.layout.framing import place_captions
    from myzing.layout import Box, FaceTrack, Keyframe
    p = plan("Here is my story")
    apply_preset(p, preset, vad=False)
    duration = p.clips[0].duration
    subject = FaceTrack("speaker", [Keyframe(0, Box(0, 0, 1, 1)), Keyframe(duration, Box(0, 0, 1, 1))])
    place_captions(p, {"a": [subject]}, {"a": (360, 640)})
    assert all(c.id in p.accepted_unsafe_layouts for c in p.captions)
    assert all(not c.layout.overlap.mask_names for c in p.captions)
    assert any("overlaps face tracks" in w for w in p.warnings)


def test_clipped_probe_shrinks_before_refusing(tmp_path, monkeypatch):
    from myzing.match import caption_fit
    from myzing.composition import Composition, CompositionCaption, CaptionStyle
    from myzing.render.validation import EDLValidationError
    def ink(c, style, *args):
        if style.size > 30:
            raise EDLValidationError("text exceeds frame bounds")
        return 0, 0, 100, 20
    monkeypatch.setattr(caption_fit, "_measure", ink)
    c = CompositionCaption("Test", 0, 1, id="c", word_timed=False)
    style, failure = caption_fit._fit(c, CaptionStyle(100), 1, 200, 50, "Arial", 1, Composition(), tmp_path)
    assert failure is None and 24 <= style.size <= 30
