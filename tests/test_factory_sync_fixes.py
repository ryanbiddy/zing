"""Sync recovery without speech models, rendering or network access."""
from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from myzing import mcp_server
from myzing.factory import batch, command, judge, pipeline, source, transcript_sync
from myzing.factory.tools import FactoryError
from myzing.studio import command as studio_command, episode as studio_episode, flow
from myzing.study import speech_models
from test_factory_transcript_sync import Answers, episode, offline, project, rendering


def speech(monkeypatch, words, offset=0, duration=3600, quiet=()):
    calls = []
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda media: SimpleNamespace(duration=duration))

    def hear(media, start, end, **kwargs):
        i = len(calls)
        calls.append((start, end))
        if i in quiet or start >= duration:
            if i == 0:
                raise RuntimeError("speech transcription produced no words")
            return [], None, 0
        return [{**w, "s": w["s"] + offset, "e": w["e"] + offset}
                for w in words if start <= w["s"] + offset < min(end, duration)], "en", .99

    monkeypatch.setattr(source, "_speech", hear)
    return calls


def failed(root):
    cfg = pipeline._read(root / "factory.json")
    pipeline._write(root / "factory.json", {**cfg, "transcript_sync": {"status": "failed", "method": "probes"}})


def test_full_episode_transcript_matches_a_ten_minute_excerpt(tmp_path, episode, monkeypatch):
    root = project(tmp_path, episode)
    calls = speech(monkeypatch, episode[2], offset=-600, duration=600)
    result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
    saved = result["settings"]["transcript_sync"]
    assert result["state"] == "waiting" and saved["status"] == "matched" and saved["offset"] == -600
    assert calls == [(50, 70), (170, 190)]
    segments = pipeline._read(root / "transcript.json")
    assert segments[0]["s"] == 0 and segments[-1]["e"] == 600
    assert segments[0]["text"].startswith("word600 ")


def test_silent_probes_are_inconclusive_and_later_speech_can_match(tmp_path, episode, monkeypatch):
    root = project(tmp_path, episode)
    calls = speech(monkeypatch, episode[2], quiet=(0, 1, 2))
    saved = pipeline.run(root, judge.Judge(root), say=lambda m: None)["settings"]["transcript_sync"]
    assert saved["status"] == "matched" and saved["offset"] == 0
    assert len(calls) == 5 and all(p["note"] == "No speech heard." for p in saved["probes"][:3])


@pytest.mark.parametrize("quiet", [(0, 1, 2, 3, 4), (0, 1, 2, 3)])
def test_too_little_speech_skips_once(tmp_path, episode, monkeypatch, quiet):
    root = project(tmp_path, episode)
    calls = speech(monkeypatch, episode[2], quiet=quiet)
    said = []
    for _ in range(2):
        result = pipeline.run(root, judge.Judge(root), say=said.append)
    saved = result["settings"]["transcript_sync"]
    assert result["state"] == "waiting" and saved["status"] == "skipped" and saved["method"] == "too_little_speech"
    assert len(calls) == 5 and len(saved["probes"]) == 5
    assert said == ["Zing skipped the transcript sync check because too little speech was heard."]


def test_unmatched_speech_fails_with_recovery_commands(tmp_path, episode, monkeypatch):
    root = project(tmp_path, episode)
    calls = speech(monkeypatch, [{**w, "w": "unrelated"} for w in episode[2]])
    with pytest.raises(FactoryError) as error:
        pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert len(calls) == 5
    assert f'zing factory run "{root}" --no-sync-check' in str(error.value)
    assert f'zing factory run "{root}" --offset SECONDS' in str(error.value)
    assert pipeline._read(root / "factory.json")["transcript_sync"]["status"] == "failed"


@pytest.mark.parametrize("error", [RuntimeError("decoder failed"), OSError("audio unavailable"),
                                  subprocess.CalledProcessError(1, ["ffmpeg"], stderr="no audio stream"),
                                  ImportError("speech extra missing"), ModuleNotFoundError("faster_whisper")])
def test_probe_errors_skip_once(tmp_path, episode, monkeypatch, error):
    root = project(tmp_path, episode)
    calls, said = [], []

    def hear(*args, **kwargs):
        calls.append(args)
        raise error

    monkeypatch.setattr(source, "_speech", hear)
    for _ in range(2):
        result = pipeline.run(root, judge.Judge(root), say=said.append)
    saved = result["settings"]["transcript_sync"]
    assert result["state"] == "waiting" and saved["status"] == "skipped" and saved["method"] == "probe_error"
    assert 0 < len(saved["error"]) <= 300 and "\n" not in saved["error"]
    assert len(calls) == 5
    assert said == ["Zing skipped the transcript sync check because the speech probes could not run."]


def test_past_end_probes_are_inconclusive(tmp_path, episode, monkeypatch):
    root = project(tmp_path, episode)

    def hear(*args, **kwargs):
        raise RuntimeError("The probe window is past the end of the media.")

    monkeypatch.setattr(source, "_speech", hear)
    saved = pipeline.run(root, judge.Judge(root), say=lambda m: None)["settings"]["transcript_sync"]
    assert saved["status"] == "skipped" and saved["method"] == "too_little_speech"
    assert all(p["note"] == "Past the media end." for p in saved["probes"])


def test_speech_off_never_uses_a_cached_model(tmp_path, episode, monkeypatch):
    root = project(tmp_path, episode)
    monkeypatch.setattr(speech_models, "resolve_name", lambda *a, **kw: "skip")
    assert transcript_sync.model() is None
    said = []
    for _ in range(2):
        result = pipeline.run(root, judge.Judge(root), say=said.append)
    assert result["settings"]["transcript_sync"] == {"status": "skipped", "method": "speech_off"}
    assert said == ["Zing skipped the transcript sync check because speech is turned off."]


@pytest.mark.parametrize("method", [None, "disabled", "offset", "no_cached_model", "too_little_speech", "probe_error", "speech_off"])
def test_only_matched_supplied_transcripts_get_the_clip_guard(tmp_path, episode, monkeypatch, method):
    root = project(tmp_path, episode)
    cfg = pipeline._read(root / "factory.json")
    if method is None:
        cfg.pop("transcript_sync")
        (root / "transcript.json").unlink()
        monkeypatch.setattr(source, "transcribe_episode", lambda *a, **kw: episode[2])
    else:
        cfg["transcript_sync"] = {"status": "skipped", "method": method}
    pipeline._write(root / "factory.json", cfg)
    rendered = rendering(monkeypatch, [{**w, "w": "different"} for w in episode[2]])

    class Pick(Answers):
        def ask(self, task, text, images=()):
            if task == "scout":
                return {"moments": [{"start": 2000, "end": 2030, "hook": "A moment"}]}
            return super().ask(task, text, images)

    result = pipeline.run(root, Pick(), say=lambda m: None)
    assert result["failed"] == {} and rendered == ["clip01"]


@pytest.mark.parametrize("key", ["text", "w"])
def test_shift_drops_outside_rows_and_clamps_both_edges(key):
    rows = [{"s": s, "e": e, key: str(i)} for i, (s, e) in enumerate(((0, 10), (8, 12), (15, 20), (29, 35), (30, 40)))]
    assert transcript_sync.shift(rows, -10, 20) == [
        {"s": 0, "e": 2, key: "1"}, {"s": 5, "e": 10, key: "2"}, {"s": 19, "e": 20, key: "3"}]
    assert rows[0]["s"] == 0 and rows[-1]["e"] == 40


def test_new_offset_bounds_words_and_segments_and_keeps_originals(tmp_path, episode, monkeypatch):
    media, _, words = episode
    captions, root = tmp_path / "words.json", tmp_path / "project"
    pipeline._write(captions, words)
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda media: SimpleNamespace(duration=600))
    pipeline.init(root, media, transcript=captions, offset=-600)
    assert pipeline._read(root / "words.json") == [{**w, "s": w["s"] - 600, "e": w["e"] - 600} for w in words[600:1200]]
    segments = pipeline._read(root / "transcript.json")
    assert segments[0]["s"] == 0 and segments[-1]["e"] == 600
    assert pipeline._read(root / "words.unsynced.json") == words


@pytest.mark.parametrize("crash", ["transcript.json", "words.json", "factory.json"])
def test_interrupted_shift_always_restarts_from_originals(tmp_path, episode, monkeypatch, crash):
    media, _, words = episode
    captions, root = tmp_path / "words.json", tmp_path / "project"
    pipeline._write(captions, words)
    pipeline.init(root, media, transcript=captions)
    original = {name: pipeline._read(root / f"{name}.json") for name in ("transcript", "words")}
    speech(monkeypatch, words, offset=100)
    write = pipeline._write

    def interrupt(path, value):
        if path.name == crash:
            raise OSError("interrupted shift")
        write(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_write", interrupt)
        with pytest.raises(OSError, match="interrupted shift"):
            pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert pipeline._read(root / "factory.json")["transcript_sync"]["status"] == "pending"
    for name, rows in original.items():
        assert pipeline._read(root / f"{name}.unsynced.json") == rows
    for _ in range(2):
        result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
        assert result["settings"]["transcript_offset"] == 100
        for name, rows in original.items():
            shifted = pipeline._read(root / f"{name}.json")
            assert shifted[0]["s"] == 100 and shifted[-1]["e"] == 3600
            assert all(0 <= row["s"] < row["e"] <= 3600 for row in shifted)
            assert pipeline._read(root / f"{name}.unsynced.json") == rows


@pytest.mark.parametrize("method", ["no_cached_model", "disabled"])
def test_interrupted_shift_restores_both_files_when_the_check_is_skipped(tmp_path, episode, monkeypatch, method):
    media, _, words = episode
    captions, root = tmp_path / "words.json", tmp_path / "project"
    pipeline._write(captions, words)
    pipeline.init(root, media, transcript=captions)
    original = pipeline._read(root / "transcript.json")
    speech(monkeypatch, words, offset=100)
    write = pipeline._write

    def interrupt(path, value):
        if path.name == "words.json":
            raise OSError("interrupted shift")
        write(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_write", interrupt)
        with pytest.raises(OSError, match="interrupted shift"):
            pipeline.run(root, judge.Judge(root), say=lambda m: None)
    monkeypatch.setattr(transcript_sync, "model", lambda: None)
    if method == "disabled":
        assert command.run(["run", str(root), "--no-sync-check"]) == 0
    result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert result["settings"]["transcript_sync"] == {"status": "skipped", "method": method}
    assert pipeline._read(root / "transcript.json") == original
    assert pipeline._read(root / "words.json") == words


@pytest.mark.parametrize("flags,method,offset", [(["--no-sync-check"], "disabled", 0),
                                               (["--offset", "-600"], "offset", -600),
                                               (["--offset", "0"], "offset", 0)])
def test_run_recovers_a_failed_project_without_shifting_twice(tmp_path, episode, flags, method, offset):
    root = project(tmp_path, episode)
    failed(root)
    for _ in range(2):
        assert command.run(["run", str(root), *flags]) == 0
        cfg = pipeline._read(root / "factory.json")
        assert cfg["transcript_sync"] == {"status": "skipped", "method": method}
        assert cfg["transcript_offset"] == offset
        assert pipeline._read(root / "transcript.json")[0]["s"] == 0
    if offset:
        assert pipeline._read(root / "transcript.json")[0]["text"].startswith("word600 ")


@pytest.mark.parametrize("settings", [{"no_sync_check": True}, {"offset": -600}])
def test_mcp_run_recovers_and_refuses_overrides_after_scouting(tmp_path, episode, settings):
    root = project(tmp_path, episode)
    failed(root)
    assert mcp_server.h_factory_run(str(root), **settings)["status"] == "started"
    with mcp_server._JOBS_LOCK:
        thread = mcp_server._FACTORY_JOBS.get(str(root))
    if thread:
        thread.join(5)
        assert not thread.is_alive()
    assert mcp_server.h_factory_status(str(root))["state"] == "waiting"
    pipeline._write(root / "moments.json", {"scouted": True, "moments": []})
    before = {p.name: p.read_bytes() for p in root.glob("*.json")}
    result = mcp_server.h_factory_run(str(root), **settings)
    assert not result["ok"] and "already been scouted" in result["error"]
    flags = ["--no-sync-check"] if "no_sync_check" in settings else ["--offset", "-600"]
    assert command.run(["run", str(root), *flags]) == 2
    assert {p.name: p.read_bytes() for p in root.glob("*.json")} == before


def test_mcp_run_exposes_optional_recovery_parameters():
    tools = asyncio.run(mcp_server.build_server().list_tools())
    assert len(tools) == 44
    schema = next(tool.input_schema for tool in tools if tool.name == "factory_run")
    assert schema["required"] == ["project"]
    assert schema["properties"]["no_sync_check"]["default"] is False
    assert schema["properties"]["offset"]["default"] is None


def test_batch_passes_opt_out_to_every_new_project(tmp_path, episode, monkeypatch):
    media, captions, _ = episode
    other = media.with_name("other.mp4")
    other.write_bytes(b"video")
    other.with_suffix(".srt").write_bytes(captions.read_bytes())
    out = tmp_path / "projects"
    monkeypatch.setattr(batch.time, "sleep", lambda seconds: None)
    assert command.run(["batch", str(tmp_path), "--out", str(out), "--no-sync-check"]) == 0
    for name in ("episode", "other"):
        cfg = pipeline._read(out / name / "factory.json")
        assert cfg["no_sync_check"] is True
        assert cfg["transcript_sync"] == {"status": "skipped", "method": "disabled"}


@pytest.mark.parametrize("answer", ["", "no"])
def test_studio_failed_reuse_offers_skip_or_transcribe(tmp_path, episode, monkeypatch, answer):
    root = project(tmp_path, episode)
    failed(root)
    probe = {"duration": 3600, "streams": [{"codec_type": "video"}]}
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda media: SimpleNamespace(to_dict=lambda: probe))
    a = {"path": "g", "episode": str(episode[0]), "transcript": str(episode[1]), "clips": 1,
         "shapes": ["9x16"], "judge": "host", "project": str(root)}
    step = flow.next_step(a)
    assert step["status"] == "question"
    q = step["question"]
    assert q["recommended"] is True and "transcript" in q["prompt"]
    a[q["id"]] = studio_command._answer(q, answer)
    step = flow.next_step(a)
    assert step["status"] == "plan"
    result = studio_episode.create(step["answers"], step["plan"])
    assert result["reused"]
    cfg = pipeline._read(root / "factory.json")
    if not answer:
        assert cfg["transcript_sync"] == {"status": "skipped", "method": "disabled"}
    else:
        assert not cfg.get("transcript_sync") and not (root / "transcript.json").exists()
        assert not (root / "words.json").exists()
        monkeypatch.setattr(source, "transcribe_episode", lambda *a, **kw: episode[2])
    assert pipeline.run(root, judge.Judge(root), say=lambda m: None)["state"] == "waiting"
