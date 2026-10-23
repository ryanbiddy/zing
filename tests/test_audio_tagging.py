"""Generated signals exercise plumbing; mocked scores do not prove accuracy."""
import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from myzing import storage
from myzing.audio import tag_models, tagging


def fake_engine(monkeypatch, scores, calls=None):
    class Engine:
        def create_stream(self):
            return self

        def accept_waveform(self, **kwargs):
            if calls is not None:
                calls.append(kwargs)

        def compute(self, stream):
            return [SimpleNamespace(name=k, prob=v) for k, v in scores.items()]
    monkeypatch.setattr(tag_models, "engine", Engine)


def generated(np, kind, rate=16000, seconds=12):
    t = np.arange(rate * seconds) / rate
    harmonic = sum(.06 / n * np.sin(2 * np.pi * 220 * n * t) for n in range(1, 7))
    formants = sum(.04 * np.sin(2 * np.pi * hz * t) for hz in (130, 650, 1300, 2600))
    formants *= (.3 + .7 * np.sin(2 * np.pi * 3.7 * t) ** 2)
    noise = np.random.default_rng(41).normal(0, .1, len(t)) * (np.sin(2 * np.pi * 4 * t) > .75)
    return {"piano": harmonic, "voice": formants, "mixed": harmonic + formants,
            "events": noise}[kind].astype(np.float32)


@pytest.mark.parametrize("kind,scores,status,under,events", [
    ("piano", {"Music": .95, "Piano": .9, "Singing": .01}, "not_detected", False, False),
    ("voice", {"Singing": .85}, "possible", False, False),
    ("mixed", {"Music": .8, "Speech": .9}, "not_detected", True, False),
    ("events", {"Laughter": .8, "Applause": .7}, "not_detected", False, True),
])
def test_generated_tag_consumers(monkeypatch, kind, scores, status, under, events):
    np = pytest.importorskip("numpy")
    calls = []
    fake_engine(monkeypatch, scores, calls)
    tags = tagging.tag_samples(generated(np, kind), 16000)
    assert tags.status == "measured" and len(tags.windows) == 3
    assert all(row["waveform"].dtype == np.float32 and row["sample_rate"] == 16000 for row in calls)
    assert bool(tags.music_under_speech) == under
    assert bool(tags.moment_candidates) == events
    assert tagging.vocal_evidence(tags, {"status": "possible", "confidence": .6})["status"] == status
    assert tagging.AudioTags.from_dict(json.loads(json.dumps(tags.to_dict()))) == tags
    assert {r["label"]: r["confidence"] for r in tags.labels}[next(iter(scores))] == next(iter(scores.values()))


@pytest.mark.parametrize("exc", [ImportError("no sherpa"), RuntimeError("corrupt model"), OSError("backend failure")])
def test_missing_or_failed_extra_keeps_labeled_heuristic(monkeypatch, exc):
    def fail():
        raise exc
    monkeypatch.setattr(tag_models, "engine", fail)
    tags = tagging.tag_samples([], 16000)
    assert tags.status == "unavailable" and not tags.labels
    evidence = tagging.vocal_evidence(tags, {"status": "possible", "confidence": .6})
    assert evidence["status"] == "possible" and evidence["method"] == "heuristic_fallback"
    assert "audio-ml" in tags.warnings[0] and "--consent" in tags.warnings[0]


def test_bad_scores_discard_partial_observations(monkeypatch):
    np = pytest.importorskip("numpy")
    fake_engine(monkeypatch, {"Music": float("nan")})
    tags = tagging.tag_samples(np.zeros(16000), 16000)
    assert tags.status == "unavailable" and not tags.windows


def test_words_support_music_candidate_without_model_speech(monkeypatch):
    np = pytest.importorskip("numpy")
    fake_engine(monkeypatch, {"Music": .6})
    tags = tagging.tag_samples(np.zeros(16000 * 10), 16000, speech=[(2, 3)])
    assert tags.music_under_speech[0]["speech_intervals"] == [[2, 3]]
    assert tags.music_under_speech[0]["speech_basis"] == "supplied word intervals"


def test_music_candidate_requires_same_window(monkeypatch):
    np = pytest.importorskip("numpy")
    fake_engine(monkeypatch, {"Music": .8})
    tags = tagging.tag_samples(np.zeros(16000 * 10), 16000, speech=[(20, 21)])
    assert not tags.music_under_speech


def test_download_requires_consent_and_https(monkeypatch, tmp_path):
    monkeypatch.setattr(tag_models, "cache_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="consent"):
        tag_models.fetch_models()
    with pytest.raises(ValueError, match="HTTPS"):
        tag_models._https("http://example.com/model")
    with pytest.raises(ValueError, match="HTTPS"):
        tag_models._HTTPSRedirect().redirect_request(None, None, 302, "", {}, "http://example.com/model")


@pytest.mark.parametrize("payload", [b"wrong", b"oversized payload"])
def test_download_hash_and_size_failure_never_installs(monkeypatch, tmp_path, payload):
    monkeypatch.setattr(tag_models, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(tag_models, "ASSETS", {"weights": (hashlib.sha256(b"right").hexdigest(), 5)})
    class Response(io.BytesIO):
        def geturl(self):
            return "https://example.com/pinned"
    monkeypatch.setattr(tag_models.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=lambda *a, **k: Response(payload)))
    with pytest.raises(RuntimeError, match="verification failed"):
        tag_models.fetch_models(consent=True)
    assert list(tmp_path.iterdir()) == []


def test_verified_download_is_atomic_and_cached(monkeypatch, tmp_path):
    payload = b"verified weights"
    monkeypatch.setattr(tag_models, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(tag_models, "ASSETS", {"weights": (hashlib.sha256(payload).hexdigest(), len(payload))})
    calls = []
    class Response(io.BytesIO):
        def geturl(self):
            return "https://example.com/pinned"
    def open_url(url, **kwargs):
        calls.append(url)
        return Response(payload)
    monkeypatch.setattr(tag_models.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=open_url))
    first = tag_models.fetch_models(consent=True)
    assert tag_models.fetch_models(consent=True) == first and len(calls) == 1
    assert first[0].read_bytes() == payload and not list(tmp_path.glob("*.part"))


def test_doctor_reports_missing_model_without_inference(monkeypatch, tmp_path):
    from myzing import doctor
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    with storage.use_workspace(tmp_path):
        result = doctor.check_audio_ml()
    assert not result.ok and result.data["network_used"] is False
    assert "--consent" in result.fix


def test_weak_singing_requires_heuristic_corroboration():
    tags = tagging.AudioTags(status="measured", method="sherpa-onnx/ced-mini-int8",
                             labels=[{"label": "Singing", "confidence": .03}])
    assert tagging.vocal_evidence(tags, {"status": "unknown"})["status"] == "unknown"
    assert tagging.vocal_evidence(tags, {"status": "possible"})["status"] == "possible"


def test_source_score_reaches_plan_without_added_music(tmp_path):
    from myzing.brief.models import Brief
    from myzing.music.planning import plan_music
    tags = {"music_under_speech": [{"start": 1, "end": 8, "confidence": .03}]}
    study = SimpleNamespace(asset_id="clip", audio_tags=tags)
    clip = SimpleNamespace(asset_id="clip", start=2, end=5)
    sequence, assets, tracks, evidence = plan_music([clip], [study], Brief(music={"source": "none"}),
                                                   None, tmp_path, None, {}, {})
    assert not tracks and not assets
    assert evidence.decisions[0]["kind"] == "source_score"
    assert "already carries" in evidence.warnings[0]


def test_explain_retains_candidate_scores():
    from myzing.explain.sections import audio_section
    tags = {"status": "measured", "method": "sherpa-onnx/ced-mini-int8",
            "music_under_speech": [{"start": 0, "end": 10, "confidence": .03}],
            "moment_candidates": [{"start": 0, "end": 10, "kind": "laughter", "confidence": .8}]}
    result = audio_section({"audio": {}, "provenance": {"audio_tags": tags}}, None)
    payload = result.to_dict()
    assert "0.030" in str(payload) and "already carries" in str(payload)
    assert "laughter" in str(payload)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("kind", ["piano", "voice", "mixed", "events"])
def test_generated_file_tags_reach_audio_map_and_advice(monkeypatch, tmp_path, kind):
    import wave
    from myzing.audio import analyze, AudioMap
    from myzing.music.advice import rate
    np = pytest.importorskip("numpy")
    scores = {"piano": {"Music": .9, "Piano": .8}, "voice": {"Singing": .8},
              "mixed": {"Music": .8, "Speech": .8}, "events": {"Laughter": .8, "Applause": .7}}[kind]
    fake_engine(monkeypatch, scores)
    path = tmp_path / (kind + ".wav")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes((generated(np, kind) * 32767).astype("<i2").tobytes())
    result = analyze(path)
    assert result.tags.status == "measured"
    assert AudioMap.from_dict(result.to_dict()) == result
    advice = rate(result, length=10, speech=True, pace=2, purpose="interview")
    assert advice.measurements["tags"]["status"] == "measured"
    assert result.structure.vocals["status"] == ("possible" if kind == "voice" else "not_detected")
