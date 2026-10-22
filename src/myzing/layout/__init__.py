"""Standalone face-aware caption planning; no model imports or downloads here."""

from .chooser import check_overlap, choose_layout
from .masks import platform_masks
from .tracking import build_tracks
from .types import (
    Box, CaptionEvent, Detection, EventLayout, FaceTrack, FrameDetections,
    Keyframe, LayoutPlan, Mask, OverlapCheck,
)

__all__ = [
    "Box", "CaptionEvent", "Detection", "EventLayout", "FaceTrack", "FrameDetections",
    "Keyframe", "LayoutPlan", "Mask", "OverlapCheck", "build_tracks", "check_overlap",
    "choose_layout", "platform_masks",
]
