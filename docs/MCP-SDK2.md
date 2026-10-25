# MCP SDK 2

Zing now uses the official Python `mcp>=2.3,<3` extra, locked to 2.3.0.
`MCPServer` replaces `FastMCP`; image and prompt helpers use the new module
paths. The public `version` argument supplies Zing's version. Subscriptions
are disabled because Zing has no subscription handlers. The native SDK runner
handles stdio; Zing adds no HTTP transport.

The MCPB manifest is now 0.4, the minimum for its existing `server.type: "uv"`.
The official MCPB 2.1.2 CLI rejected the previous 0.3/uv combination. Bundles
include `uv.lock` and third-party notices, and launch with `uv run --frozen`
so their installed dependencies match the audited lockfile. This uv runtime
requires a host with MCPB 0.4 support; see the
[official manifest specification](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md#uv-runtime-v04).

The pre-port [wire fixture](../tests/fixtures/mcp_wire/README.md) records all
32 tool names, descriptions, input/output schemas, five prompt declarations
and bodies, empty resource lists, and five representative tool calls.
SDK 2 matches those normalized payloads, including embedded JSON text,
`structuredContent`, and `{ok: false, error: ...}` domain errors with
`isError: false`. Clients must still inspect `ok`.

## Protocol differences

| Boundary | SDK 2 behavior and reason |
|---|---|
| Legacy initialization | Omits `capabilities.experimental: {}`. The native `MCPServer` runner leaves unused experimental capabilities unset; SDK 1 emitted an empty object. This is the only SDK migration difference in the legacy fixture; COPY1 product copy changes are listed below. |
| Modern opening | `server/discover`, or an ordinary request with metadata, replaces the legacy initialize/initialized exchange under the stateless specification. |
| Modern results | Include `resultType: "complete"` and `_meta["io.modelcontextprotocol/serverInfo"]`. Discovery and list results also include `ttlMs: 0` and `cacheScope: "private"`. These fields are required by the SDK's modern serialization; tool payloads and prompt bodies are unchanged. |

Legacy clients can initialize with `2024-11-05`, `2025-03-26`, `2025-06-18`
or `2025-11-25`, then send `notifications/initialized`. An unsupported
initialize version, including `2026-07-28`, negotiates `2025-11-25`.
The first request selects the era for the connection. Reconnect to change eras.

Modern requests carry metadata on **every request**, for example:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
```

The Python test API also changed: `call_tool()` returns `CallToolResult`, and
model fields use `input_schema` and `mime_type`. Wire names remain camelCase.
SDK 2 executes synchronous handlers in worker threads. No handler logic changed.

Sources: [official SDK 2.3.0 implementation](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/server.py),
and the read-only Uoink reference migration at commit
`505881722db6b488eb8ae807cb96be4918e7bd01` (PR #281). Uoink was never launched
or contacted to develop or test this port.

## Replay and regeneration

Use the environment variables in the build-pass rules, then run:

```powershell
uv sync --all-extras
uv run --frozen pytest -q tests/test_mcp_wire.py tests/test_mcp_stdio.py
```

The replay compares canonical UTF-8 bytes and prints a unified diff on failure.
It runs every recorded exchange for each legacy version, then compares the same
payloads with exact modern envelopes for discover-first, list-first and
call-first connections. Separate tests launch the unmodified CLI and call the
real doctor in an isolated home. Normalization and test-only host inputs are
listed beside the fixture; the SDK 1 file is never rewritten by a test.

To regenerate the **SDK 1** evidence, export the original source into an ignored
directory in this worktree. Keep the current environment separate:

```powershell
git archive --format=zip --output=zing-workspace/sdk1-source.zip a8691ef4727d69705133841918366ce74f8548b0
Expand-Archive zing-workspace/sdk1-source.zip zing-workspace/sdk1-source
Copy-Item tests/mcp_wire.py,tests/mcp_wire_child.py,tests/update_mcp_wire_fixture.py zing-workspace/sdk1-source/tests/
uv run --directory zing-workspace/sdk1-source --frozen --extra dev python tests/update_mcp_wire_fixture.py --output ../sdk1-regenerated.json
```

The recorder refuses any MCP version other than 1.28.1 or a server without the
original FastMCP import. Compare `zing-workspace/sdk1-regenerated.json` with
`tests/fixtures/mcp_wire/sdk1.json` before replacing anything. Deliberate product
changes need a new, separately named baseline and review; do not bless SDK 2
output as the old contract. `.gitattributes` pins fixture line endings to LF.

Dependency versions and verified wheel licenses are in
[third-party notices](THIRD-PARTY-NOTICES.md#mcp-sdk-2-october-2026).

## COPY1 copy changes

`tests/fixtures/mcp_wire/copy1.json` pins the reviewed current server
instructions, tool descriptions with ASCII punctuation, and the missing-breakdown
error. Replay substitutes these exact expected fields in memory for both protocol
eras. It does not strip instructions or normalize arbitrary strings; unexpected
copy, schemas, envelopes and payloads still fail. The error is pinned in both
text and structured content. A negative test checks that instructions and other
initialization fields cannot drift. The SDK1 capture and its SHA-256 stay unchanged.
