"""Tests for the study() seam and the CLI command: every measurement stage
is mocked; what's under test is orchestration, assembly, persistence, and
honesty of the composed result."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import storage
from myzing.schemas import (
    AudioLayout,
    Breakdown,
    CaptionEvent,
    Shot,
    TransitionObservation,
    VideoMeta,
    Word,
)
from myzing.study import api
from myzing.study.audio import AudioResult
from myzing.study.captions import CaptionsResult
from myzing.study.ingest import IngestResult
from myzing.study.proc import MediaError
from myzing.study.shots import ShotResult
from myzing.study.transcribe import TranscribeResult

SOURCE = "https://www.tiktok.com/@cleo/video/777"


def wire_measurement_stages_only(monkeypatch):
    """Everything AFTER ingest, mocked — ingest itself stays real so the
    acquisition path is exercised end to end (family-scenario regression)."""
    monkeypatch.setattr(
        api.shots_mod, "detect_shots",
        lambda p, d, f: ShotResult(
            shots=[Shot(0, 0.0, 12.0)], provenance={"shot_detector": "test"},
        ),
    )
    monkeypatch.setattr(
        api.keyframes_mod, "extract_keyframes",
        lambda media, bdir, shots, duration, warnings: None,
    )
    monkeypatch.setattr(
        api.transcribe_mod, "transcribe",
        lambda p, duration=0.0: TranscribeResult(
            words=[Word("hi", 0.0, 0.2, 0.9)],
            provenance={"whisper_model": "test"},
        ),
    )
    monkeypatch.setattr(
        api.captions_mod, "read_captions",
        lambda p, d: CaptionsResult(provenance={"ocr_backend": "test"}),
    )
    monkeypatch.setattr(
        api.audio_mod, "measure_audio",
        lambda p, d: AudioResult(
            audio=AudioLayout(False, 0.0, True, 0.9, [-20.0]),
            provenance={"vad": "test"},
        ),
    )


def wire_stages(monkeypatch, slug="tiktok-777"):
    def fake_ingest(source, root=None, **stage_kwargs):
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
        lambda p, duration=0.0: TranscribeResult(
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


def test_study_transition_detection_is_opt_in(zing_workspace, monkeypatch):
    wire_stages(monkeypatch)
    calls: list[Path] = []
    observation = TransitionObservation(
        kind="hard_cut",
        start=12.0,
        end=12.0,
        frame_pair_count=1,
        audio_aligned=True,
        audio_onset_delta=-0.02,
    )

    def fake_detect(media_path):
        calls.append(media_path)
        return SimpleNamespace(
            transitions=[observation],
            warnings=[],
            provenance={
                "transition_detector": "test-v2",
                "transition_thresholds": {"hard_cut_difference": 15.0},
            },
        )

    monkeypatch.setattr(
        api,
        "transitions_mod",
        SimpleNamespace(detect_transitions=fake_detect),
        raising=False,
    )

    disabled = api.study(SOURCE)
    phases: list[str] = []
    enabled = api.study(
        SOURCE,
        detect_transitions=True,
        phase_callback=phases.append,
    )

    assert disabled.transitions == []
    assert "transition_detector" not in disabled.provenance
    assert calls == [storage.breakdown_dir("tiktok-777") / "media.mp4"]
    assert enabled.transitions == [observation]
    assert enabled.provenance["transition_detector"] == "test-v2"
    assert enabled.schema_version == 1
    assert phases[-2:] == ["transitions", "markdown"]


def test_study_transition_failure_is_named(zing_workspace, monkeypatch):
    wire_stages(monkeypatch)

    class ProbeError(RuntimeError):
        pass

    def failing_detect(media_path):
        raise ProbeError("ffmpeg could not decode transition frames")

    monkeypatch.setattr(
        api,
        "transitions_mod",
        SimpleNamespace(
            TransitionProbeError=ProbeError,
            detect_transitions=failing_detect,
            detector_provenance=lambda: {
                "transition_detector": "test-v2",
                "transition_thresholds": {},
            },
        ),
        raising=False,
    )

    breakdown = api.study(SOURCE, detect_transitions=True)

    assert breakdown.transitions == []
    assert breakdown.provenance["transition_detector"] == "test-v2"
    assert breakdown.warnings[-1] == (
        "transition detection skipped: "
        "ffmpeg could not decode transition frames"
    )


def test_workspace_override_never_touches_env_with_use_workspace(
    tmp_path, monkeypatch
):
    """F-15 closed: with storage.use_workspace available (ContextVar pin),
    study(workspace=...) must not mutate process env at any point."""
    wire_stages(monkeypatch)
    monkeypatch.delenv(storage.ENV_VAR, raising=False)
    ws = tmp_path / "ctx-ws"
    probes: list[bool] = []

    real_detect = api.shots_mod.detect_shots

    def probing_detect(p, d, f):
        probes.append(storage.ENV_VAR in os.environ)  # mid-study probe
        return real_detect(p, d, f)
    monkeypatch.setattr(api.shots_mod, "detect_shots", probing_detect)

    api.study(SOURCE, workspace=ws)

    assert probes == [False]  # env untouched even DURING the study
    assert (ws / "breakdowns" / "tiktok-777" / "breakdown.json").is_file()


def test_study_media_error_propagates(zing_workspace, monkeypatch):
    def failing(source, root=None, **stage_kwargs):
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


def test_command_forwards_transition_opt_in(monkeypatch, capsys):
    seen: dict[str, object] = {}

    def fake_study(source, workspace=None, detect_transitions=False):
        seen.update(
            source=source,
            workspace=workspace,
            detect_transitions=detect_transitions,
        )
        return Breakdown(
            meta=VideoMeta(source_url=source, platform="file"),
        )

    monkeypatch.setattr("myzing.study.api.study", fake_study)
    from myzing.study import command

    rc = command.run(["clip.mp4", "--transitions", "--json"])

    assert rc == 0
    assert seen == {
        "source": "clip.mp4",
        "workspace": None,
        "detect_transitions": True,
    }
    assert json.loads(capsys.readouterr().out)["transitions"] == []


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


def test_kept_media_provenance_reaches_breakdown(zing_workspace, monkeypatch):
    """A-S6: ingest's kept-media evidence must survive into
    Breakdown.provenance (the family scenario's 'provenance cites the
    sidecar' requirement)."""
    wire_stages(monkeypatch)

    def fake_ingest(source, root=None, **stage_kwargs):
        d = storage.breakdown_dir("tiktok-777")
        d.mkdir(parents=True, exist_ok=True)
        return IngestResult(
            slug="tiktok-777",
            meta=VideoMeta(
                source_url=source, platform="tiktok", author="cleo",
                title="t", duration=20.0, width=1080, height=1920,
                fps=30.0, media_path="media.mp4",
            ),
            media_path=d / "media.mp4",
            breakdown_dir=d,
            warnings=[],
            provenance={
                "media_source": "kept-media",
                "kept_media_sha256": "ab" * 32,
            },
        )
    monkeypatch.setattr(api.ingest_mod, "ingest", fake_ingest)

    b = api.study(SOURCE, kept_media="C:/kept/clip.mp4")

    assert b.provenance["media_source"] == "kept-media"
    assert b.provenance["kept_media_sha256"] == "ab" * 32


def test_workspace_env_fallback_without_use_workspace(tmp_path, monkeypatch):
    """The env-var fallback path: a storage build without use_workspace
    still gets workspace routing, and the env var is restored after."""
    wire_stages(monkeypatch)
    monkeypatch.delenv(storage.ENV_VAR, raising=False)
    monkeypatch.delattr(storage, "use_workspace")
    ws = tmp_path / "legacy-ws"

    api.study(SOURCE, workspace=ws)

    assert storage.ENV_VAR not in os.environ  # restored to absent


def test_workspace_env_fallback_restores_prior_value(tmp_path, monkeypatch):
    wire_stages(monkeypatch)
    monkeypatch.delattr(storage, "use_workspace")
    monkeypatch.setenv(storage.ENV_VAR, "prior-home")

    api.study(SOURCE, workspace=tmp_path / "other-ws")

    assert os.environ[storage.ENV_VAR] == "prior-home"


def test_zing_version_unknown_on_metadata_failure(monkeypatch):
    import importlib.metadata

    def boom(name):
        raise importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(importlib.metadata, "version", boom)

    assert api._zing_version() == "unknown"


# -- family-scenario regression (S6, Lane A half) ----------------------------

def _probe_json() -> str:
    return json.dumps({
        "streams": [
            {
                "codec_type": "video", "codec_name": "h264",
                "width": 1080, "height": 1920,
                "avg_frame_rate": "30/1", "r_frame_rate": "30/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "8.0"},
    })


def _cfr_pts() -> str:
    return "\n".join(f"{i / 30:.6f}" for i in range(240)) + "\n"


def _tools_that_must_not_fetch(calls):
    """proc.run stub: answers ffprobe honestly, records everything, and
    FAILS the test if yt-dlp is ever invoked."""
    import subprocess as sp

    def run(cmd, timeout=None):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            if any("packet=pts_time" in part for part in cmd):
                return sp.CompletedProcess(cmd, 0, _cfr_pts(), "")
            return sp.CompletedProcess(cmd, 0, _probe_json(), "")
        raise AssertionError(f"zero-refetch violated: {cmd[0]} was invoked")
    return run


def test_family_scenario_kept_media_hop_end_to_end(
    zing_workspace, tmp_path, monkeypatch
):
    """S6 family scenario, Lane A half, fully offline: a uoink-kept file
    plus its uoink.media.handoff record must produce a persisted breakdown
    with ZERO network fetch and the contract's path-free provenance
    (acquisition kept_media / refetch false) — what the gate asserts.

    Real ingest; only subprocess and the measurement stages are stubbed.
    """
    import hashlib

    wire_measurement_stages_only(monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr("myzing.study.ingest.proc.run", _tools_that_must_not_fetch(calls))
    monkeypatch.setattr("myzing.doctor.resolve_ytdlp_argv", lambda: ["yt-dlp"])

    payload = b"uoink-kept-bytes-for-the-family-scenario"
    kept = tmp_path / "uoink-corpus" / "short-123" / "video.mp4"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(payload)
    url = "https://www.tiktok.com/@creator/video/7239871234"
    handoff = {
        "source_ref": "uoink://item/short-123",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_length": len(payload),
    }

    breakdown = api.study(url, kept_media=kept, handoff=handoff)

    assert not [c for c in calls if c[0] == "yt-dlp"]        # zero refetch
    sh = breakdown.provenance["source_handoff"]
    assert sh == {
        "contract": "uoink.media.handoff",
        "version": 1,
        "source_ref": "uoink://item/short-123",
        "acquisition": "kept_media",
        "refetch": False,
        "sha256": handoff["sha256"],
    }
    assert not any("path" in str(v).lower() for v in sh.values())
    # persisted, and the stable reference stays URL-derived
    saved = storage.load_breakdown("tiktok-7239871234")
    assert saved.provenance["source_handoff"] == sh
    assert saved.meta.source_url == url
    assert saved.meta.platform == "tiktok"


def test_family_scenario_tampered_kept_media_refetches_honestly(
    zing_workspace, tmp_path, monkeypatch
):
    """The gate's negative: bytes that do not match the handoff must NOT
    be measured — integrity fails, the study refetches, and provenance
    says so (acquisition source_refetch / reason integrity_mismatch)."""
    import hashlib
    import subprocess as sp

    wire_measurement_stages_only(monkeypatch)
    fetched: list[list[str]] = []

    def run(cmd, timeout=None):
        if cmd[0] == "ffprobe":
            if any("packet=pts_time" in part for part in cmd):
                return sp.CompletedProcess(cmd, 0, _cfr_pts(), "")
            return sp.CompletedProcess(cmd, 0, _probe_json(), "")
        if cmd[0] == "yt-dlp":
            fetched.append(cmd)
            dest = Path(cmd[cmd.index("-P") + 1])
            (dest / "media.mp4").write_bytes(b"authentic-fetched-bytes")
            return sp.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)
    monkeypatch.setattr("myzing.study.ingest.proc.run", run)
    monkeypatch.setattr("myzing.doctor.resolve_ytdlp_argv", lambda: ["yt-dlp"])

    # Same LENGTH, different bytes — the realistic tamper, and the case
    # only the hash can catch (a size-only check would pass it through).
    original = b"the-original-bytes-from-uoink"
    tampered = b"the-TAMPERED-bytes-from-nope!"
    assert len(original) == len(tampered)
    kept = tmp_path / "tampered.mp4"
    kept.write_bytes(tampered)
    handoff = {
        "source_ref": "uoink://item/short-123",
        "sha256": hashlib.sha256(original).hexdigest(),
        "byte_length": len(original),
    }

    breakdown = api.study(
        "https://www.tiktok.com/@creator/video/7239871234",
        kept_media=kept,
        handoff=handoff,
    )

    assert len(fetched) == 1
    sh = breakdown.provenance["source_handoff"]
    assert sh["acquisition"] == "source_refetch"
    assert sh["refetch"] is True
    assert sh["reason"] == "integrity_mismatch"
    assert any("integrity mismatch" in w for w in breakdown.warnings)
