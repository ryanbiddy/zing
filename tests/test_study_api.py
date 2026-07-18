"""Tests for the study() seam and the CLI command: every measurement stage
is mocked; what's under test is orchestration, assembly, persistence, and
honesty of the composed result."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from myzing import storage
from myzing.schemas import AudioLayout, Breakdown, CaptionEvent, Shot, VideoMeta, Word
from myzing.study import api
from myzing.study.audio import AudioResult
from myzing.study.captions import CaptionsResult
from myzing.study.ingest import IngestResult
from myzing.study.proc import MediaError
from myzing.study.shots import ShotResult
from myzing.study.transcribe import TranscribeResult

SOURCE = "https://www.tiktok.com/@cleo/video/777"


def wire_stages(monkeypatch, slug="tiktok-777"):
    def fake_ingest(source, root=None):
        d = storage.breakdown_dir(slug)
        d.mkdir(parents=True, exist_ok=True)
        return IngestResult(
            slug=slug,
            meta=VideoMeta(
                source_url=source, platform="tiktok", author="cleo",
                title="t", duration=20.0, width=1080, height=1920,
                fps=30.0, media_path="media.mp4",
            ),
            media_path=d / "media.mp4",
            breakdown_dir=d,
            warnings=["ingest note"],
        )
    monkeypatch.setattr(api.ingest_mod, "ingest", fake_ingest)
    monkeypatch.setattr(
        api.shots_mod, "detect_shots",
        lambda p, d, f: ShotResult(
            shots=[Shot(0, 0.0, 12.0), Shot(1, 12.0, 20.0)],
            provenance={"shot_detector": "test"},
            warnings=["shots note"],
        ),
    )
    def fake_keyframes(media, bdir, shots, duration, warnings):
        for s in shots:
            s.keyframe = f"frames/shot_{s.index:03d}.jpg"
    monkeypatch.setattr(api.keyframes_mod, "extract_keyframes", fake_keyframes)
    monkeypatch.setattr(
        api.transcribe_mod, "transcribe",
        lambda p: TranscribeResult(
            words=[Word("hi", 0.0, 0.2, 0.9)],
            provenance={"whisper_model": "test"},
        ),
    )
    monkeypatch.setattr(
        api.captions_mod, "read_captions",
        lambda p, d: CaptionsResult(
            captions=[CaptionEvent("HI", 0.0, 0.5, "lower", True, 1, 0.9)],
            provenance={"ocr_backend": "test"},
            warnings=["ocr note"],
        ),
    )
    monkeypatch.setattr(
        api.audio_mod, "measure_audio",
        lambda p, d: AudioResult(
            audio=AudioLayout(True, 0.6, True, 0.5, [-20.0]),
            provenance={"vad": "test"},
        ),
    )


def test_study_assembles_and_persists(zing_workspace, monkeypatch):
    wire_stages(monkeypatch)

    b = api.study(SOURCE)

    # assembly
    assert [s.keyframe for s in b.shots] == [
        "frames/shot_000.jpg", "frames/shot_001.jpg"
    ]
    assert b.avg_shot_duration == 10.0
    assert b.cuts_per_10s == [0.0, 1.0]
    assert b.warnings == ["ingest note", "shots note", "ocr note"]
    for key in ("shot_detector", "whisper_model", "ocr_backend", "vad",
                "zing_version", "measured_at"):
        assert key in b.provenance

    # persistence via storage
    d = storage.breakdown_dir("tiktok-777")
    saved = Breakdown.from_json((d / "breakdown.json").read_text(encoding="utf-8"))
    assert saved.to_dict() == b.to_dict()
    md = (d / "breakdown.md").read_text(encoding="utf-8")
    assert "# Edit breakdown" in md and "ingest note" in md

    # the gate requirement: lossless JSON roundtrip on composed output
    assert Breakdown.from_json(b.to_json()).to_dict() == b.to_dict()


def test_study_workspace_override_and_env_restore(tmp_path, monkeypatch):
    wire_stages(monkeypatch)
    monkeypatch.delenv(storage.ENV_VAR, raising=False)
    ws = tmp_path / "custom-ws"

    api.study(SOURCE, workspace=ws)

    assert (ws / "breakdowns" / "tiktok-777" / "breakdown.json").is_file()
    assert storage.ENV_VAR not in os.environ  # restored


def test_study_reports_phases_in_order(zing_workspace, monkeypatch):
    wire_stages(monkeypatch)
    phases: list[str] = []

    api.study(SOURCE, phase_callback=phases.append)

    assert phases == [
        "ingest", "shots", "keyframes", "transcribe", "ocr", "audio",
        "markdown",
    ]


def test_study_survives_crashing_phase_callback(zing_workspace, monkeypatch):
    wire_stages(monkeypatch)

    def boom(name):
        raise RuntimeError("status write failed")

    b = api.study(SOURCE, phase_callback=boom)

    assert b.meta.platform == "tiktok"  # measurement completed regardless


def test_study_threads_root_explicitly_when_storage_supports_it(
    tmp_path, monkeypatch
):
    """A-Q7/F-15: once storage's path functions accept root=, study() must
    pass the workspace through explicitly and never touch process env."""
    wire_stages(monkeypatch)
    ws = tmp_path / "explicit-ws"
    seen: dict = {}

    def rooted_breakdown_dir(slug, root=None):
        seen["breakdown_dir_root"] = root
        return (root or tmp_path) / "breakdowns" / slug

    def rooted_save(b, slug=None, markdown=None, root=None):
        seen["save_root"] = root
        d = rooted_breakdown_dir(slug, root)
        d.mkdir(parents=True, exist_ok=True)
        (d / "breakdown.json").write_text(b.to_json(), encoding="utf-8")
        return d

    monkeypatch.setattr(api.storage, "breakdown_dir", rooted_breakdown_dir)
    monkeypatch.setattr(api.storage, "save_breakdown", rooted_save)
    monkeypatch.delenv(storage.ENV_VAR, raising=False)

    def env_probing_ingest(source, root=None):
        assert storage.ENV_VAR not in os.environ  # no global mutation
        seen["ingest_root"] = root
        d = rooted_breakdown_dir("tiktok-777", root)
        d.mkdir(parents=True, exist_ok=True)
        return IngestResult(
            slug="tiktok-777",
            meta=VideoMeta(
                source_url=source, platform="tiktok", duration=20.0, fps=30.0,
            ),
            media_path=d / "media.mp4",
            breakdown_dir=d,
        )
    monkeypatch.setattr(api.ingest_mod, "ingest", env_probing_ingest)

    api.study(SOURCE, workspace=ws)

    assert seen["ingest_root"] == ws
    assert seen["save_root"] == ws
    assert (ws / "breakdowns" / "tiktok-777" / "breakdown.json").is_file()
    assert storage.ENV_VAR not in os.environ


def test_study_media_error_propagates(zing_workspace, monkeypatch):
    def failing(source, root=None):
        raise MediaError("yt-dlp could not fetch")
    monkeypatch.setattr(api.ingest_mod, "ingest", failing)
    with pytest.raises(MediaError):
        api.study(SOURCE)


# -- CLI wrapper ------------------------------------------------------------

def test_command_happy_path(zing_workspace, monkeypatch, capsys):
    wire_stages(monkeypatch)
    from myzing.study import command

    rc = command.run([SOURCE])

    out = capsys.readouterr().out
    assert rc == 0
    assert "studied: t" in out
    assert "2 shots" in out and "1 words" in out and "1 captions" in out
    assert "breakdown.md" in out


def test_command_json_output(zing_workspace, monkeypatch, capsys):
    wire_stages(monkeypatch)
    from myzing.study import command

    rc = command.run([SOURCE, "--json"])

    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["meta"]["platform"] == "tiktok"


def test_command_media_error_is_exit_1(zing_workspace, monkeypatch, capsys):
    def failing(source, workspace=None):
        raise MediaError("no such file: nope.mp4")
    monkeypatch.setattr("myzing.study.api.study", failing)
    from myzing.study import command

    rc = command.run(["nope.mp4"])

    assert rc == 1
    assert "no such file" in capsys.readouterr().out


def test_cli_dispatch_reaches_study_command(zing_workspace, monkeypatch, capsys):
    wire_stages(monkeypatch)
    from myzing import cli

    rc = cli.main(["study", SOURCE, "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["meta"]["platform"] == "tiktok"
