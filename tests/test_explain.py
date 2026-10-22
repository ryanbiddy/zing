"""CARD1 model, measured units, abstention, comparisons and public boundaries."""

import inspect
import json
from copy import deepcopy

import pytest

from myzing.explain.api import explain_video
from myzing.explain.compare import compare_cards
from myzing.explain.models import Section, StyleCard
from myzing.explain.sections import build_sections, captions, pacing, transitions
from myzing.schemas import Breakdown, VideoMeta, Shot


def breakdown():
    return Breakdown(VideoMeta("test.mp4", "file", duration=12, width=360, height=640, fps=30),
                     shots=[Shot(0, 0, 4), Shot(1, 4, 8), Shot(2, 8, 12)],
                     provenance={"shot_detector": "synthetic oracle", "transition_evidence": []}).to_dict()


def card():
    return StyleCard("test.mp4", "a"*64, 12, build_sections(breakdown()), "recipe.json", [], ["one", "two", "three"])


def test_card_roundtrip_and_copy():
    original = card()
    wire = original.to_dict()
    restored = StyleCard.from_dict(json.loads(json.dumps(wire)))
    assert restored == original
    wire["sections"]["pacing"]["facts"]["cut_times"].append(9)
    assert restored.sections["pacing"].facts["cut_times"] == [4, 8]


@pytest.mark.parametrize("version", [None, 2, True, "1"])
def test_version_rejected(version):
    wire = card().to_dict()
    wire["version"] = version
    with pytest.raises(ValueError):
        StyleCard.from_dict(wire)


def test_nested_version_and_nonfinite_rejected():
    wire = card().to_dict()
    wire["sections"]["audio"]["version"] = 20
    with pytest.raises(ValueError):
        StyleCard.from_dict(wire)
    with pytest.raises(ValueError):
        Section("bad", {"x": float("nan")})


def test_pacing_rates_distribution_and_beats():
    section = pacing(breakdown(), {"beats": [4.03, 8.2], "structure": {"moments": [{"kind": "drop", "time": 8}]}})
    assert section.facts["cuts_per_minute"] == 10
    assert section.facts["shot_seconds"] == {"min": 4, "median": 4, "max": 4, "values": [4, 4, 4]}
    assert section.facts["cuts_on_beats"] == 1
    assert section.facts["drop_alignment"][-1]["delta_seconds"] == 0
    assert section.facts["windows"][1]["change"] == "slower"


def test_missing_measurement_is_not_zero():
    b = breakdown()
    b["shots"] = []
    b["provenance"] = {}
    sections = build_sections(b)
    assert sections["pacing"].facts == {}
    assert sections["audio"].facts["speech_share"] is None
    assert sections["audio"].facts["music_presence_candidate"] is None
    assert sections["color"].facts == {}
    assert all(s.unknowns for s in sections.values())


def test_transitions_keep_unknown_apart():
    b = breakdown()
    b["provenance"]["transition_evidence"] = [dict(signature=kind, start_seconds=i, end_seconds=i+.3, confidence=.8, reason="test") for i, kind in enumerate(["dissolve", "unknown"])]
    s = transitions(b)
    assert len(s.facts["events"]) == len(s.facts["abstentions"]) == 1
    assert s.facts["events"][0]["signature"] == "dissolve"
    assert "Unclassified" in s.unknowns[-1]


def test_caption_height_uses_short_side_and_low_font_score_is_substitute():
    geometry = {"version": 2, "tracks": [dict(id="t1", text="HELLO WORLD", kind="caption", motion="popping", median_text_height=.05,
                   samples=[{"t": 0, "text": "HELLO WORLD", "box": [.1, .7, .9, .75]}])],
                "font_candidates": {"tracks": [{"track_id": "t1", "candidates": [{"family": "Anton", "score": .72}]}]}}
    s = captions(breakdown(), geometry)
    assert s.facts["tracks"][0]["size_percent_short_side"] == pytest.approx(.05*640/360*100)
    assert s.facts["tracks"][0]["zone"] == "lower"
    assert s.facts["tracks"][0]["display"] == "cumulative word popping"
    assert s.facts["font_candidates"][0]["candidates"][0]["label"] == "best substitute"
    assert s.facts["caption_geometry_summary"] is None  # no speech-supported caption role


def test_rejected_ocr_never_becomes_appearance_evidence():
    geometry = {"version": 2, "frames": [{"t": 0, "detections": [{"text": "FAKE", "confidence": .99, "validation": {"accepted": False}, "appearance": {"stroke_width_px": 3}}]}]}
    assert captions(breakdown(), geometry).facts["appearance_samples"] == []


def test_comparison_close_differs_unknown_have_numbers():
    a, b = card(), card()
    result = compare_cards(a, b)["sections"]
    assert result["pacing"]["status"] == "close"
    assert result["color"]["status"] == "unknown"
    assert result["captions"]["status"] == "unknown"
    b.sections["pacing"].facts["shot_seconds"]["median"] = 2
    result = compare_cards(a, b)["sections"]["pacing"]
    assert result["status"] == "differs"
    assert result["metrics"]["median_shot_seconds"]["target"] == 4
    assert result["metrics"]["median_shot_seconds"]["observed"] == 2
    assert result["metrics"]["median_shot_seconds"]["tolerance"] == .4


def test_public_signature_and_download_consent(tmp_path, monkeypatch):
    assert list(inspect.signature(explain_video).parameters) == ["source", "out_dir", "transitions", "offline"]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("unexpected network"))
    result = explain_video("https://example.com/video.mp4", tmp_path / "out")
    assert not result["ok"] and "consent" in result["error"]
    assert not (tmp_path / "out").exists()


def test_no_overwrite_or_source_output(tmp_path):
    media = tmp_path / "clips" / "source.mp4"
    media.parent.mkdir()
    media.write_bytes(b"test")
    assert not explain_video(media, media.parent / "out")["ok"]
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("keep")
    assert "not empty" in explain_video(media, out)["error"]
    assert (out / "keep.txt").read_text() == "keep"


def test_cli_against_and_mcp_wire_contract(monkeypatch, capsys):
    from myzing.explain import command
    from myzing import mcp_server
    seen = []
    def fake(*args, **kwargs):
        seen.append((args, kwargs))
        return {"ok": True, "card_json": "card.json", "card_md": "card.md", "card_png": "card.png", "summary": ["a", "b", "c"]}
    monkeypatch.setattr(command, "_explain", fake)
    assert command.run(["a.mp4", "--against", "b.mp4", "--out", "out", "--json"]) == 0
    assert seen[-1][1]["against"] == "b.mp4"
    assert json.loads(capsys.readouterr().out)["ok"]
    monkeypatch.setattr("myzing.explain.api._explain", fake)
    assert mcp_server.h_zing_explain("a.mp4", "out")["ok"]
    assert seen[-1][1]["allow_download"] is False


def test_palette_known_neutrals():
    from myzing.explain.palette import lab_hex
    assert lab_hex([0, 0, 0]) == "#000000"
    assert lab_hex([100, 0, 0]) == "#ffffff"
