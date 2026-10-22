"""Write synthetic, non-renderable contract examples for COMPOSITION-V2.md.

Repeated-digit media/LUT hashes are explicit placeholders, not media checksums.
The font hash is the checked-in Anton asset's real hash. No media is downloaded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from myzing.composition import (
    AssetRef, CaptionStyle, ColorTransform, Composition, CompositionAudio,
    CompositionCaption, CompositionClip, FontAsset, LoudnessTarget,
    SourceRange, Transition, TransitionRecipe, lower_to_v1,
)
from myzing.layout.chooser import choose_layout
from myzing.layout.types import Box, CaptionEvent, FaceTrack, Keyframe
from myzing.project.models import Rational
from myzing.schemas import Breakdown, Word
from myzing.style_recipe import FontCandidate, build_style_recipe
from myzing.timing import transform_word

ROOT = Path(__file__).resolve().parents[1]


def talking_head_example():
    assets = [AssetRef(f"asset-take-{i}", f"media/take-{i}.mp4", str(i) * 64, 12)
              for i in range(1, 4)]
    assets.append(AssetRef("asset-music", "media/music.wav", "4" * 64, 12))
    look = ColorTransform("looks/teal-orange.cube", "a" * 64, 0.7, "SDR Rec.709 display-referred RGB")
    clips = [
        CompositionClip("media/take-1.mp4", 1, 4, 0, id="clip-1", asset_id="asset-take-1", color=look),
        CompositionClip("media/take-2.mp4", 2, 5, 2.5, id="clip-2", asset_id="asset-take-2", color=look),
        CompositionClip("media/take-3.mp4", 0, 2.5, 5.5, id="clip-3", asset_id="asset-take-3", color=look),
    ]
    face = FaceTrack("synthetic-face", [Keyframe(0, Box(0.32, 0.15, 0.36, 0.4)),
                                       Keyframe(8, Box(0.32, 0.15, 0.36, 0.4))])
    moving = [Keyframe(3.2, Box(0.15, 0.68, 0.6, 0.12)),
              Keyframe(4.3, Box(0.25, 0.72, 0.6, 0.12))]
    layout = choose_layout([
        CaptionEvent("caption-1", 0.3, 1.5, 0.6, 0.12, preferred_anchor="center"),
        CaptionEvent("caption-2", 3.2, 4.3, 0.6, 0.12, path=moving),
        CaptionEvent("caption-3", 6, 7.5, 0.6, 0.12),
    ], [face], [])
    layout.provenance["construction"] = "Synthetic padded face box; no detector was run."
    font = FontAsset("../../../src/myzing/_data/fonts/Anton-Regular.ttf",
                     "a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab", "OFL-1.1")
    phrases = [("Keep", "your", "focus"), ("Make", "it", "clear"), ("Then", "cut")]
    captions = []
    for index, (placed, phrase, clip) in enumerate(zip(layout.events, phrases, clips)):
        step = (placed.end - placed.start) / len(phrase)
        words = []
        for j, text in enumerate(phrase):
            start, end = placed.start + j * step, placed.start + (j + 1) * step
            source = Word(text, clip.source_at(start), clip.source_at(end), timing={
                "status": "measured", "method": "synthetic_fixture", "version": 1,
                "original": {"start": clip.source_at(start), "end": clip.source_at(end)}, "adjustments": [],
            })
            words.append(transform_word(source, start, end, "timeline_map", corrected=False, clip_id=clip.id))
        captions.append(CompositionCaption(
            " ".join(phrase), placed.start, placed.end, words=words, id=placed.id,
            layout=placed, font=font, style=CaptionStyle(64),
            backend="hyperframes" if index == 1 else "ass",
            template="kinetic" if index == 1 else None,
        ))
    composition = Composition(
        assets=assets, clips=clips, captions=captions,
        transitions=[Transition("dissolve-1", "clip-1", "clip-2", 2.5, 3,
                                TransitionRecipe("dissolve", 0.5, "Chosen half-second dissolve; original preset unknown."),
                                SourceRange(3.5, 4), SourceRange(2, 2.5))],
        audio=[CompositionAudio("media/music.wav", "music", gain_db=-14, duck_under_speech=True,
                                id="music-1", asset_id="asset-music", role="music", duck_scope="all_speech")],
        fps=Rational(30, 1), loudness_target=LoudnessTarget(-16, -1),
        warnings=["Synthetic contract example: replace placeholder media/LUT hashes with inventory checksums."],
    )
    return composition, layout


def example_documents():
    composition, layout = talking_head_example()
    breakdown = Breakdown.from_json((ROOT / "tools/eval/sample/breakdown.json").read_text(encoding="utf-8"))
    recipe = build_style_recipe(breakdown, font_candidates=[FontCandidate(
        "Anton", ["Chosen bundled OFL font for the example; no glyph match was measured."], composition.captions[0].font,
    )], transition_recipes=[composition.transitions[0].recipe])
    try:
        lower_to_v1(composition)
    except ValueError as exc:
        failure = {"error": str(exc)}
    return {"talking-head.json": composition.to_dict(), "layout-plan.json": layout.to_dict(),
            "style-recipe.json": recipe.to_dict(), "lowering-failure.json": failure}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/examples/composition-v2")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, data in example_documents().items():
        payload = (json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        path = args.out / name
        if args.check:
            if not path.is_file() or path.read_bytes() != payload:
                parser.exit(1, f"Stale example: {path}. Run uv run python -m tools.composition_examples\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        print(path)


if __name__ == "__main__":
    main()
