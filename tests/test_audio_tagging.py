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


def _pin(monkeypatch, tmp_path, payload=b"verified weights"):
    from myzing import model_fetch
    monkeypatch.setattr(tag_models, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(tag_models, "ASSETS", {"weights": (hashlib.sha256(payload).hexdigest(), len(payload))})
    return model_fetch


def test_download_requires_consent_and_uses_the_shared_https_fetch(monkeypatch, tmp_path):
    model_fetch = _pin(monkeypatch, tmp_path)
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: pytest.fail("unconsented network"))
    for consent in (False, "yes", 1):
        with pytest.raises(ValueError, match="consent"):
            tag_models.fetch_models(consent=consent)
    # The real seam refuses non-HTTPS before any request (ONBOARD1's model_fetch).
    with pytest.raises(ValueError, match="HTTPS"):
        model_fetch.https_open("http://example.com/model")
    assert tag_models.BASE_URL.startswith("https://huggingface.co/") and tag_models.REVISION in tag_models.BASE_URL


@pytest.mark.parametrize("payload", [b"wrong", b"oversized payload"])
def test_download_hash_and_size_failure_never_installs(monkeypatch, tmp_path, payload):
    model_fetch = _pin(monkeypatch, tmp_path, b"right")
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: io.BytesIO(payload))
    with pytest.raises(RuntimeError, match="pinned size|SHA-256"):
        tag_models.fetch_models(consent=True)
    assert not (tmp_path / "weights").exists() and not list(tmp_path.glob("*.part"))


def test_verified_download_is_atomic_and_cached(monkeypatch, tmp_path):
    payload = b"verified weights"
    model_fetch = _pin(monkeypatch, tmp_path, payload)
    calls = []
    def open_url(url, **kwargs):
        calls.append(url)
        return io.BytesIO(payload)
    monkeypatch.setattr(model_fetch, "open_url", open_url)
    first = tag_models.fetch_models(consent=True)
    assert tag_models.fetch_models(consent=True) == first and len(calls) == 1
    assert calls[0] == tag_models.BASE_URL + "weights"
    assert first[0].read_bytes() == payload and not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("surface", ["doctor", "setup", "audio"])
def test_doctor_setup_and_audio_share_the_audio_model_consent(monkeypatch, tmp_path, capsys, surface):
    from myzing import doctor, setup_flow
    from myzing.audio import command
    payload = b"verified weights"
    model_fetch = _pin(monkeypatch, tmp_path, payload)
    monkeypatch.setattr(doctor, "run_checks", lambda: [])
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: pytest.fail("unconsented network"))
    monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))  # a pipe is non-interactive
    run = {"doctor": doctor.run, "setup": setup_flow.run, "audio": lambda argv: command.run(["fetch-model", *argv[2:]])}[surface]
    if surface != "audio":
        assert run(["--audio-model", "ced-mini"]) == 2
        assert "explicit consent" in "".join(capsys.readouterr())
        assert run(["--yes"]) == 2
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: io.BytesIO(payload))
    assert run(["--audio-model", "ced-mini", "--yes"] if surface != "audio" else ["", "", "--consent"]) in (0, 1)
    assert (tmp_path / "weights").read_bytes() == payload
    assert '"downloaded_bytes": 16' in capsys.readouterr().out


def test_doctor_reports_missing_model_without_inference(monkeypatch, tmp_path):
    from myzing import doctor
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    with storage.use_workspace(tmp_path):
        result = doctor.check_audio_ml()
    assert not result.ok and result.data["network_used"] is False
    assert "--consent" in result.fix


@pytest.mark.parametrize("answer,accepted", [("yes\n", True), ("y\n", True), ("\n", False), ("no\n", False)])
def test_audio_setup_interactive_consent(monkeypatch, tmp_path, answer, accepted):
    payload = b"verified weights"
    model_fetch = _pin(monkeypatch, tmp_path, payload)
    stream = io.StringIO(answer)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True, readline=stream.readline))
    calls = []
    def download(*args, **kwargs):
        calls.append(args)
        return io.BytesIO(payload)
    monkeypatch.setattr(model_fetch, "open_url", download)
    if accepted:
        assert tag_models.setup()["downloaded_bytes"] == len(payload)
        assert len(calls) == 1
    else:
        with pytest.raises(ValueError, match="declined"):
            tag_models.setup()
        assert calls == [] and not (tmp_path / "weights").exists()


@pytest.mark.parametrize("yes", [1, "yes"])
def test_audio_setup_requires_boolean_yes_like_speech(monkeypatch, tmp_path, yes):
    model_fetch = _pin(monkeypatch, tmp_path)
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: pytest.fail("invalid consent reached network"))
    with pytest.raises(ValueError, match="consent"):
        tag_models.setup(yes=yes)


def test_audio_json_never_prompts_and_cached_setup_needs_no_consent(monkeypatch, tmp_path, capsys):
    from myzing import doctor
    payload = b"verified weights"
    model_fetch = _pin(monkeypatch, tmp_path, payload)
    monkeypatch.setattr(doctor, "run_checks", lambda: [])
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True,
                        readline=lambda: pytest.fail("JSON setup must not prompt")))
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: pytest.fail("unconsented network"))
    assert doctor.run(["--audio-model=ced-mini", "--json"]) == 2
    assert "explicit consent" in json.loads(capsys.readouterr().out)["error"]
    (tmp_path / "weights").write_bytes(payload)
    assert doctor.run(["--audio-model=ced-mini", "--json"]) == 0
    receipt = json.loads(capsys.readouterr().out)["audio_setup"]
    assert receipt["verified"] and receipt["downloaded_bytes"] == 0


def test_audio_receipt_counts_only_bytes_this_process_downloaded(monkeypatch, tmp_path):
    payload = b"verified weights"
    model_fetch = _pin(monkeypatch, tmp_path, payload)
    def published_while_waiting(url, target, digest, limit, **kwargs):
        target.write_bytes(payload)
        return False  # another downloader published the verified asset under the folder lock
    monkeypatch.setattr(model_fetch, "fetch_verified", published_while_waiting)
    assert tag_models.setup(yes=True)["downloaded_bytes"] == 0


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


@pytest.mark.parametrize("kind", ["piano", "voice", "mixed", "events"])
def test_generated_decoded_tags_reach_audio_map_and_advice(monkeypatch, tmp_path, kind):
    import wave
    from myzing.audio import api, media, structure
    from myzing.audio.models import Loudness
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
    # Exercise both consumers in lean CI. Existing media gates own FFmpeg;
    # this test supplies its decoded signal and meter observations.
    rates = []
    def decoded(source, *, max_seconds, sample_rate=media.SAMPLE_RATE):
        assert source == path.resolve()
        rates.append(sample_rate)
        return generated(np, kind, rate=sample_rate), False
    monkeypatch.setattr(api, "decode_mono", decoded)
    monkeypatch.setattr(media, "decode_mono", decoded)
    monkeypatch.setattr(api, "measure_loudness", lambda *a, **k: Loudness(None, None, None))
    monkeypatch.setattr(structure, "channel_quality", lambda *a, **k: {})
    monkeypatch.setattr(api, "ffmpeg_version", lambda: "mocked decoder")
    result = analyze(path)
    assert result.tags.status == "measured"
    assert calls and {row["sample_rate"] for row in calls} == {16000}  # decoded at CED's rate
    assert rates == [22050, 16000]
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


def test_analysis_reuses_the_study_windows_only_for_the_identical_measurement(monkeypatch):
    np = pytest.importorskip("numpy")
    fake_engine(monkeypatch, {"Music": .8, "Speech": .1})
    study = tagging.tag_samples(np.zeros(16000 * 12, dtype=np.float32), 16000, speech=[])
    study.provenance["analyzed_seconds"] = 12.0
    assert not study.music_under_speech  # no words, weak model speech
    reused = tagging.reuse(study.to_dict(), speech=[(2.0, 4.0)], duration=12.0)
    assert reused.windows == study.windows and "reused_from" in reused.provenance
    assert reused.music_under_speech and reused.music_under_speech[0]["speech_intervals"] == [[2.0, 4.0]]
    for change in ({"algorithm": "ced-windows-1"}, {"analyzed_seconds": 11.0}, {"model_sha256": "0" * 64}):
        stale = tagging.AudioTags.from_dict({**study.to_dict(), "provenance": {**study.provenance, **change}})
        assert tagging.reuse(stale, speech=[], duration=12.0) is None
    assert tagging.reuse({"status": "unavailable"}, speech=[], duration=12.0) is None
    assert tagging.reuse({"not": "tags"}, speech=[], duration=12.0) is None
