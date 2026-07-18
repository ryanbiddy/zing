from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from myzing import cli, storage
from myzing.schemas import (
    AudioLayout,
    Breakdown,
    CaptionEvent,
    Shot,
    VideoMeta,
    Word,
)
from myzing.thumbs import (
    FrameMetrics,
    craft_thumbnail_prompts,
    generate_thumbnails,
    select_thumbnail_candidates,
)


SLUG = "youtube-thumbnail-test"


def _breakdown() -> Breakdown:
    words = [
        Word("Today", 0.1, 0.3),
        Word("we", 0.35, 0.5),
        Word("test", 0.55, 0.75),
        Word("a", 0.8, 0.9),
        Word("strange", 0.95, 1.25),
        Word("machine", 1.3, 1.7),
        Word("robot", 6.35, 6.75),
        Word("wow", 7.9, 8.2),
    ]
    return Breakdown(
        meta=VideoMeta(
            source_url="https://www.youtube.com/watch?v=thumbnail-test",
            platform="youtube",
            title="Robot Reveal",
            duration=12.0,
            width=640,
            height=360,
            fps=30.0,
            media_path="media.mp4",
        ),
        shots=[
            Shot(index, float(index * 2), float((index + 1) * 2))
            for index in range(6)
        ],
        words=words,
        captions=[
            CaptionEvent("SUBTITLE", 4.0, 5.5),
        ],
        audio=AudioLayout(
            has_voiceover=True,
            speech_ratio=0.25,
            loudness_curve=[
                -30.0,
                -29.0,
                -30.0,
                -30.0,
                -30.0,
                -30.0,
                -30.0,
                -30.0,
                -20.0,
                -30.0,
                -30.0,
                -30.0,
            ],
        ),
    )


def _fake_probe(timestamp: float) -> FrameMetrics:
    shot_index = min(5, int(timestamp // 2))
    digest = hashlib.sha256(str(shot_index).encode()).digest()
    return FrameMetrics(
        contrast=20.0 + shot_index,
        colorfulness=15.0 + shot_index,
        sharpness=100.0 + shot_index * 10,
        small_size_score=30.0 + shot_index,
        perceptual_hash=int.from_bytes(digest[:8], "big"),
    )


def test_candidate_selection_enforces_research_hard_rules() -> None:
    breakdown = _breakdown()

    candidates = select_thumbnail_candidates(breakdown, _fake_probe)

    assert 3 <= len(candidates) <= 5
    assert {
        "emotional_peak",
        "object_reveal",
        "hook_window",
        "contrast_sharpness",
    }.issubset({candidate["selector"] for candidate in candidates})
    cuts = [shot.start for shot in breakdown.shots[1:]]
    for candidate in candidates:
        timestamp = candidate["timestamp"]
        assert all(abs(timestamp - cut) > 0.2 for cut in cuts)
        assert all(
            not (caption.start <= timestamp <= caption.end)
            for caption in breakdown.captions
        )
        assert candidate["scores"]["contrast"] > 0
        assert candidate["description"]
    hashes = [candidate["perceptual_hash"] for candidate in candidates]
    assert all(
        (left ^ right).bit_count() > 6
        for index, left in enumerate(hashes)
        for right in hashes[index + 1 :]
    )


def test_three_prompts_are_distinct_grounded_and_hook_congruent() -> None:
    breakdown = _breakdown()
    candidates = select_thumbnail_candidates(breakdown, _fake_probe)
    for index, candidate in enumerate(candidates, start=1):
        candidate["frame"] = f"thumbnails/candidate-{index:02d}.jpg"

    prompts = craft_thumbnail_prompts(breakdown, candidates)

    assert [prompt["archetype"] for prompt in prompts] == [
        "EMOTION",
        "OBJECT_RESULT_TEASE",
        "STORY_CONTRAST",
    ]
    assert len({prompt["prompt"] for prompt in prompts}) == 3
    for prompt in prompts:
        text = prompt["prompt"]
        assert "3840x2160" in text
        assert "Maximum 3 elements" in text
        assert "at least a third of the frame" in text
        assert "hue AND luminance contrast" in text
        assert "120 PIXELS WIDE" in text
        assert "TEXT: none" in text
        assert "logos, watermarks, borders" in text
        assert prompt["reference_frames"]
        assert prompt["promise"]["delivered_at"] <= 30.0
        assert prompt["promise"]["evidence_quote"] == (
            "Today we test a strange machine robot wow"
        )
        assert prompt["congruence"] == "literal_hook_grounding"


def test_cli_routes_thumbs_command(monkeypatch, capsys) -> None:
    called = {}

    def fake_generate(slug: str, **kwargs):
        called["slug"] = slug
        return {
            "slug": slug,
            "candidates": [{"frame_path": "C:/frames/one.jpg"}],
            "prompts": [{}, {}, {}],
            "manifest_path": "C:/frames/thumbs.json",
        }

    monkeypatch.setattr("myzing.thumbs.generate_thumbnails", fake_generate)

    assert cli.main(["thumbs", SLUG, "--json"]) == 0
    assert called == {"slug": SLUG}
    assert json.loads(capsys.readouterr().out)["slug"] == SLUG


@pytest.mark.ffmpeg
def test_generate_thumbnails_extracts_source_resolution_frames(
    zing_workspace: Path,
) -> None:
    breakdown = _breakdown()
    storage.save_breakdown(breakdown, slug=SLUG)
    media_path = storage.media_target(SLUG, "mp4")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for index in range(6):
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                (
                    "color=c=0x204060:size=640x360:rate=30:duration=2,"
                    f"drawbox=x={10 + index * 100}:y=40:w=80:h=280:"
                    "c=white:t=fill"
                ),
            ]
        )
    command.extend(
        [
            "-filter_complex",
            "".join(f"[{index}:v]" for index in range(6))
            + "concat=n=6:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(media_path),
        ]
    )
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    package = generate_thumbnails(SLUG)

    assert len(package["candidates"]) >= 3
    assert len(package["prompts"]) == 3
    manifest = json.loads(
        Path(package["manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["slug"] == SLUG
    assert manifest["prompts"] == package["prompts"]
    for candidate in package["candidates"]:
        frame = Path(candidate["frame_path"])
        assert frame.is_file()
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(frame),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 0
        assert probe.stdout.strip() == "640x360"
