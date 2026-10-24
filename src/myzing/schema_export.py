"""Export the P4 dataclass shapes as local-reference JSON Schema 2020-12.

Relational checks (interval order, box sums, asset references, overlaps and
speed maps) remain in Python. No third-party import is needed to export.
"""

from __future__ import annotations

import types
from dataclasses import MISSING, fields, is_dataclass
from typing import Any, Literal, Union, get_args, get_origin

from myzing.contracts import hints


def _constraints(cls: type, properties: dict) -> None:
    name = cls.__name__
    for key in ("version", "schema_version"):
        if key in properties:
            properties[key] = {"type": "integer", "const": 2 if key == "schema_version" else 1}
    for key in ("sha256",):
        if key in properties:
            # Nullable identity is used only where old producers lack a hash.
            schema = properties[key]
            target = next((s for s in schema.get("anyOf", []) if s.get("type") == "string"), schema)
            target["pattern"] = "^[0-9a-f]{64}$"
    if name in {"Box", "Detection", "FaceTrack"}:
        for key in ("x", "y", "width", "height", "confidence"):
            if key in properties:
                properties[key].update(minimum=0, maximum=1)
        if name == "Box":
            for key in ("width", "height"):
                properties[key]["exclusiveMinimum"] = 0
    if name == "Rational":
        for key in ("numerator", "denominator"):
            properties[key]["minimum"] = 1
    if name == "Composition":
        for key in ("width", "height"):
            properties[key]["minimum"] = 1
    if name == "Brief":
        properties["caption_mode"]["enum"] = ["reference", "phone", "punch", "box", "clean", "none"]
        properties["picture_crop"]["enum"] = ["auto", "on", "off"]
        properties["framing"]["enum"] = ["auto", "fit", "fill", "reframe", "zoomfill", "blurfill"]
        properties["aspects"]["items"] = {"enum": ["16:9", "1:1", "9:16"]}
        properties["aspects"]["uniqueItems"] = True
        properties["framing_max_upscale"].update(minimum=1, maximum=16)
        properties["short_side"] = {"anyOf": [{"type": "integer", "minimum": 18, "maximum": 4320, "multipleOf": 18},
                                              {"const": "auto"}]}
    if name == "Framing":
        for key in ("source_width", "source_height", "width", "height"):
            properties[key]["minimum"] = 1
        properties["max_velocity"]["exclusiveMinimum"] = 0
        properties["max_upscale"]["minimum"] = 1
        properties["confidence"].update(minimum=0, maximum=1)
        properties["keyframes"]["maxItems"] = 256
        top = next(s for s in properties["foreground_top"]["anyOf"] if s.get("type") == "number")
        top.update(minimum=0, maximum=1)
    if name == "CropAssessment":
        for key in ("sharp_height_share", "sharp_area_share", "retained_area", "subject_coverage"):
            properties[key].update(minimum=0, maximum=1)
        properties["enlargement"]["exclusiveMinimum"] = 0
    if name in {"SpeechWord", "SpeakerTurn"}:
        properties["confidence"].update(minimum=0, maximum=1)
        properties["start"]["minimum"] = 0
        properties["end"]["exclusiveMinimum"] = 0
    if name in {"Framing", "CropKeyframe", "CropBounds"}:
        for key in ("time", "x", "y", "center_x", "center_y"):
            if key in properties:
                properties[key]["minimum"] = 0
    if name == "CropBounds":
        for key in ("width", "height"):
            properties[key]["exclusiveMinimum"] = 0
    if name in {"CompositionClip", "SourceRange", "SpeedSegment", "CompositionAudio"}:
        for key in ("src_in", "src_out", "timeline_start"):
            if key in properties:
                properties[key]["minimum"] = 0
    if name == "SpeedSegment":
        properties["rate"]["exclusiveMinimum"] = 0
    if name == "ColorTransform":
        properties["strength"].update(minimum=0, maximum=1)
    if name == "CaptionStyle":
        properties["size"].update(minimum=1, maximum=512)
        properties["outline_width"].update(minimum=0, maximum=20)
        for key in ("color", "highlight", "outline_color", "box_color", "highlight_box_color", "before_color", "after_color"):
            properties[key]["pattern"] = "^#[0-9a-fA-F]{6}$"
        for key in ("highlight_box_padding", "highlight_box_radius"):
            properties[key].update(minimum=0, maximum=64)
        properties["highlight_box_opacity"].update(minimum=0, maximum=1)
    if name in {"Word", "MeasuredFact", "TransitionEvidence", "Coverage", "Segment", "Tempo"}:
        for key in ("confidence", "fraction"):
            if key in properties:
                properties[key].update(minimum=0, maximum=1)
    if name == "Coverage":
        properties["samples"]["minimum"] = 0
    if name == "TransitionEvidence":
        properties["signature"]["enum"] = ["hard_cut", "dissolve", "wipe", "zoom_punch", "unknown"]
        properties["direction"]["enum"] = [None, "left", "right", "up", "down"]
        properties["detector_version"]["minimum"] = 1
    for key in ("id", "asset_id", "reference", "path", "license", "unit", "basis", "family", "reason"):
        if properties.get(key, {}).get("type") == "string":
            properties[key]["minLength"] = 1


def export_schema(root: type) -> dict:
    definitions = {}

    def shape(annotation):
        origin, args = get_origin(annotation), get_args(annotation)
        if annotation is Any:
            return {}
        if origin in (Union, types.UnionType):
            return {"anyOf": [shape(a) for a in args]}
        if origin is Literal:
            return {"enum": list(args)}
        if origin is list or annotation is list:
            return {"type": "array", "items": shape(args[0]) if args else {}}
        if origin is dict or annotation is dict:
            return {"type": "object", "additionalProperties": shape(args[1]) if args else {}}
        if is_dataclass(annotation):
            key = annotation.__module__.replace(".", "_") + "_" + annotation.__name__
            if key not in definitions:
                definitions[key] = {}  # Reserve before descending.
                properties = {f.name: shape(hints(annotation)[f.name]) for f in fields(annotation)}
                _constraints(annotation, properties)
                required = [f.name for f in fields(annotation)
                            if (f.default is MISSING and f.default_factory is MISSING)
                            or f.name in ("version", "schema_version")]
                definitions[key] = {"type": "object", "properties": properties,
                                    "required": required, "additionalProperties": False}
                if annotation.__name__ == "Transition":
                    handle = properties["outgoing_handle"]["anyOf"][0]
                    definitions[key]["allOf"] = [{
                        "if": {"properties": {"recipe": {"properties": {"kind": {"enum": ["dissolve", "wipe", "zoom_punch", "dip_to_black", "dip_to_white"]}},
                                                         "required": ["kind"]}}, "required": ["recipe"]},
                        "then": {"required": ["outgoing_handle", "incoming_handle"],
                                 "properties": {"outgoing_handle": handle, "incoming_handle": handle}},
                    }]
            return {"$ref": "#/$defs/" + key}
        return {"type": {str: "string", int: "integer", float: "number", bool: "boolean", type(None): "null"}[annotation]}

    ref = shape(root)["$ref"].rsplit("/", 1)[1]
    document = definitions.pop(ref)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:myzing:" + ("composition:2" if root.__name__ == "Composition" else "style-recipe:1"),
        "title": root.__name__,
        "description": "Structural contract. Apply Python validation for cross-field time, geometry and reference constraints.",
        **document, "$defs": definitions,
    }


def schemas() -> dict[str, dict]:
    from myzing.composition import Composition
    from myzing.style_recipe import StyleRecipe

    return {"composition-v2.schema.json": export_schema(Composition),
            "style-recipe-v1.schema.json": export_schema(StyleRecipe)}
