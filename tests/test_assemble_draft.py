"""Tests for draft-EDL production (S4): keeper trims -> contiguous
timeline, loud failures, measured-keeper divergence warnings."""

from __future__ import annotations

import json

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
    assert not [w for w in result.warnings if "measured keeper" in w]


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
    assert not [w for w in result.warnings if "measured keeper" in w]  # within 0.35s tolerance


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


def test_missing_dimensions_fail_instead_of_inventing_portrait(media):
    """Lane C P2: absent measured w/h/fps must not silently become
    1080x1920@30 — that fabricates the output orientation."""
    b = make_breakdown()
    b.meta.width = 0
    b.meta.height = 0
    b.meta.fps = 0.0
    with pytest.raises(AssembleError, match="lacks measured width/height/fps"):
        draft_edl(b, direction_with([
            {"start": 5.0, "end": 10.0, "why": "x"},
        ]), media)


def test_missing_media_is_an_error(tmp_path):
    with pytest.raises(AssembleError, match="source media missing"):
        draft_edl(make_breakdown(), direction_with([
            {"start": 1.0, "end": 5.0, "why": "x"},
        ]), tmp_path / "gone.mp4")


def test_captions_derived_from_measured_words(media):
    """D-8: word-timed CaptionSpecs from the breakdown's words inside each
    trim, remapped to the output timeline."""
    from myzing.schemas import Word

    b = make_breakdown()
    b.words = [
        Word("hello", 5.2, 5.5, 0.9), Word("world", 5.6, 5.9, 0.9),
        Word("outside", 20.0, 20.4, 0.9),   # not inside any clip
        Word("after", 7.0, 7.4, 0.9),       # gap > 0.6s -> second window
    ]
    result = draft_edl(b, direction_with([
        {"start": 5.0, "end": 10.0, "why": "the take"},
    ]), media)

    caps = result.edl.captions
    assert len(caps) == 2
    # timeline remap: clip src_in 5.0 -> timeline 0.0, so 5.2 -> 0.2
    assert caps[0].start == 0.2 and caps[0].words[0].start == 0.2
    assert caps[0].text == "HELLO WORLD"      # default style: caps
    assert caps[0].word_timed is True
    assert caps[1].text == "AFTER" and caps[1].start == 2.0
    assert all("outside" not in c.text.lower() for c in caps)


def test_caption_style_measured_from_source(media):
    from myzing.schemas import CaptionEvent, Word

    b = make_breakdown()
    b.words = [Word("hi", 5.0, 5.3, 0.9)]
    b.captions = [
        CaptionEvent("lower case block", 1.0, 3.0, "top", False, 6, 0.9),
        CaptionEvent("another block", 4.0, 6.0, "top", False, 6, 0.9),
    ]
    result = draft_edl(b, direction_with([
        {"start": 4.5, "end": 8.0, "why": "x"},
    ]), media)

    (cap,) = result.edl.captions
    assert cap.position == "top"
    assert cap.all_caps is False and cap.text == "hi"
    assert cap.word_timed is False            # source shows 6 words at once


def test_no_transcript_names_caption_omission(media):
    b = make_breakdown()
    result = draft_edl(b, direction_with([
        {"start": 5.0, "end": 10.0, "why": "x"},
    ]), media)
    assert result.edl.captions == []
    assert any("no transcript" in w for w in result.warnings)


def test_assemble_cli(zing_workspace, tmp_path, capsys):
    """D-7: the direction->draft step is reachable from the CLI."""
    from myzing import cli, storage
    from myzing.schemas import Word

    b = make_breakdown(measured_keepers=[(2.0, 9.0)])
    b.words = [Word("take", 2.5, 2.9, 0.9)]
    storage.save_breakdown(b, slug="cli-asm")
    storage.media_target("cli-asm", "mp4").write_bytes(b"fake" * 4)
    direction_file = tmp_path / "direction.json"
    direction_file.write_text(json.dumps(direction_with([
        {"start": 2.0, "end": 9.0, "why": "the take"},
    ])), encoding="utf-8")

    rc = cli.main(["assemble", "cli-asm", "--direction", str(direction_file)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "draft EDL: 1 clip(s), 7.0s, 1 caption(s)" in out
    assert (storage.breakdown_dir("cli-asm") / "draft-edl.json").is_file()


def test_assemble_cli_bad_direction_file(zing_workspace, tmp_path, capsys):
    from myzing import cli

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    rc = cli.main(["assemble", "any", "--direction", str(bad)])
    assert rc == 1
    assert "unreadable direction file" in capsys.readouterr().out


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
