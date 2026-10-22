"""Versioned composition contracts and explicit, loss-checked v1 migration."""

from .compatibility import audio_from_map, load_composition, lower_to_v1, lowering_blockers, upgrade_edl
from .models import (
    AssetRef, CaptionStyle, ColorTransform, Composition, CompositionAudio,
    CompositionCaption, CompositionClip, FontAsset, LoudnessTarget, SourceRange,
    SpeedSegment, Transition, TransitionRecipe,
)
from .timebase import frame_index, frame_time
from .framing import CropBounds, CropKeyframe, Framing

__all__ = [
    "AssetRef", "CaptionStyle", "ColorTransform", "Composition", "CompositionAudio",
    "CompositionCaption", "CompositionClip", "FontAsset", "LoudnessTarget", "SourceRange",
    "SpeedSegment", "Transition", "TransitionRecipe", "audio_from_map", "load_composition",
    "lower_to_v1", "lowering_blockers", "upgrade_edl", "frame_index", "frame_time",
    "CropBounds", "CropKeyframe", "Framing",
]
