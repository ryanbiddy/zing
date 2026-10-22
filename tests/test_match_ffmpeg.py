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
        assert all(d["status"] in {"pass", "approximate", "miss"} for d in report["dimensions"].values())
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
    assert failed["failures"][0]["step"] == "render-B"
    assert "forced B encoder failure" in Path(failed["failures"][0]["log"]).read_text()
    assert "2 of 3 render complete" in (out / "comparison.md").read_text()
    assert len(read(trace)["calls"]) == 7
    # The same measurements also expose a real director shortage unchanged.
    code, shortage, _ = command("--resume", "--answers", json.dumps({**ANSWERS, "target_length_seconds": 60}))
    assert code == 1 and shortage["status"] == "shortage" and shortage["ready"] == 0
    assert shortage["shortages"] == read(out / "director" / "comparison.json")["shortages"]
    assert not read(trace)["network_attempts"] and len(read(trace)["calls"]) == 7
