"""Voice, photo rights, sources and output measured from a story's local files."""
from __future__ import annotations

import json
from pathlib import Path

from . import StoryError
from .contract import load


def write(directory: Path, output: Path) -> Path:
    directory, output = Path(directory), Path(output)
    story = load(directory)
    timings = json.loads((directory / "timings.json").read_text(encoding="utf-8"))
    if not output.is_file():
        raise StoryError(f"cannot write a receipt: output file is missing: {output}")
    try:
        file = output.resolve().relative_to(directory.resolve()).as_posix()
    except ValueError:
        file = str(output.resolve())
    photos = [
        {"cast": who, "name": member["name"], "path": photo["path"],
         "credit": photo["credit"], "license": photo["license"], "source_url": photo["source_url"]}
        for who, member in story.get("cast", {}).items() for photo in member.get("photos", [])
    ]
    result = {"voice": {"provider": timings["provider"], "name": timings.get("voice"),
                        "synthetic": timings["provider"] != "lines" or timings.get("synthetic") is True},
              "photos": photos, "sources": story["sources"], "output": file, "duration": timings["duration"]}
    if story.get("images"):
        from .images import prepared_path

        result["images"] = [
            {"image_id": image_id, "path": picture["path"], "image": prepared_path(image_id, picture),
             "cut": picture.get("cut", "photo"), "credit": picture["credit"],
             "license": picture["license"], "source_url": picture["source_url"]}
            for image_id, picture in story["images"].items()
        ]
    if story.get("music"):
        result["music"] = dict(story["music"])
    path = directory / "story-receipt.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
