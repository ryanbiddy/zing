from __future__ import annotations

import inspect

from myzing.render import command, otio_export, pipeline, tts


def test_render_exception_handlers_do_not_repeat_caught_subclasses() -> None:
    redundant_names = {
        command: ("json.JSONDecodeError", "UnicodeError"),
        otio_export: ("ModuleNotFoundError",),
        pipeline: ("json.JSONDecodeError",),
        tts: ("ModuleNotFoundError",),
    }
    assert [
        f"{module.__name__}:{name}"
        for module, names in redundant_names.items()
        for name in names
        if name in inspect.getsource(module)
    ] == []
