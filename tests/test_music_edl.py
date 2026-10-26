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
from myzing.music.ducking import duck_passages  # noqa: E402
from myzing.music.models import MusicPlan  # noqa: E402
from myzing.schemas import EDL  # noqa: E402

REAL_PLAN_MUSIC = planning.plan_music


@pytest.fixture
def music_project(tmp_path, zing_workspace, monkeypatch, request):
    """The P17 example project with a supplied music bed. Track choice and
    analysis are stubbed (MUSIC1's own tests cover them); planning, lowering
    and publishing are real."""
    media = getattr(request, "param", False)
    root, _, _ = example_project(tmp_path / "project", media=media)
    # This fixture tests v1 music export. Reference captions now need v2
    # appearance/layout; request no captions for the legacy picture export.
    brief_path = root / "brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    brief_path.write_text(json.dumps({**brief, "caption_mode": "none"}), encoding="utf-8")
    bed = root / "clips" / "bed.wav"
    bed.write_bytes(b"RIFF stub")

    def fake_plan_music(sequence, studies, brief, manifest, root_, pace, required, forbidden, cache=None, **kwargs):
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
        assert edl.audio == [] and edl.clips and not edl.captions
        sidecar = json.loads(Path(result["music_sidecars"][label]).read_text(encoding="utf-8"))
        assert sidecar["kind"] == "zing.music_sidecar" and sidecar["version"] == 1
        assert sidecar["edl"] == f"plan-{label}.edl.json" and sidecar["plan"] == f"plan-{label}.json"
        track = sidecar["tracks"][0]
        assert track["source_in"] == 3.0 and track["timeline_start"] == 0.0 and track["gain_db"] == -14.5
        assert track["source_out"] - track["source_in"] == pytest.approx(track["timeline_end"] - track["timeline_start"])
        assert track["fade_in_seconds"] == .15 and track["fade_out_seconds"] == 1.0
        duck = track["duck"]
        assert duck["scope"] == "source_speech" and duck["depth_db"] == 9.0
        # The renderer's passages (MIX2): the 0.5 s gap is held, the 1.4 s
        # pause releases, and the 0.2 s lead-in and 0.8 s tail stay ducked.
        assert duck["passages"] == [[0.0, 3.1], [4.5, 6.0]]
        assert duck["passages"] == duck_passages([[0.2, 1.4], [1.9, 3.1], [4.5, 5.2]], 6.0)
        assert duck["release_gap_seconds"] == pytest.approx(1.3) and duck["plateau_seconds"] == .3
        assert duck["speech_to_music_target_lu"] == 19.2 and duck["bed_gain_points"] == []
        envelope = dict(map(tuple, duck["envelope_db"]))
        assert envelope[0.0] == -9.0 and envelope[3.1] == -9.0 and envelope[4.5] == -9.0 and envelope[6.0] == -9.0
        assert envelope[3.9] == pytest.approx(0.0) and envelope[4.3] == pytest.approx(0.0)
        assert all(-9.0 <= gain <= 0.0 for _, gain in duck["envelope_db"])
        # No dialogue gain in this plan; source changes still fade speech-free edges.
        assert all(d["gain_db"] == 0 and d["compressor"] is None and
                   (d["fade_in_seconds"] or d["fade_out_seconds"]) for d in sidecar["dialogue"])
        assert any("source trim" in item for item in sidecar["cannot_carry"])
        assert any("source speech" in item for item in sidecar["cannot_carry"])
        assert track["reason"] == "stub: highest score"


def test_sidecar_carries_dialogue_matching_and_per_clip_bed_gain():
    """LISTEN1 levels live in MUSIC1 evidence, which the v1 EDL drops: the
    sidecar lists each clip's dialogue gain, compressor and source-change
    fades, and folds the per-clip bed gain points into the duck envelope."""
    from myzing.composition import Composition, CompositionClip
    from myzing.director.plans import MUSIC_CANNOT_CARRY, music_sidecar
    from myzing.music.models import attach

    clips = [CompositionClip("loud.mp4", 0, 6, 0, id="c1", asset_id="loud"),
             CompositionClip("quiet.mp4", 0, 6, 6, id="c2", asset_id="quiet")]
    track = CompositionAudio(id="music-1", asset_id="bed", src="bed.wav", kind="music", role="music", src_in=0,
                             src_out=12, gain_db=-20.0, duck_under_speech=True, duck_scope="source_speech")
    compressor = {"threshold_db": -7.4, "ratio": 4.0, "attack_ms": 5.0, "release_ms": 120.0, "knee_db": 6.0}
    points = [[0.0, 0.0], [4.5, 0.0], [5.5, -8.0], [12.0, -8.0]]
    evidence = MusicPlan(mode="speech-led", speech_spans=[[.5, 2.5], [3.5, 5.5], [6.5, 8.5], [9.5, 11.5]],
                         tracks=[{"id": "music-1"}], bed_gain_points=points,
                         dialogue_gains=[{"asset_id": "quiet", "start": 6.0, "end": 12.0, "gain_db": 18.0,
                                          "compressor": compressor}])
    plan = Composition(assets=[AssetRef("loud", "loud.mp4", None), AssetRef("quiet", "quiet.mp4", None),
                               AssetRef("bed", "bed.wav", None)], clips=clips, audio=[track])
    sidecar = music_sidecar(attach(plan, evidence), "A")
    assert sidecar["dialogue"] == [
        {"clip_id": "c1", "asset_id": "loud", "timeline_start": 0, "timeline_end": 6, "gain_db": 0.0,
         "compressor": None, "fade_in_seconds": 0.0, "fade_out_seconds": .3},
        {"clip_id": "c2", "asset_id": "quiet", "timeline_start": 6, "timeline_end": 12, "gain_db": 18.0,
         "compressor": compressor, "fade_in_seconds": .1, "fade_out_seconds": 0.0}]
    duck = sidecar["tracks"][0]["duck"]
    assert duck["bed_gain_points"] == points and duck["passages"] == [[0.0, 12.0]]
    envelope = dict(map(tuple, duck["envelope_db"]))
    assert envelope[0.0] == -9.0 and envelope[4.5] == -9.0 and envelope[5.5] == -17.0 and envelope[12.0] == -17.0
    assert sidecar["cannot_carry"] == MUSIC_CANNOT_CARRY
    assert any("dialogue gain" in item and "compressor" in item for item in MUSIC_CANNOT_CARRY)
    assert any("bed gain points" in item for item in MUSIC_CANNOT_CARRY)


def test_other_blockers_still_block_the_derivative(music_project, monkeypatch):
    from myzing.director import plans as director_plans

    original = director_plans.lowering_blockers

    def also_layout(composition):
        return [*original(composition), "captions[0].layout"]

    monkeypatch.setattr(director_plans, "lowering_blockers", also_layout)
    result = plan_drafts(music_project, music_project / "recipe.json", music_project / "plans", seed=17)
    assert result["v1_edls"] == {} and result["music_sidecars"] == {}
    assert not any(path.name.endswith(".edl.music.json") for path in (music_project / "plans").iterdir())


def test_reference_captions_block_the_music_derivative(music_project):
    """A v1 export cannot silently discard reference appearance or layout."""
    brief_path = music_project / "brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    brief_path.write_text(json.dumps({**brief, "caption_mode": "reference"}), encoding="utf-8")
    result = plan_drafts(music_project, music_project / "recipe.json", music_project / "plans", seed=17)
    assert result["status"] == "ready" and result["v1_edls"] == {} and result["music_sidecars"] == {}
    comparison = json.loads(Path(result["comparison_path"]).read_text(encoding="utf-8"))
    for label in "ABC":
        blockers = comparison["plans"][label]["v1"]["blockers"]
        assert "captions[0].layout" in blockers and "audio[0].source_trim" in blockers
    assert not any(path.name.endswith(".edl.music.json") for path in (music_project / "plans").iterdir())


def test_rerun_without_music_removes_owned_sidecars(music_project, monkeypatch):
    out = music_project / "plans"
    plan_drafts(music_project, music_project / "recipe.json", out, seed=17)
    assert (out / "plan-A.edl.music.json").is_file()
    # The real planner (the brief supplies no music). Undo only this patch:
    # monkeypatch.undo() would also drop the caption-ink stand-in and workspace.
    monkeypatch.setattr(planning, "plan_music", REAL_PLAN_MUSIC)
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
