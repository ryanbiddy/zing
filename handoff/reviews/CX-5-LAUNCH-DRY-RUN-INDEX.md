# CX-5 launch dry-run index

CX-5 rehearsed the authorization-free part of `LAUNCH-PLAN.md` step 6. The
canonical evidence packet is:

- `E:\AI\projects\uoink\handoff\suite-split\LAUNCH-DRY-RUN.md`
- 28,358 bytes
- SHA-256
  `2F3F3DBAE733751F89EE6CB7E558335A00F312424BDB99CC366C76F943E3F672`

The packet inventories the exact artifacts, isolated-host checks, MCP surface
results, copy-ready-but-unsent registry drafts, engineering blockers, and
Ryan-only actions. It does not authorize a ship.

## Exact artifact inventory

| Product/source | Artifact | Bytes | SHA-256 |
|---|---|---:|---|
| Uoink `0df29c86f7df0eb5243192c6d6ad892ab38d732f` | `Uoink-Setup-3.7.0.exe` | 339,807,188 | `902F104C9B8CBF68FEA79C0C451D63AF8D448058554642F72704E641F5DCB275` |
| Uoink `0df29c86f7df0eb5243192c6d6ad892ab38d732f` | `uoink-3.7.0.mcpb` | 38,792 | `495F065072BA29B620B5DD81F2F8E19A1ADC78940F22CCF37CBFC97C665D68C1` |
| Zing `49ac87db315b2397b795c2c99282650aa2101ee9` | `myzing-0.1.0-py3-none-any.whl` | 178,844 | `7DF5A12D3D5B265B1FDE5026859DC2588174428C3D0707EEF4AEB9BBBED4AA76` |
| Zing `49ac87db315b2397b795c2c99282650aa2101ee9` | `myzing-0.1.0.tar.gz` | 295,538 | `7061C083618DB2A9606DB35EBA56ED932759B2BBFE635199C57E178754B9C4F5` |
| Writer `1d2ce1abf1a8db631e5b694c7db4f4f6aacae53e` | `ryan_writer-0.1.0.dev0-py3-none-any.whl` | 53,816 | `B05C7BA45EA90E43B9FB74D4DB8681E6790BE4E0C3E4DED3BBE2D6998D692A7C` |
| Writer `1d2ce1abf1a8db631e5b694c7db4f4f6aacae53e` | `ryan_writer-0.1.0.dev0.tar.gz` | 66,284 | `B1340B8AADBBCABB7138642E10822241381C99AB78562E9FC1B5A780FD737A3F` |

The exact Uoink draft assets match GitHub's draft-release digests and prior
download round trip. A same-commit rehearsal rebuild did not reproduce the
installer: `yarl` floated from 1.24.2 to 1.24.5. The current official MCPB
packer also rejects the draft bundle's BOM-prefixed `manifest.json`. Those are
release blockers, not Ryan-only clerical steps.

## Local gates

| Product | clean-host result | MCP surface result | Honest limit |
|---|---|---|---|
| Uoink | Fresh installer staging passed schema/import/WhisperX checks under its embedded Python. | Black-box `initialize` → `tools/list` → `tools/call` passed under `-P`; exactly 14 canonical tools were listed. | The exact installer plus MCPB still needs a disposable Windows host. The staged result is not mislabeled as that proof. |
| Zing | Exact current-main wheel passed all 7 clean-host steps in a bare environment. | The installed wheel listed exactly 19 tools; `zing_status`, prompt listing, and error-as-data calls passed (3 protocol tests). | `[mcp]` omits study/render extras, and the official MCPB packer rejects `server.type: "uv"`. |
| Writer | Exact wheel passed all 7 clean-host steps in a bare environment. | All 17 listed tools were called successfully with no errors. | `initialize.serverInfo.version` is incorrectly the MCP SDK version `1.28.1`, not Writer `0.1.0.dev0`. |

## Unsent directory work

The packet contains assembled drafts for the Official MCP Registry, the
Anthropic Connectors Directory, and Smithery:

- Uoink has an intentionally invalid pending-release registry URL and exact
  SHA-256. It remains blocked by the MCPB BOM, dependency reproducibility,
  public URL, clean Windows, privacy, and tool-annotation gates.
- Zing has an MCPB gap inventory plus a PyPI `server.json` draft. It remains
  blocked by the packer/runtime mismatch, absent public package and ownership
  marker, incomplete launch extra, P1 URL/token boundary, privacy metadata,
  and tool annotations.
- Writer has a PyPI `server.json` draft and Anthropic field inventory. It
  remains outside this launch: no public package or MCPB exists, the ownership
  marker is absent, and the MCP identity version is wrong.
- Smithery's local path requires a pre-built MCPB. Uoink's current bundle is
  rejected by the official packer; Zing has no bundle; Writer has no bundle.

Current requirements were checked against the official MCP Registry package
guide and schema, Anthropic's submission checklist, and Smithery's publish
documentation on 2026-07-19. No login or submission command was run.

## Ryan-only actions

Only after the engineering blockers close may Ryan authorize a disposable
host, select a release candidate, publish a package or GitHub release, approve
an Official MCP Registry entry, use the Anthropic Connectors Directory form,
or invoke Smithery. Launch copy, delivery, and any paid distribution remain
separate decisions.

- `publish`: **not performed**
- `release`: **not performed**
- `submit`: **not performed**
- `post`: **not performed**
- `deliver`: **not performed**
- `purchase`: **not performed**
- `spend`: **not performed**

## Regression record

`tests/test_launch_dry_run_evidence.py` failed with two missing-file failures
before this index existed. It now pins the packet name, all three candidate
families, the clean-host and MCP evidence, all three directory surfaces,
SHA-256 evidence, Ryan-only actions, and the complete external-action ledger.
