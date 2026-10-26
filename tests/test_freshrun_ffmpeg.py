"""Real synthetic close-up: subject avoidance may warn, readable text renders."""
from pathlib import Path
import subprocess
import time

import pytest


@pytest.mark.ffmpeg
@pytest.mark.parametrize("mode", ["phone", "reference"])
def test_closeup_caption_fallback_renders_at_phone_floor(tmp_path, monkeypatch, zing_workspace, mode):
    from myzing.brief.models import Brief
    from myzing.composition import AssetRef, Composition, CompositionCaption, CompositionClip, CaptionStyle
    from myzing.layout import Box, FaceTrack, Keyframe
    from myzing.layout.framing import centered_framing, place_captions
    from myzing.layout.readability import phone_minimum
    from myzing.match.caption_fit import fit_captions
    from myzing.match.evidence import decode
    from myzing.render.composition import render_composition
    source = tmp_path / "closeup.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=360x640:r=30:d=2",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=2",
        "-vf", "drawbox=x=45:y=40:w=270:h=400:color=tan:t=fill,drawbox=x=15:y=400:w=330:h=240:color=gray:t=fill",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)], check=True, capture_output=True)
    from myzing.match import api
    monkeypatch.delenv("ZING_WHISPER_MODEL", raising=False)
    monkeypatch.setattr("myzing.study.speech_models.local_path", lambda name: None)
    monkeypatch.setattr(api, "_study", lambda *a, **k: pytest.fail("missing model reached study"))
    started = time.monotonic()
    result = api.match(str(source), str(tmp_path), str(tmp_path / "preflight"), answers={})
    assert time.monotonic() - started < 3
    assert result["status"] == "shortage" and "--speech-model large-v2 --yes" in result["error"]
    plan = Composition(width=360, height=640, brief=Brief(caption_mode=mode),
        assets=[AssetRef("a", str(source), None, 2)],
        clips=[CompositionClip(str(source), 0, 2, 0, id="shot", asset_id="a",
                               framing=centered_framing("fit", 360, 640, 360, 640))],
        captions=[CompositionCaption("Here is my story" if mode == "phone" else "We went into space to learn more about the world and everyone who lives here", .1, 1.8, id="speech", word_timed=False, style=CaptionStyle(150) if mode == "reference" else None)])
    # Conservative close-up subject envelope: the old code could not place
    # any text without collision and the public renderer refused the draft.
    subject = FaceTrack("speaker", [Keyframe(0, Box(0, 0, 1, 1)), Keyframe(2, Box(0, 0, 1, 1))])
    place_captions(plan, {"a": [subject]}, {"a": (360, 640)})
    fit_captions(plan, tmp_path / "fit")
    caption = plan.captions[0]
    assert caption.style.size * caption.layout.scale >= (phone_minimum(plan, caption) if mode == "phone" else 24) - .01
    if mode == "reference":
        assert caption.style.size < 150 and "\n" in caption.text
    assert not caption.layout.overlap.safe and "speech" in plan.accepted_unsafe_layouts
    assert any("overlaps face tracks" in warning for warning in plan.warnings)
    assert caption.layout.box.x >= .06 and caption.layout.box.right <= .84
    assert caption.layout.box.y >= .08 and caption.layout.box.bottom <= .80
    output = tmp_path / "draft.mp4"
    render_composition(plan, output, base_dir=tmp_path)
    assert output.stat().st_size > 0
    assert decode(output, plan)["full_decode"]
