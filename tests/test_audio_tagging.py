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
    assert tags.status == "measured" and len(tags.windows) == 8  # 5 s windows, 1 s hops over 12 s
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
                             labels=[{"label": "Singing", "confidence": .15}])
    assert tagging.vocal_evidence(tags, {"status": "unknown"})["status"] == "unknown"
    assert tagging.vocal_evidence(tags, {"status": "possible"})["status"] == "possible"


def test_noise_floor_singing_is_not_corroborated():
    # Speech-over-music clips reach 0.08 on the singing family; 0.03 is noise.
    tags = tagging.AudioTags(status="measured", method="sherpa-onnx/ced-mini-int8",
                             labels=[{"label": "Singing", "confidence": .03}])
    assert tagging.vocal_evidence(tags, {"status": "possible"})["status"] == "not_detected"


@pytest.mark.parametrize("label", ["Mantra", "Yodeling", "Synthetic singing", "A capella"])
def test_whole_audioset_singing_subtree_counts_as_vocals(monkeypatch, label):
    # The Charm 68's wordless vocal reads as Mantra (0.30) and Duck and Cover's
    # chant as Yodeling (0.38); the first family left both out.
    np = pytest.importorskip("numpy")
    fake_engine(monkeypatch, {"Music": .85, label: .3, "Piano": .1})
    tags = tagging.tag_samples(np.zeros(16000 * 6, dtype=np.float32), 16000)
    evidence = tagging.vocal_evidence(tags, {"status": "unknown"})
    assert evidence["status"] == "possible" and evidence["label"] == label
    assert tags.vocal_spans and tags.vocal_spans[0]["label"] == label


def test_family_names_follow_the_audioset_ontology():
    assert {"Singing", "Choir", "Yodeling", "Chant", "Mantra", "Male singing", "Female singing",
            "Child singing", "Synthetic singing", "Rapping"} <= tagging.VOCALS
    assert {"Baby laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"} <= tagging.LAUGHTER
    assert not tagging.VOCALS & (tagging.SPEECH | tagging.MUSIC)


def test_music_at_the_noise_floor_is_not_a_score_under_speech(monkeypatch):
    # Tears of Steel "dialogue" (speech and an explosion) peaks at Music 0.04.
    np = pytest.importorskip("numpy")
    fake_engine(monkeypatch, {"Speech": .83, "Music": .043})
    tags = tagging.tag_samples(np.zeros(16000 * 20, dtype=np.float32), 16000, speech=[(4, 16)])
    assert tags.music_under_speech == []


def test_windows_merge_into_located_spans_with_compact_rows(monkeypatch):
    # A three-second sung phrase at 20-23 s in a minute of quiet backing.
    np = pytest.importorskip("numpy")
    class Engine:
        def create_stream(self):
            return SimpleNamespace(accept_waveform=lambda **k: setattr(self, "loud", float(np.abs(k["waveform"]).max())))
        def compute(self, stream):
            return [SimpleNamespace(name="Music", prob=.8), SimpleNamespace(name="Female singing", prob=.35 if self.loud > .5 else .01)]
    monkeypatch.setattr(tagging.tag_models, "engine", Engine)
    samples = np.full(16000 * 60, .01, dtype=np.float32)
    samples[16000 * 20:16000 * 23] = .9
    tags = tagging.tag_samples(samples, 16000)
    assert [(s["start"], s["end"], s["label"]) for s in tags.vocal_spans] == [(16, 27.0, "Female singing")]
    assert tags.vocal_spans[0]["windows"] == 7 and tags.vocal_spans[0]["confidence"] == .35
    assert set(tags.windows[0]) == {"start", "end", "vocals", "vocal_label", "music", "speech", "instrument", "laughter", "applause"}
    assert len(tags.windows) == 56 and tags.provenance["window_seconds"] == 5.0


def test_tagging_never_asks_sherpa_to_resample(monkeypatch):
    # sherpa-onnx logs a resampler for every non-16 kHz stream (4,728 stderr lines per 10 minutes).
    np = pytest.importorskip("numpy")
    calls = []
    fake_engine(monkeypatch, {"Music": .9}, calls)
    tags = tagging.tag_samples(np.zeros(22050 * 6, dtype=np.float32), 22050)
    assert tags.status == "unavailable" and not calls and "16000 Hz" in tags.warnings[0]


def test_source_score_reaches_plan_without_added_music(tmp_path):
    from myzing.brief.models import Brief
    from myzing.music.planning import plan_music
    tags = {"music_under_speech": [{"start": 1, "end": 8, "confidence": .75}]}
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
            "music_under_speech": [{"start": 0, "end": 10, "confidence": .75}],
            "moment_candidates": [{"start": 0, "end": 10, "kind": "laughter", "confidence": .8}]}
    result = audio_section({"audio": {}, "provenance": {"audio_tags": tags}}, None)
    payload = result.to_dict()
    assert "0.750" in str(payload) and "already carries" in str(payload)
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
    calls = []
    fake_engine(monkeypatch, scores, calls)
    path = tmp_path / (kind + ".wav")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes((generated(np, kind) * 32767).astype("<i2").tobytes())
    result = analyze(path)
    assert result.tags.status == "measured"
    assert calls and {row["sample_rate"] for row in calls} == {16000}  # decoded at CED's rate
    assert AudioMap.from_dict(result.to_dict()) == result
    advice = rate(result, length=10, speech=True, pace=2, purpose="interview")
    assert advice.measurements["tags"]["status"] == "measured"
    assert result.structure.vocals["status"] == ("possible" if kind == "voice" else "not_detected")


@pytest.mark.parametrize("version,supported", [("2.0.0", True), ("2.3.1", True), ("1.13.8", False),
                                               ("1.12.40", False), (None, False), ("garbage", False)])
def test_runtime_floor_excludes_gpl_linked_sherpa(version, supported):
    # sherpa-onnx 1.x links espeak-ng (GPL-3.0-or-later); 2.0.0 removed it.
    assert tag_models.runtime_supported(version) is supported


def test_old_runtime_degrades_to_the_labeled_heuristic(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace())
    monkeypatch.setattr(tag_models, "runtime_version", lambda: "1.13.8")
    tags = tagging.tag_samples([0.0] * 16000, 16000)
    assert tags.status == "unavailable" and "predates 2.0" in tags.warnings[0]
