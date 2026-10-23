"""POLISH1 item 5: music plans still export a picture-and-dialogue v1 EDL plus a music sidecar."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.plan_examples import example_project  # noqa: E402

from myzing.composition import AssetRef, CompositionAudio  # noqa: E402
from myzing.director.api import plan_drafts  # noqa: E402
from myzing.music import planning  # noqa: E402
from myzing.music.models import MusicPlan  # noqa: E402
from myzing.schemas import EDL  # noqa: E402


@pytest.fixture
def music_project(tmp_path, zing_workspace, monkeypatch, request):
    """The P17 example project with a supplied music bed. Track choice and
    analysis are stubbed (MUSIC1's own tests cover them); planning, lowering
    and publishing are real."""
    media = getattr(request, "param", False)
    root, _, _ = example_project(tmp_path / "project", media=media)
    bed = root / "clips" / "bed.wav"
    bed.write_bytes(b"RIFF stub")

    def fake_plan_music(sequence, studies, brief, manifest, root_, pace, required, forbidden, cache=None):
        duration = sum(c.duration for c in sequence)
        track = CompositionAudio(id="music-1", asset_id="bed", src=str(bed), kind="music", role="music",
                                 src_in=3.0, src_out=3.0 + duration, gain_db=-14.5, duck_under_speech=True,
                                 duck_scope="source_speech")
        evidence = MusicPlan(mode="speech-led", speech_spans=[[0.2, 1.4], [1.9, 3.1], [4.5, 5.2]],
                             tracks=[{"id": "music-1", "asset_id": "bed", "path": str(bed), "sha256": "0" * 64,
                                      "source_offset": 3.0, "source_end": 3.0 + duration,
                                      "fade_in": .15, "fade_out": 1.0, "reason": "stub: highest score"}],
                             timeline=planning.timeline_of(sequence))
        return sequence, [AssetRef("bed", str(bed), "0" * 64, 30.0)], [track], evidence

    monkeypatch.setattr(planning, "plan_music", fake_plan_music)
    return root


def test_music_plans_export_v1_picture_and_dialogue_and_a_sidecar(music_project):
    result = plan_drafts(music_project, music_project / "recipe.json", music_project / "plans", seed=17)
    assert result["status"] == "ready"
    assert set(result["v1_edls"]) == set(result["music_sidecars"]) == {"A", "B", "C"}
    comparison = json.loads(Path(result["comparison_path"]).read_text(encoding="utf-8"))
    for label in "ABC":
        v1 = comparison["plans"][label]["v1"]
        assert v1["representable"] and v1["music_removed"] == ["music-1"]
        assert v1["scope"].startswith("picture and dialogue")
        assert "audio[0].source_trim" in v1["blockers"]  # what a full v1 lowering could not keep
        edl = EDL.from_dict(json.loads(Path(result["v1_edls"][label]).read_text(encoding="utf-8")))
        assert edl.audio == [] and edl.clips and edl.captions
        sidecar = json.loads(Path(result["music_sidecars"][label]).read_text(encoding="utf-8"))
        assert sidecar["kind"] == "zing.music_sidecar" and sidecar["version"] == 1
        assert sidecar["edl"] == f"plan-{label}.edl.json" and sidecar["plan"] == f"plan-{label}.json"
        track = sidecar["tracks"][0]
        assert track["source_in"] == 3.0 and track["timeline_start"] == 0.0 and track["gain_db"] == -14.5
        assert track["source_out"] - track["source_in"] == pytest.approx(track["timeline_end"] - track["timeline_start"])
        assert track["fade_in_seconds"] == .15 and track["fade_out_seconds"] == 1.0
        duck = track["duck"]
        assert duck["scope"] == "source_speech" and duck["depth_db"] == 9.0
        # Clause gaps under the 0.8 s hold stay ducked: two passages, not three.
        assert duck["passages"] == [[0.2, 3.1], [4.5, 5.2]]
        envelope = dict(map(tuple, duck["envelope_db"]))
        assert envelope[0.2] == -9.0 and envelope[3.1] == -9.0 and envelope[4.5] == -9.0
        assert envelope[0.0] == 0.0 and envelope[3.9] == pytest.approx(0.0)
        assert all(-9.0 <= gain <= 0.0 for _, gain in duck["envelope_db"])
        assert any("source trim" in item for item in sidecar["cannot_carry"])
        assert any("source speech" in item for item in sidecar["cannot_carry"])
        assert track["reason"] == "stub: highest score"


def test_other_blockers_still_block_the_derivative(music_project, monkeypatch):
    from myzing.director import plans as director_plans

    original = director_plans.lowering_blockers

    def also_layout(composition):
        return [*original(composition), "captions[0].layout"]

    monkeypatch.setattr(director_plans, "lowering_blockers", also_layout)
    result = plan_drafts(music_project, music_project / "recipe.json", music_project / "plans", seed=17)
    assert result["v1_edls"] == {} and result["music_sidecars"] == {}
    assert not any(path.name.endswith(".edl.music.json") for path in (music_project / "plans").iterdir())


def test_rerun_without_music_removes_owned_sidecars(music_project, monkeypatch):
    out = music_project / "plans"
    plan_drafts(music_project, music_project / "recipe.json", out, seed=17)
    assert (out / "plan-A.edl.music.json").is_file()
    monkeypatch.undo()  # the real planner: the brief supplies no music
    result = plan_drafts(music_project, music_project / "recipe.json", out, seed=17)
    assert result["music_sidecars"] == {} and set(result["v1_edls"]) == {"A", "B", "C"}
    assert not (out / "plan-A.edl.music.json").exists()


@pytest.mark.ffmpeg
@pytest.mark.parametrize("music_project", [True], indirect=True)
def test_music_plan_v1_derivative_renders(music_project, tmp_path):
    from myzing.render.pipeline import render_edl

    result = plan_drafts(music_project, music_project / "recipe.json", music_project / "plans", seed=17)
    edl_path = Path(result["v1_edls"]["A"])
    edl = EDL.from_dict(json.loads(edl_path.read_text(encoding="utf-8")))
    rendered = render_edl(edl, tmp_path / "picture-dialogue.mp4", base_dir=edl_path.parent)
    assert Path(rendered.output_path).is_file()
