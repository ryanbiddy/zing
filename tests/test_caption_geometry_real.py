"""Small opt-in offline test of the pinned real no-text counterexample."""

import hashlib
import json
import os
from pathlib import Path

import pytest


@pytest.mark.real_caption
def test_pinned_korky_face_does_not_become_caption():
    root = os.environ.get("ZING_CG2_REAL_ROOT")
    if not root:
        pytest.skip("set ZING_CG2_REAL_ROOT for the pinned real caption negative")
    # An explicit opt-in must fail, not skip, for missing assets/runtime.
    from myzing.study.caption_geometry import read_geometry
    from myzing.study.caption_models import model_paths
    model_paths()
    labels = json.loads((Path(__file__).resolve().parents[1] / "tools/eval/real/labels.json").read_text())
    media = Path(root) / "clips/korky.mp4"
    assert hashlib.sha256(media.read_bytes()).hexdigest() == labels["clips"]["korky"]["media_sha256"]
    result = read_geometry(media, 2.6)
    sample = next(f for f in result.frames if abs(f.t - 2.4) < .01)
    assert sample.detections, "Pinned OCR counterexample was not exercised"
    assert all(d.validation and not d.validation["accepted"] for d in sample.detections)
    assert not [t for t in result.tracks if any(abs(s["t"] - 2.4) < .01 for s in t.samples)]
    assert all(f.status != "ocr_error" for f in result.frames)

