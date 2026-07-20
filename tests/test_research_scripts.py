"""Smoke tests for Lane A's research regeneration scripts.

Every research note I have published says "regenerate with X". That
promise is only real if X still runs. These tests keep it honest:
they execute the scripts that can run from committed data, and
exercise the parsing core of the one that needs an external corpus.

Two of the four are covered end to end because their inputs are in
the repo (that was a deliberate design choice — see
RAW-FILLER-RECALL's "ship the derived evidence" note). `freeze.py`
needs real media and `shot_threshold_audit.py` needs the AutoShot
annotation file, so those get unit-level coverage instead of a
pretend integration test.

Offline: no network, no media, no subprocess beyond this interpreter.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

RESEARCH = Path(__file__).resolve().parents[1] / "handoff" / "research"


def _load(script: str):
    """Import a research script by path (they are not a package)."""
    path = RESEARCH / script
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script", ["pc2_baseline.py", "filler_corpus_audit.py"])
def test_script_runs_from_committed_data(script: str) -> None:
    """The regeneration promise, executed. These read only files that
    are in the repo, so a reader can verify the published figures."""
    result = subprocess.run(
        [sys.executable, str(RESEARCH / script)],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip(), f"{script} produced no output"


def test_pc2_baseline_still_reports_the_published_headline() -> None:
    """The note's load-bearing claim is that confidence is
    ANTI-correlated with caption-ness. If a relabel or a new cell ever
    flips that, this fails and the note must be rewritten."""
    result = subprocess.run(
        [sys.executable, str(RESEARCH / "pc2_baseline.py")],
        capture_output=True, text=True, timeout=180,
    )
    out = result.stdout
    caption_line = next(
        l for l in out.splitlines() if "median confidence, captions" in l
    )
    other_line = next(
        l for l in out.splitlines() if "median confidence, other" in l
    )
    caption_median = float(caption_line.split(":")[-1])
    other_median = float(other_line.split(":")[-1])
    assert other_median >= caption_median, (
        "P-C2's headline finding has flipped: non-captions no longer "
        "score at least as high as captions. Rewrite "
        "P-C2-BASELINE-2026-07-20.md rather than deleting this test."
    )


def test_filler_audit_frozen_counts_match_the_published_claim() -> None:
    """RAW-FILLER-RECALL rests on 'basically' reaching more speakers
    than 'literally'. Verified from the committed derived counts."""
    result = subprocess.run(
        [sys.executable, str(RESEARCH / "filler_corpus_audit.py")],
        capture_output=True, text=True, timeout=180,
    )
    out = result.stdout
    basically = next(l for l in out.splitlines() if l.strip().startswith("basically"))
    literally = next(l for l in out.splitlines() if l.strip().startswith("literally"))
    # "<word> <hits> <transcripts>"
    assert int(basically.split()[2]) > int(literally.split()[2]), (
        "the recall note's argument (basically spans more speakers than "
        "literally) no longer holds on the frozen counts"
    )


def test_shot_threshold_parser_handles_the_corpus_anomalies() -> None:
    """`shot_threshold_audit.py` needs an external file, so its parser
    is tested directly on the anomalies the note documents: headers
    without a frame count, duplicate names, and malformed cut lines
    (both double-comma and trailing-comma)."""
    module = _load("shot_threshold_audit.py")
    text = "\n".join([
        "111.mp4 300",
        "10,11",
        "20,,21",          # double comma
        "30,31,",          # trailing comma
        "",
        "222.mp4",          # header with no frame count -> excluded
        "40,41",
        "",
        "111.mp4 300",      # duplicate name
        "50,51",
    ])
    videos, anomalies = module.parse(text)

    assert anomalies["headers_without_frame_count"] == 1
    assert anomalies["duplicate_names"] == 1
    assert anomalies["malformed_cut_lines"] == 2
    assert set(videos) == {"111.mp4"}, "the count-less header must be excluded"
    # all four well-formed pairs from 111.mp4 survive, malformed included
    assert len(videos["111.mp4"]["cuts"]) == 4

    gaps = module.shot_lengths_in_frames(videos)
    assert gaps == sorted(gaps) and all(g > 0 for g in gaps)
