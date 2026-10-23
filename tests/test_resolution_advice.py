"""POLISH1 item 1: low-resolution sources in 9:16/1:1 say so up front, with numbers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from myzing.brief.models import Brief, BriefError
from myzing.composition import AssetRef, Composition, CompositionClip
from myzing.layout.framing import select_framing
from myzing.layout.resolution import (auto_gain, chosen_short_side, mark_auto_declined, resolution_advice)
from myzing.layout.types import Box, FaceTrack, Keyframe
from myzing.project.models import Rational


def clip(asset="a", duration=4.0):
    return CompositionClip(src=f"{asset}.mp4", src_in=0, src_out=duration, timeline_start=0, id="clip-1",
                           asset_id=asset)


def face(duration=4.0):
    """A steady centered subject: the crop is limited by resolution, not by missing evidence."""
    box = Box(.42, .3, .16, .4)
    return [FaceTrack(id="face-1", keyframes=[Keyframe(time=0, box=box), Keyframe(time=duration, box=box)])]


def advise(sw, sh, width, height, mode="auto", limit=2.5, tracks=()):
    c = clip()
    c.framing = select_framing(mode, sw, sh, width, height, c, list(tracks), max_upscale=limit)
    return resolution_advice([c], {"a": (sw, sh)}, width, height, max_upscale=limit,
                             command="zing render plan.json --aspect 9:16")


def test_wide_low_res_source_in_9x16_states_numbers_and_recommends_720():
    advice = advise(862, 360, 1080, 1920, tracks=face())
    source = advice["sources"][0]
    assert advice["limited"] and source["source"] == [862, 360]
    assert source["full_frame_scale"] == pytest.approx(5.333, abs=1e-3)
    assert source["sharp_height_share"] < .5 and source["enlargement"] <= 2.5 + 1e-9
    rec = advice["recommendation"]
    assert rec["choice"] == "lower_resolution" and rec["short_side"] == 720 and rec["output"] == [720, 1280]
    assert rec["expected_sharp_height_share"] == pytest.approx(.70, abs=1e-3)
    assert rec["expected_enlargement"] <= 2.5
    assert rec["command"] == "zing render plan.json --aspect 9:16 --short-side 720"
    assert rec["brief_answer"] == {"short_side": 720}
    assert advice["alternatives"][0]["choice"] == "keep_framing"
    summary = advice["summary"]
    for fact in ("862x360", "5.33x", "1080x1920", "2.5x limit", "720x1280", "up to 70% sharp height",
                 "Upscaling cannot recover detail"):
        assert fact in summary, (fact, summary)
    assert chosen_short_side(advice, "auto") == 720 and chosen_short_side(advice, 1080) == 1080


def test_square_and_full_hd_sources_are_not_flagged():
    assert not advise(862, 360, 1080, 1080)["limited"]  # 1:1 reaches its 70% target
    assert not advise(1920, 1080, 1080, 1920)["limited"]
    assert not advise(1080, 1920, 1080, 1920)["limited"]
    assert advise(1920, 1080, 1080, 1920)["recommendation"]["choice"] == "none"


def test_same_aspect_fit_past_the_limit_recommends_the_size_that_stays_within_it():
    advice = advise(360, 640, 1080, 1920)  # a 360p portrait phone clip
    assert advice["limited"] and advice["sources"][0]["modes"] == ["fit"]
    assert advice["sources"][0]["enlargement"] == pytest.approx(3.0)
    rec = advice["recommendation"]
    assert rec["output"] == [900, 1600] and rec["expected_enlargement"] == pytest.approx(2.5)


def test_tiny_sources_keep_the_size_with_zoomfill_or_blurfill():
    advice = advise(160, 90, 1080, 1920)
    assert advice["limited"] and advice["recommendation"]["choice"] == "keep_framing"
    assert "below 360p" in advice["summary"]
    # Review fix: the kept size is 6.75x, so neither text may claim "within the limit".
    assert "6.75x, past the 2.5x limit" in advice["recommendation"]["reason"]
    assert "within the" not in advice["summary"] and "within the limit" not in advice["recommendation"]["reason"]


def test_brief_short_side_is_validated_omitted_by_default_and_accepts_auto():
    assert "short_side" not in Brief().to_dict()
    assert Brief(short_side=720).to_dict()["short_side"] == 720
    assert Brief.from_answers({"short_side": "auto"}).short_side == "auto"
    for bad in (700, 0, 5000, "720", 720.0, True):
        with pytest.raises(BriefError, match="short_side"):
            Brief(short_side=bad)
    from myzing.brief.questions import brief_questions
    assert any(f["key"] == "short_side" for f in brief_questions()["optional_fields"])


def test_director_plan_reports_resolution_and_auto_replans(tmp_path, zing_workspace):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.plan_examples import example_project, write_json
    from myzing.director.api import plan_drafts

    root, _, _ = example_project(tmp_path / "project")  # 320x180 clips, 16:9 brief
    result = plan_drafts(root, root / "recipe.json", root / "plans", seed=17)
    assert result["status"] == "ready"
    first = result["summary"]["resolution"]["A"]
    assert first["limited"] and first["output"] == [1920, 1080]
    assert first["recommendation"]["output"] == [800, 450]
    assert result["summary"]["warnings"][0].startswith("Low-resolution source for 16:9: 320x180")
    plan = Composition.from_json(Path(result["plans"]["A"]).read_text(encoding="utf-8"))
    assert plan.warnings[0].startswith("Low-resolution source")
    data = json.loads((root / "brief.json").read_text(encoding="utf-8"))
    write_json(root / "brief.json", {**data, "short_side": "auto"})
    auto = plan_drafts(root, root / "recipe.json", root / "auto", seed=17)
    plan = Composition.from_json(Path(auto["plans"]["A"]).read_text(encoding="utf-8"))
    assert (plan.width, plan.height) == (800, 450)
    comparison = json.loads(Path(auto["comparison_path"]).read_text(encoding="utf-8"))
    selected = comparison["plans"]["A"]["resolution"]["auto_selected"]
    assert selected["from"] == [1920, 1080] and selected["to"] == [800, 450]
    assert plan.warnings[0].startswith("short_side auto delivered 800x450 instead of 1920x1080.")


def low_res_clip(path, size="640x360", seconds=2):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, timeout=120)
    return path


@pytest.mark.ffmpeg
def test_low_res_delivery_renders_at_the_recommended_size(tmp_path):
    from myzing.project.api import hash_file
    from myzing.render.deliveries import render_deliveries

    source = low_res_clip(tmp_path / "small.mp4")
    plan = Composition(assets=[AssetRef("a", str(source), hash_file(source), 2.0)],
                       clips=[CompositionClip(src=str(source), src_in=0, src_out=2, timeline_start=0, id="clip-1",
                                              asset_id="a")],
                       width=1920, height=1080, fps=Rational(30, 1))
    fixed = render_deliveries(plan, tmp_path / "fixed.mp4", aspects="9:16", base_dir=tmp_path)
    row = fixed["deliveries"]["9:16"]
    assert (row["width"], row["height"]) == (1080, 1920)
    assert row["resolution"]["limited"] and row["resolution"]["recommendation"]["short_side"] == 720
    saved = Composition.from_json(Path(row["plan"]).read_text(encoding="utf-8"))
    assert saved.warnings[0].startswith("Low-resolution source for 9:16: 640x360")
    auto = render_deliveries(plan, tmp_path / "auto.mp4", aspects="9:16,1:1", base_dir=tmp_path, short_side="auto")
    vertical, square = auto["deliveries"]["9:16"], auto["deliveries"]["1:1"]
    assert (vertical["width"], vertical["height"]) == (720, 1280)
    assert vertical["resolution"]["auto_selected"]["from"] == [1080, 1920]
    assert vertical["resolution"]["summary"].startswith("short_side auto delivered 720x1280 instead of 1080x1920.")
    assert vertical["resolution"]["sources"][0]["sharp_height_share"] >= .69
    assert vertical["resolution"]["sources"][0]["enlargement"] <= 2.5 + 1e-9
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", vertical["video"]],
                           capture_output=True, text=True, check=True).stdout.strip()
    assert probe == "720,1280"
    # 640x360 into 1:1 reaches its sharp target at 1080; auto keeps the size.
    assert (square["width"], square["height"]) == (1080, 1080) and "auto_selected" not in square["resolution"]
    # The CLI flag spells the same choice and prints the advice.
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.to_json(indent=2), encoding="utf-8")
    cli = subprocess.run([sys.executable, "-m", "myzing.cli", "render", str(plan_path), "--aspect", "9:16",
                          "--short-side", "720", "-o", str(tmp_path / "cli.mp4")],
                         capture_output=True, text=True, timeout=600)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)["deliveries"]["9:16"]["width"] == 720
    assert "resolution" not in cli.stderr  # at 720 the source reaches its target


@pytest.mark.parametrize("source, size, expected, share", [
    ((320, 240), (1080, 1080), [792, 792], .75),  # 4:3 in 1:1: the width fit needs 3.375x at 1080
    ((240, 320), (1080, 1920), [594, 1056], .75),  # 3:4 in 9:16
    ((360, 480), (1080, 1920), [900, 1600], .75),
    ((400, 360), (1080, 1080), [990, 990], .9),  # was kept at 1080 (2.70x) as if within the limit
])
def test_slightly_wider_sources_get_a_size_whose_width_fit_stays_within_the_limit(source, size, expected, share):
    """Review fix: the fitted-to-width picture is above the 70% target, so the
    recommendation must bound that fit's enlargement, not the 70% crop's."""
    advice = advise(*source, *size, tracks=face())
    rec = advice["recommendation"]
    assert advice["limited"] and rec["choice"] == "lower_resolution" and rec["output"] == expected
    assert rec["expected_enlargement"] <= 2.5 + 1e-9 and rec["expected_sharp_height_share"] == pytest.approx(share)
    keep = advice["alternatives"][0]
    assert keep["expected_enlargement"] > 2.5 and "past the 2.5x limit" in keep["reason"]
    assert "within the limit" not in keep["reason"] and "enlarged past the 2.5x limit" in advice["summary"]
    lower = advise(*source, *expected, tracks=face())
    assert not lower["limited"] and lower["sources"][0]["enlargement"] <= 2.5 + 1e-9
    assert auto_gain(advice, lower)


def test_a_crop_held_wide_by_missing_subject_evidence_is_not_a_resolution_problem():
    """Review fix: without subject evidence the zoomfill window keeps 2/3 of the
    source width (1.88x here), so a smaller delivery would show the same 35%."""
    advice = advise(862, 360, 1080, 1920)
    assert advice["sources"][0]["enlargement"] < 2.4 and advice["sources"][0]["sharp_height_share"] < .4
    assert not advice["limited"] and advice["recommendation"]["choice"] == "none"
    assert "subject or evidence limits" in advice["recommendation"]["reason"]
    assert advise(862, 360, 1080, 1920, tracks=face())["limited"]


def test_auto_keeps_the_size_when_the_lower_plan_shows_no_more_picture():
    """Review fix: 640x360 reaches the limit at 1080x1920, but without subject
    evidence its crop stays at 47% at 720x1280 too; auto must not lower it."""
    first = advise(640, 360, 1080, 1920)
    assert first["limited"] and first["recommendation"]["short_side"] == 720
    second = advise(640, 360, 720, 1280)
    assert second["sources"][0]["sharp_height_share"] < first["sources"][0]["sharp_height_share"] + .01
    assert not auto_gain(first, second)
    mark_auto_declined(first, second)
    assert first["auto_declined"]["tried"] == [720, 1280]
    assert "short_side auto kept 1080x1920" in first["summary"] and "subject evidence" in first["summary"]
    with_subject = advise(640, 360, 720, 1280, tracks=face())
    assert auto_gain(advise(640, 360, 1080, 1920, tracks=face()), with_subject)
