"""Retain the exact output-coordinate obstacles used for each caption."""


def is_face(track):
    return not track.id.startswith(("person-", "object-", "saliency-")) and not any(
        o.class_name == "person" for o in track.observations)


def remember(context, caption, tracks, masks):
    if context is not None:
        context[caption.id] = {"tracks": [t.to_dict() for t in tracks],
                               "masks": [m.to_dict() for m in masks]}


def restore(context, caption):
    from .types import FaceTrack, Mask
    row = (context or {}).get(caption.id)
    if row is None or "tracks" not in row or "masks" not in row:
        return {"obstacles": None}
    return {"obstacles": [FaceTrack.from_dict(t) for t in row["tracks"]],
            "masks": [Mask.from_dict(m) for m in row["masks"]]}
