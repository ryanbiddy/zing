"""HOOKCARD: evidence, unknowns, thresholds and all readable surfaces."""

import json

import pytest

from myzing.explain import hook
from myzing.explain.models import HookMetric, StyleCard
from myzing.explain.plain import hook_lines
from myzing.explain.presentation import markdown
from myzing.explain.sections import build_sections
from myzing.schemas import Breakdown, CaptionEvent, Shot, VideoMeta, Word


def breakdown(duration=40, cuts=(1, 2, 3, 20)):
    edges = [0, *cuts, duration]
    return Breakdown(VideoMeta("clip.mp4", "file", duration=duration, fps=10, width=64, height=64),
                     shots=[Shot(i, a, b) for i, (a, b) in enumerate(zip(edges, edges[1:]))],
                     words=[Word("Hello", .7, 1)], captions=[CaptionEvent(text="Hello", start=.4, end=1)],
                     provenance={"shot_detector": "fixture"})


def section(b=None, visual=None):
    return build_sections((b or breakdown()).to_dict(), hook_visual=visual)["hook"]


def test_first_timings_use_the_profile_helpers(monkeypatch):
    for name, value in (("word", .11), ("cut", .22), ("caption", .33)):
        monkeypatch.setattr(hook.profile, "_first_" + name, lambda b, v=value: v)
    facts = section().facts
    for name, value in (("word", .11), ("cut", .22), ("caption", .33)):
        row = facts["time_to_first_" + name]
        assert row["value"] == value
        assert row["status"] == "measured" and row["basis"] and row["method"]


def test_timings_rates_boundary_and_roundtrip():
    s = section()
    assert s.facts["time_to_first_word"]["value"] == .7
    assert s.facts["time_to_first_caption"]["value"] == .4
    assert s.facts["time_to_first_cut"]["value"] == 1
    rate = s.facts["opening_cut_rate"]["value"]
    assert rate["opening_end_seconds"] == 3
    assert rate["opening_cuts_per_10s"] == pytest.approx(20 / 3)
    assert rate["rest_cuts_per_10s"] == pytest.approx(20 / 37)
    for row in s.facts.values():
        assert HookMetric.from_dict(json.loads(json.dumps(row))).to_dict() == row
    card = StyleCard("clip.mp4", "a" * 64, 40, build_sections(breakdown().to_dict()), "recipe.json", [], ["a", "b", "c"])
    assert StyleCard.from_dict(card.to_dict()).sections["hook"] == s
    text = markdown(card)
    assert "## Hook and loop" in text and "First word at 0.7s" in text
    assert "Payoff spacing (unknown)" in text and "> 0.98" in text
    assert text.index("## Cuts and pacing") < text.index("## Hook and loop")
    assert "### How these were measured" in text
    for fact in s.facts.values():
        assert fact["method"].rstrip(".") in text and fact["basis"] in text


@pytest.mark.parametrize("duration", [1, 12, 30, 60])
def test_short_window_is_ten_percent_and_no_cuts_is_measured_zero(duration):
    b = breakdown(duration, ())
    b.words, b.captions = [], []
    s = section(b)
    for name in ("word", "cut", "caption"):
        assert s.facts["time_to_first_" + name]["value"] is None
        assert any(f"first {name} unknown" in line.lower() for line in s.lines)
    rate = s.facts["opening_cut_rate"]["value"]
    assert rate["opening_end_seconds"] == min(3, duration * .1)
    assert rate["opening_cuts_per_10s"] == rate["rest_cuts_per_10s"] == 0


@pytest.mark.parametrize("cause", ["no_shots", "skipped", "zero_duration"])
def test_unmeasured_cuts_never_become_zero(cause):
    b = breakdown()
    if cause == "no_shots":
        b.shots = []
    elif cause == "skipped":
        b.warnings.append("shot detection skipped: missing dependency")
    else:
        b.meta.duration = 0
    s = section(b)
    assert s.facts["opening_cut_rate"]["value"] is None
    assert s.facts["time_to_first_cut"]["value"] is None


def test_disagreeing_cut_detectors_are_disclosed_in_hook():
    b = breakdown()
    b.provenance["transition_evidence"] = [{"start_seconds": .5, "end_seconds": .5, "signature": "hard_cut", "confidence": .9}]
    s = section(b)
    assert "may undercount" in s.facts["opening_cut_rate"]["basis"]
    assert "may be late" in s.facts["time_to_first_cut"]["basis"]


def test_payoff_spacing_reuses_stored_story_judgments_only():
    b = breakdown()
    b.judgment = {"beats": [{"label": "payoff", "start": t, "end": t + 1, "evidence": "Supplied annotation"}
                            for t in (1, 5, 15)]}
    row = section(b).facts["payoff_spacing"]
    assert row["status"] == "judgment"
    assert row["value"] == {"median": 7, "min": 4, "max": 10, "gap_count": 2}
    assert any("Labeled payoffs: median gap 7s (range 4-10s)." in line for line in section(b).lines)
    assert len(section(b).lines) == 4
    b.judgment = {"beats": [{"label": "build", "start": 0, "end": 40}]}
    assert section(b).facts["payoff_spacing"]["value"] is None


@pytest.mark.parametrize("bad", [{"start": -1}, {"end": 60}, {"start": True}, {"evidence": ""}, {"start": 2}])
def test_bad_payoff_annotations_abstain(bad):
    b = breakdown()
    b.judgment = {"beats": [{"label": "payoff", "start": 1, "end": 4, "evidence": "annotation"},
                            {"label": "payoff", "start": 5, "end": 6, "evidence": "annotation", **bad}]}
    assert section(b).facts["payoff_spacing"]["status"] == "unknown"


@pytest.mark.parametrize("delta,clean", [(0, True), (5.1, False), (255, False)])
def test_visual_threshold_is_strict_and_uses_existing_distance(monkeypatch, delta, clean):
    monkeypatch.setattr(hook, "distance", lambda a, b: delta)
    observed = hook._compare_frames(bytes(80 * 3), 80, 3, 8, 10)
    seam = observed["loop_seam"]["value"]
    assert seam["loops_cleanly"] is clean
    assert seam["last_seconds"] == 7.9
    flash = observed["flash_forward"]["value"]
    assert flash["candidate"] is clean
    assert (flash["matched_seconds"] is not None) is clean
    text = " ".join(section(visual=observed).lines)
    assert ("loops cleanly" in text) is clean


def test_short_visual_windows_do_not_match_a_frame_with_itself():
    observed = hook._compare_frames(bytes([0, 255]), 2, 1, .2, 10)
    assert observed["flash_forward"]["status"] == "unknown"  # no frame strictly after midpoint
    assert observed["loop_seam"]["value"]["loops_cleanly"] is False


def test_sixty_seconds_is_not_loop_eligible():
    assert hook._compare_frames(bytes(120), 120, 1, 60, 2)["loop_seam"]["status"] == "not_applicable"
    lines = section(breakdown(60)).lines
    assert "Loop not checked: 60s or longer." in lines
    assert "Flash-forward not checked: 60s or longer." in lines


@pytest.mark.parametrize("data", [b"", b"short", bytes(3 * hook.FRAME_SIDE**2 * 3)], ids=["missing", "partial", "capped"])
def test_decode_missing_partial_or_capped_abstains(monkeypatch, data):
    monkeypatch.setattr(hook, "MAX_FRAMES", 3)
    monkeypatch.setattr("myzing.inspect.media.Decoder.run", lambda *a: data)
    assert hook.measure_visual("unused.mp4", 8, 10)["loop_seam"]["status"] == "unknown"


def test_decode_failure_stays_unknown(monkeypatch):
    def fail(*a):
        raise ValueError("ffmpeg unavailable")
    monkeypatch.setattr("myzing.inspect.media.Decoder.run", fail)
    observed = hook.measure_visual("unused.mp4", 8, 10)
    assert all(row["value"] is None and "ffmpeg unavailable" in row["basis"] for row in observed.values())


def test_cli_prints_hook_measurements(monkeypatch, capsys):
    from myzing.explain import command
    monkeypatch.setattr(command, "_explain", lambda *a, **k: {
        "ok": True, "summary": [], "card_md": "card.md", "card_png": None, "hook": section().lines})
    assert command.run(["clip.mp4"]) == 0
    text = capsys.readouterr().out
    assert "Hook and loop:" in text and "First word at 0.7s" in text and "Loop not checked:" in text
    assert "Visual method" not in text and "Minimum stored" not in text


def test_missing_words_do_not_establish_no_speech():
    b = breakdown()
    b.words = []
    assert section(b).lines[0].startswith("First word unknown;")
    b.warnings.append("no audio stream")
    s = section(b)
    assert s.lines[0].startswith("No speech; first cut at 1.0s;")
    assert s.facts["time_to_first_word"]["value"] is None
    assert s.facts["time_to_first_word"]["status"] == "unknown"


def test_hook_summary_is_four_plain_lines_without_changing_facts():
    b = breakdown(8, (1, 3, 6, 7))
    b.words, b.captions = [], []
    b.warnings.append("no audio stream")
    # Exact repeated red at 6s, different blue endpoint.
    red, green, blue = bytes((255, 0, 0)), bytes((0, 255, 0)), bytes((0, 0, 255))
    visual = hook._compare_frames(red * 10 + green * 50 + red * 10 + blue * 10, 80, 3, 8, 10)
    s = section(b, visual)
    before = json.loads(json.dumps(s.facts))
    assert s.lines == [
        "No speech; first cut at 1.0s; first caption unknown.",
        "Opens slower: no cuts in the first 0.8s, then 5.6 per 10s.",
        "Ending does not match the opening frame, so it does not loop cleanly by this pixel check.",
        "Possible flash-forward: the opening image returns at 6.0s (pixel match only).",
    ]
    assert hook_lines(s.facts, has_audio_stream=False) == s.lines
    assert s.facts == before


def test_png_hook_has_the_same_caps_and_keeps_not_knowable(monkeypatch, tmp_path):
    pytest.importorskip("PIL")
    from PIL import ImageDraw
    from myzing.explain import presentation

    card = StyleCard("clip.mp4", "a" * 64, 40, build_sections(breakdown().to_dict()), "recipe.json", [], ["a", "b", "c"])
    card.sections["hook"].lines = ["word " * 48 + "TRIMMED", "second", "third", "fourth", "FIFTH"]
    before = {key: json.loads(json.dumps(s.facts)) for key, s in card.sections.items()}
    drawn = []
    original = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        drawn.append(text)
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    monkeypatch.setattr(presentation, "_grab", lambda media, t, width, height: bytes(width * height * 3))
    presentation.render_png(card, "unused.mp4", tmp_path / "card.png")
    text = " ".join(drawn)
    assert "TRIMMED" not in text and "FIFTH" not in text and "fourth" in text
    assert text.index("What a viewer notices") < text.index("Cuts and pacing") < text.index("Hook and loop")
    assert "Not knowable: " + card.sections["hook"].not_knowable in text
    assert {key: s.facts for key, s in card.sections.items()} == before


def test_metric_contract_rejects_false_facts():
    with pytest.raises(ValueError):
        HookMetric("method", "basis", 0)
    with pytest.raises(ValueError):
        HookMetric("method", "", 0, "measured")
    with pytest.raises(ValueError):
        HookMetric("method", "basis", float("nan"), "measured")
