"""Draft comparison summaries use the measured values on every surface."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from myzing.explain import api, command, presentation
from myzing.explain.against import comparison_summary, summary_text
from myzing.explain.compare import compare_cards
from myzing.explain.models import StyleCard
from test_explain import full_card


@pytest.fixture
def cards():
    reference, draft = full_card(), full_card()
    for card, shot, face, lufs, box in (
        (reference, 2.36, 27.2, -19.5, [.1, .7, .9, .8]),
        (draft, 7.17, 6.28, -14.1, [.1, .1, .9, .2]),
    ):
        card.sections["pacing"].facts["shot_seconds"]["median"] = shot
        card.sections["framing"].facts["face_height_percent"] = face
        card.sections["audio"].facts.update(speech_share=.6, tempo=None, loudness={"integrated_lufs": lufs})
        card.sections["captions"].facts["caption_geometry_summary"] = {"box": box, "samples": 3}
        card.sections["transitions"].facts["events"] = None
    draft.sections["color"].facts["luma_percentiles"] = [.12, .608, .88]
    return reference, draft


def rows(cards):
    return {row["section"]: row for row in compare_cards(*cards)["summary"]}


def test_summary_orders_differences_then_unknowns_then_close(cards):
    comparison = compare_cards(*cards)
    fake = {"sections": deepcopy(comparison["sections"])}
    before = deepcopy(fake)
    summary = comparison_summary(fake)
    assert fake == before
    assert summary == comparison["summary"]
    assert len(summary) == 6
    assert [row["verdict"] for row in summary] == ["differs"] * 4 + ["unknown", "close"]
    assert {row["section"] for row in summary[:4]} == {"pacing", "framing", "audio", "captions"}
    fake["sections"]["extra"] = deepcopy(fake["sections"]["pacing"])
    assert len(comparison_summary(fake)) == 6


def test_actions_and_units_come_from_measured_numbers(cards):
    summary = rows(cards)
    assert summary["pacing"]["numbers"] == "Median shot 2.36 s reference vs 7.17 s yours."
    assert summary["pacing"]["action"] == "Cut about every 2.4 s (yours every 7.2 s)."
    assert summary["framing"]["numbers"] == "Face height 27.2% reference vs 6.28% yours."
    assert summary["framing"]["action"] == "Punch in so the face fills about 27% of the height (yours 6%)."
    assert summary["audio"]["numbers"] == "Loudness -19.5 LUFS reference vs -14.1 LUFS yours. Unknown tempo."
    assert summary["audio"]["action"] == "Bring loudness down about 5.4 dB to -19.5 LUFS."
    assert summary["captions"]["numbers"] == "Captions sit 75% down in the reference, 15% down in yours."
    assert summary["captions"]["action"] == "Move captions down to about 75% of the height."
    assert summary["color"]["numbers"] == "Brightness range within 0.11 of the reference."
    assert summary["color"]["action"] == "No change needed in these measurements."
    assert "unknown" in summary["transitions"]["numbers"]
    assert summary["transitions"]["action"] == "Measure transitions in both videos before changing them."


def test_actions_follow_reversed_targets(cards):
    summary = rows(tuple(reversed(cards)))
    assert summary["pacing"]["action"] == "Cut about every 7.2 s (yours every 2.4 s)."
    assert summary["framing"]["action"] == "Widen the framing so the face fills about 6% of the height (yours 27%)."
    assert summary["audio"]["action"] == "Bring loudness up about 5.4 dB to -14.1 LUFS."
    assert summary["captions"]["action"] == "Move captions up to about 15% of the height."


def test_caption_action_handles_size_and_horizontal_position(cards):
    cards[1].sections["captions"].facts["caption_geometry_summary"]["box"] = [.4, .7, .6, .9]
    row = rows(cards)["captions"]
    assert row["verdict"] == "differs"
    assert row["action"] == "Match the caption box width, about 80% of the frame (yours 20%)."


@pytest.mark.parametrize("section,key,value,words", [
    ("framing", "aspect", 1.78, "0.562 times its height"),
    ("audio", "speech_share", .2, "speech in about 60% of the clip (yours 20%)"),
    ("audio", "tempo", {"bpm": 160}, "tempo near 120 BPM (yours 160 BPM)"),
])
def test_another_metric_can_be_the_measured_difference(section, key, value, words):
    reference = full_card()
    reference.sections["audio"].facts.update(speech_share=.6, tempo={"bpm": 120}, loudness={"integrated_lufs": -18})
    draft = deepcopy(reference)
    draft.sections[section].facts[key] = value
    row = rows((reference, draft))[section]
    assert row["verdict"] == "differs"
    assert words in row["action"]


def test_missing_measurements_remain_unknown(cards):
    reference, draft = cards
    draft.sections["pacing"].facts["shot_seconds"]["median"] = None
    draft.sections["captions"].facts["caption_geometry_summary"] = None
    reference.sections["color"].facts["luma_percentiles"] = None
    summary = rows(cards)
    assert summary["pacing"]["verdict"] == "unknown"
    assert summary["pacing"]["numbers"] == "Median shot 2.36 s reference vs unknown yours."
    assert "Cut about" not in summary["pacing"]["action"]
    assert "unknown yours" in summary["captions"]["numbers"]
    assert "Move captions" not in summary["captions"]["action"]
    assert summary["color"]["numbers"] == "Brightness range unknown."
    assert summary["color"]["verdict"] == "unknown"


def test_disputed_pacing_does_not_recommend_a_cut_interval(cards):
    cards[0].sections["pacing"].facts["v6_additional_cut_times"] = [1.2]
    row = rows(cards)["pacing"]
    assert row["verdict"] == "unknown"
    assert "detectors disagree" in row["action"]
    assert "Cut about" not in row["action"]


def test_close_measurements_need_no_changes(cards):
    reference = cards[0]
    reference.sections["audio"].facts["tempo"] = {"bpm": 120}
    reference.sections["transitions"].facts["events"] = []
    summary = compare_cards(reference, deepcopy(reference))["summary"]
    assert len(summary) == 6
    assert all(row["verdict"] == "close" and row["action"].startswith("No change needed") for row in summary)
    transitions = next(row for row in summary if row["section"] == "transitions")
    assert transitions["numbers"] == "No transition signatures detected in either video."


def test_color_action_only_addresses_measured_brightness(cards):
    cards[1].sections["color"].facts["luma_percentiles"] = [.4, .7, 1]
    row = rows(cards)["color"]
    assert row["verdict"] == "differs"
    assert row["numbers"] == "Brightness range differs by up to 0.30."
    assert row["action"] == "Match the reference's measured brightness range."


def test_transition_action_uses_rates_for_each_duration(cards):
    reference, draft = cards
    reference.duration_seconds, draft.duration_seconds = 20, 6
    reference.sections["transitions"].facts["events"] = [{"signature": "dissolve"}] * 6
    draft.sections["transitions"].facts["events"] = []
    row = rows(cards)["transitions"]
    assert row["verdict"] == "differs"
    assert "18 per minute reference vs 0 per minute yours" in row["numbers"]
    assert row["action"] == "Aim for about 18 dissolves per minute (yours 0)."


@pytest.fixture
def drawn(monkeypatch):
    pytest.importorskip("PIL.Image")
    from PIL import ImageDraw

    drawn = []
    original = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        drawn.append((xy, text, kwargs["font"].size, kwargs["fill"]))
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    monkeypatch.setattr(presentation, "_grab", lambda media, t, width, height: bytes(width * height * 3))
    return drawn


def test_png_leads_with_readable_colored_summary(cards, drawn, tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    card = cards[0]
    card.comparison = compare_cards(*cards)
    out = tmp_path / "card.png"
    preview = presentation.render_png(card, "unused.mp4", out)
    text = " ".join(t for _, t, _, _ in drawn)
    assert text.index("measured from the export") < text.index("Your draft vs the reference") < text.index("What a viewer notices")
    for row in card.comparison["summary"]:
        assert row["numbers"] in text and row["action"] in text
    assert "see the top of this card" in text and "numbers in card.md" not in text
    expected = {"differs": "#b14b2d", "close": "#247c75", "unknown": "#52615c"}
    verdicts = [(t, size, color) for _, t, size, color in drawn if t in expected]
    assert len(verdicts) == 6
    assert all(size == 30 and color == expected[t] for t, size, color in verdicts)
    with Image.open(out) as image:
        assert image.width == 800 and image.height == preview["height"]
        assert all(36 <= x <= 764 and y + size < image.height for (x, y), t, size, _ in drawn if t)
        top = next(xy[1] for xy, t, _, _ in drawn if t == "Your draft vs the reference")
        bottom = next(xy[1] for xy, t, _, _ in drawn if t == "What a viewer notices")
        font_path = Path(presentation.__file__).resolve().parents[1] / "_data/fonts/IBMPlexSans.ttf"
        for xy, t, size, _ in drawn:
            if top <= xy[1] < bottom:
                box = ImageDraw.Draw(image).textbbox(xy, t, font=ImageFont.truetype(str(font_path), size))
                assert 36 <= box[0] and box[2] <= 764
    assert min(size for _, t, size, _ in drawn if t) == 26


@pytest.fixture
def measured(cards, tmp_path, monkeypatch):
    clips = tmp_path / "clips"
    clips.mkdir()
    sources = [clips / "reference.mp4", clips / "draft.mp4"]
    for path in sources:
        path.write_bytes(b"fake media")
    monkeypatch.setattr(api, "probe_video", lambda path: {})

    def measure(source, out, **kwargs):
        card = deepcopy(cards[sources.index(Path(source))])
        card.source = str(source)
        card.recipe_path = str(out / "style-recipe.json")
        return card, source

    monkeypatch.setattr(api, "_measure", measure)
    return sources


@pytest.mark.parametrize("json_output", [False, True])
def test_cli_and_saved_cards_share_the_leading_summary(measured, drawn, tmp_path, capsys, json_output):
    reference, draft = measured
    out = tmp_path / "card"
    args = [str(reference), "--against", str(draft), "--out", str(out)]
    assert command.run(args + (["--json"] if json_output else [])) == 0
    text = capsys.readouterr().out
    stored = json.loads((out / "card.json").read_text(encoding="utf-8"))
    summary = stored["comparison"]["summary"]
    assert StyleCard.from_dict(stored).to_dict() == stored
    md = (out / "card.md").read_text(encoding="utf-8")
    block = "\n".join("- " + summary_text(row) for row in summary)
    assert "## Your draft vs the reference\n\n" + block + "\n\n## What a viewer notices" in md
    assert md.count("Against the draft:") == 6
    if json_output:
        assert json.loads(text)["comparison"] == stored["comparison"]
    else:
        assert text.startswith("Your draft vs the reference:\n" + block + "\nWhat a viewer notices:")
    assert (out / "card.png").is_file()
    other = json.loads((out / "against" / "card.json").read_text(encoding="utf-8"))
    assert other["comparison"] == {}


def test_comparison_summary_survives_missing_pillow(measured, tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise ImportError("Pillow unavailable")

    monkeypatch.setattr(presentation, "render_png", missing)
    out = tmp_path / "card"
    result = api._explain(measured[0], out, against=measured[1])
    assert result["ok"] and result["card_png"] is None
    stored = json.loads((out / "card.json").read_text(encoding="utf-8"))
    assert len(result["comparison"]["summary"]) == 6
    assert result["comparison"] == stored["comparison"]
    assert "## Your draft vs the reference" in (out / "card.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("json_output", [False, True])
def test_without_against_keeps_existing_output(measured, drawn, tmp_path, capsys, json_output):
    reference, _ = measured
    out = tmp_path / "card"
    args = [str(reference), "--out", str(out)]
    assert command.run(args + (["--json"] if json_output else [])) == 0
    text = capsys.readouterr().out
    stored = json.loads((out / "card.json").read_text(encoding="utf-8"))
    assert stored["comparison"] == {}
    md = (out / "card.md").read_text(encoding="utf-8")
    assert md == presentation.markdown(StyleCard.from_dict(stored))
    assert md.split("## ")[1].startswith("What a viewer notices")
    assert "Your draft vs the reference" not in md
    assert "Your draft vs the reference" not in " ".join(t for _, t, _, _ in drawn)
    assert "Against the draft" not in md
    if json_output:
        result = json.loads(text)
        assert set(result) == {"ok", "card_json", "card_md", "card_png", "summary", "hook"}
        assert result["summary"] == stored["summary"]
    else:
        expected = ["What a viewer notices:", *["- " + line for line in stored["summary"]], "Hook and loop:",
                    *["- " + line for line in stored["sections"]["hook"]["lines"]], str(out / "card.md"), str(out / "card.png")]
        assert text == "\n".join(expected) + "\n"
    assert not (out / "against").exists()
