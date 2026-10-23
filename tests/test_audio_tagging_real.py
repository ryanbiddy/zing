"""Explicit local acceptance; tests never provision weights or licensed media."""
import csv
import hashlib
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_model(env="ZING_AUD1_REAL")


def _verified(name, file):
    root = Path(os.environ["ZING_AUD1_MEDIA"])
    rows = json.loads((root / "verified-media.json").read_text(encoding="utf-8"))
    row = next(r for r in rows if r["id"] == name)
    path = root / file
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
    return path


# tos-lab is the LISTEN1 clip whose own film score was heard under the dialogue;
# tos-dialogue is speech plus an explosion, with CED Music at most 0.04.
@pytest.mark.parametrize("name,file,status,score_under_speech", [
    ("calm", "calm.mp3", "not_detected", False),
    ("electric", "electric.mp3", "not_detected", False),
    ("vocals", "vocals.wav", "possible", False),
    ("korky", "korky.mp4", "not_detected", False),
    ("tos-dialogue", "tos-dialogue.mp4", "not_detected", False),
    ("tos-lab", "tos-lab.mp4", "not_detected", True),
    ("tos-memory", "tos-memory.mp4", "not_detected", True),
])
def test_licensed_ced_acceptance(name, file, status, score_under_speech):
    from myzing.audio import analyze
    result = analyze(_verified(name, file))
    assert result.tags.status == "measured", result.tags.warnings
    assert result.structure.vocals["status"] == status
    assert bool(result.tags.music_under_speech) == score_under_speech
    if score_under_speech:
        assert {row["strength"] for row in result.tags.music_under_speech} == {"candidate"}
    if name == "vocals":
        assert result.tags.vocal_spans and result.structure.vocals["strength"] == "candidate"


def test_family_labels_exist_in_the_provisioned_class_list():
    from myzing.audio import tag_models, tagging
    names = {row["display_name"] for row in csv.DictReader(
        tag_models.model_paths()["class_labels_indices.csv"].open(encoding="utf-8"))}
    assert len(names) == 527 and tagging.LABELS <= names


def test_local_korky_hint_and_timing_provenance():
    from myzing.study.transcribe import transcribe
    root = Path(os.environ["ZING_AUD1_MEDIA"])
    result = transcribe(root / "korky.mp4", model_name=os.environ["ZING_AUD1_WHISPER"],
                        local_files_only=True, vocabulary=["Korky Paul"])
    assert any("Korky" in w.text for w in result.words), result.warnings
    timing = result.provenance["timing"]
    assert len(timing["original"]) == len(timing["adjusted"]) == len(result.words)
    assert timing["speech_regions"] and timing["method"] == "vad_edge_snap"
    assert result.provenance["asr_prompt"]["counting"] == "model tokenizer"


@pytest.mark.parametrize("batched", [False, True])
def test_vocabulary_at_the_byte_limit_still_transcribes(batched):
    # 500 UTF-8 bytes of CJK names were ~260 tokens; sent as hotwords and
    # initial_prompt they overflowed Whisper's 448 positions and lost every word.
    from myzing.study import transcribe as module
    from myzing.study.asr_hygiene import vocabulary_context
    root = Path(os.environ["ZING_AUD1_MEDIA"])
    vocabulary = ["王小明", "李华强", "欧阳娜娜", "上官婉儿", "司马相如", "诸葛孔明"] + [f"东方不败{i}" for i in range(60)]
    assert len(vocabulary_context(vocabulary)["text"].encode("utf-8")) > 450
    model, *_ = module._load_model(os.environ["ZING_AUD1_WHISPER"], local_files_only=True)
    run = module._run_model_batched if batched else module._run_model
    words, language, _, _, prompt = run(model, root / "korky.mp4", vocabulary=vocabulary)
    assert len(words) > 30 and language == "en"
    assert 1 + prompt["hotwords_tokens"] + prompt["initial_prompt_tokens"] + 4 <= 223
