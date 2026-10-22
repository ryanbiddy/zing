"""Strict stdlib JSON codec shared by the new, versioned P4 contracts.

Legacy schemas deliberately keep their own serializer and field order.
"""

from __future__ import annotations

import json
import math
import types
from dataclasses import fields, is_dataclass
from functools import lru_cache
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints


@lru_cache(maxsize=None)
def hints(cls: type) -> dict:
    return get_type_hints(cls)


def json_value(value: Any, path: str = "value") -> Any:
    """Copy JSON data without coercion; reject NaN even in free-form evidence."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return value
    if isinstance(value, list):
        return [json_value(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return {k: json_value(v, f"{path}.{k}") for k, v in value.items()}
    raise ValueError(f"{path} must contain only JSON values and string object keys")


def typed(value: Any, annotation: Any, path: str, *, decode: bool = False) -> Any:
    """Read/check the declared shape, including reused dataclasses and Word."""
    origin, args = get_origin(annotation), get_args(annotation)
    if annotation is Any:
        return json_value(value, path)
    if origin in (Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        choices = [a for a in args if a is not type(None)]
        if len(choices) == 1:
            return typed(value, choices[0], path, decode=decode)
        for choice in choices:
            try:
                return typed(value, choice, path, decode=decode)
            except ValueError:
                pass
        raise ValueError(f"{path} does not match any allowed type")
    if origin is Literal:
        if any(type(value) is type(v) and value == v for v in args):
            return value
        raise ValueError(f"{path} must be one of {args!r}; got {value!r}")
    if origin is list or annotation is list:
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        return [typed(v, args[0] if args else Any, f"{path}[{i}]", decode=decode)
                for i, v in enumerate(value)]
    if origin is dict or annotation is dict:
        if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
            raise ValueError(f"{path} must be an object with string keys")
        return {k: typed(v, args[1] if args else Any, f"{path}.{k}", decode=decode)
                for k, v in value.items()}
    if is_dataclass(annotation):
        if decode:
            if not isinstance(value, dict):
                raise ValueError(f"{path} must be an object")
            declared = {f.name for f in fields(annotation)}
            extra = set(value) - declared
            if extra:
                raise ValueError(f"{path}: unsupported fields {sorted(extra)}")
            for key in ("version", "schema_version"):
                if key in declared:
                    expected = 2 if key == "schema_version" else 1
                    if type(value.get(key)) is not int or value[key] != expected:
                        raise ValueError(f"unsupported {path}.{key}; expected {expected}")
            values = {k: typed(v, hints(annotation)[k], f"{path}.{k}", decode=True)
                      for k, v in value.items()}
            try:
                return annotation(**values)
            except TypeError as exc:
                raise ValueError(f"invalid {path}: {exc}") from exc
        if not isinstance(value, annotation):
            raise ValueError(f"{path} must be a {annotation.__name__}")
        for f in fields(annotation):
            typed(getattr(value, f.name), hints(annotation)[f.name], f"{path}.{f.name}")
            if f.name in ("version", "schema_version"):
                expected = 2 if f.name == "schema_version" else 1
                if getattr(value, f.name) != expected:
                    raise ValueError(f"unsupported {path}.{f.name}; expected {expected}")
        return value
    valid = (type(value) in (int, float) if annotation is float
             else type(value) is annotation)
    if not valid:
        raise ValueError(f"{path} must be {getattr(annotation, '__name__', annotation)}")
    return json_value(value, path)


def encode(value: Any) -> Any:
    if is_dataclass(value):
        typed(value, type(value), type(value).__name__)
        post = getattr(value, "__post_init__", None)
        if post:
            post()
        return {f.name: encode(getattr(value, f.name)) for f in fields(value)
                if not (f.name == "timing" and getattr(value, f.name) is None)}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    return json_value(value)


class Record:
    def __post_init__(self) -> None:
        typed(self, type(self), type(self).__name__)

    def to_dict(self) -> dict[str, Any]:
        return encode(self)

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False,
                          sort_keys=True, indent=indent,
                          separators=(",", ":") if indent is None else None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        return typed(data, cls, cls.__name__, decode=True)

    @classmethod
    def from_json(cls, value: str):
        return cls.from_dict(json.loads(value))


def nonempty(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must be nonempty")


def digest(value: str | None, name: str) -> None:
    if value is not None and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError(f"{name} must be a lowercase SHA-256 (64 hex digits)")


def interval(start: float, end: float, name: str) -> None:
    if not 0 <= start < end:
        raise ValueError(f"{name} requires 0 <= start < end")


def bounded(value: float, low: float, high: float, name: str) -> None:
    if not low <= value <= high:
        raise ValueError(f"{name} must be in [{low}, {high}]")
