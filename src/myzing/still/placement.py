"""Place text with the layout package; reserve an external bar on conflicts."""

from __future__ import annotations

from myzing.layout.chooser import check_overlap, choose_layout
from myzing.layout.types import Box, CaptionEvent, FaceTrack, Keyframe, Mask
from myzing.memes import MemeError
from myzing.memes.render import Rect, fit_rect, normalized_regions, output_size, text_layers
from .models import Photo

LAYOUTS = ("auto", "classic", "caption", "labels")


def protected_boxes(photo: Photo) -> list[Box]:
    if photo.face_method == "center_heuristic":
        return [Box(.2, .2, .6, .6)]
    return [Box.from_dict(face).pad(.025) for face in photo.faces]


def output_faces(photo: Photo, aspect: str, layout: str,
                 size: tuple[int, int] | None = None) -> list[Box]:
    w, h = size or output_size(aspect, (photo.width, photo.height))
    bar = round(h * .26) if layout == "caption" else 0
    frame = fit_rect((photo.width, photo.height), Rect(0, bar, w, h - bar), "contain")
    return [Box((frame.x + b.x * frame.width) / w, (frame.y + b.y * frame.height) / h,
                b.width * frame.width / w, b.height * frame.height / h) for b in protected_boxes(photo)]


def _tracks(boxes: list[Box]) -> list[FaceTrack]:
    return [FaceTrack(str(i), [Keyframe(0, b), Keyframe(1, b)]) for i, b in enumerate(boxes)]


def safe_geometry(photo: Photo, texts: list[str], aspect: str, layout: str,
                  regions: list[list[float]] | None, *, size: tuple[int, int] | None = None) -> bool:
    size = size or output_size(aspect, (photo.width, photo.height))
    try:
        _, layers = text_layers(texts, source_size=(photo.width, photo.height), size=size,
                               layout=layout, fit="contain", font="sans", regions=regions)
    except MemeError:
        return False
    tracks = _tracks(output_faces(photo, aspect, layout, size))
    masks = []
    for layer in layers:
        if not layer.text:
            continue
        r = layer.box
        box = Box(r.x / size[0], r.y / size[1], r.width / size[0], r.height / size[1])
        if not check_overlap([Keyframe(0, box), Keyframe(1, box)], tracks, masks).safe:
            return False
        masks.append(Mask(str(len(masks)), box))
    return True


def place(photo: Photo, texts: list[str], aspect: str, requested: str = "auto",
          regions: list[list[float]] | None = None) -> tuple[str, list[list[float]] | None, list[str]]:
    if requested not in LAYOUTS:
        raise MemeError("layout must be auto, classic, caption, or labels")
    if regions is not None:
        normalized_regions(regions)
        if len(regions) != len(texts):
            raise MemeError("Provide one region per text box, including empty boxes.")
        if requested not in ("auto", "labels"):
            raise MemeError("Custom/template regions require auto or labels layout.")
    chosen = requested
    if chosen == "auto":
        chosen = ("labels" if regions is not None or len(texts) > 3 else
                  "caption" if len(texts) > 2 or photo.edge_density > .12 or photo.band_density > .10
                  else "classic")
    notes = []
    if chosen == "labels":
        desired = normalized_regions(regions) if regions else [
            Rect(.05, .04 + i * .86 / len(texts), .9, .23) for i in range(len(texts))]
        tracks, masks, planned = _tracks(protected_boxes(photo)), [], []
        for i, region in enumerate(desired):
            event = CaptionEvent(str(i), 0, 1, region.width, region.height,
                                 [region.x + region.width / 2, region.y + region.height / 2])
            result = choose_layout([event], tracks, masks, allow_motion=False, shrink_scales=()).events[0]
            if not result.overlap.safe:
                break
            b = result.box
            planned.append([b.x, b.y, b.width, b.height])
            if texts[i]:
                masks.append(Mask(str(i), b))
        if len(planned) == len(texts) and safe_geometry(photo, texts, aspect, chosen, planned):
            if regions is not None and planned != regions:
                notes.append("Label regions moved to avoid protected areas and other text.")
            return chosen, planned, notes
    elif safe_geometry(photo, texts, aspect, chosen, None):
        return chosen, None, notes
    if len(texts) > 3:
        raise MemeError("No safe label placement found; use at most three beats for an external caption bar.")
    notes.append(f"{chosen} placement was blocked; using a separate caption bar to keep text off protected areas.")
    return "caption", None, notes
