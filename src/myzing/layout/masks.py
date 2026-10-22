"""Approximate vertical-video UI exclusions, not platform specifications."""

from .types import Box, Mask


def platform_masks(platform: str, custom: list[Mask] | None = None) -> list[Mask]:
    if platform == "custom":
        if custom is None:
            raise ValueError("custom platform requires explicit masks (an empty list is allowed)")
        return list(custom)
    if custom is not None:
        raise ValueError("custom masks require platform='custom'")
    if platform == "none":
        return []
    # Tune for the target device, locale, UI state and actual publishing preview.
    presets = {
        "tiktok": (0.12, 0.78, 0.86, 0.28),
        "reels": (0.10, 0.80, 0.87, 0.32),
        "shorts": (0.10, 0.80, 0.86, 0.30),
    }
    if platform not in presets:
        raise ValueError(f"unknown platform: {platform}")
    top, bottom, rail, rail_top = presets[platform]
    return [Mask("top-bar", Box(0, 0, 1, top)),
            Mask("bottom-description", Box(0, bottom, 1, 1 - bottom)),
            Mask("right-action-rail", Box(rail, rail_top, 1 - rail, bottom - rail_top))]
