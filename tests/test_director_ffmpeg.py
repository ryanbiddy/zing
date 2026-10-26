"""Generated clips -> reference groups -> native v2 output; no models."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from myzing.director import plan_drafts
from myzing.render.composition import render_composition
from myzing.composition import Composition

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.plan_examples import example_project


@pytest.mark.ffmpeg
def test_reference_plan_renders_with_real_media(tmp_path, zing_workspace):
    project, _, _ = example_project(tmp_path / "project", media=True)
    result = plan_drafts(project, project / "recipe.json", tmp_path / "plans", seed=17)
    assert result["status"] == "ready", result
    plan = Composition.from_json(Path(result["plans"]["A"]).read_text(encoding="utf-8"))
    assert all(c.framing is None for c in plan.clips)
    assert all(len(c.words) == 2 and c.word_timed and c.style.box_color is None for c in plan.captions)
    from myzing.match.caption_fit import fit_captions
    fit_captions(plan, tmp_path / "caption-fit")
    assert all("\n" not in c.text and c.style.box_color is None for c in plan.captions)
    output = tmp_path / "plan-A.mp4"
    render_composition(plan, output, work_dir=tmp_path / "render-work")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output)],
                           capture_output=True, text=True, check=True, timeout=30)
    data = json.loads(probe.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1920, 1080)
    assert video["codec_name"] == "h264" and video["r_frame_rate"] == "30/1"
    assert abs(float(data["format"]["duration"]) - 6) <= 2 / 30
    assert any(s["codec_type"] == "audio" for s in data["streams"])
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"],
                   check=True, capture_output=True, timeout=60)
    # Verify planned source choices at a caption-free upper-right pixel. Each
    # known source shot is a distinct color, so this catches mapping/order bugs.
    palette = [(255, 0, 0), (0, 0, 255), (0, 128, 0), (255, 255, 0)]
    for clip in plan.clips:
        relative = min(.1, (clip.src_out - clip.src_in) / 2)
        sample = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(clip.timeline_start + relative),
                                 "-i", str(output), "-frames:v", "1", "-vf", "crop=2:2:1800:100,format=rgb24",
                                 "-f", "rawvideo", "-"], capture_output=True, check=True, timeout=30).stdout
        expected = palette[min(3, int((clip.src_in + relative) / 2))]
        assert len(sample) == 12
        assert max(abs(sample[i] - expected[i]) for i in range(3)) < 30


@pytest.mark.ffmpeg
def test_in_band_openings_win_over_early_natural_cuts(tmp_path):
    """Real frame cuts, authored clauses, and the production candidate/search path."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("scenedetect")
    from myzing.director.models import ClipStudy
    from myzing.director.selection import candidates, choose, envelope, shot_lengths
    from myzing.director.continuity import score
    from myzing.project.api import hash_file
    from myzing.schemas import Breakdown, Shot, VideoMeta, Word
    from myzing.study.shots import detect_shots
    from myzing.style_recipe import build_style_recipe
    from myzing.style_ranges import timing_band

    palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]
    frames_per_shot = [6, 24, 24, 24, 24, 24]
    studies = []
    for i in range(3):
        path = tmp_path / f"take-{i}.mp4"
        frames = np.concatenate([np.full((n, 90, 160, 3), palette[(j + i) % 6], dtype=np.uint8)
                                 for j, n in enumerate(frames_per_shot)])
        subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "160x90",
                        "-r", "30", "-i", "pipe:0", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                       input=frames.tobytes(), capture_output=True, check=True, timeout=30)
        shots = detect_shots(path, 4.2, 30, min_scene_len_s=0).shots
        assert [round(s.start * 30) for s in shots[1:]] == [6, 30, 54, 78, 102]
        # This clause spans the 1 s natural cut. Trimming at that cut would
        # violate continuity; starting in the silence before it is feasible.
        studies.append(ClipStudy(str(i), str(path), hash_file(path), 4.2, "ready", shots=shots,
                                 words=[Word("Keep", .35, .65), Word("this.", .7, 1.15)]))
    reference = Breakdown(VideoMeta("fixture", "file", duration=4, fps=30),
                          shots=[Shot(i, i * .8, (i + 1) * .8) for i in range(5)])
    style = envelope(build_style_recipe(reference))
    keep = {s.asset_id: [(.35, 1.15)] for s in studies}
    pool, required = candidates(studies, keep, {}, style, 4.8)
    band = timing_band(.8, [.8] * 5)
    opening_lengths = [shot_lengths([c], studies)[0] for c in pool]
    assert any(d < band["lower"] for d in opening_lengths)
    assert any(band["lower"] <= d <= band["upper"] for d in opening_lengths)
    evidence = {}
    selected = choose(pool, required, studies, style, 4.8, 30, 0, timing_evidence=evidence)
    for label, sequence in selected.items():
        assert band["lower"] <= shot_lengths(sequence, studies)[0] <= band["upper"]
        assert evidence[label]["median_shot_seconds"]["distance_outside_seconds"] == 0
        assert score(sequence, studies)["partial_clauses"] == 0
        assert all(any(c.asset_id == s.asset_id and c.start <= .35 and c.end >= 1.15
                       for c in sequence) for s in studies)
