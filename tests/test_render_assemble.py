from __future__ import annotations

from pathlib import Path

import pytest

from myzing.render import assemble
from myzing.render.assemble import VoiceoverScript, render_assembled_edl
from myzing.render.otio_export import OTIOExportResult
from myzing.render.pipeline import RenderResult
from myzing.render.tts import SynthesisResult, TTSGenerationError
from myzing.schemas import AudioTrack, Clip, EDL


class RecordingProvider:
    name = "fixture-provider"

    def __init__(self) -> None:
        self.requests = []

    def synthesize(self, request, output_path: Path) -> SynthesisResult:
        self.requests.append(request)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"voice")
        return SynthesisResult(
            path=output_path.resolve(),
            provider=self.name,
            voice=request.voice,
            sample_rate=24_000,
            duration=1.0,
        )


def test_assembly_synthesizes_scripts_without_mutating_input_edl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    music = tmp_path / "music.wav"
    source.write_bytes(b"video")
    music.write_bytes(b"music")
    edl = EDL(
        clips=[Clip(str(source), 0.0, 2.0, 0.0)],
        audio=[AudioTrack(str(music), "music", duck_under_speech=True)],
    )
    provider = RecordingProvider()
    captured: dict[str, object] = {}
    output = tmp_path / "draft.mp4"
    otio_path = tmp_path / "draft.otio"

    def fake_render(render_edl, output_path, **kwargs):
        captured["edl"] = render_edl
        captured["render_base_dir"] = kwargs["base_dir"]
        return RenderResult(output_path, 2.0, (), (), "graph", None)

    def fake_export(export_edl, export_path, **kwargs):
        captured["export_edl"] = export_edl
        captured["export_base_dir"] = kwargs["base_dir"]
        return OTIOExportResult(export_path, 4, 2.0)

    monkeypatch.setattr(assemble, "render_edl", fake_render)
    monkeypatch.setattr(assemble, "export_otio", fake_export)

    result = render_assembled_edl(
        edl,
        output,
        scripts=[
            VoiceoverScript(
                "Open with the result.",
                timeline_start=0.25,
                voice="af_heart",
                speed=0.95,
            )
        ],
        provider=provider,
        base_dir=tmp_path,
        otio_path=otio_path,
    )

    assert len(edl.audio) == 1
    augmented = captured["edl"]
    assert isinstance(augmented, EDL)
    assert [track.kind for track in augmented.audio] == ["music", "voiceover"]
    assert augmented.audio[1].timeline_start == 0.25
    assert Path(augmented.audio[1].src).name == "voiceover-01.wav"
    assert captured["export_edl"] is augmented
    assert captured["render_base_dir"] == tmp_path.resolve()
    assert captured["export_base_dir"] == tmp_path.resolve()
    assert provider.requests[0].text == "Open with the result."
    assert result.render.output_path == output
    assert result.otio is not None
    assert result.otio.output_path == otio_path
    assert result.voiceovers[0].provider == "fixture-provider"


def test_voiceover_script_rejects_blank_text() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        VoiceoverScript("   ")


def test_failed_tts_setup_removes_new_empty_asset_directory(tmp_path: Path) -> None:
    class FailingProvider:
        name = "missing-model-provider"

        def synthesize(self, request, output_path: Path) -> SynthesisResult:
            raise TTSGenerationError("model assets are missing")

    output = tmp_path / "draft-vo.mp4"
    asset_dir = tmp_path / "draft-vo-assets"
    edl = EDL(clips=[Clip(str(tmp_path / "source.mp4"), 0.0, 2.0, 0.0)])

    with pytest.raises(TTSGenerationError, match="model assets are missing"):
        render_assembled_edl(
            edl,
            output,
            scripts=[VoiceoverScript("Open with the result.")],
            provider=FailingProvider(),
        )

    assert not asset_dir.exists()
