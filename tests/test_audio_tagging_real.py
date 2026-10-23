"""Explicit local acceptance; tests never provision weights or licensed media."""
import hashlib
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_model(env="ZING_AUD1_REAL")


@pytest.mark.parametrize("name,file,status", [
    ("calm", "calm.mp3", "not_detected"),
    ("electric", "electric.mp3", "not_detected"),
    ("vocals", "vocals.wav", "possible"),
    ("tos-dialogue", "tos-dialogue.mp4", "not_detected"),
])
def test_licensed_ced_acceptance(name, file, status):
    from myzing.audio import analyze
    root = Path(os.environ["ZING_AUD1_MEDIA"])
    rows = json.loads((root / "verified-media.json").read_text(encoding="utf-8"))
    row = next(r for r in rows if r["id"] == name)
    path = root / file
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
    result = analyze(path)
    assert result.tags.status == "measured", result.tags.warnings
    assert result.structure.vocals["status"] == status
    if name == "tos-dialogue":
        assert result.tags.music_under_speech


def test_local_korky_hint_and_timing_provenance():
    from myzing.study.transcribe import transcribe
    root = Path(os.environ["ZING_AUD1_MEDIA"])
    result = transcribe(root / "korky.mp4", model_name=os.environ["ZING_AUD1_WHISPER"],
                        local_files_only=True, vocabulary=["Korky Paul"])
    assert any("Korky" in w.text for w in result.words), result.warnings
    timing = result.provenance["timing"]
    assert len(timing["original"]) == len(timing["adjusted"]) == len(result.words)
    assert timing["speech_regions"] and timing["method"] == "vad_edge_snap"
