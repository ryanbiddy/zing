"""Tool hints must describe the whole handler and survive both wire protocols."""
import asyncio
from pathlib import Path

import pytest

from mcp_wire import MODERN_VERSION, StdioClient, modern_params, rpc
from myzing import mcp_server, storage
from test_mcp_stdio import EXPECTED_TOOLS

pytest.importorskip("mcp", reason='mcp SDK not installed (pip install "myzing[mcp]")')

READ_ONLY = {
    "brief_questions", "factory_prompt", "factory_status", "get_frames", "get_profile",
    "get_prompt", "list_breakdowns", "list_presets", "list_profiles", "meme_check",
    "meme_ideas", "meme_templates", "music_check", "zing_moments",
}
OPEN_WORLD = {
    "factory_run", "match_start", "meme_render", "setup_taste", "study_uoink_item",
    "study_video", "zing_explain", "zing_studio_run",
}
HINTS = {
    "readOnlyHint": "read_only_hint", "destructiveHint": "destructive_hint",
    "idempotentHint": "idempotent_hint", "openWorldHint": "open_world_hint",
}


@pytest.fixture(scope="module")
def registered():
    return {tool.name: tool for tool in asyncio.run(mcp_server.build_server().list_tools())}


def test_every_registered_tool_has_explicit_hints(registered):
    assert set(registered) == EXPECTED_TOOLS == set(mcp_server._tool_annotations())
    for name, tool in registered.items():
        assert tool.annotations is not None, name
        assert all(type(getattr(tool.annotations, field)) is bool for field in HINTS.values()), name


def test_registration_requires_a_table_entry(monkeypatch):
    annotations = mcp_server._tool_annotations()
    del annotations["zing_status"]
    monkeypatch.setattr(mcp_server, "_tool_annotations", lambda: annotations)
    with pytest.raises(KeyError, match="zing_status"):
        mcp_server.build_server()


@pytest.fixture(scope="module", params=[False, True], ids=["legacy", "modern"])
def wire_tools(request, tmp_path_factory):
    with StdioClient(tmp_path_factory.mktemp("annotations"), fixture_inputs=False) as client:
        if request.param:
            result = client.exchange(rpc(1, "server/discover", modern_params()))["result"]
            assert result["supportedVersions"] == [MODERN_VERSION]
        else:
            result = client.exchange(rpc(1, "initialize", {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "zing-annotations-test", "version": "1"},
            }))["result"]
            assert result["protocolVersion"] == "2025-11-25"
            client.exchange({"jsonrpc": "2.0", "method": "notifications/initialized"})
        result = client.exchange(rpc(2, "tools/list", modern_params() if request.param else {}))
        return {tool["name"]: tool for tool in result["result"]["tools"]}


def test_annotations_survive_stdio(wire_tools, registered):
    assert set(wire_tools) == EXPECTED_TOOLS
    for name, tool in wire_tools.items():
        assert tool.get("annotations") == {
            key: getattr(registered[name].annotations, field) for key, field in HINTS.items()
        }, name


def test_known_read_only_set_over_stdio(wire_tools):
    assert {name for name, tool in wire_tools.items() if tool["annotations"]["readOnlyHint"]} == READ_ONLY


@pytest.mark.parametrize("name", [
    "factory_new", "render_edl", "meme_render", "push_to_uoink", "save_judgment",
    "zing_status", "get_breakdown", "get_render", "match_status", "zing_studio",
])
def test_writers_are_not_read_only(wire_tools, name):
    assert wire_tools[name]["annotations"]["readOnlyHint"] is False


def test_network_hints_over_stdio(wire_tools):
    assert {name for name, tool in wire_tools.items() if tool["annotations"]["openWorldHint"]} == OPEN_WORLD


def test_overwrites_and_additions(registered):
    for name in ("factory_new", "factory_clip", "factory_edit", "factory_answer", "render_edl",
                 "save_judgment", "brief_save", "meme_render", "meme_render_video", "generate_thumbnails"):
        assert registered[name].annotations.destructive_hint is True, name
    for name in ("import_shot_list", "push_to_uoink", "still_concepts", "zing_explain",
                 "zing_studio", "zing_status", "get_breakdown", "get_render", "match_status"):
        assert registered[name].annotations.destructive_hint is False, name


def test_repeat_effects(registered):
    for name in READ_ONLY | {"import_shot_list", "brief_save", "factory_answer", "export_otio"}:
        assert registered[name].annotations.idempotent_hint is True, name
    for name in ("study_video", "study_uoink_item", "factory_new", "factory_run", "factory_edit",
                 "factory_clip", "render_edl", "match_start", "zing_studio_run", "meme_render",
                 "meme_render_video", "push_to_uoink", "save_judgment", "build_profile", "setup_taste"):
        assert registered[name].annotations.idempotent_hint is False, name


@pytest.mark.parametrize("name", ["zing_status", "get_breakdown", "get_render", "match_status"])
def test_polling_can_write_stale_state(tmp_path, monkeypatch, name):
    monkeypatch.setenv("ZING_HOME", str(tmp_path))
    monkeypatch.setattr(mcp_server.doctor, "run_checks", lambda: [])
    if name == "match_status":
        directory, args = tmp_path / "match-job", (str(tmp_path),)
    elif name == "get_render":
        directory, args = storage.render_dir("stale"), ("stale",)
    else:
        directory = storage.breakdown_dir("stale")
        args = () if name == "zing_status" else ("stale",)
    storage.write_status_at(directory, state="running", pid=0)
    handler = getattr(mcp_server, "h_" + name)
    handler(*args)
    assert storage.read_status_at(directory)["state"] == "failed"
    saved = (directory / "status.json").read_bytes()
    handler(*args)
    assert (directory / "status.json").read_bytes() == saved


def test_connect_table_matches_hints(registered):
    text = (Path(__file__).resolve().parents[1] / "docs/CONNECT.md").read_text(encoding="utf-8")
    table = text.split("## Tool hints\n", 1)[1].split("\n## ", 1)[0]
    rows = [line.split("|")[1:-1] for line in table.splitlines() if line.startswith("| `")]
    assert {row[0].strip().strip("`") for row in rows} == EXPECTED_TOOLS
    for name, read_only, destructive, open_world in rows:
        hints = registered[name.strip().strip("`")].annotations
        assert [value.strip() for value in (read_only, destructive, open_world)] == [
            "yes" if value else "no" for value in
            (hints.read_only_hint, hints.destructive_hint, hints.open_world_hint)
        ]
