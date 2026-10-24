"""Place text with the layout package; reserve an external bar on conflicts."""

from __future__ import annotations

from myzing.layout.chooser import check_overlap, choose_layout
from myzing.layout.types import Box, CaptionEvent, FaceTrack, Keyframe, Mask
from myzing.memes import MemeError
from myzing.memes.framing import focus_box, resolve
from myzing.memes.render import Rect, caption_bar, fit_rect, normalized_regions, output_size, text_layers
from myzing.memes.subject import protected_regions
from .models import Photo

LAYOUTS = ("auto", "classic", "caption", "labels")
FIT_REQUESTS = ("auto", "fill", "blur", "contain", "cover")


def _bar(layout: str, texts: list[str] | None, size: tuple[int, int]) -> int:
    if layout != "caption":
        return 0
    # The caption bar fits its text; without texts use the 26% maximum.
    return caption_bar(texts, size) if texts else round(size[1] * .26)


def frame(photo: Photo, aspect: str, layout: str, fit: str = "contain",
          size: tuple[int, int] | None = None,
          texts: list[str] | None = None) -> tuple[str, list[float] | None, list[str]]:
    """Resolve the photo's framing for this layout's image viewport.

    ``auto`` fills the frame when the crop keeps every prominent face (or
    the estimated subject, keeping most of the photo) and blur-fills otherwise.
    """
    w, h = size or output_size(aspect, (photo.width, photo.height))
    bar = _bar(layout, texts, (w, h))
    focus, basis = focus_box([[f["x"], f["y"], f["width"], f["height"]] for f in photo.faces],
                             photo.face_method, photo.subject)
    if photo.detections and basis != "no_detector":
        from myzing.memes.framing import union
        boxes = [[d["box"][n] for n in ("x", "y", "width", "height")] for d in photo.detections]
        focus, basis = union(([focus] if focus else []) + boxes), "subject"
    return resolve(fit, (photo.width, photo.height), (w, h - bar), focus, basis)


def protected_boxes(photo: Photo, protect: list[list[float]] | None = None) -> list[Box]:
    """Faces (or the center heuristic), the subject estimate, and user boxes."""
    if photo.face_method == "center_heuristic" and photo.subject_estimate is None and not protect and not photo.detections:
        return [Box(.2, .2, .6, .6)]
    if photo.face_method != "center_heuristic" and photo.subject_estimate is None and not protect and not photo.detections:
        return [Box.from_dict(face).pad(.025) for face in photo.faces]
    faces = [[f["x"], f["y"], f["width"], f["height"]] for f in photo.faces]
    return [Box(*region["box"]) for region in
            protected_regions(faces, photo.face_method, photo.subject_estimate, protect, photo.detections)]


def output_faces(photo: Photo, aspect: str, layout: str,
                 size: tuple[int, int] | None = None, fit: str = "contain",
                 focus: list[float] | None = None, texts: list[str] | None = None,
                 protect: list[list[float]] | None = None) -> list[Box]:
    """Protected boxes in output coordinates, clipped to the visible image."""
    w, h = size or output_size(aspect, (photo.width, photo.height))
    bar = _bar(layout, texts, (w, h))
    rect = fit_rect((photo.width, photo.height), Rect(0, bar, w, h - bar), fit, focus)
    boxes = []
    for b in protected_boxes(photo, protect):
        left, top = max(rect.x + b.x * rect.width, 0), max(rect.y + b.y * rect.height, bar)
        right = min(rect.x + b.right * rect.width, w)
        bottom = min(rect.y + b.bottom * rect.height, h)
        if right > left and bottom > top:  # a crop can remove background faces
            boxes.append(Box(left / w, top / h, (right - left) / w, (bottom - top) / h))
    return boxes


def _tracks(boxes: list[Box]) -> list[FaceTrack]:
    return [FaceTrack(str(i), [Keyframe(0, b), Keyframe(1, b)]) for i, b in enumerate(boxes)]


def safe_geometry(photo: Photo, texts: list[str], aspect: str, layout: str,
                  regions: list[list[float]] | None, *, size: tuple[int, int] | None = None,
                  fit: str = "contain", focus: list[float] | None = None,
                  protect: list[list[float]] | None = None) -> bool:
    """Text boxes avoid protected boxes for this framing. ``fit`` is either a
    resolved fit (with its focus) or a request such as ``auto`` to resolve."""
    size = size or output_size(aspect, (photo.width, photo.height))
    try:
        if fit not in ("contain", "cover", "fill", "blur") or (fit == "fill" and focus is None):
            fit, focus, _ = frame(photo, aspect, layout, fit, size, texts)
        # The same fonts the renderer uses: box sizes follow the text.
        _, layers = text_layers(texts, source_size=(photo.width, photo.height), size=size,
                               layout=layout, fit=fit, font="sans" if layout == "caption" else "anton",
                               regions=regions, focus=focus)
    except MemeError:
        return False
    tracks = _tracks(output_faces(photo, aspect, layout, size, fit, focus, texts, protect))
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
          regions: list[list[float]] | None = None,
          fit: str = "contain",
          protect: list[list[float]] | None = None) -> tuple[str, list[list[float]] | None, list[str]]:
    """Choose a layout whose text avoids protected areas under ``fit``
    (resolved per layout with :func:`frame`)."""
    if fit not in FIT_REQUESTS:
        raise MemeError("fit must be auto, fill, blur, contain, or cover")
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
        tracks, masks, planned = _tracks(protected_boxes(photo, protect)), [], []
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
        if len(planned) == len(texts) and safe_geometry(photo, texts, aspect, chosen, planned, fit=fit,
                                                         protect=protect):
            if regions is not None and planned != regions:
                notes.append("Label regions moved to avoid protected areas and other text.")
            return chosen, planned, notes
    elif safe_geometry(photo, texts, aspect, chosen, None, fit=fit, protect=protect):
        return chosen, None, notes
    if len(texts) > 3:
        raise MemeError("No safe label placement found; use at most three beats for an external caption bar.")
    kinds = []
    if photo.detections:
        kinds.append("detected " + ", ".join(sorted({d["class_name"] for d in photo.detections})))
    if photo.faces or photo.face_method == "center_heuristic":
        kinds.append("faces" if photo.face_method != "center_heuristic" else "the central-60% face heuristic")
    if photo.subject_estimate is not None and any(
            r["kind"] == "subject_estimate" for r in protected_regions(
                [[f["x"], f["y"], f["width"], f["height"]] for f in photo.faces],
                photo.face_method, photo.subject_estimate)):
        kinds.append("the estimated subject")
    if protect:
        kinds.append("your protect boxes")
    notes.append(f"{chosen} placement was blocked; using a separate caption bar to keep text off protected areas"
                 + (f" ({', '.join(kinds)})." if kinds else "."))
    return "caption", None, notes
