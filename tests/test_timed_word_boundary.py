"""P2 regressions: synthetic measurements, real assembly, no model downloads."""

import json
import math
import subprocess
from types import SimpleNamespace

import pytest

from myzing import cli, storage
from myzing.assemble.draft import AssembleError, draft_edl, draft_for_slug
from myzing.schemas import Breakdown, EDL, VideoMeta, Word
from myzing.study import api as study_api
from myzing.study import captions
from myzing.timing import TimingProvenance, TimingReviewError, prepare_words


def breakdown(words, duration=8.0):
    return Breakdown(
        meta=VideoMeta("fixture.mp4", "file", duration=duration,
                       width=180, height=320, fps=30, media_path="media.mp4"),
        words=words,
    )


def direction(start=0, end=8):
    return {"keepers": [{"start": start, "end": end}]}


def england_words(left=7.2, right=7.6):
    return [Word("in", 7, left, .9), Word("England", 7.4, 7.4, .8),
            Word("today", right, 7.9, .95)]


def saved_input(words):
    b = breakdown(words)
    storage.save_breakdown(b, slug="timing")
    (storage.breakdown_dir("timing") / "media.mp4").write_bytes(b"synthetic")
    return storage.breakdown_dir("timing") / "draft-edl.json"


def test_england_repaired_before_save_with_original_measurement(zing_workspace):
    words = england_words()
    target = saved_input(words)
    result = draft_for_slug("timing", direction())
    saved = EDL.from_json(target.read_text(encoding="utf-8"))
    out = [w for c in saved.captions for w in c.words]
    assert [w.text for w in out] == ["IN", "ENGLAND", "TODAY"]
    assert out[1].end - out[1].start == pytest.approx(.04)
    assert (out[0].start, out[0].end) == (words[0].start, words[0].end)
    assert (out[2].start, out[2].end) == (words[2].start, words[2].end)
    assert out[1].timing["status"] == "corrected"
    assert out[1].timing["original"] == {"start": 7.4, "end": 7.4}
    assert out[1].timing["method"] == "adjacent_silence_40ms"
    assert out[0].timing["status"] == out[2].timing["status"] == "measured"
    assert storage.load_breakdown("timing").words[1].start == 7.4
    assert storage.load_breakdown("timing").words[1].end == 7.4
    assert any("corrected" in w and "England" in w for w in result.warnings)


@pytest.mark.parametrize("existing", [False, True])
def test_no_room_requires_review_without_writing_edl(zing_workspace, existing):
    target = saved_input(england_words(7.4, 7.4))
    if existing:
        target.write_text("prior draft", encoding="utf-8")
    with pytest.raises(AssembleError, match=r"review.*England.*7\.400.*40 ms"):
        draft_for_slug("timing", direction())
    assert target.read_text() == "prior draft" if existing else not target.exists()


@pytest.mark.parametrize("start,end", [(-.1, .2), (1, .9),
    (math.nan, 1), (0, math.inf), (-math.inf, 1), (7.9, 8.1), (8.1, 8.1)])
def test_invalid_word_is_not_hidden_by_keeper_filter(zing_workspace, start, end):
    target = saved_input([Word("bad", start, end)])
    with pytest.raises(AssembleError, match="review.*bad"):
        draft_for_slug("timing", direction(2, 3))
    assert not target.exists()


@pytest.mark.parametrize("words", [
    [Word("later", 2, 2.3), Word("earlier", 1, 1.3)],
    [Word("first", 1, 2), Word("overlap", 1.5, 2.5)],
])
def test_out_of_order_or_overlapping_words_require_review(zing_workspace, words):
    target = saved_input(words)
    with pytest.raises(AssembleError, match="review.*(order|overlap)"):
        draft_for_slug("timing", direction())
    assert not target.exists()


def test_cli_review_names_word_and_fix(zing_workspace, tmp_path, capsys):
    target = saved_input(england_words(7.4, 7.4))
    plan = tmp_path / "direction.json"
    plan.write_text(json.dumps(direction()), encoding="utf-8")
    assert cli.main(["assemble", "timing", "--direction", str(plan)]) == 1
    message = capsys.readouterr().out
    assert all(text in message for text in ("review", "England", "7.400", "correct"))
    assert not target.exists()


def test_ocr_end_clamped_and_reported():
    observations = [captions.Observation(4, .25, [captions.Line("END", .9, .6)])]
    events, notes = captions.cluster_regions(observations, 4.12)
    assert len(events) == 1
    assert (events[0].start, events[0].end) == (4, 4.12)
    assert any("clamped" in note and "4.250" in note and "4.120" in note for note in notes)
    assert observations[0].step == .25  # original observation is unchanged


def test_ocr_clamping_persisted_in_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(captions, "_engine", lambda: (object(), "test"))
    monkeypatch.setattr(captions, "_iter_frames", lambda *a: [(4, .25, object())])
    monkeypatch.setattr(captions, "_ocr", lambda *a: [captions.Line("END", .9, .6)])
    result = captions.read_captions(tmp_path / "fake.mp4", 4.12)
    assert result.captions[0].end == 4.12
    record = result.provenance["ocr_interval_corrections"][0]
    assert record["original"] == {"start": 4, "end": 4.25}
    assert record["corrected"] == {"start": 4, "end": 4.12}
    assert record["method"] == "clamped_to_media"


@pytest.mark.parametrize("at,duration", [(0, 8), (8, 8), (7.4, 8)])
def test_zero_repair_is_bounded_deterministic_and_does_not_mutate(at, duration):
    original = Word("edge", at, at, .75)
    first, _ = prepare_words([original], duration)
    second, _ = prepare_words([original], duration)
    assert first == second
    assert original.start == original.end == at and original.timing is None
    assert first[0].end - first[0].start == pytest.approx(.04)
    assert 0 <= first[0].start < first[0].end <= duration
    assert abs(first[0].start - at) <= .04 + 1e-9
    assert abs(first[0].end - at) <= .04 + 1e-9


def test_repair_splits_available_gap_without_touching_neighbors():
    original = england_words(7.39, 7.43)
    words, _ = prepare_words(original, 8)
    assert words[1].start == pytest.approx(7.39)
    assert words[1].end == pytest.approx(7.43)
    assert (words[0].start, words[0].end) == (7, 7.39)
    assert (words[2].start, words[2].end) == (7.43, 7.9)


def test_retry_is_lazy_and_default_is_off():
    def forbidden(*args):
        pytest.fail("deterministic repair must precede retry")
    prepare_words(england_words(), 8, retry=forbidden)
    with pytest.raises(TimingReviewError, match="review.*40 ms"):
        prepare_words(england_words(7.39, 7.41), 8)


def test_retry_once_in_bounded_span_preserves_neighbors_and_original():
    calls = []
    original = england_words(7.39, 7.41)
    def retry(word, start, end):
        calls.append((word.text, start, end))
        return [Word("England", 7.392, 7.408, .7)]
    words, notes = prepare_words(original, 8, retry=retry)
    assert calls == [("England", 6.4, 8)]
    assert [w.text for w in words] == [w.text for w in original]
    assert [(w.start, w.end) for w in words[::2]] == [(w.start, w.end) for w in original[::2]]
    assert words[1].timing["status"] == "corrected"
    assert words[1].timing["method"] == "bounded_retranscription"
    assert words[1].timing["original"] == {"start": 7.4, "end": 7.4}
    assert "corrected" in notes[0]


@pytest.mark.parametrize("retry_words", [[], [Word("different", 7.392, 7.408)],
    [Word("England", 7.392, 7.408)] * 2, [Word("England", 7.4, 7.4)],
    [Word("England", 7.3, 7.5)], [Word("England", math.nan, 7.4)],
    [Word("England", 9, 9.1)], [Word("England", 7.408, 7.392)]])
def test_unresolved_retry_requires_review_and_never_drops_word(retry_words):
    calls = []
    def retry(*args):
        calls.append(args)
        return retry_words
    original = england_words(7.39, 7.41)
    with pytest.raises(TimingReviewError, match="review.*England.*retry"):
        prepare_words(original, 8, retry=retry)
    assert len(calls) == 1
    assert original[1].start == original[1].end == 7.4


def test_retry_failure_is_review_message():
    def retry(*args):
        raise RuntimeError("model unavailable")
    with pytest.raises(TimingReviewError, match="review.*England.*model unavailable"):
        prepare_words(england_words(7.39, 7.41), 8, retry=retry)


def test_total_retry_budget_is_three_spans():
    calls = []
    words = []
    for at in (1, 2, 3, 4):
        words.extend([Word("before", at - .1, at - .01), Word("zero", at, at),
                      Word("after", at + .01, at + .1)])
    def retry(word, start, end):
        calls.append((start, end))
        return [Word("zero", word.start - .005, word.end + .005)]
    with pytest.raises(TimingReviewError, match="retry budget exhausted"):
        prepare_words(words, 5, retry=retry)
    assert len(calls) == 3
    assert all(0 < end - start <= 2 for start, end in calls)


def test_trim_and_mapping_keep_correction_history(tmp_path):
    media = tmp_path / "media.mp4"
    media.write_bytes(b"fixture")
    measured = Word("edge", 1, 1.5)
    result = draft_edl(breakdown([measured]), direction(1.1, 2), media)
    word = result.edl.captions[0].words[0]
    assert (word.start, word.end) == (0, .4)
    assert word.timing["status"] == "corrected"
    assert word.timing["method"] == "trim_clamp"
    assert word.timing["original"] == {"start": 1, "end": 1.5}
    assert [a["method"] for a in word.timing["adjustments"]] == ["trim_clamp", "timeline_mapping"]
    assert TimingProvenance.from_dict(word.timing).to_dict() == word.timing
    assert measured.timing is None
    assert EDL.from_json(result.edl.to_json()).to_dict() == result.edl.to_dict()


def test_repaired_word_cannot_silently_fall_out_of_trim(tmp_path):
    media = tmp_path / "media.mp4"
    media.write_bytes(b"fixture")
    b = breakdown([Word("England", 7.4, 7.4), Word("next", 7.4, 7.9)])
    with pytest.raises(AssembleError, match="review.*England.*extend the keeper"):
        draft_edl(b, direction(7.4, 8), media)


def test_millisecond_collapse_rejected_before_save(zing_workspace):
    target = saved_input([Word("tiny", 1.0001, 1.0002)])
    with pytest.raises(AssembleError, match="review.*tiny|review.*TINY"):
        draft_for_slug("timing", direction())
    assert not target.exists()


def test_legacy_json_loads_and_readers_can_ignore_timing(zing_workspace):
    target = saved_input(england_words())
    draft_for_slug("timing", direction())
    data = json.loads(target.read_text(encoding="utf-8"))
    for caption in data["captions"]:
        for word in caption["words"]:
            word.pop("timing")
            assert Word(**word).end > Word(**word).start
    restored = EDL.from_dict(data)
    assert restored.schema_version == 1
    assert all(w.timing is None for c in restored.captions for w in c.words)


@pytest.mark.parametrize("duration", [4.12, 4.1208, 4.1204])
def test_fractional_media_duration_is_strict_ocr_bound(duration):
    events, _ = captions.cluster_regions([
        captions.Observation(4, .25, [captions.Line("END", .9, .6)])], duration)
    assert len(events) == 1 and 0 <= events[0].start < events[0].end <= duration


def test_invalid_ocr_observation_does_not_create_out_of_bounds_event():
    events, notes = captions.cluster_regions([
        captions.Observation(5, .25, [captions.Line("late", .9, .6)]),
        captions.Observation(math.nan, .25, [captions.Line("invalid", .9, .6)]),
    ], 4.12)
    assert events == []
    assert len(notes) == 2 and all("excluded" in note for note in notes)


@pytest.mark.ffmpeg
def test_study_assemble_render_injected_zero_word(tmp_path, monkeypatch, capsys):
    source = tmp_path / "generated.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=180x320:r=30:d=8", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=8", "-c:v", "libx264", "-c:a", "aac",
        str(source),
    ], check=True, capture_output=True)
    monkeypatch.setattr(study_api.transcribe_mod, "transcribe", lambda *a, **kw:
                        SimpleNamespace(words=england_words(), warnings=[], provenance={"fixture": True}))
    monkeypatch.setattr(captions, "_engine", lambda: (object(), "synthetic"))
    monkeypatch.setattr(captions, "_iter_frames", lambda *a: [(7.9, .25, object())])
    monkeypatch.setattr(captions, "_ocr", lambda *a: [captions.Line("END", .9, .6)])
    workspace = tmp_path / "home"
    assert cli.main(["study", str(source), "--workspace", str(workspace)]) == 0
    slug = storage.slug_for(str(source))
    with storage.use_workspace(workspace):
        measured = storage.load_breakdown(slug)
        assert measured.words[1].start == measured.words[1].end == 7.4
        assert measured.captions[0].end <= measured.meta.duration
        assert measured.provenance["ocr_interval_corrections"]
    plan = tmp_path / "direction.json"
    plan.write_text(json.dumps(direction()), encoding="utf-8")
    assert cli.main(["assemble", slug, "--workspace", str(workspace),
                     "--direction", str(plan)]) == 0
    edl_path = workspace / "breakdowns" / slug / "draft-edl.json"
    edl = EDL.from_json(edl_path.read_text(encoding="utf-8"))
    words = [w for c in edl.captions for w in c.words]
    assert len(words) == 3 and words[1].end > words[1].start
    assert words[1].timing["status"] == "corrected"
    output = tmp_path / "rendered.mp4"
    code = cli.main(["render", str(edl_path), "-o", str(output),
                     "--keep-work", str(tmp_path / "render-work")])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "json", str(output)], check=True, capture_output=True, text=True)
    assert float(json.loads(probe.stdout)["format"]["duration"]) == pytest.approx(8, abs=.05)
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(output),
                    "-f", "null", "-"], check=True, capture_output=True)


def test_unrepaired_words_serialize_without_a_timing_key():
    """v1 documents stay byte-identical when no word was corrected."""
    from myzing.schemas import EDL, CaptionSpec, Clip, Word

    words = [Word(text="hi", start=0.0, end=0.2)]
    edl = EDL(clips=[Clip(src="a.mp4", src_in=0.0, src_out=1.0, timeline_start=0.0)],
              captions=[CaptionSpec(text="hi", start=0.0, end=0.2, words=words)])
    assert '"timing"' not in edl.to_json()
    words[0].timing = {"method": "adjacent_silence_40ms"}
    assert '"timing"' in edl.to_json()
