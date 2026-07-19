"""Tests for draft-EDL production (S4): keeper trims -> contiguous
timeline, loud failures, measured-keeper divergence warnings."""

from __future__ import annotations

import pytest

from myzing.schemas import Breakdown, VideoMeta
from myzing.assemble import draft
from myzing.assemble.draft import AssembleError, draft_edl


def make_breakdown(duration=60.0, measured_keepers=None) -> Breakdown:
    b = Breakdown(
        meta=VideoMeta(
            source_url="file.mp4", platform="file", duration=duration,
            width=1080, height=1920, fps=30.0, media_path="media.mp4",
        ),
    )
    if measured_keepers is not None:
        b.provenance["raw_mode"] = {
            "keepers": [
                {"start": s, "end": e, "words": 10, "evidence": []}
                for s, e in measured_keepers
            ]
        }
    return b


def direction_with(keepers):
    return {
        "verdict": "ok",
        "gaps": [],
        "shot_prompts": [],
        "keepers": keepers,
        "assembly_notes": "",
    }


@pytest.fixture
def media(tmp_path):
    p = tmp_path / "media.mp4"
    p.write_bytes(b"fake")
    return p


def test_contiguous_timeline_in_direction_order(media):
    b = make_breakdown(measured_keepers=[(8.0, 15.2), (20.0, 30.0)])
    result = draft_edl(b, direction_with([
        {"start": 20.0, "end": 30.0, "why": "payoff first"},
        {"start": 8.0, "end": 15.2, "why": "then setup"},
    ]), media)

    clips = result.edl.clips
    assert [(c.src_in, c.src_out) for c in clips] == [(20.0, 30.0), (8.0, 15.2)]
    assert clips[0].timeline_start == 0.0
    assert clips[1].timeline_start == 10.0     # contiguous, no gaps
    assert result.edl.width == 1080 and result.edl.fps == 30.0
    assert result.warnings == []


def test_unmeasured_span_is_flagged_not_blocked(media):
    b = make_breakdown(measured_keepers=[(8.0, 15.2)])
    result = draft_edl(b, direction_with([
        {"start": 40.0, "end": 45.0, "why": "AI liked this bit"},
    ]), media)

    assert len(result.edl.clips) == 1
    assert any(
        "not a measured keeper" in w and "AI's call" in w
        for w in result.warnings
    )


def test_edge_tolerance_on_measured_match(media):
    b = make_breakdown(measured_keepers=[(8.0, 15.2)])
    result = draft_edl(b, direction_with([
        {"start": 8.2, "end": 15.4, "why": "trimmed a hair looser"},
    ]), media)
    assert result.warnings == []               # within 0.35s tolerance


def test_no_raw_mode_yields_crosscheck_warning(media):
    b = make_breakdown()                       # no raw_mode provenance
    result = draft_edl(b, direction_with([
        {"start": 5.0, "end": 10.0, "why": "x"},
    ]), media)
    assert any("could not be cross-checked" in w for w in result.warnings)


def test_span_beyond_media_is_an_error(media):
    b = make_breakdown(duration=30.0)
    with pytest.raises(AssembleError, match="exceeds the measured media"):
        draft_edl(b, direction_with([
            {"start": 25.0, "end": 45.0, "why": "hallucinated span"},
        ]), media)


def test_no_keepers_is_an_error(media):
    with pytest.raises(AssembleError, match="no keepers"):
        draft_edl(make_breakdown(), direction_with([]), media)


def test_impossible_span_is_an_error(media):
    with pytest.raises(AssembleError, match="impossible span"):
        draft_edl(make_breakdown(), direction_with([
            {"start": 10.0, "end": 4.0, "why": "reversed"},
        ]), media)


def test_too_short_spans_dropped_with_warning(media):
    b = make_breakdown()
    result = draft_edl(b, direction_with([
        {"start": 1.0, "end": 1.1, "why": "blink"},
        {"start": 5.0, "end": 10.0, "why": "real"},
    ]), media)
    assert len(result.edl.clips) == 1
    assert any("shorter than" in w and "dropped" in w for w in result.warnings)


def test_missing_media_is_an_error(tmp_path):
    with pytest.raises(AssembleError, match="source media missing"):
        draft_edl(make_breakdown(), direction_with([
            {"start": 1.0, "end": 5.0, "why": "x"},
        ]), tmp_path / "gone.mp4")


def test_draft_for_slug_writes_edl(zing_workspace, monkeypatch):
    from myzing import storage
    from myzing.schemas import EDL

    b = make_breakdown(measured_keepers=[(2.0, 9.0)])
    storage.save_breakdown(b, slug="draft-test")
    media = storage.media_target("draft-test", "mp4")
    media.write_bytes(b"fake" if isinstance(b"fake", bytes) else b"fake")

    result = draft.draft_for_slug("draft-test", direction_with([
        {"start": 2.0, "end": 9.0, "why": "the take"},
    ]))

    saved = storage.breakdown_dir("draft-test") / "draft-edl.json"
    assert saved.is_file()
    loaded = EDL.from_json(saved.read_text(encoding="utf-8"))
    assert loaded.to_dict() == result.edl.to_dict()
    assert loaded.clips[0].src_in == 2.0
