# CX-4 integration documentation QA

Date: 2026-07-19

Outcome: **documentation corrected; three executable contract gaps routed**.
`SUITE-CONNECT.md` now describes the configuration and handoffs that current
builds perform. It no longer promises automatic credential discovery or hides
the remaining runtime-lease gaps.

## Review basis

The ratified source of truth is
`uoink/handoff/suite-split/INTEGRATION-CONTRACT.md`, contract family version 1.
I checked its requirements against these product revisions:

| Product | Revision checked |
|---|---|
| Uoink | `9905e2df711ed0d712d2d56c104378eb39cdae83` |
| Writer | `1d2ce1abf1a8db631e5b694c7db4f4f6aacae53e` |
| Zing | `bb35183ef3fd5b4d41de64c030e965591e25831b` |

The behavior check used the implementations and their negative fixtures, not
only prose. The strongest end-to-end receipt is the merged-main deterministic
family record from Zing run `29712806856`: 11 passing steps, 12 recorded
claims, 17 independent assertions, and zero residual processes. Its record
SHA-256 is
`C28BB18AFFB4DBA5ECE56C629EA525DAFC54C20A8B1341B483273A6E0FB69D15`;
the independent evaluation SHA-256 is
`E707A5B1BEAC64515C45B6F0112886EBEF642ED0350F1B7DB70EAD8FF6CAEC2A`.
That deterministic run does not replace the separate local real-capture
record.

Review scope covered the current integration surfaces:

- the ratified contract, `S6-INTEGRATION.md`, `SUITE-CONNECT.md`,
  `LAUNCH-PLAN.md`, and the Decision Week packet;
- Zing's `docs/CONNECT.md`, `docs/DEVELOPER-GUIDE.md`, and
  `docs/SUITE-SMOKE-CI.md`;
- Writer's README and `docs/ARCHITECTURE.md`;
- Uoink's README, `docs/v2-mcp.md`,
  `docs/writer-compatibility.md`, and short-video `keep_media` surface map.

Historical research, implementation notes, generated smoke work directories,
and superseded review drafts were checked when a live document cited them, but
they are not current setup instructions and were not rewritten.

## Contract-by-contract result

| Boundary | Actual behavior | Documentation result |
|---|---|---|
| Direct MCP registration | Uoink, Writer, and Zing each expose their own stdio MCP server. Product-to-product calls use HTTP, not another product's MCP process. | **Pass after correction.** `SUITE-CONNECT.md` now gives three direct entries and separates Uoink stdio's no-token boundary from its authenticated HTTP APIs. |
| Discovery and runtime leases | Writer resolves Uoink by explicit URL, valid lease, then default. Zing resolves by explicit URL or default. Uoink's Writer check resolves by explicit URL or default. | **Docs corrected; code gaps routed.** The guide recommends explicit URLs for non-default addresses and states which callers do not yet consume leases. |
| Credential custody | Zing requires `UOINK_TOKEN`; Writer requires `WRITER_UOINK_TOKEN`; Uoink's Writer check requires `UOINK_WRITER_TOKEN`. None should open the callee's token file. | **Pass after correction.** Removed “read automatically,” “nothing to configure,” and “automatic, no wiring.” Token locations are instructions for the human, not discovery inputs. |
| Peer states | The ratified states are `available`, `absent`, `unconfigured`, and `unhealthy`. Zing and Writer retain those states; Zing's human doctor marker abbreviates `unconfigured` as `unconfig`. | **Pass after correction for Zing and Writer.** `CONNECT.md` now distinguishes the contract state from the short human marker. Uoink's Writer result still uses its older envelope; routed below. |
| Stable references | Cross-product receipts use `uoink://item/<id>`, `writer://script/<id>`, and `zing://breakdown/<slug>`. Persisted Zing and Writer records do not use a peer path as identity. | **Pass.** The revised suite guide uses only stable references outside the two authenticated file handoffs. |
| Kept-media handoff | Uoink may return one confined absolute file path in `uoink.media.handoff` v1. Zing verifies size and SHA-256 and persists path-free provenance. | **Pass after correction.** The guide now says fallback is allowed only from a returned HTTP(S) source URL. No URL or a failed refetch is a failure, not an implied success. |
| Writer shot-list handoff | Writer exports a chosen `writer.shot-list` v1 Markdown file. Zing imports it idempotently and persists a path-free receipt. Writer makes no Zing call. | **Pass.** Current Writer, Zing, and suite documents agree. |
| Engagement accounting | Writer's `cite` and Zing's `opened` events are accepted, duplicate-counted, permanently rejected with durable visibility, or retained in a caller spool. | **Pass.** The family smoke exercises accepted and spooled outcomes; revised suite docs no longer reduce an attempted request to success. |

## Surface verdicts

| Surface | Verdict | Correction or evidence |
|---|---|---|
| `SUITE-CONNECT.md` | **Accurate after CX-4 edits** | Rewritten around direct MCP registration, explicit credentials, exact peer states, the two file handoffs, and current lease behavior. “No cloud” became the narrower and true local-product statement because an AI client may use a network model. |
| `S6-INTEGRATION.md` | **Accurate after CX-4 edits** | Replaced the pre-ratification 5178-range description with 5178 reserved, Uoink 5179, Zing HTTP 5180 reserved, Writer 5181, and Zing MCP stdio. Updated future-tense work items to delivered behavior and named remaining gaps. |
| `LAUNCH-PLAN.md` | **Pass** | Step 5 correctly requires three direct MCP servers, versioned loopback HTTP, per-product tokens, file-only Writer to Zing, and no suite proxy. |
| `DECISION-WEEK-PACKET.md` | **Pass for integration after the guide fix** | Its family-flow instruction delegates setup detail to `SUITE-CONNECT.md`; it does not add a conflicting token or handoff claim. |
| Zing `docs/CONNECT.md` | **Accurate after CX-4 edits** | Added installed Windows/macOS/source token locations, explicit custody, exact peer-state language, and conditional HTTP(S)-only refetch. |
| Zing `docs/SUITE-SMOKE-CI.md` | **Pass** | The deterministic-versus-live boundary, artifacts, assertions, cleanup, and red lines match the workflow and merged-main record. |
| Writer README and architecture | **Pass for integration** | They name `WRITER_UOINK_URL` and `WRITER_UOINK_TOKEN`, constrain corpus access to `uoink.corpus.read` v1, preserve the stable reference, and state that Writer makes no live Zing call. The README's stale “private migration work” sentence is release-status drift, not an integration claim; CX-1 already owns collateral drift. |
| Uoink README and integration docs | **Pass with routed peer-client gap** | Direct stdio and authenticated HTTP are distinguished; `keep_media` is opt-in and short-video-only; `UOINK_WRITER_URL` and `UOINK_WRITER_TOKEN` are explicit. The peer response implementation is not yet the ratified envelope. |

## Routed code gaps

These are executable deviations, not wording problems. CX-4 did not edit
another lane's product code.

1. **P1 — Zing can send a Uoink credential to a non-loopback explicit URL.**
   `src/myzing/suite_peer.py` validates peer URLs, but
   `src/myzing/uoink_bridge.py:57-62,107-118,210-225` uses `UOINK_URL`
   directly for kept-media and note calls. A value such as
   `http://example.test:5179` can therefore receive `X-Uoink-Token`, contrary
   to contract sections 1.2 and 3.3. The bridge must share the loopback URL
   validator and fail before constructing a credentialed request.
2. **P2 — Zing does not consume Uoink's runtime lease.**
   `src/myzing/suite_peer.py:192-204` chooses explicit `UOINK_URL` or the
   default address and never reads `uoink.json`. This misses the ratified
   explicit URL → valid lease → default order. A Uoink service on a valid
   non-default leased port appears absent unless the user duplicates its URL
   into Zing's environment.
3. **P2 — Uoink's Writer peer remains on the pre-contract shape and discovery
   order.** `writer_peer.py:34-46,79-168` chooses explicit
   `UOINK_WRITER_URL` or the default, does not read `writer.json`, and returns
   `availability=detected_unconfigured|not_running|...` instead of the exact
   `ryan.suite.peer` v1 states and error envelope. The compatibility path
   remains calm, but it is not contract-conformant.

The safe current setup is the one in the corrected suite guide: keep every
product on its default loopback address or supply the caller's explicit URL,
and always supply the caller-owned token variable. Closing the three gaps
requires product-code regressions and normal CI in the owning repositories.

## Anti-drift regression

`tests/test_integration_docs_contract.py` failed before the edits on the stale
source-checkout-only token path, the abbreviated peer state presented as the
contract state, the unconditional refetch promise, and the missing QA record.
It now pins the corrected Zing setup language and this review's coverage of all
ratified integration boundaries.
