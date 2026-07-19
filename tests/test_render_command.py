from __future__ import annotations

import json
from pathlib import Path

from myzing.render import command
from myzing.render.assemble import AssembleResult
from myzing.render.otio_export import OTIOExportResult
from myzing.render.pipeline import RenderResult
from myzing.render.tts import SynthesisResult
from myzing.schemas import Clip, EDL


def test_command_loads_relative_edl_and_prints_output(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    edl_path = tmp_path / "edit.json"
    edl_path.write_text(
        EDL(clips=[Clip("source.mp4", 0.0, 1.0, 0.0)]).to_json(),
        encoding="utf-8",
    )
    output = tmp_path / "custom output.mp4"
    captured = {}

    def fake_render(edl, output_path, **kwargs):
        captured["edl"] = edl
        captured["output"] = output_path
        captured["base_dir"] = kwargs["base_dir"]
        return RenderResult(output_path, 1.0, ("caption warning",), (), "", None)

    monkeypatch.setattr(command, "render_edl", fake_render)

    assert command.run([str(edl_path), "-o", str(output)]) == 0
    stdout, stderr = capsys.readouterr()
    assert str(output) in stdout
    assert "warning: caption warning" in stderr
    assert captured["base_dir"] == tmp_path
    assert captured["edl"].clips[0].src == "source.mp4"


def test_command_rejects_missing_and_malformed_edl(
    tmp_path: Path, capsys
) -> None:
    assert command.run([str(tmp_path / "missing.json")]) == 2
    assert "does not exist" in capsys.readouterr().err

    malformed = tmp_path / "bad.json"
    malformed.write_text(json.dumps({"clips": [{"src": "missing"}]}), encoding="utf-8")
    assert command.run([str(malformed)]) == 2
    assert "invalid EDL JSON" in capsys.readouterr().err


def test_command_usage_returns_two_without_exiting(capsys) -> None:
    assert command.run([]) == 2
    assert "usage: zing render" in capsys.readouterr().err


def test_command_accepts_scripted_voiceover_and_otio_export(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    edl_path = tmp_path / "edit.json"
    edl_path.write_text(
        EDL(clips=[Clip("source.mp4", 0.0, 1.0, 0.0)]).to_json(),
        encoding="utf-8",
    )
    script = tmp_path / "voice.txt"
    script.write_text("Lead with the result.", encoding="utf-8")
    output = tmp_path / "draft.mp4"
    otio_path = tmp_path / "draft.otio"
    captured = {}

    def fake_assemble(edl, output_path, **kwargs):
        captured["edl"] = edl
        captured["output"] = output_path
        captured.update(kwargs)
        voice_path = tmp_path / "draft-assets" / "voiceover-01.wav"
        return AssembleResult(
            render=RenderResult(output_path, 1.0, (), (), "", None),
            voiceovers=(
                SynthesisResult(
                    voice_path,
                    "kokoro-onnx",
                    "af_sarah",
                    24_000,
                    0.8,
                ),
            ),
            otio=OTIOExportResult(otio_path, 3, 1.0),
        )

    monkeypatch.setattr(command, "render_assembled_edl", fake_assemble)

    assert (
        command.run(
            [
                str(edl_path),
                "-o",
                str(output),
                "--voiceover-script",
                str(script),
                "--voiceover-start",
                "0.2",
                "--otio",
                str(otio_path),
            ]
        )
        == 0
    )
    stdout, stderr = capsys.readouterr()
    assert str(output) in stdout
    assert "voiceover:" in stderr
    assert "OpenTimelineIO:" in stderr
    assert captured["scripts"][0].text == "Lead with the result."
    assert captured["scripts"][0].timeline_start == 0.2
    assert captured["otio_path"] == otio_path.resolve()
