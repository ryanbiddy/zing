"""Prompt pack: integrity of the shipped files, loader, and the CLI.

The pack defines the judgment contract (frontmatter required_keys) that
save_judgment enforces — so the pack's own worked example must satisfy it,
and the shipped files must keep parsing. These tests run against the REAL
repo prompts/, not fixtures: a broken pack is a broken product.
"""

from __future__ import annotations

import json
import re

import pytest

from myzing import mcp_server, prompt_pack, storage
from myzing.schemas import Breakdown, VideoMeta

STUDY_REQUIRED = {"hook", "beats", "caption_style", "why_it_works"}


@pytest.fixture
def real_pack(monkeypatch):
    monkeypatch.delenv(prompt_pack.PROMPTS_DIR_ENV, raising=False)


# -- shipped pack integrity --------------------------------------------------

def test_pack_ships_study_and_direct(real_pack):
    assert prompt_pack.available_prompts() == ["direct", "study"]


def test_study_frontmatter_contract(real_pack):
    meta, text = prompt_pack.load_prompt("study")
    assert meta["name"] == "study"
    assert re.fullmatch(r"\d+\.\d+\.\d+", meta["version"])
    assert set(meta["required_keys"]) == STUDY_REQUIRED
    assert meta["description"]
    assert len(text.splitlines()) < 500  # skills guidance: stay lean


def test_direct_is_an_honest_stub(real_pack):
    meta, text = prompt_pack.load_prompt("direct")
    assert "STUB" in meta["description"]
    assert "NOT IMPLEMENTED" in text


def test_study_example_judgment_satisfies_its_own_contract(real_pack):
    """The worked example inside study.md must parse as JSON and carry every
    required key — otherwise the prompt teaches a shape save_judgment
    rejects."""
    meta, text = prompt_pack.load_prompt("study")
    m = re.search(
        r"<example_judgment>\s*(\{.*?\})\s*</example_judgment>", text, re.DOTALL
    )
    assert m, "study.md lost its <example_judgment> block"
    example = json.loads(m.group(1))
    assert set(meta["required_keys"]) <= set(example)
    # the example must practice what the prompt preaches:
    assert example["hook"]["evidence"], "example hook has no evidence"
    keys = list(example["hook"])
    assert keys.index("evidence") < keys.index("type"), (
        "evidence must precede verdict fields in the example"
    )


def test_example_judgment_accepted_by_save_judgment(real_pack, zing_workspace):
    """End-to-end: the shape the prompt teaches is the shape the tool takes."""
    b = Breakdown(meta=VideoMeta(source_url="https://youtu.be/x", platform="youtube"))
    storage.save_breakdown(b, slug="youtube-x")
    _meta, text = prompt_pack.load_prompt("study")
    example = json.loads(
        re.search(
            r"<example_judgment>\s*(\{.*?\})\s*</example_judgment>", text, re.DOTALL
        ).group(1)
    )
    result = mcp_server.h_save_judgment("youtube-x", example, model="test")
    assert result["ok"] is True, result.get("error")
    assert result["prompt_version"] == _meta["version"]


def test_mcp_prompts_capability_serves_the_real_pack(real_pack):
    pytest.importorskip("mcp")
    server = mcp_server.build_server()
    import anyio

    prompts = anyio.run(server.list_prompts)
    assert {p.name for p in prompts} == {"direct", "study"}


# -- CLI ---------------------------------------------------------------------

def test_cli_prints_prompt(real_pack, capsys):
    assert prompt_pack.run(["study"]) == 0
    out = capsys.readouterr().out
    assert "cannot_judge" in out and "save_judgment" in out


def test_cli_unknown_name_lists_available(real_pack, capsys):
    assert prompt_pack.run(["nope"]) == 1
    out = capsys.readouterr().out
    assert "study" in out and "direct" in out


def test_cli_no_args_shows_usage(real_pack, capsys):
    assert prompt_pack.run([]) == 2
    assert "usage" in capsys.readouterr().out


def test_cli_routes_from_zing(real_pack, capsys):
    from myzing import cli

    assert cli.main(["prompt", "study"]) == 0
    assert "Judging a Zing breakdown" in capsys.readouterr().out


def test_missing_pack_dir_is_honest(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(prompt_pack.PROMPTS_DIR_ENV, str(tmp_path / "void"))
    assert prompt_pack.run(["study"]) == 1
    assert "no prompt pack found" in capsys.readouterr().out
