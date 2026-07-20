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

## CITATION AUDIT (2026-07-19, self-initiated after CX-6's trust flag)

Every load-bearing claim above re-verified against PRIMARY sources —
raw files and enforcement code, not mirror sites or search summaries.
**Zero errors found; two sharpenings.** Honest process note: the marker
and _meta claims were ORIGINALLY taken from a third-party mirror
(modelcontextprotocol.info) and a vendor blog (glama.ai) while feeding
a launch-checklist action. They happened to be right. Sourcing a launch
action from a secondary summary is the process defect, independent of
the outcome.

- `manifest_version: "0.3"` — CONFIRMED verbatim in raw MANIFEST.md.
  This is the claim that CHANGED a shipping artifact (our bundle said
  "0.4"); it now rests on primary evidence, as it should have from the
  start. uv rules and `tools`-is-optional confirmed in the same fetch.
- mcpb license — CONFIRMED from the raw LICENSE: Apache-2.0 for new
  contributions, MIT legacy. **Sharpening:** their DOCUMENTATION is
  CC-BY-4.0, which matters because we quote their docs in records.
- PyPI ownership marker — CONFIRMED from the registry's own validator
  SOURCE (`internal/validators/registries/pypi.go`), which reads PyPI's
  `info.description` (the README) for `mcp-name: <server-name>`.
  **Sharpening no secondary source mentioned:** the token is
  BOUNDARY-ANCHORED — it must be followed by a space, newline, HTML tag,
  or comment close, and the validator emits a distinct "glued trailing"
  error otherwise. Launch action: put the marker on its OWN LINE, never
  inside a badge or mid-sentence.
- `_meta` rules — CONFIRMED verbatim in `docs/reference/server-json/
  official-registry-requirements.md`: only
  `io.modelcontextprotocol.registry/publisher-provided` is preserved
  (others "silently dropped"), limited to 4KB (4096 bytes).

## Sources (primary, re-fetched at the audit)

- raw MANIFEST.md and raw LICENSE, modelcontextprotocol/mcpb
- modelcontextprotocol/registry: `internal/validators/registries/pypi.go`
  (enforcement code) and
  `docs/reference/server-json/official-registry-requirements.md`
- https://www.anthropic.com/engineering/desktop-extensions (dxt-to-mcpb
  history; background only, nothing load-bearing rests on it)
