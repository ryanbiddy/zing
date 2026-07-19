"""Tests for the S2 profile builder: aggregation against hand-computed
stats, honest exclusions, verbatim judged collection. Offline; sources are
synthetic Breakdowns stored via the shared zing_workspace fixture."""

from __future__ import annotations

import pytest

from myzing import storage
from myzing.schemas import (
    AudioLayout,
    Breakdown,
    CaptionEvent,
    Shot,
    TransitionObservation,
    VideoMeta,
    Word,
)
from myzing.profile import api
from myzing.profile.api import ProfileError, build_profile


def make_source(
    slug: str,
    duration: float,
    cut_times: list[float],
    avg_shot: float,
    first_word: float | None = 0.2,
    captions: bool = True,
    speech_ratio: float = 0.8,
    music_confidence: float = 0.7,
    has_music: bool = True,
    judgment: dict | None = None,
    warnings: list[str] | None = None,
    transitions_ran: bool = False,
) -> Breakdown:
    starts = [0.0] + cut_times
    ends = cut_times + [duration]
    b = Breakdown(
        meta=VideoMeta(
            source_url=f"https://youtube.com/shorts/{slug}",
            platform="youtube",
            duration=duration,
        ),
        shots=[Shot(i, s, e) for i, (s, e) in enumerate(zip(starts, ends))],
        words=[Word("hi", first_word, first_word + 0.2, 0.9)]
        if first_word is not None else [],
        captions=[CaptionEvent("HI THERE", 0.5, 1.0, "lower", True, 2, 0.9)]
        if captions else [],
        audio=AudioLayout(has_music, music_confidence, True, speech_ratio, [-20.0]),
        avg_shot_duration=avg_shot,
        judgment=judgment or {},
        warnings=warnings or [],
    )
    if transitions_ran:
        b.provenance["transition_detector"] = "prototype-1"
        b.transitions = [TransitionObservation("dissolve", 1.0, 1.5)]
    storage.save_breakdown(b, slug=slug)
    return b


def test_stats_match_hand_computed(zing_workspace):
    # duration values 10, 20, 30, 40 -> inclusive quartiles 17.5/25/32.5
    # (inclusive method: percentiles never leave the observed range)
    for i, d in enumerate((10.0, 20.0, 30.0, 40.0), start=1):
        make_source(f"src-{i}", d, cut_times=[d / 2], avg_shot=d / 2)

    p = build_profile("taste", [f"src-{i}" for i in range(1, 5)])

    assert p.duration.n == 4
    assert p.duration.median == 25.0
    assert (p.duration.p25, p.duration.p75) == (17.5, 32.5)
    assert p.shot_duration.median == 12.5      # avg shots 5,10,15,20
    assert p.time_to_first_cut.median == 12.5  # cuts at 5,10,15,20
    assert p.time_to_first_word.median == 0.2
    assert p.speech_ratio.median == 0.8


def test_n2_percentiles_stay_inside_observed_range(zing_workspace):
    # The S2 gate run hit p25 = -1.085s on two non-negative first-word
    # times — exclusive-method extrapolation. Never again.
    make_source("a", 20.0, [4.0], 10.0, first_word=0.0)
    make_source("b", 20.0, [4.0], 10.0, first_word=11.065)

    p = build_profile("pair", ["a", "b"])

    assert p.time_to_first_word.p25 >= 0.0
    assert p.time_to_first_word.p25 >= 0.0
    assert 0.0 <= p.time_to_first_word.p25 <= p.time_to_first_word.p75 <= 11.065


def test_incoherent_band_gets_named_warning(zing_workspace):
    # 18s and 635s "shorts" in one profile: the duration stat can't
    # falsify anything — the profile must say so (gate-pack finding 2).
    make_source("tiny", 18.0, [4.0], 9.0)
    make_source("huge", 635.0, [100.0], 300.0)

    p = build_profile("mixed-format", ["tiny", "huge"])

    assert any(
        "profile coherence" in w and "18" in w and "635" in w
        and "may not share a format" in w
        for w in p.warnings
    )


def test_coherent_band_gets_no_warning(zing_workspace):
    make_source("s1", 30.0, [5.0], 10.0)
    make_source("s2", 45.0, [8.0], 15.0)

    p = build_profile("coherent", ["s1", "s2"])

    assert not any("profile coherence" in w for w in p.warnings)


def test_normalized_curve_aligns_relative_position(zing_workspace):
    # One cut at 50% of runtime in both a 10s and a 40s source: both land
    # in bucket 5 of 10 — the normalization the spec demands.
    make_source("short", 10.0, cut_times=[5.0], avg_shot=5.0)
    make_source("long", 40.0, cut_times=[20.0], avg_shot=20.0)

    p = build_profile("curve", ["short", "long"])

    assert len(p.cuts_per_10s_curve) == 10
    assert p.cuts_per_10s_curve[5].median == 1.0
    assert p.cuts_per_10s_curve[5].n == 2
    assert all(
        p.cuts_per_10s_curve[i].median == 0.0 for i in range(10) if i != 5
    )


def test_missing_measurements_excluded_and_named(zing_workspace):
    make_source("full", 20.0, cut_times=[4.0], avg_shot=10.0)
    make_source(
        "bare", 20.0, cut_times=[], avg_shot=20.0,
        first_word=None, captions=False,
        warnings=["speech ratio skipped: VAD failed"],
        music_confidence=0.0,
    )

    p = build_profile("mixed", ["full", "bare"])

    assert p.time_to_first_cut.n == 1          # bare has no cut
    assert p.time_to_first_word.n == 1
    assert p.time_to_first_caption.n == 1
    assert p.speech_ratio.n == 1               # bare's was skipped, not 0.0
    assert p.music_present_rate == 1.0         # over the 1 conclusive source
    assert any("time to first cut" in w and "bare" in w for w in p.warnings)
    assert any("speech ratio" in w and "bare" in w for w in p.warnings)
    assert any("music rate" in w and "bare" in w for w in p.warnings)


def test_judged_collected_verbatim_and_unjudged_named(zing_workspace):
    section = {
        "hook_type": "curiosity_gap",
        "_meta": {"prompt_version": "0.4.0"},
    }
    make_source("judged-1", 20.0, [4.0], 10.0, judgment={"study": section})
    make_source("unjudged-1", 20.0, [4.0], 10.0)

    p = build_profile("half", ["judged-1", "unjudged-1"])

    assert p.judged["study"]["judged-1"] == section   # verbatim
    assert p.judged["_meta"]["prompt_versions"] == ["0.4.0"]
    assert p.unjudged_source_slugs == ["unjudged-1"]


def test_transition_counts_only_from_sources_that_ran(zing_workspace):
    make_source("ran", 20.0, [4.0], 10.0, transitions_ran=True)
    make_source("not-run", 20.0, [4.0], 10.0)

    p = build_profile("trans", ["ran", "not-run"])

    assert p.transition_kind_counts == {"dissolve": 1}
    assert any(
        "transition counts" in w and "not-run" in w for w in p.warnings
    )


def test_missing_source_is_an_error_not_a_silent_drop(zing_workspace):
    make_source("exists", 20.0, [4.0], 10.0)
    with pytest.raises(ProfileError, match="nope"):
        build_profile("broken", ["exists", "nope"])


def test_profile_persisted_and_roundtrips(zing_workspace):
    make_source("only", 20.0, [4.0], 10.0)

    p = build_profile("saved", ["only"])

    loaded = storage.load_profile("saved")
    assert loaded.to_dict() == p.to_dict()
    assert loaded.provenance["source_count"] == 1


def test_cli_build_and_show(zing_workspace, capsys):
    from myzing import cli

    make_source("cli-1", 20.0, [4.0], 10.0)
    make_source("cli-2", 30.0, [6.0], 15.0)

    rc = cli.main(["profile", "build", "cli-taste", "cli-1", "cli-2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "profile: cli-taste" in out
    assert "sources: 2" in out

    rc = cli.main(["profile", "show", "cli-taste", "--json"])
    assert rc == 0
    import json as json_mod
    parsed = json_mod.loads(capsys.readouterr().out)
    assert parsed["name"] == "cli-taste"


def test_cli_show_missing_profile_is_honest(zing_workspace, capsys):
    from myzing import cli

    rc = cli.main(["profile", "show", "ghost"])
    assert rc == 1
    assert "ghost" in capsys.readouterr().out
