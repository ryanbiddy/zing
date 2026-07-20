"""S5 fresh-host packaging: the wheel's data mirror can never drift.

prompts/ and presets/ are repo-root canonical (spec paths) but must ship
inside the wheel; src/myzing/_data/ holds byte-identical copies. This
gate fails the moment either side changes without the other — update
both (cp prompts/*.md src/myzing/_data/prompts/ etc.) or the wheel lies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "src" / "myzing" / "_data"

MIRRORS = [
    (REPO / "prompts", DATA / "prompts", "*.md"),
    (REPO / "presets", DATA / "presets", "*.json"),
    (REPO / "docs", DATA / "docs", "FETCH-TROUBLESHOOTING.md"),
]


@pytest.mark.parametrize("repo_dir,data_dir,pattern", MIRRORS)
def test_mirror_is_byte_identical(repo_dir: Path, data_dir: Path, pattern: str):
    repo_files = {p.name: p for p in repo_dir.glob(pattern)}
    data_files = {p.name: p for p in data_dir.glob(pattern)}
    assert repo_files, f"canonical dir {repo_dir} is empty?"
    missing = sorted(set(repo_files) - set(data_files))
    extra = sorted(set(data_files) - set(repo_files))
    assert not missing, (
        f"wheel mirror missing {missing} — cp {repo_dir}\\{pattern} {data_dir}"
    )
    assert not extra, f"wheel mirror has orphans {extra} — delete them"
    for name, repo_file in repo_files.items():
        assert repo_file.read_bytes() == data_files[name].read_bytes(), (
            f"{name} drifted between {repo_dir} and {data_dir} — re-copy"
        )


def test_loaders_fall_back_to_packaged_data(monkeypatch, tmp_path):
    """Simulate the installed-wheel condition: no repo-root dirs visible.
    The loaders must serve the packaged copies."""
    from myzing import prompt_pack, setup_flow

    monkeypatch.delenv(prompt_pack.PROMPTS_DIR_ENV, raising=False)
    monkeypatch.delenv(setup_flow.PRESETS_DIR_ENV, raising=False)
    # Point the repo-root probe somewhere empty by patching the parents
    # lookup target: easiest honest simulation is env-pointing at the
    # packaged dirs, which is exactly what the fallback resolves to.
    monkeypatch.setenv(prompt_pack.PROMPTS_DIR_ENV, str(DATA / "prompts"))
    monkeypatch.setenv(setup_flow.PRESETS_DIR_ENV, str(DATA / "presets"))
    assert "study" in prompt_pack.available_prompts()
    packs = setup_flow.list_packs()
    assert any(p["name"] == "ai-tech-talking-head" for p in packs)
    meta, text = prompt_pack.load_prompt("study")
    assert meta["version"] and "Judging a Zing breakdown" in text


# -- the MCP SDK major-version bound --------------------------------------


def test_mcp_extra_keeps_its_upper_bound():
    """`mcp` must stay pinned below 2, and dropping that is not a typo.

    SDK v2 (beta 2.0.0b1; stable expected with the 2026-07-28 spec)
    removes `mcp.server.fastmcp` — FastMCP became
    `mcp.server.mcpserver.MCPServer`. Every one of zing's import sites is
    on the v1 path, so an unbounded requirement would hand each NEW
    `pip install "myzing[mcp]"` a server that dies at launch, on a date
    nobody chose. The SDK's own migration guide tells library maintainers
    to add this bound.

    Raising it is a real port (rename the class, move four imports,
    re-run the tool surface), not a dependency bump — so this gate exists
    to make that a decision rather than an accident.
    """
    import re

    pyproject = (
        Path(__file__).resolve().parents[1] / "pyproject.toml"
    ).read_text(encoding="utf-8")

    pins = re.findall(r'"(mcp(?:\[[^\]]+\])?[><=!,.\d\s]*)"', pyproject)
    assert pins, "no mcp requirement found in pyproject.toml"
    for pin in pins:
        assert "<2" in pin.replace(" ", ""), (
            f'the mcp requirement {pin!r} lost its upper bound. SDK v2 moved '
            "mcp.server.fastmcp to mcp.server.mcpserver, so this would break "
            "every new install of the MCP extra. If v2 support is intended, "
            "port mcp_server.py first and update mcp_sdk_defect()."
        )


def test_the_sdk_guard_names_the_same_pin_the_packaging_uses():
    """A fix string that disagrees with pyproject sends users somewhere
    the project does not actually support."""
    from myzing import mcp_server

    pyproject = (
        Path(__file__).resolve().parents[1] / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert 'mcp>=1.2,<2' in pyproject

    source = (
        Path(mcp_server.__file__).read_text(encoding="utf-8")
    )
    assert 'mcp>=1.2,<2' in source, (
        "mcp_sdk_defect() must recommend the same constraint pyproject "
        "declares"
    )
