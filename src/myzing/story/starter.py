"""Create an editable draft with a source placeholder that blocks rendering."""
from __future__ import annotations

import json
from pathlib import Path

from . import StoryError
from .contract import PLACEHOLDER_SOURCE_URL, check


def new(directory: Path, *, topic: str) -> dict:
    directory = Path(directory)
    story = {
        "schema_version": 1, "topic": topic, "captions": True, "sfx": True,
        "cast": {"mira": {"name": "Mira Paper"}},
        "sources": [{"title": "Replace this source", "url": PLACEHOLDER_SOURCE_URL}],
        "beats": [{"id": ident, "chapter": chapter, "lines": [{"text": text}]}
                  for ident, chapter, text in (
                      ("hook", "DRAFT", "This draft needs a first fact from your sources."),
                      ("problem", "THE PROBLEM", "Explain what happened and why it mattered."),
                      ("turn", "THE TURN", "Add the detail that changes the story."),
                      ("end", "THE END", "End with a fact worth remembering."))],
        "panels": [{"from": "hook", "set": {"wall": "#FFD21F", "floor": "#17161C"},
                    "actors": [{"who": "mira", "x": 320, "pose": "present"}],
                    "cards": [{"kind": "note", "text": "Replace this draft", "x": 80, "y": 220, "at": "hook"}]}],
    }
    errors = [error for error in check(story) if not error.startswith("sources[0]: replace this source")]
    if errors:
        raise StoryError("\n".join(errors))
    targets = [directory / "story.json", directory / "README-STORY.txt"]
    if any(path.exists() for path in targets):
        raise StoryError("story.json or README-STORY.txt already exists; choose a new story folder.")
    directory.mkdir(parents=True, exist_ok=True)
    readme = """This is an editable draft, with an invented cast and no photos.
Replace the draft lines and the source placeholder with facts you have checked.
Zing makes no model calls. Your agent writes and checks the story.

From this folder, run:
  zing story prompt
  zing story check . --json
  zing story voice .
  zing story heads . --sheet
  zing story render . --stills 1,2,3
  zing story build .

To use recordings, add --lines-dir ./lines to voice or build.
Keep cards and puppet heads clear of the caption band, y=1560..1720.
Build refuses the source placeholder. Review stills and listen before posting.
"""
    with targets[0].open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(story, indent=2, ensure_ascii=False) + "\n")
    with targets[1].open("x", encoding="utf-8") as stream:
        stream.write(readme)
    return {"story": str(targets[0]), "readme": str(targets[1])}
