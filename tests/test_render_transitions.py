"""Transition preflight and no-transition command compatibility."""

import json
from pathlib import Path

import pytest

from myzing import ffmpeg_capabilities as capabilities
from myzing.composition import Composition
from myzing.project.models import Rational
from myzing.render import pipeline
from myzing.render.graph import build_graph
from myzing.render.transitions import sample_span, timeline_joins, validate_render_windows, video_frame
from myzing.render.validation import EDLValidationError, MediaInfo, ResolvedClip, ValidatedEDL
from myzing.schemas import EDL
from test_render_composition import ROOT


def plan():
    return Composition.from_json((ROOT / "docs/examples/composition-v2/talking-head.json").read_text(encoding="utf-8"))


def test_frozen_graded_cut_graph_and_ffmpeg_6_9_commands(monkeypatch):
    baseline = json.loads((ROOT / "tests/fixtures/render-v2-graded-cut-baseline.json").read_text(encoding="utf-8"))
    edl = EDL.from_dict(baseline["edl"])
    v = ValidatedEDL(edl, tuple(ResolvedClip(c, Path(c.src), MediaInfo(10, True, True)) for c in edl.clips), (), 4, (), "square")
    graph = build_graph(v, False, fps_rate="30/1", clip_luts=tuple(baseline["luts"]))
    assert graph.graph.encode() == baseline["graph"].encode()
    for version in (6, 9):
        monkeypatch.setattr(pipeline, "ffmpeg_major_version", lambda _, v=version: v)
        command = pipeline._ffmpeg_command("ffmpeg", graph, Path("graph.txt"), Path("output.mp4"), v, "30/1")
        assert json.dumps(command).encode() == json.dumps(baseline["commands"][str(version)]).encode()


@pytest.mark.parametrize("kind", ["dip_to_black", "dip_to_white"])
def test_dip_recipe_roundtrips_without_inventing_observations(kind):
    c = plan()
    c.transitions[0].recipe.kind = kind
    reloaded = Composition.from_json(c.to_json())
    assert reloaded.to_dict() == c.to_dict()
    assert reloaded.transitions[0].recipe.observation == c.transitions[0].recipe.observation


@pytest.mark.parametrize("flags", [".S.", ".S"])
def test_transition_capability_uses_filters_not_major_version(monkeypatch, flags):
    import subprocess
    capabilities._filters_for_executable.cache_clear()
    monkeypatch.setattr(capabilities.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(capabilities.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout=f" {flags} xfade VV->V crossfade\n {flags} acrossfade AA->A crossfade\n {flags} zoompan V->V zoom\n", stderr=""))
    try:
        capabilities.require_transitions(zoom=True)
    finally:
        capabilities._filters_for_executable.cache_clear()


def test_missing_transition_capability_reports_remedy(monkeypatch):
    monkeypatch.setattr(capabilities.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(capabilities, "_filters_for_executable", lambda _: frozenset({"xfade"}))
    with pytest.raises(capabilities.FFmpegCapabilityError, match="acrossfade.*zoompan") as error:
        capabilities.require_transitions(zoom=True)
    assert "4.3" in str(error.value) and "ffmpeg-full" in str(error.value)


def test_subframe_overlap_fails_with_ids():
    c = plan()
    c.fps = Rational(1, 10)
    with pytest.raises(EDLValidationError, match="clip-1 -> clip-2.*one output frame"):
        validate_render_windows(c)


def test_overlap_does_not_shift_output_coordinates():
    c = plan()
    joins = timeline_joins(c)
    assert joins[0] == c.transitions[0]
    assert joins[1] is None
    assert joins[0].start == 2.5 and joins[0].end == 3
    assert sum(x.duration for x in c.clips) - sum(t.recipe.duration_seconds for t in c.transitions) == 8
    assert max(x.timeline_end for x in c.clips) == 8


def test_sample_endpoint_rounding_telescopes_over_many_fractional_joins():
    # Test the shared sample clock independently of FFmpeg encoding.
    end, total = 0.0, 0
    for index in range(1000):
        start = end - (.123457 if index else 0)
        next_end = start + 1.000371
        total += sample_span(start, next_end) - sample_span(start, end)
        end = next_end
    assert total == round(end * 48000)


def test_video_frame_ties_match_composition_contract():
    assert video_frame(.25, "30/1") == 8
    assert video_frame(.15, "30/1") == 5  # Python round() would choose 4.
    assert video_frame(1001, "30000/1001") == 30000
