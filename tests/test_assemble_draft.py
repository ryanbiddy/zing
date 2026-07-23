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


@pytest.mark.parametrize(
    ("measured", "expected", "preset"),
    [
        ((240, 426), (234, 416), "vertical"),
        ((426, 240), (416, 234), "landscape"),
        ((1079, 1080), (1078, 1078), "square"),
    ],
)
def test_near_preset_source_maps_to_exact_even_output(
    media,
    measured,
    expected,
    preset,
):
    from myzing.render.validation import output_preset

    b = make_breakdown()
    b.meta.width, b.meta.height = measured

    result = draft_edl(b, direction_with([
        {"start": 5.0, "end": 10.0, "why": "x"},
    ]), media)

    assert (result.edl.width, result.edl.height) == expected
    assert output_preset(*expected) == preset
    assert any(
        f"measured {measured[0]}x{measured[1]}" in warning
        and f"output {expected[0]}x{expected[1]}" in warning
        for warning in result.warnings
    )
    assert (b.meta.width, b.meta.height) == measured


def test_non_preset_source_aspect_fails_before_render(media):
    b = make_breakdown()
    b.meta.width = 1000
    b.meta.height = 700

    with pytest.raises(AssembleError, match="not within 2%"):
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


def test_trim_edge_words_captioned_with_clamped_times(media):
    """D-10: a word straddling a trim edge is admitted when its midpoint
    lies inside the span, with start/end clamped to the trim (both edges);
    a word whose midpoint falls outside stays dropped."""
    from myzing.schemas import Word

    b = make_breakdown()
    b.words = [
        Word("intro", 4.85, 5.05, 0.9),     # straddles src_in, midpoint 4.95 outside
        Word("start", 4.9, 5.2, 0.9),       # straddles src_in, midpoint 5.05 inside
        Word("this", 9.72, 10.02, 0.9),     # gate's case: 93% audible, tail past src_out
    ]
    result = draft_edl(b, direction_with([
        {"start": 5.0, "end": 10.0, "why": "the take"},
    ]), media)

    caps = result.edl.captions
    texts = " ".join(c.text for c in caps)
    assert "INTRO" not in texts
    assert "START" in texts and "THIS" in texts
    words = [w for c in caps for w in c.words]
    assert words[0].start == 0.0            # 4.9 clamped to src_in -> timeline 0.0
    assert words[-1].end == 5.0             # 10.28 clamped to src_out -> timeline 5.0
    assert all(0.0 <= w.start <= w.end <= 5.0 for w in words)


def test_trim_inside_measured_words_warns_without_changing_edl(media):
    from myzing.schemas import Word

    b = make_breakdown()
    b.words = [
        Word("opening", 4.8, 5.2, 0.9),
        Word("middle", 6.0, 6.4, 0.9),
        Word("closing", 9.8, 10.2, 0.9),
    ]
    result = draft_edl(b, direction_with([
        {"start": 5.0, "end": 10.0, "why": "the take"},
    ]), media)

    boundary = [
        warning for warning in result.warnings
        if "context-boundary risk" in warning
    ]
    assert boundary == [
        "draft EDL: context-boundary risk — keeper 0 starts at 5.000s "
        "inside measured word 'opening' (4.800-5.200s, confidence 0.90); "
        "adjust the trim or verify the audible cut",
        "draft EDL: context-boundary risk — keeper 0 ends at 10.000s "
        "inside measured word 'closing' (9.800-10.200s, confidence 0.90); "
        "adjust the trim or verify the audible cut",
    ]
    assert [
        (clip.src_in, clip.src_out, clip.timeline_start)
        for clip in result.edl.clips
    ] == [(5.0, 10.0, 0.0)]


def test_exact_word_edges_and_missing_transcript_do_not_warn(media):
    from myzing.schemas import Word

    exact = make_breakdown()
    exact.words = [
        Word("before", 4.5, 5.0, 0.9),
        Word("inside", 5.0, 6.0, 0.9),
        Word("after", 10.0, 10.4, 0.9),
    ]
    exact_result = draft_edl(exact, direction_with([
        {"start": 5.0, "end": 10.0, "why": "exact boundaries"},
    ]), media)
    missing_result = draft_edl(make_breakdown(), direction_with([
        {"start": 5.0, "end": 10.0, "why": "no transcript"},
    ]), media)

    assert not any(
        "context-boundary risk" in warning
        for warning in exact_result.warnings + missing_result.warnings
    )


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


def test_assemble_cli_json_output(zing_workspace, tmp_path, capsys):
    from myzing import cli, storage
    from myzing.schemas import Word

    b = make_breakdown(measured_keepers=[(2.0, 9.0)])
    b.words = [Word("take", 2.5, 2.9, 0.9)]
    storage.save_breakdown(b, slug="cli-json")
    storage.media_target("cli-json", "mp4").write_bytes(b"fake" * 4)
    direction_file = tmp_path / "direction.json"
    direction_file.write_text(json.dumps(direction_with([
        {"start": 2.0, "end": 9.0, "why": "the take"},
    ])), encoding="utf-8")

    rc = cli.main(["assemble", "cli-json", "--direction", str(direction_file), "--json"])

    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["clips"][0]["src_in"] == 2.0


def test_assemble_cli_missing_media_is_honest(zing_workspace, tmp_path, capsys):
    from myzing import cli, storage

    b = make_breakdown()
    storage.save_breakdown(b, slug="cli-nomedia")
    direction_file = tmp_path / "direction.json"
    direction_file.write_text(json.dumps(direction_with([
        {"start": 2.0, "end": 9.0, "why": "x"},
    ])), encoding="utf-8")

    rc = cli.main(["assemble", "cli-nomedia", "--direction", str(direction_file)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "no stored media" in out
def test_thin_caption_style_basis_warns(media):
    """O-3 (S5 gate): a handful of measured on-screen text events styling
    every derived caption is a guess, and says so."""
    from myzing.schemas import CaptionEvent, Word

    b = make_breakdown()
    b.words = [Word("hi", 5.0, 5.3, 0.9), Word("there", 5.4, 5.7, 0.9)]
    b.captions = [
        CaptionEvent("junk", 1.0, 2.0, "center", True, 1, 0.8)
        for _ in range(13)
    ]
    result = draft_edl(b, direction_with([
        {"start": 4.5, "end": 8.0, "why": "x"},
    ]), media)

    assert result.edl.captions
    assert any(
        "13 on-screen text event(s)" in w
        and "thin basis" in w
        and "guess" in w
        for w in result.warnings
    )


def test_rich_caption_style_basis_does_not_warn(media):
    from myzing.schemas import CaptionEvent, Word

    b = make_breakdown()
    b.words = [Word("hi", 5.0, 5.3, 0.9)]
    b.captions = [
        CaptionEvent(f"word {i}", i * 1.0, i * 1.0 + 0.5, "lower", False, 1, 0.9)
        for i in range(20)
    ]
    result = draft_edl(b, direction_with([
        {"start": 4.5, "end": 8.0, "why": "x"},
    ]), media)

    # Assert the CATEGORY, not a phrase: this test asserted a substring
    # that a later merge deleted, so it could not fail for one cycle —
    # the vacuous-test class Lane B found in #358. Category survives
    # rewording; a phrase does not.
    assert not any("caption style" in w for w in result.warnings)


def test_every_keeper_too_short_is_an_error(media):
    with pytest.raises(AssembleError, match="too short to trim"):
        draft_edl(make_breakdown(), direction_with([
            {"start": 1.0, "end": 1.1, "why": "blink"},
        ]), media)


def test_no_words_inside_spans_names_caption_omission(media):
    from myzing.schemas import Word

    b = make_breakdown()
    b.words = [Word("outside", 50.0, 50.4, 0.9)]
    result = draft_edl(b, direction_with([
        {"start": 5.0, "end": 10.0, "why": "x"},
    ]), media)

    assert result.edl.captions == []
    assert any("no transcript words fall inside" in w for w in result.warnings)


def test_source_too_small_for_even_preset_is_an_error(media):
    """_output_dimensions: a 9:16 source too small for any even-scaled
    preset frame refuses rather than emitting a degenerate render."""
    b = make_breakdown()
    b.meta.width = 9
    b.meta.height = 16
    with pytest.raises(AssembleError, match="too small for an even preset"):
        draft_edl(b, direction_with([
            {"start": 5.0, "end": 10.0, "why": "x"},
        ]), media)


def test_keeper_missing_start_key_is_an_error(media):
    with pytest.raises(AssembleError, match="lacks numeric start/end"):
        draft_edl(make_breakdown(), direction_with([
            {"end": 9.0, "why": "no start"},
        ]), media)


def test_long_form_caption_style_basis_warns(media):
    """Counterpart to the thin-basis warning: past the short-form
    boundary the overlay exclusion is MEASURED to under-fire, so a big
    caption basis may be watermarks and HUD. zing assemble runs with no
    AI in the loop, so the warning must come from the engine."""
    from myzing.schemas import CaptionEvent, Word

    b = make_breakdown(duration=430.0)
    b.words = [Word("hi", 5.0, 5.3, 0.9), Word("there", 5.4, 5.7, 0.9)]
    b.captions = [
        CaptionEvent(f"TOP RUN {i}", i * 1.0, i * 1.0 + 0.5, "center", True, 2, 0.9)
        for i in range(40)
    ]
    result = draft_edl(b, direction_with([
        {"start": 4.5, "end": 8.0, "why": "x"},
    ]), media)

    assert any(
        "overlay exclusion is measured to under-fire" in w
        and "verify it against a frame" in w
        for w in result.warnings
    )


def test_short_form_caption_style_does_not_get_the_long_form_warning(media):
    from myzing.schemas import CaptionEvent, Word

    b = make_breakdown(duration=45.0)
    b.words = [Word("hi", 5.0, 5.3, 0.9)]
    b.captions = [
        CaptionEvent(f"WORD {i}", i * 1.0, i * 1.0 + 0.5, "lower", False, 1, 0.9)
        for i in range(40)
    ]

    result = draft_edl(b, direction_with([
        {"start": 4.5, "end": 8.0, "why": "x"},
    ]), media)

    assert not any("caption style" in w for w in result.warnings)


def test_both_caption_style_risks_produce_one_warning_naming_both(media):
    """They were two warnings until both fired on one draft with
    overlapping text — redundant noise in the list judging AIs read
    first. One warning now, naming every risk that applies."""
    from myzing.schemas import CaptionEvent, Word

    b = make_breakdown(duration=430.0)          # long-form AND
    b.words = [Word("hi", 5.0, 5.3, 0.9), Word("there", 5.4, 5.7, 0.9)]
    b.captions = [                              # thin basis
        CaptionEvent(f"x{i}", i * 1.0, i * 1.0 + 0.5, "center", True, 1, 0.9)
        for i in range(8)
    ]

    result = draft_edl(b, direction_with([
        {"start": 4.5, "end": 8.0, "why": "x"},
    ]), media)

    style = [w for w in result.warnings if "caption style" in w]
    assert len(style) == 1, f"expected one merged warning, got {style}"
    assert "under-fire" in style[0] and "thin basis" in style[0]


def test_word_timed_is_corrupted_by_non_caption_text_documented(media):
    """DOCUMENTED DEFECT, pinned so it stays visible (queued fix:
    region-merge item). Single-token NON-caption text — product labels,
    HUD, price tags — dominates the words_visible mode and flips
    word_timed to True even when the real captions are phrases.

    Measured on youtube-fuxm3vz-keo (38s, frame-verified phrase
    captions, 42 single-token product-image events): style comes back
    word_timed=True, and NEITHER guard fires because the basis is large
    and the video is short. Filtering to speech-overlapping events was
    tested and does NOT fix it (84/86 events survive).

    If a future change fixes this, update this test to assert
    word_timed is False for the mixed case.
    """
    from myzing.schemas import CaptionEvent, Word

    b = make_breakdown(duration=38.0)
    b.words = [Word("samsung", 1.0, 1.4, 0.9), Word("debate", 1.5, 1.9, 0.9)]
    b.captions = (
        # the real captions: phrases
        [CaptionEvent(f"PHRASE {i} HERE", i * 2.0, i * 2.0 + 1.0, "center", True, 3, 0.9)
         for i in range(10)]
        # product-image text: single tokens, more numerous
        + [CaptionEvent(f"Pro{i}", i * 0.5, i * 0.5 + 0.3, "top", False, 1, 0.9)
           for i in range(20)]
    )

    result = draft_edl(b, direction_with([
        {"start": 0.5, "end": 8.0, "why": "x"},
    ]), media)

    assert result.edl.captions[0].word_timed is True   # the documented defect
    assert not any("caption style" in w for w in result.warnings), (
        "neither guard fires here — that absence is the point of this test"
    )
