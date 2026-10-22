# MCP wire baseline

`sdk1.json` was recorded over stdio from the unchanged Zing server at
`a8691ef4727d69705133841918366ce74f8548b0`, using MCP 1.28.1 and
Pydantic 2.13.4, before the SDK 2 port. Its SHA-256 is
`930e1f8711a27c8561a6ad4f92e26d74dfbea9915f967381163d49b193b1329d`.
The capture contains initialization, all 32 tools with input/output schemas and
descriptions, all five prompts and their bodies, both empty resource listings,
and five tool calls (including a domain error).

Normalization is limited to:

- Outer JSON objects use sorted keys, two-space indentation, UTF-8 and LF.
  Array order and embedded text remain significant.
- `initialize.result.serverInfo.version` becomes `<ZING_VERSION>`.
- In both copies of the `zing_status` payload (text and structured content),
  `version` becomes `<ZING_VERSION>` and `workspace.root` becomes `<ZING_HOME>`.
  The original root must equal the isolated child's configured home. The status
  text is re-encoded with SDK 1's two-space JSON indentation.
- No timestamp is removed. A fresh empty home has no jobs or receipts carrying
  volatile times. Protocol versions, prompt versions and schema versions stay.

The test-only `mcp_wire_child.py` fixes doctor inputs to two synthetic checks
(FFmpeg available, Uoink offline). The real `zing_status` handler and doctor
summary still run; hardware inventory is outside this wire baseline. All other
handlers, prompt files, SDK registration and serialization are real. The child
rejects network access, allowing only Windows asyncio's private socketpair.
Its home, model cache and user roots are disposable, credentials are removed,
and an invalid explicit Uoink URL prevents peer discovery.

See [MCP-SDK2.md](../../../docs/MCP-SDK2.md) for replay and regeneration commands.
