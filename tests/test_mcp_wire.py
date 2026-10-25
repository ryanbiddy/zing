"""Compare product wire bytes to the pre-port SDK 1 capture."""
import copy
import difflib
import hashlib
import json

import pytest

from mcp_wire import (
    FIXTURES, LEGACY_VERSIONS, MODERN_VERSION, StdioClient, canonical,
    modern_params, normalize, rpc,
)

pytest.importorskip("mcp", reason='install "myzing[mcp]" for wire tests')
GOLDEN = json.loads((FIXTURES / "sdk1.json").read_text(encoding="utf-8"))["exchanges"]

COPY1 = json.loads((FIXTURES / "copy1.json").read_text(encoding="utf-8"))

def without_protect(tool):
    """POLISH1 added an optional protect argument (and one description
    sentence) to still_concepts and meme_render; compare everything else."""
    from myzing.mcp_server import PROTECT_DESCRIPTIONS

    if tool["name"] not in PROTECT_DESCRIPTIONS:
        return tool
    tool = copy.deepcopy(tool)
    assert PROTECT_DESCRIPTIONS[tool["name"]] in tool["description"]
    tool["description"] = tool["description"].replace(PROTECT_DESCRIPTIONS[tool["name"]], "")
    assert "protect" in tool["inputSchema"]["properties"]
    del tool["inputSchema"]["properties"]["protect"]
    return tool


def assert_wire(actual, expected):
    # The SDK1 capture is immutable historical evidence. MUSIC1/CARD1 add tools;
    # continue comparing every original tool byte, and test the addition via
    # the current registry/stdio pins and test_music.py. POLISH1's protect
    # argument is stripped the same way and tested in test_meme_protect.py.
    # REL1 adds the distribution version to prompt frontmatter. The individual
    # prompt contract/version stays byte-identical to the SDK1 evidence.
    # Release parity is checked separately in test_release_packaging.py.
    from myzing import __version__

    def without_release_stamp(value):
        if isinstance(value, str):
            return value.replace(f"release_version: {__version__}\n", "").replace(
                f"release_version: {__version__}\\n", "")
        if isinstance(value, list):
            return [without_release_stamp(item) for item in value]
        if isinstance(value, dict):
            return {key: without_release_stamp(item) for key, item in value.items()}
        return value

    actual = without_release_stamp(copy.deepcopy(actual))
    if isinstance(actual, dict) and isinstance(actual.get("result"), dict) and "tools" in actual["result"]:
        actual["result"]["tools"] = [without_protect(t) for t in actual["result"]["tools"]
                                     if t["name"] not in {"music_check", "zing_explain", "zing_studio", "zing_studio_run"}]
        for tool in actual["result"]["tools"]:
            if tool["name"] in {"study_video", "study_uoink_item", "match_start"}:
                # DOGFOOD2 adds optional reference trims. Preserve the historical
                # schema and pin the new fields' optional/default behavior.
                for name in ("ref_start", "ref_end", "reference_range"):
                    option = tool["inputSchema"]["properties"].pop(name)
                    assert option["default"] is None
                    assert name not in tool["inputSchema"].get("required", [])
                    assert {part["type"] for part in option["anyOf"]} == (
                        {"string", "null"} if name == "reference_range" else {"string", "number", "null"})
            if tool["name"] == "match_start":
                # STUDIO1 adds an optional adapter argument. The historical
                # input fields and their required/default behavior stay pinned.
                option = tool["inputSchema"]["properties"].pop("studio_options")
                assert option["default"] is None
                assert "studio_options" not in tool["inputSchema"].get("required", [])
    # COPY1 changes only these reviewed copy fields. Pin their new values
    # exactly; preserve SDK1 as historical evidence and diff every other byte.
    expected = copy.deepcopy(expected)
    if isinstance(expected, dict) and isinstance(expected.get("result"), dict):
        result = expected["result"]
        if "instructions" in result:
            result["instructions"] = COPY1["instructions"]
        for tool in result.get("tools", []):
            if tool["name"] in COPY1["tool_descriptions"]:
                tool["description"] = COPY1["tool_descriptions"][tool["name"]]
        payload = result.get("structuredContent", {})
        if payload.get("state") == "absent" and "missing-wire-fixture" in payload.get("error", ""):
            payload["error"] = COPY1["missing_breakdown_error"]
            text_payload = json.loads(result["content"][0]["text"])
            text_payload["error"] = COPY1["missing_breakdown_error"]
            result["content"][0]["text"] = json.dumps(text_payload, indent=2)
    actual, expected = canonical(actual), canonical(expected)
    assert actual == expected, "".join(difflib.unified_diff(
        expected.splitlines(True), actual.splitlines(True),
        fromfile="SDK 1 fixture", tofile="SDK 2 wire",
    ))


def legacy_expected(exchange, version):
    expected = copy.deepcopy(exchange["response"])
    if exchange["request"]["method"] == "initialize":
        expected["result"]["protocolVersion"] = version
        # SDK 2's native runner omits an absent experimental capability.
        assert expected["result"]["capabilities"].pop("experimental") == {}
    return expected


def test_sdk1_fixture_provenance():
    assert hashlib.sha256((FIXTURES / "sdk1.json").read_bytes()).hexdigest() == (
        "930e1f8711a27c8561a6ad4f92e26d74dfbea9915f967381163d49b193b1329d"
    )
    from test_mcp_stdio import EXPECTED_TOOLS
    tools = GOLDEN[2]["response"]["result"]["tools"]
    assert len(tools) == 32
    assert {tool["name"] for tool in tools} == EXPECTED_TOOLS - {"music_check", "zing_explain", "zing_studio", "zing_studio_run"}
    assert len(GOLDEN[3]["response"]["result"]["prompts"]) == 5


@pytest.mark.parametrize("version", LEGACY_VERSIONS)
def test_legacy_wire_fixture(tmp_path, version):
    with StdioClient(tmp_path) as client:
        for exchange in GOLDEN:
            request = copy.deepcopy(exchange["request"])
            if request["method"] == "initialize":
                request["params"]["protocolVersion"] = version
            response = client.exchange(request)
            actual = normalize(request, response, client.env) if response is not None else None
            assert_wire(actual, legacy_expected(exchange, version))


@pytest.mark.parametrize("opening", ["server/discover", "tools/list", "tools/call"])
def test_modern_handshake_and_wire_fixture(tmp_path, opening):
    from myzing import __version__

    with StdioClient(tmp_path) as client:
        init = legacy_expected(GOLDEN[0], LEGACY_VERSIONS[-1])["result"]
        first = {
            "server/discover": ({}, {"capabilities": init["capabilities"],
                                    "instructions": init["instructions"],
                                    "supportedVersions": [MODERN_VERSION]}),
            "tools/list": ({}, GOLDEN[2]["response"]["result"]),
            "tools/call": (GOLDEN[7]["request"]["params"], GOLDEN[7]["response"]["result"]),
        }[opening]
        cases = [(rpc(100, opening, first[0]), first[1])]
        cases += [(row["request"], row["response"]["result"]) for row in GOLDEN[2:]]
        for request, payload in cases:
            request = copy.deepcopy(request)
            request["params"] = modern_params(**request.get("params", {}))
            expected = copy.deepcopy(payload)
            expected.update(resultType="complete", _meta={
                "io.modelcontextprotocol/serverInfo": {"name": "zing", "version": __version__},
            })
            if request["method"] in {
                "server/discover", "tools/list", "prompts/list",
                "resources/list", "resources/templates/list",
            }:
                expected.update(ttlMs=0, cacheScope="private")
            actual = normalize(request, client.exchange(request), client.env)
            assert_wire(actual, {"jsonrpc": "2.0", "id": request["id"], "result": expected})


@pytest.mark.parametrize("modern", [False, True])
def test_real_entry_point_and_version_refusal(tmp_path, modern):
    """No injected doctor inputs here: launch the installed production CLI."""
    with StdioClient(tmp_path, fixture_inputs=False) as client:
        if not modern:
            request = copy.deepcopy(GOLDEN[0]["request"])
            # initialize always selects legacy, even with a modern version.
            request["params"]["protocolVersion"] = MODERN_VERSION
            result = client.exchange(request)["result"]
            assert result["protocolVersion"] == "2025-11-25"
            client.exchange(GOLDEN[1]["request"])
        else:
            result = client.exchange(rpc(1, "server/discover", modern_params()))["result"]
            assert result["supportedVersions"] == [MODERN_VERSION]
            bad = modern_params()
            bad["_meta"]["io.modelcontextprotocol/protocolVersion"] = "2099-01-01"
            error = client.exchange(rpc(2, "tools/list", bad))["error"]
            assert error["code"] == -32022
        params = {"name": "zing_status", "arguments": {}}
        result = client.exchange(rpc(3, "tools/call", modern_params(**params) if modern else params))["result"]
        payload = json.loads(result["content"][0]["text"])
        assert payload["ok"] and payload["workspace"]["breakdowns"] == 0
        assert result["structuredContent"] == payload
        checks = payload["environment"]["checks"]
        assert any(check["name"] == "uoink" and not check["ok"] for check in checks)


@pytest.mark.parametrize("field", ["instructions", "capabilities", "extra"])
def test_copy1_replay_rejects_unreviewed_changes(field):
    expected = legacy_expected(GOLDEN[0], LEGACY_VERSIONS[-1])
    actual = copy.deepcopy(expected)
    actual["result"]["instructions"] = COPY1["instructions"]
    assert_wire(actual, expected)
    actual["result"][field] = "unreviewed drift"
    with pytest.raises(AssertionError):
        assert_wire(actual, expected)
