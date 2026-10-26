"""CLI -> owned worker -> real offline pipeline -> warm resume and failure."""

import json
import sys
from pathlib import Path

import pytest

from myzing.match.command import run
from myzing.match.state import read

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.match_examples import ANSWERS, generate


@pytest.mark.ffmpeg
def test_match_three_decodable_drafts_resume_and_failed_render(tmp_path, monkeypatch, zing_workspace, capsys):
    for module in ("cv2", "numpy", "PIL", "scenedetect", "pysubs2"):
        pytest.importorskip(module)
    reference, clips = generate(tmp_path / "inputs")
    out, trace = tmp_path / "project", tmp_path / "measurement-trace.json"
    worker = [sys.executable, "-m", "tools.match_examples", "--worker", str(trace)]
    monkeypatch.setattr("myzing.match.jobs.worker_command", lambda: worker)

    def command(*extra):
        code = run([str(reference), "--clips", str(clips), "--out", str(out), "--seed", "18", "--json", *extra])
        streams = capsys.readouterr()
        return code, json.loads(streams.out), streams.err

    code, result, progress = command("--answers", json.dumps(ANSWERS))
    assert code == 0 and result["summary"].startswith("3 of 3 render complete"), result
    assert all(row["render_status"] == "render complete" and "style_match" in row for row in result["drafts"].values())
    assert "reference-study: starting" in progress and "report-C: done" in progress
    assert len(read(trace)["calls"]) == 7  # reference, three raw clips, three renders
    assert len(list((out / "drafts").glob("plan-*.json"))) == 3
    assert Path(result["recipe"]).is_file() and (out / "comparison.md").is_file()
    comparison = (out / "comparison.md").read_text(encoding="utf-8")
    assert len(comparison) < 50_000 and "P17 planning evidence:" not in comparison
    assert "director/comparison.json" in comparison
    assert len({read(row["plan"])["clips"][0]["asset_id"] + str(read(row["plan"])["clips"][0]["src_in"])
                for row in result["drafts"].values()}) >= 2
    for row in result["drafts"].values():
        report = read(row["report"])
        assert not any(w.startswith("P17 planning evidence:") for w in report["warnings"])
        assert report["render"]["full_decode"] and report["render"]["frames"] == 180
        assert report["render"]["audio_streams"] >= 1
        assert Path(row["timeline"]).read_bytes().startswith(b"\x89PNG")
        assert set(report["dimensions"]) >= {"shot_pace", "first_cut", "caption_timing", "caption_placement", "color"}
        assert all(d["status"] in {"pass", "approximate", "miss", "not_applicable", "detector_disagreement"}
                   for d in report["dimensions"].values())
        assert Path(report["rendered_study"]["meta"]["source_url"]).resolve() == Path(row["video"]).resolve()
    reference_breakdown = read(next((out / "reference" / "breakdowns").glob("*/breakdown.json")))
    assert [s["start"] for s in reference_breakdown["shots"]] == [0, 2, 4]
    assert reference_breakdown["captions"]  # burned-in captions were observed
    code, warm, _ = command("--resume")
    assert code == 0 and warm["ready"] == 3 and len(read(trace)["calls"]) == 7
    assert all("render-" + label in warm["reused_steps"] for label in "ABC")
    assert "director" in warm["reused_steps"]
    from myzing.project.choices import choose_draft
    from myzing.project.api import hash_file
    choice = choose_draft(out, "B")
    assert choice["receipt"]["draft_sha256"] == hash_file(Path(warm["drafts"]["B"]["plan"]))
    assert choice["receipt"]["delivery"]["state"] == "local_only"
    # An old report must not hide a newly failed render of corrupted media.
    Path(result["drafts"]["B"]["video"]).write_bytes(b"truncated output")
    worker.append("--fail-render")
    code, failed, _ = command("--resume")
    assert code == 1 and failed["summary"].startswith("2 of 3 render complete")
    assert failed["drafts"]["B"]["status"] == "failed"
    assert not Path(result["drafts"]["B"]["video"]).exists()
    assert Path(failed["drafts"]["B"]["failed_artifact"]).read_bytes() == b"truncated output"
    assert failed["failures"][0]["step"] == "render-B"
    assert "forced B encoder failure" in Path(failed["failures"][0]["log"]).read_text()
    assert "2 of 3 render complete" in (out / "comparison.md").read_text()
    assert len(read(trace)["calls"]) == 7
    # The same measurements also expose a real director shortage unchanged.
    code, shortage, _ = command("--resume", "--answers", json.dumps({**ANSWERS, "target_length_seconds": 60}))
    assert code == 1 and shortage["status"] == "shortage" and shortage["ready"] == 0
    assert shortage["shortages"] == read(out / "director" / "comparison.json")["shortages"]
    assert not read(trace)["network_attempts"] and len(read(trace)["calls"]) == 7


@pytest.mark.ffmpeg
@pytest.mark.parametrize("size", [(320, 180), (240, 240), (180, 320)])
@pytest.mark.parametrize("mode,portrait", [("fit", False), ("fit", True), ("blurfill", False), ("zoomfill", False)])
def test_color_ignores_differently_colored_fill(tmp_path, size, mode, portrait):
    """Generated sharp yellow subject over a blue band, in every delivery aspect."""
    import subprocess
    pytest.importorskip("numpy")
    from dataclasses import replace
    from myzing.composition import AssetRef, Composition, CompositionClip, Framing, CropBounds, CropKeyframe
    from myzing.color.measure import measure_video
    from myzing.match.picture import measure_output_color
    from myzing.match.evidence import report
    from myzing.schemas import Breakdown, VideoMeta
    from myzing.style_recipe import build_style_recipe

    width, height = size
    sw, sh = (80, 480) if portrait else (480, 80)
    cropw = 400 if mode == "zoomfill" else sw
    f = Framing(mode, sw, sh, CropBounds(0, 0, sw, sh), cropw, sh, sw / 2, sh / 2,
                keyframes=[CropKeyframe(0, sw / 2, sh / 2)] if mode == "zoomfill" else [])
    # Independent dimensions for this fixture, rounded to even like the renderer.
    scale = min(width / cropw, height / sh)
    fw, fh = int(cropw * scale) // 2 * 2, int(sh * scale) // 2 * 2
    x, y = (width - fw) // 4 * 2, (height - fh) // 4 * 2
    plan = Composition(width=width, height=height, assets=[AssetRef("a", "unused.mp4", "a" * 64)], clips=[CompositionClip(
        id="subject", asset_id="a", src="unused.mp4", src_in=0, src_out=1, timeline_start=0, framing=f)])
    video = tmp_path / "bands.mp4"
    # Blurfill is deliberately a different color from the subject. A whole-frame
    # measurement must fail, so this test cannot pass by weakening the tolerance.
    filters = f"gblur=sigma=12,drawbox=x={x}:y={y}:w={fw}:h={fh}:color=yellow:t=fill"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=blue:s={width}x{height}:d=1:r=30",
                    "-vf", filters, "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", str(video)],
                   check=True, capture_output=True)
    reference = tmp_path / "yellow.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=yellow:s=160x90:d=1:r=30",
                    "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", str(reference)], check=True, capture_output=True)
    target = measure_video(reference, count=4)[0]
    full = measure_video(video, count=4)[0].to_dict()
    sharp = measure_output_color(video, plan, count=4)
    recipe = build_style_recipe(Breakdown(VideoMeta("ref", "file", duration=1, fps=30)))
    recipe.color_mode = "reference"
    from myzing.style_recipe import Coverage
    recipe.measured.extend(replace(recipe.measured[0], name="color."+key, value=value,
                                   coverage=Coverage(4, 1, "generated", target.coverage),
                                   confidence=target.confidence, confidence_kind="heuristic")
                           for key, value in target.aggregate.to_dict().items())
    b = Breakdown(VideoMeta("out", "file", duration=1, fps=30))
    assert report(recipe, b, {}, full, {}, plan)["dimensions"]["color"]["status"] == "miss"
    checked = report(recipe, b, {}, sharp, {}, plan)["dimensions"]["color"]
    assert checked["status"] == "approximate"
    assert checked["max_luma_percentile_delta"] < .03
    assert sharp["picture_area"]["samples"][0]["rect"] == (x, y, fw, fh)


@pytest.mark.ffmpeg
def test_verification_detector_keeps_five_frame_shots(tmp_path):
    import subprocess
    np = pytest.importorskip("numpy")
    pytest.importorskip("scenedetect")
    from myzing.study.shots import detect_shots
    path = tmp_path / "short-cuts.mp4"
    lengths = [30, 6, 24, 5, 7, 24]
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]
    frames = np.concatenate([np.full((n, 90, 160, 3), color, dtype=np.uint8) for n, color in zip(lengths, colors)])
    subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "160x90", "-r", "30",
                    "-i", "pipe:0", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   input=frames.tobytes(), check=True, capture_output=True)
    default = detect_shots(path, sum(lengths) / 30, 30)
    checked = detect_shots(path, sum(lengths) / 30, 30, min_scene_len_s=0)
    expected = [sum(lengths[:i]) for i in range(1, len(lengths))]
    assert [round(s.start * 30) for s in checked.shots[1:]] == expected
    assert len(default.shots) < len(checked.shots)
    assert checked.provenance["min_scene_len_frames"] == 2
