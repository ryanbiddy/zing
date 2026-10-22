"""The optional retry only uses a local model and a temporary bounded crop."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import cli, storage
from myzing.assemble import word_retry
from myzing.schemas import Breakdown, VideoMeta, Word
from myzing.study import transcribe


def test_local_retry_crops_audio_once_and_reuses_offline_model(tmp_path, monkeypatch):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    model_calls = []
    model = object()
    def load(*args, **kwargs):
        model_calls.append((args, kwargs))
        return model
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=load))
    commands = []
    def run(command, timeout):
        commands.append((command, timeout))
        Path(command[-1]).write_bytes(b"cropped audio fixture")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(word_retry, "run", run)
    def recognize(supplied_model, crop):
        assert supplied_model is model and crop.read_bytes() == b"cropped audio fixture"
        return [Word("England", .992, 1.008, .8)], "en", .9
    monkeypatch.setattr(transcribe, "_run_model", recognize)
    retry = word_retry.local_word_retry(tmp_path / "source.mp4", model_dir)
    assert model_calls == commands == []  # factory is lazy
    for _ in range(2):
        result = retry(Word("England", 7.4, 7.4), 6.4, 8)
        assert result[0].start == pytest.approx(7.392)
        assert result[0].end == pytest.approx(7.408)
        assert result[0].timing["adjustments"][0]["model_directory"] == str(model_dir)
    assert model_calls == [((str(model_dir),), {
        "device": "cpu", "compute_type": "int8", "local_files_only": True,
    })]
    assert len(commands) == 2
    for command, timeout in commands:
        assert command[command.index("-ss") + 1] == "6.4"
        assert float(command[command.index("-t") + 1]) == pytest.approx(1.6)
        assert timeout == 30
        assert not Path(command[-1]).parent.exists()  # crop cleaned up


@pytest.mark.parametrize("start,end", [(-1, 1), (1, 1), (1, 3.01), (float("nan"), 2)])
def test_retry_rejects_unbounded_span_before_model_or_ffmpeg(tmp_path, start, end):
    retry = word_retry.local_word_retry(tmp_path / "source.mp4", tmp_path / "missing")
    with pytest.raises(ValueError, match="at most 2 seconds"):
        retry(Word("bad", 1, 1), start, end)


def test_retry_requires_existing_local_directory(tmp_path):
    retry = word_retry.local_word_retry(tmp_path / "source.mp4", tmp_path / "tiny")
    with pytest.raises(ValueError, match="local whisper model directory missing"):
        retry(Word("zero", 1, 1), 0, 2)


def test_cli_enables_retry_only_with_explicit_option(tmp_path, zing_workspace, monkeypatch):
    import json

    storage.save_breakdown(Breakdown(
        meta=VideoMeta("source.mp4", "file", duration=2,
                       width=180, height=320, fps=30, media_path="media.mp4"),
        words=[Word("before", .5, .99), Word("zero", 1, 1), Word("after", 1.01, 1.5)],
    ), slug="retry")
    media = storage.breakdown_dir("retry") / "media.mp4"
    media.write_bytes(b"fixture")
    direction = tmp_path / "direction.json"
    direction.write_text(json.dumps({"keepers": [{"start": 0, "end": 2}]}), encoding="utf-8")
    calls = []
    def factory(media_path, model_path):
        calls.append((media_path, model_path))
        return lambda *args: [Word("zero", .995, 1.005)]
    monkeypatch.setattr(word_retry, "local_word_retry", factory)
    args = ["assemble", "retry", "--direction", str(direction)]
    assert cli.main(args) == 1
    assert calls == []
    assert cli.main([*args, "--retry-word-timing-model", str(tmp_path / "model")]) == 0
    assert calls == [(media, tmp_path / "model")]
    saved = json.loads((media.parent / "draft-edl.json").read_text(encoding="utf-8"))
    assert saved["captions"][0]["words"][1]["timing"]["method"] == "bounded_retranscription"
