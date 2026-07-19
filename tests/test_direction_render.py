"""direction.md renderer (S3-B 2/3): creator order, honest fallbacks."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from myzing import direction, mcp_server, prompt_pack, storage
from myzing.schemas import Breakdown, VideoMeta

SLUG = "raw-take"


def contract_example() -> dict:
    """The worked example from the shipped prompt IS the render fixture —
    prompt, tool, and renderer can never drift apart."""
    _meta, text = prompt_pack.load_prompt("direct")
    return json.loads(
        re.search(
            r"<example_judgment>\s*(\{.*?\})\s*</example_judgment>", text, re.DOTALL
        ).group(1)
    )


@pytest.fixture
def real_pack(monkeypatch):
    monkeypatch.delenv(prompt_pack.PROMPTS_DIR_ENV, raising=False)


def test_renders_in_creator_order(real_pack):
    md = direction.render_direction(contract_example(), SLUG)
    works = md.index("## What already works")
    missing = md.index("## What's missing")
    film = md.index("## What to film")
    assert works < missing < film  # what works -> what's missing -> what to film
    assert "MUST FIX" in md
    assert "Keep 6.2s–41.8s" in md
    assert "Film a 3-second opener" in md


def test_severity_ordering_and_receipts(real_pack):
    md = direction.render_direction(contract_example(), SLUG)
    must = md.index("MUST FIX")
    polish = md.index("POLISH")
    assert must < polish
    # internal vocabulary stays in the collapsed receipts, out of the body
    body = md[: md.index("<details>")]
    assert "G-TH-1" not in body.replace("`G-TH-1`", "")  # only inside receipts
    assert "G-TH-1" in md[md.index("<details>"):]


def test_empty_judgment_renders_honestly():
    md = direction.render_direction({}, SLUG)
    assert "Nothing was marked keepable" in md
    assert "No gaps found" in md
    assert "Nothing to film" in md


def test_save_judgment_direct_writes_direction_md(real_pack, zing_workspace):
    storage.save_breakdown(
        Breakdown(meta=VideoMeta(source_url="raw.mp4", platform="file")),
        slug=SLUG,
    )
    result = mcp_server.h_save_judgment(
        SLUG, contract_example(), section="direct", model="test"
    )
    assert result["ok"] is True, result.get("error")
    md_path = Path(result["direction_md"])
    assert md_path.name == "direction.md"
    md = md_path.read_text(encoding="utf-8")
    assert "## What to film" in md
    assert "prompt 1.0.0" in md  # _meta stamp rendered


def test_render_failure_keeps_judgment_and_reports(real_pack, zing_workspace, monkeypatch):
    storage.save_breakdown(
        Breakdown(meta=VideoMeta(source_url="raw.mp4", platform="file")),
        slug=SLUG,
    )

    def explode(direct, slug):
        raise RuntimeError("renderer bug")

    monkeypatch.setattr(direction, "render_direction", explode)
    result = mcp_server.h_save_judgment(
        SLUG, contract_example(), section="direct", model="test"
    )
    assert result["ok"] is True  # the judgment itself saved
    assert "failed to render" in result["direction_md_error"]
    assert storage.load_breakdown(SLUG).judgment["direct"]["verdict"]


def test_non_direct_sections_do_not_render(real_pack, zing_workspace):
    storage.save_breakdown(
        Breakdown(meta=VideoMeta(source_url="https://youtu.be/x", platform="youtube")),
        slug="youtube-x",
    )
    result = mcp_server.h_save_judgment("youtube-x", {"anything": 1}, section="notes")
    assert result["ok"] is True
    assert "direction_md" not in result
    assert not (storage.breakdown_dir("youtube-x") / "direction.md").exists()