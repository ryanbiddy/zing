# SG-4 scan: MCP distribution landscape vs zing's install story

Scope: how zing reaches users at launch — the official MCP registry,
the .mcpb bundle format's current state, and whether our shipped
packaging surfaces (uv-type .mcpb, `--print-config`, CONNECT.md) match
the July-2026 ecosystem. Live-verified cycle (WebSearch/WebFetch);
each claim carries its source.

## Official MCP registry — ADOPT AT LAUNCH (gated on naming decision)

The registry (registry.modelcontextprotocol.io, backed by Anthropic,
GitHub, PulseMCP, Microsoft) is the discovery layer AI clients
increasingly read. Publishing is free, namespace-authenticated, and
fits our shape exactly:

- PyPI-distributed servers are first-class: `server.json` references
  `{"registry_type": "pypi", "identifier": "myzing", "version": ...}`;
  the registry restricts PyPI references to pypi.org only and verifies
  package ownership via a marker line in the package README:
  `mcp-name: io.github.<user>/<server>`.
- `io.github.*` namespaces authenticate with `mcp-publisher login
  github` (browser OAuth) — no infrastructure to run.
- Only `_meta` under `io.modelcontextprotocol.registry/
  publisher-provided` survives publishing (4 KB cap); everything else
  is silently dropped — do not park provenance there.

**Gate:** the server NAME is a launch-naming decision (Decision Week
owns naming). Wrong namespace at first publish = a rename migration
later. Filed as a PROPOSED queue line, not built.

## .mcpb format — CURRENT, one real drift found and fixed

The format moved from Anthropic's dxt into the MCP org
(modelcontextprotocol/mcpb, toolchain v2.1.2 as of 2025-12-04;
Apache-2.0 new contributions / MIT existing — license-clean either
way, and we vendor nothing from it). Bundles now install across
Claude Desktop, Claude Code, and MCP for Windows — our one bundle
serves more clients than when we built it.

- **DRIFT FIXED THIS CYCLE:** current MANIFEST.md requires
  `manifest_version: "0.3"`. Our manifest said `"0.4"` — a mixup with
  the toolchain version ("uv type available in v0.4+"), never a valid
  manifest_version, and a plausible one-click-install failure.
  Corrected to "0.3"; the staging test now pins it with the citation.
- uv-type constraints re-verified: `pyproject.toml` required, no
  `server/lib`/`server/venv` in the archive, `mcp_config` optional.
  Our bundle conforms (that's why it's ~100 KB, not 5-10 MB).
- `tools` list in manifest.json: optional, display-only. Considered
  and REJECTED enumerating our 19 tools there — it duplicates
  EXPECTED_TOOLS as a second drift surface with no install benefit.

## Sources

- https://modelcontextprotocol.io/registry/about (registry overview)
- https://modelcontextprotocol.info/tools/registry/publishing/ (PyPI
  marker + server.json + mcp-publisher flow)
- https://glama.ai/blog/2026-01-24-official-mcp-registry-serverjson-requirements
  (validation, _meta rules)
- https://github.com/modelcontextprotocol/mcpb + raw MANIFEST.md
  (manifest_version 0.3, uv rules, licenses, cross-client)
- https://www.anthropic.com/engineering/desktop-extensions (dxt→mcpb
  history)
