"""Offline playbook tests: no real listings, media fetches or model calls."""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
from datetime import datetime, timezone

import pytest

from conftest import FakeHTTPResponse
from myzing.playbook import sources, measure, notes, distill
from myzing.playbook.common import read_json, write_json
from myzing.schemas import AudioLayout, Breakdown, CaptionEvent, Shot, VideoMeta, Word

SECRET = "test-secret-not-for-disk"
TRANSCRIPT = "FIXTURE_TRANSCRIPT_MUST_NEVER_BE_PUBLISHED"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(notes.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(sources.proc, "run", refuse)
    monkeypatch.setattr(measure.study_api, "study", refuse)
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(notes.time, "sleep", lambda seconds: None)


def entry(ident="video0", group="worked", channel="channel", **extra):
    return {"platform": "youtube", "channel": channel, "id": ident,
            "url": f"https://www.youtube.com/shorts/{ident}", "title": "private title",
            "views": 200 if group == "worked" else 20, "channel_median": 100,
            "outlier": 2 if group == "worked" else .2, "set": group, "listed_at": "2026-10-01T00:00:00+00:00", **extra}


def make_library(root, entries=None):
    write_json(root / "library.json", {"schema_version": 1, "entries": entries or [entry()]})


def rubric(**extra):
    return {**{name: choices[0] for name, choices in notes.ENUMS.items()},
            "opening_line": "A question about a difficult decision", "speaker_count": 1,
            "topic": "Decision making", "attention_reason": "The question creates a clear reason to wait for the answer.",
            "confidence": .8, **extra}


def response(value=None):
    return FakeHTTPResponse(json.dumps({"responseId": "response-1", "candidates": [{"finishReason": "STOP",
        "content": {"parts": [{"text": json.dumps(rubric() if value is None else value)}]}}]}).encode())


def breakdown():
    return Breakdown(meta=VideoMeta("file", "file", duration=10, width=1080, height=1920),
        shots=[Shot(0, 0, 2, "frame.jpg"), Shot(1, 2, 10)],
        words=[Word(TRANSCRIPT, 1, 1.5), Word("another", 2, 2.5)],
        captions=[CaptionEvent(TRANSCRIPT, .5, 2, "lower", True, 2)],
        audio=AudioLayout(has_music=True, music_confidence=.7, speech_ratio=.6), avg_shot_duration=5)


def test_selection_math():
    rows = [{"id": f"v{i}", "view_count": i + 1} for i in range(50)]
    result = sources.select(rows)
    assert result["n"] == 40 and result["median_views"] == 30.5
    assert [r["views"] for r in result["didnt"]] == [11, 12, 13, 14, 15]
    assert [r["views"] for r in result["worked"]] == [50, 49, 48, 47, 46]
    assert sources.select(rows[:39])["status"] == "skipped"
    assert sources.select(rows[:40])["status"] == "listed"


def test_dates_zero_views_and_ties():
    rows = [{"id": f"v{i}", "view_count": i, "upload_date": "20260901"} for i in range(40)]
    rows[0]["upload_date"] = "20261029"
    result = sources.select(rows, skip_newest=0, now=datetime(2026, 10, 30, tzinfo=timezone.utc))
    assert result["n"] == 39 and result["age_unverified"] == 0
    assert sources.select([{**r, "view_count": 0} for r in rows])["reason"] == "channel median is zero"
    assert "strictly" in sources.select([{**r, "view_count": 1} for r in rows])["reason"]


def test_listing_resolves_study_executable_and_does_not_download(tmp_path, monkeypatch):
    monkeypatch.setattr(sources.doctor, "resolve_ytdlp_argv", lambda: ["python-custom", "-m", "yt_dlp"])
    def run(argv, **kwargs):
        assert argv[:3] == ["python-custom", "-m", "yt_dlp"]
        assert "--flat-playlist" in argv and "--skip-download" in argv
        assert argv[-1] == "https://www.youtube.com/@Example/shorts"
        return subprocess.CompletedProcess(argv, 0, "\n".join(json.dumps({"id": f"v{i}", "view_count": i}) for i in range(50)), "")
    monkeypatch.setattr(sources.proc, "run", run)
    result = sources.build(tmp_path, ["@Example"])
    assert len(result["entries"]) == 10
    assert result["entries"][0]["outlier"] == 49 / 29.5
    assert (tmp_path / "channels" / "Example.json").exists()


def test_import_candidates_cli(tmp_path, monkeypatch):
    from myzing.cli import main
    rows = [{"id": f"v{i}", "views": i+1} for i in range(50)]
    selection = sources.select(rows)
    source = tmp_path / "candidates.json"
    write_json(source, {"Example": {k: selection[k] for k in ("n", "median_views", "worked", "didnt")}})
    out = tmp_path / "out"
    assert main(["playbook", "list", "--from-candidates", str(source), "--out", str(out)]) == 0
    result = read_json(out / "library.json")
    assert len(result["entries"]) == 10
    assert result["entries"][0]["outlier"] == 50/30.5
    assert result["channels"]["Example"]["origin"] == "candidates"


def test_measure_missing_never_fetches(tmp_path, monkeypatch):
    from myzing.study import ingest
    make_library(tmp_path)
    calls = []
    monkeypatch.setattr(ingest, "_fetch", lambda *a, **k: calls.append(a))
    result = measure.measure(tmp_path)
    assert result["unmeasured"] == 1 and calls == []
    assert read_json(tmp_path / "features.json")["entries"] == [{"id": "video0", "source": "measured", "status": "unmeasured", "reason": "no local media"}]


def test_measure_download_explicit_and_resume(tmp_path, monkeypatch, zing_workspace):
    make_library(tmp_path)
    calls = []
    def study(source, **kwargs):
        calls.append(source)
        assert kwargs["local_models_only"] is True
        assert kwargs["model_workspace"] == zing_workspace
        return breakdown()
    monkeypatch.setattr(measure.study_api, "study", study)
    assert measure.measure(tmp_path, download=True)["done"] == 1
    assert calls == [entry()["url"]]
    assert measure.measure(tmp_path)["cached"] == 1
    assert len(calls) == 1
    assert measure.measure(tmp_path, download=True, force=True)["done"] == 1
    assert len(calls) == 2
    features = (tmp_path / "features.json").read_text()
    assert TRANSCRIPT not in features and "frame.jpg" not in features
    assert TRANSCRIPT in (tmp_path / "measured" / "video0.json").read_text()


def test_measure_local_features_and_face_evidence(tmp_path, monkeypatch):
    make_library(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    (media / "video0.mp4").write_bytes(b"fixture; not a video")
    def study(source, **kwargs):
        assert source == str(media / "video0.mp4")
        write_json(kwargs["workspace"] / "fixture" / "caption-geometry.json", {"frames": [
            {"width": 100, "height": 100, "face_boxes": [[0, 0, .5, .5]]},
            {"width": 100, "height": 100, "face_boxes": []},
            {"width": 100, "height": 100, "face_boxes": None}]})
        return breakdown()
    monkeypatch.setattr(measure.study_api, "study", study)
    measure.measure(tmp_path)
    row = read_json(tmp_path / "features.json")["entries"][0]
    assert row["duration"] == 10 and row["avg_shot_duration"] == 5
    assert "shots_per_10s" not in row and "silence_before_first_word" not in row
    assert row["time_to_first_cut"] == 2 and row["time_to_first_word"] == 1
    assert row["time_to_first_caption"] == .5 and row["words_per_second_first_3s"] == 2/3
    assert row["caption_words_visible_mode"] == 2 and row["caption_all_caps_share"] == 1
    assert row["caption_position_mode"] == "lower" and row["speech_ratio"] == .6
    assert row["source_aspect"] == 1080/1920
    assert row["face_presence_share"] == .5 and row["largest_face_area_share"] == .125
    assert (tmp_path / "measured" / "video0.caption-geometry.json").exists()
    shutil.rmtree(tmp_path / "working")
    assert measure.measure(tmp_path)["cached"] == 1
    assert read_json(tmp_path / "features.json")["entries"][0] == row


def test_measure_unknowns_are_null():
    b = Breakdown(VideoMeta("file", "file", duration=10), warnings=["speech ratio skipped: unavailable", "caption OCR skipped"])
    values = measure.extract(b)
    for feature in ("music_present", "caption_presence", "speech_ratio", "time_to_first_word", "words_per_second_first_3s", "face_presence_share"):
        assert values[feature] is None


def test_failed_geometry_does_not_claim_no_captions():
    b = Breakdown(VideoMeta("file", "file", duration=10), provenance={"caption_geometry": {"sampled_frames": 0}})
    assert measure.extract(b, {"frames": [], "warnings": ["caption geometry incomplete: missing model"]})["caption_presence"] is None
    assert measure.extract(b, {"frames": [{"status": "ocr_error"}]})["caption_presence"] is None
    assert measure.extract(b, {"frames": [{"status": "no_text_detected"}]})["caption_presence"] is False


def test_notes_blind_header_cache_and_no_secret(tmp_path, monkeypatch, capsys, caplog):
    make_library(tmp_path)
    calls = []
    def urlopen(req, **kwargs):
        calls.append(req)
        assert req.get_header("X-goog-api-key") == SECRET
        assert SECRET not in req.full_url and SECRET.encode() not in req.data
        body = json.loads(req.data)
        assert body["contents"][0]["parts"][0]["file_data"]["file_uri"] == entry()["url"]
        prompt = body["contents"][0]["parts"][1]["text"]
        for word in ("worked", "didnt", "views", "outlier", "median", "private title"):
            assert word not in prompt
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseSchema" in body["generationConfig"]
        return response()
    monkeypatch.setattr(notes.urllib.request, "urlopen", urlopen)
    assert notes.notes(tmp_path)["done"] == 1
    assert notes.notes(tmp_path, model="another-model")["cached"] == 1
    assert len(calls) == 1
    record = read_json(tmp_path / "notes" / "video0.json")
    assert record["response_id"] == "response-1" and record["model"] == notes.DEFAULT_MODEL
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text()
    assert SECRET not in capsys.readouterr().out + caplog.text


@pytest.mark.parametrize("bad", [{}, rubric(hook_type="made up"), rubric(confidence=2), rubric(speaker_count=True),
    rubric(opening_line="word " * 21), rubric(attention_reason="word " * 61), rubric(extra="field")])
def test_invalid_rubric_failure(tmp_path, monkeypatch, bad):
    make_library(tmp_path)
    monkeypatch.setattr(notes.urllib.request, "urlopen", lambda *a, **k: response(bad))
    summary = notes.notes(tmp_path)
    assert summary["failed_count"] == 1
    record = read_json(tmp_path / "notes" / "video0.json")
    assert record["status"] == "failed" and "schema-invalid" in record["reason"]
    assert "rubric" not in record


@pytest.mark.parametrize("code", [429, 500, 503])
def test_retry_then_success(tmp_path, monkeypatch, code):
    make_library(tmp_path)
    calls, sleeps = [], []
    def urlopen(req, **kwargs):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, code, SECRET, {}, FakeHTTPResponse(SECRET.encode()))
        return response()
    monkeypatch.setattr(notes.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(notes.time, "sleep", sleeps.append)
    result = notes.notes(tmp_path)
    assert result["done"] == 1 and result["video_seconds_sent"] == 120
    assert 1 in sleeps and any(s > 1 for s in sleeps)


def test_retry_bounded_and_error_sanitized(tmp_path, monkeypatch):
    make_library(tmp_path)
    calls = []
    def fail(req, **kwargs):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 429, SECRET, {}, FakeHTTPResponse(SECRET.encode()))
    monkeypatch.setattr(notes.urllib.request, "urlopen", fail)
    summary = notes.notes(tmp_path)
    assert len(calls) == 4 and summary["failed_count"] == 1
    assert SECRET not in json.dumps(summary)


def test_budget_duration_fallback_and_retries(tmp_path, monkeypatch):
    make_library(tmp_path, [entry("v0", duration=15), entry("v1"), entry("v2")])
    write_json(tmp_path / "measured" / "v1.json", {"meta": {"duration": 20}})
    calls = []
    monkeypatch.setattr(notes.urllib.request, "urlopen", lambda *a, **k: (calls.append(1), response())[1])
    summary = notes.notes(tmp_path, budget_hours=35/3600)
    assert summary["done"] == 2 and summary["skipped_for_budget"] == 1
    assert summary["video_seconds_sent"] == 35 and len(calls) == 2
    assert notes.notes(tmp_path, budget_hours=0)["cached"] == 2


def test_retry_cannot_exceed_budget(tmp_path, monkeypatch):
    make_library(tmp_path)
    calls = []
    def fail(req, **kwargs):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 429, "busy", {}, FakeHTTPResponse(b"{}"))
    monkeypatch.setattr(notes.urllib.request, "urlopen", fail)
    summary = notes.notes(tmp_path, budget_hours=60/3600)
    assert len(calls) == 1 and summary["skipped_for_budget"] == 1
    assert summary["video_seconds_sent"] == 60


def test_missing_key_and_limit(tmp_path, monkeypatch):
    make_library(tmp_path)
    assert notes.notes(tmp_path, limit=0)["skipped_for_limit"] == 1
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(notes.NotesError, match="GEMINI_API_KEY"):
        notes.notes(tmp_path)


def test_response_echo_cannot_persist_key(tmp_path, monkeypatch):
    make_library(tmp_path)
    monkeypatch.setattr(notes.urllib.request, "urlopen", lambda *a, **k: response(rubric(topic=SECRET)))
    assert notes.notes(tmp_path)["failed_count"] == 1
    assert all(SECRET not in p.read_text() for p in tmp_path.rglob("*.json"))


def test_nested_json_escape_cannot_persist_key(tmp_path, monkeypatch):
    make_library(tmp_path)
    inner = json.dumps(rubric(topic=SECRET)).replace(SECRET, "".join(f"\\u{ord(c):04x}" for c in SECRET))
    payload = {"candidates": [{"content": {"parts": [{"text": inner}]}}]}
    monkeypatch.setattr(notes.urllib.request, "urlopen", lambda *a, **k: FakeHTTPResponse(json.dumps(payload).encode()))
    assert notes.notes(tmp_path)["failed_count"] == 1
    assert all(SECRET not in p.read_text() for p in tmp_path.rglob("*.json"))


@pytest.mark.parametrize("candidates", [None, [], [None], [123], [{"content": {"parts": [None]}}]])
def test_malformed_response_envelope_is_recorded(tmp_path, monkeypatch, candidates):
    make_library(tmp_path)
    monkeypatch.setattr(notes.urllib.request, "urlopen", lambda *a, **k: FakeHTTPResponse(json.dumps({"candidates": candidates}).encode()))
    assert notes.notes(tmp_path)["failed_count"] == 1


def test_channel_timeout_is_reported(tmp_path, monkeypatch):
    def fail(handle):
        raise subprocess.TimeoutExpired("fixture", 240)
    monkeypatch.setattr(sources, "list_channel", fail)
    result = sources.build(tmp_path, ["Example"])
    assert result["channels"]["Example"]["status"] == "failed"
    assert result["entries"] == []


def test_models_pagination_and_model_precedence(tmp_path, monkeypatch):
    calls = []
    def urlopen(req, **kwargs):
        calls.append(req.full_url)
        assert req.get_header("X-goog-api-key") == SECRET
        return FakeHTTPResponse(json.dumps({"models": [{"name": f"models/m{len(calls)}"}],
            **({"nextPageToken": "next token"} if len(calls) == 1 else {})}).encode())
    monkeypatch.setattr(notes.urllib.request, "urlopen", urlopen)
    assert len(notes.models()) == 2 and "pageToken=next+token" in calls[1]
    make_library(tmp_path)
    monkeypatch.setenv("ZING_GEMINI_MODEL", "env-model")
    def generate(req, **kwargs):
        assert "/models/env-model:generateContent" in req.full_url
        return response()
    monkeypatch.setattr(notes.urllib.request, "urlopen", generate)
    assert notes.notes(tmp_path)["done"] == 1


def synthetic(root):
    entries, rows = [], []
    for channel in range(20):
        count = 5
        for group in ("worked", "didnt"):
            for i in range(count):
                ident = f"c{channel}_{group}_{i}"
                entries.append(entry(ident, group, f"c{channel}"))
                rows.append({"id": ident, "status": "measured", "source": "measured",
                    **{name: 0 for name, spec in measure.FEATURES.items() if spec.kind == "numeric"},
                    "caption_presence": True, "caption_position_mode": "lower",
                    "duration": 20 + i % 3 if group == "worked" else 50 + i % 3,
                    "speech_ratio": i % 5 / 5,
                    "music_present": group == "worked", "transcript": TRANSCRIPT})
                write_json(root / "notes" / f"{ident}.json", {"schema_version": 1, "id": ident, "status": "done",
                    "prompt_version": notes.PROMPT_VERSION, "rubric": rubric(energy="high" if group == "worked" else "low", opening_line=TRANSCRIPT)})
    make_library(root, entries)
    write_json(root / "features.json", {"schema_version": 1, "entries": rows})


def test_distill_signal_noise_confound_categories_determinism_and_rights(tmp_path):
    synthetic(tmp_path)
    thresholds = distill.Thresholds()
    result = distill.distill(tmp_path, thresholds=thresholds)
    duration = next(p for p in result["patterns"] if p["feature"] == "duration")
    assert duration["direction"] == "lower" and duration["effect"] == -1
    assert duration["n"] == {"worked": 100, "didnt": 100}
    assert duration["ci"] == [-1, -1]
    assert duration["channels"]["consistency"] == 1
    noise = next(p for p in result["no_separation"] if p["feature"] == "speech_ratio")
    assert noise["effect"] == 0 and noise["ci"] == [0, 0]
    music = next(p for p in result["patterns"] if p["feature"] == "music_present" and p["category"] is True)
    assert music["effect"] == 1 and music["counts"] == {"worked": 100, "didnt": 0}
    assert music["ci"] == [1, 1]
    comparisons = result["patterns"] + result["no_separation"]
    assert result["tests_run"] == len(comparisons) == 49
    assert all(p["ci_level"] == 1 - .05 / 49 for p in comparisons)
    assert [p["category"] for p in comparisons if p["feature"] == "music_present"] == [True]
    assert [p["category"] for p in comparisons if p["feature"] == "caption_presence"] == [True]
    assert "Tests actually run: 49" in (tmp_path / "WHATS-WORKING-v0.md").read_text(encoding="utf-8")
    energy = next(p for p in result["patterns"] if p["feature"] == "energy" and p["category"] == "high")
    assert energy["source"] == "estimated"
    first = (tmp_path / "playbook-v0.json").read_bytes()
    assert distill.distill(tmp_path, thresholds=thresholds) == result
    assert first == (tmp_path / "playbook-v0.json").read_bytes()
    for name in ("playbook-v0.json", "WHATS-WORKING-v0.md"):
        content = (tmp_path / name).read_text(encoding="utf-8")
        assert TRANSCRIPT not in content and "private title" not in content
        assert "frame.jpg" not in content and "opening_line" not in content
    assert len(result["inputs_sha256"]) == 202


def test_consistency_excludes_sparse_channels():
    rows = [{"channel": "sparse", "set": "worked", "value": 1}]
    result = distill.consistency(rows, 1, False, 3)
    assert result["excluded"] == 1 and result["eligible"] == 0 and result["consistency"] is None


def test_cliffs_ties_and_bootstrap():
    assert distill.cliffs_delta([1, 2], [1, 2]) == 0
    assert distill.cliffs_delta([3], [1, 2]) == 1
    args = ([([1, 2, 3], [2, 3, 4]), ([5], [6])], distill.cliffs_delta, 200, 7)
    assert distill.bootstrap(*args) == distill.bootstrap(*args)


def test_reject_path_escape_and_bad_thresholds(tmp_path):
    make_library(tmp_path, [entry("../../escape")])
    with pytest.raises(ValueError):
        measure.measure(tmp_path)
    with pytest.raises(ValueError):
        distill.distill(tmp_path, version="../escape")
    with pytest.raises(ValueError):
        distill.Thresholds(min_consistency=2).validate()


HOME = "C:/Users/" + "private/"  # split so the public-tree scan doesn't read it as a real home path


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired(["ffmpeg", HOME + "secret.mp4", SECRET], 60),
                                  KeyError(SECRET), RuntimeError(HOME + SECRET)])
def test_measure_failure_continues_and_resume_skips(tmp_path, monkeypatch, error):
    make_library(tmp_path, [entry(f"v{i}") for i in range(3)])
    calls = []
    def study(source, **kwargs):
        calls.append(source)
        if source.endswith("/v0"):
            raise error
        return breakdown()
    monkeypatch.setattr(measure.study_api, "study", study)
    result = measure.measure(tmp_path, download=True)
    assert result["done"] == 2 and result["failed"] == 1 and len(calls) == 3
    failure = read_json(tmp_path / "features.json")["entries"][0]
    assert failure["status"] == "failed" and type(error).__name__ in failure["reason"]
    assert len(failure["reason"]) < 130
    assert SECRET not in json.dumps(failure) and "private" not in json.dumps(failure)
    result = measure.measure(tmp_path, download=True)
    assert result["cached"] == 2 and result["failed"] == 1 and len(calls) == 3
    monkeypatch.setattr(measure.study_api, "study", lambda *a, **k: breakdown())
    assert measure.measure(tmp_path, download=True, force=True)["done"] == 3
    assert not (tmp_path / "measured" / "v0.failed.json").exists()


@pytest.mark.parametrize("tags, expected", [
    ({"status": "measured", "windows": [{"music": 0.0, "speech": .9}]}, False),
    ({"status": "measured", "windows": [{"music": .1, "speech": .9}]}, True),
    ({"status": "measured", "windows": [], "music_under_speech": [{"confidence": .2}]}, True),
    ({"status": "unavailable", "windows": []}, None),
])
def test_music_uses_completed_ced_check(tags, expected):
    b = breakdown()
    b.audio.has_music, b.audio.music_confidence = False, 0
    b.provenance["audio_tags"] = tags
    assert measure.extract(b)["music_present"] is expected


@pytest.mark.parametrize("categorical", [False, True])
def test_two_eligible_channels_cannot_keep(categorical):
    rows = []
    for channel in range(12):
        for group in ("worked", "didnt"):
            for _ in range(5 if channel < 2 else 2):
                value = (0 if group == "worked" else 1) if channel < 2 else .5
                rows.append({"channel": f"c{channel}", "set": group, "value": bool(value) if categorical else value})
    spec = measure.FEATURES["music_present" if categorical else "duration"]
    result = distill.compare("music_present" if categorical else "duration", "measured", spec,
                             rows, distill.Thresholds(), True if categorical else None)
    assert result["status"] == "no separation"
    assert "too few eligible channels" in result["reasons"]
    assert result["n"] == {"worked": 10, "didnt": 10}
    assert result["effect"] == -1 and result["ci"] == [-1, -1]
    assert result["channels"]["eligible_channels"] == ["c0", "c1"]
    assert result["channels"]["excluded"] == 10


def test_channel_pairs_stay_together_in_bootstrap():
    clusters = [([0] * 5, [0] * 5), ([100] * 5, [100] * 5)]
    # Independent side resampling would invent an effect here.
    assert distill.bootstrap(clusters, distill.rate_difference, 200, 42) == [0, 0]


def test_heavy_channel_cannot_dominate_the_effect():
    rows = []
    for channel in range(20):
        for group in ("worked", "didnt"):
            values = ([100 if group == "worked" else 0] * 150 if channel == 0
                      else [9 if group == "worked" else 10] * 5)
            rows.extend({"channel": f"c{channel}", "set": group, "value": v} for v in values)
    result = distill.compare("avg_shot_duration", "measured", measure.FEATURES["avg_shot_duration"],
                             rows, distill.Thresholds())
    # Each channel counts once: 19 channels say lower, one 150-row channel says higher.
    assert result["effect"] == pytest.approx(-.9) and result["direction"] == "lower"
    assert result["channels"]["consistency"] == .95 and result["ci"][1] < 0
    assert result["status"] == "kept"


def test_consistency_uses_the_per_channel_effect_not_medians():
    rows = []
    for channel in range(20):
        # Half the channels: worked median is higher but its Cliff's delta is negative (-0.28).
        worked, didnt = ([0, 0, 5, 5, 5], [4, 4, 4, 6, 6]) if channel < 10 else ([10] * 5, [0] * 5)
        for group, values in (("worked", worked), ("didnt", didnt)):
            rows.extend({"channel": f"c{channel}", "set": group, "value": v} for v in values)
    result = distill.compare("duration", "measured", measure.FEATURES["duration"], rows, distill.Thresholds(), tests_run=49)
    assert result["effect"] == pytest.approx(.36) and result["channels"]["aligned"] == 10
    assert "insufficient within-channel consistency" in result["reasons"]
    assert result["bootstrap_samples_used"] == 19600


def test_channel_offsets_do_not_dilute_a_within_channel_effect():
    rows = []
    for channel in range(20):
        base = 100 * channel  # e.g. one show's Shorts all run longer
        for group, shift in (("worked", 0), ("didnt", 1)):
            rows.extend({"channel": f"c{channel}", "set": group, "value": base + shift + i} for i in range(5))
    a = [r["value"] for r in rows if r["set"] == "worked"]
    b = [r["value"] for r in rows if r["set"] == "didnt"]
    assert abs(distill.cliffs_delta(a, b)) < .33  # pooled across channels, the effect washes out
    result = distill.compare("duration", "measured", measure.FEATURES["duration"], rows, distill.Thresholds())
    assert result["effect"] == pytest.approx(-.36) and result["status"] == "kept"


def test_actual_tests_count_and_correction_flag(tmp_path):
    entries, rows = [], []
    for channel in range(8):
        for group in ("worked", "didnt"):
            for i in range(3):
                ident = f"c{channel}_{group}_{i}"
                entries.append(entry(ident, group, f"c{channel}"))
                rows.append({"id": ident, "status": "measured", "duration": 1 if group == "worked" else 2,
                             "music_present": group == "worked"})
    make_library(tmp_path, entries)
    write_json(tmp_path / "features.json", {"schema_version": 1, "entries": rows})
    result = distill.distill(tmp_path)
    assert result["tests_run"] == 2 and result["ci_level"] == .975
    assert sum(p["test_run"] for p in result["patterns"] + result["no_separation"]) == 2
    from myzing.cli import main
    assert main(["playbook", "distill", str(tmp_path), "--version", "uncorrected",
                 "--multiple-testing", "none", "--min-channels", "9"]) == 0
    uncorrected = read_json(tmp_path / "playbook-uncorrected.json")
    assert uncorrected["ci_level"] == .95 and not uncorrected["patterns"]


@pytest.mark.parametrize("code", [429, 503])
@pytest.mark.parametrize("header, expected", [("17", 17), ("999", 120), ("-1", 0), ("nonsense", 1),
    ("Fri, 30 Oct 2026 12:00:45 GMT", 45), ("Fri, 30 Oct 2026 13:00:00 GMT", 120)])
def test_retry_after_header(tmp_path, monkeypatch, code, header, expected):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(notes, "datetime", Clock)
    make_library(tmp_path)
    calls, sleeps = [], []
    def urlopen(req, **kwargs):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, code, "busy", {"Retry-After": header}, FakeHTTPResponse(b"{}"))
        return response()
    monkeypatch.setattr(notes.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(notes.time, "sleep", sleeps.append)
    assert notes.notes(tmp_path)["done"] == 1
    assert sleeps[0] == expected


def test_daily_budget_across_runs_and_utc_rollover(tmp_path, monkeypatch):
    make_library(tmp_path, [entry("v0"), entry("v1"), entry("v2")])
    day = ["2026-10-30"]
    monkeypatch.setattr(notes, "utc_now", lambda: day[0] + "T23:59:59+00:00")
    calls = []
    monkeypatch.setattr(notes.urllib.request, "urlopen", lambda *a, **k: (calls.append(1), response())[1])
    assert notes.notes(tmp_path, limit=1, budget_hours=120/3600)["video_seconds_sent"] == 60
    second = notes.notes(tmp_path, budget_hours=120/3600)
    assert second["done"] == 1 and second["skipped_for_budget"] == 1
    assert len(calls) == 2
    assert read_json(tmp_path / "notes" / "usage-2026-10-30.json")["video_seconds_sent"] == 120
    day[0] = "2026-10-31"
    assert notes.notes(tmp_path, budget_hours=120/3600)["done"] == 1
    assert read_json(tmp_path / "notes" / "usage-2026-10-31.json")["video_seconds_sent"] == 60


def test_failed_attempts_persist_daily_usage(tmp_path, monkeypatch):
    make_library(tmp_path)
    calls = []
    def fail(req, **kwargs):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, FakeHTTPResponse(b"{}"))
    monkeypatch.setattr(notes.urllib.request, "urlopen", fail)
    assert notes.notes(tmp_path, budget_hours=120/3600)["video_seconds_sent"] == 120
    assert notes.notes(tmp_path, budget_hours=120/3600)["video_seconds_sent"] == 0
    assert len(calls) == 2


def test_ledger_reservation_precedes_send_and_locks(tmp_path, monkeypatch):
    make_library(tmp_path)
    def interrupted(req, **kwargs):
        ledgers = list((tmp_path / "notes").glob("usage-*.json"))
        assert read_json(ledgers[0])["video_seconds_sent"] == 60
        raise KeyboardInterrupt
    monkeypatch.setattr(notes.urllib.request, "urlopen", interrupted)
    with pytest.raises(KeyboardInterrupt):
        notes.notes(tmp_path)
    assert notes.notes(tmp_path, budget_hours=60/3600)["skipped_for_budget"] == 1
    (tmp_path / "notes" / ".usage.lock").touch()
    assert notes.notes(tmp_path)["failed_count"] == 1


@pytest.mark.parametrize("has_key", [False, True])
def test_notes_dry_run_exact_request_no_send_or_writes(tmp_path, monkeypatch, capsys, has_key):
    from myzing.cli import main
    make_library(tmp_path, [entry("v0"), entry("v1")])
    if not has_key:
        monkeypatch.delenv("GEMINI_API_KEY")
    assert main(["playbook", "notes", str(tmp_path), "--dry-run", "--model", "fixture-model"]) == 0
    output = capsys.readouterr().out
    preview = json.loads(output)
    assert SECRET not in output and preview["headers"]["x-goog-api-key"] == "[REDACTED]"
    assert preview["body"] == notes.request_body(entry("v0"))
    assert preview["body"]["contents"][0]["parts"][0] == {"file_data": {"file_uri": entry("v0")["url"]}}
    assert not (tmp_path / "notes").exists() and not (tmp_path / "notes-summary.json").exists()
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    def live(req, **kwargs):
        assert req.full_url == preview["url"] and json.loads(req.data) == preview["body"]
        return response()
    monkeypatch.setattr(notes.urllib.request, "urlopen", live)
    assert notes.notes(tmp_path, model="fixture-model", limit=1)["done"] == 1
