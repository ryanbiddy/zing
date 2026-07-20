# CX-5 launch dry-run index

Canonical evidence is
`E:\AI\projects\uoink\handoff\suite-split\LAUNCH-DRY-RUN.md`.
It is one bounded, internal rehearsal packet for the authorization-free part
of launch-plan step 6. It contains exact artifact hashes, clean-host limits,
MCP surface results, unsent directory field sets, blockers, and Ryan-only
actions. It does not claim that any product may ship.

## Candidate artifacts

| Product | Exact candidate | SHA-256 | Result |
|---|---|---|---|
| Uoink 3.7.0 | `Uoink-Setup-3.7.0.exe` | `902F104C9B8CBF68FEA79C0C451D63AF8D448058554642F72704E641F5DCB275` | Version and draft-release bytes agree; exact disposable-Windows install still required. |
| Uoink 3.7.0 | `uoink-3.7.0.mcpb` | `495F065072BA29B620B5DD81F2F8E19A1ADC78940F22CCF37CBFC97C665D68C1` | Manifest 0.4, product 3.7.0, 14 tools; thin launcher depends on installed helper. |
| Zing 0.1.0 | `myzing-0.1.0` wheel and sdist | wheel `D49C62F503B01905B027CAB14712F8C97A428D8C940E9712F5647C1CCD38D016`; sdist `5C69B321E314687A8570E834ECF6388056F11559485B5DE21FF3222AB21AE7DC` | Exact wheel initializes as Zing 0.1.0 with 19 tools and four prompts; MCPB build and full install story are blocked. |
| Writer 0.1.0.dev0 | `ryan_writer-0.1.0.dev0` wheel and sdist | wheel `B05C7BA45EA90E43B9FB74D4DB8681E6790BE4E0C3E4DED3BBE2D6998D692A7C`; sdist `B1340B8AADBBCABB7138642E10822241381C99AB78562E9FC1B5A780FD737A3F` | All 17 installed tools pass, but MCP identifies version 1.28.1 instead of 0.1.0.dev0. |

## Clean-host MCP surface verdict

- Zing: exact isolated wheel passed initialize, 19-tool listing, four-prompt
  listing, and `zing_status`. The advertised `[mcp]` install omits study and
  render extras, so this is a connection proof rather than a complete product
  install.
- Writer: exact isolated wheel passed doctor and successful calls to all 17
  tools. Its server-version value is a release blocker.
- Uoink: prior staged release gates remain green, but the exact installer and
  thin MCPB were not installed over the current workstation because the
  installer writes a fixed autostart entry. A disposable Windows clean-host
  run remains required.

## Unsent packet status

- **Official MCP Registry:** Uoink's schema-shaped draft includes the exact
  MCPB digest and an intentionally invalid pending public-release URL. Zing
  has no MCPB, release URL, or bundle digest. Writer and the suite shell are
  outside this launch's registry surface.
- **Anthropic Connectors Directory:** Uoink and Zing field inventories are
  assembled, but both lack required tool annotations and privacy-policy
  metadata. Uoink also lacks the exact clean-install record; Zing lacks a
  bundle and retains a P1 credential-boundary defect.
- **Smithery:** proposed product namespaces and prerequisites are recorded.
  Uoink remains a draft thin launcher; Zing has no pre-built MCPB.

## Ryan-only actions

Ryan's decisions begin only after the engineering blockers in the canonical
packet close: approve the disposable Uoink Windows test host; choose and
publish an exact release; approve the final public-URL/hash registry body;
authorize any registry or directory submission; choose Zing and Writer's first
public milestones; and approve launch communications or paid distribution.

## External-action ledger

- `publish`: **not performed**
- `release`: **not performed**
- `submit`: **not performed**
- `post`: **not performed**
- `deliver`: **not performed**
- `purchase`: **not performed**
- `spend`: **not performed**

