# Saved references and draft choices

Resolve a saved reference before studying it:

```powershell
zing project init --reference uoink:ref-123 --clips .\clips --out .\zing-workspace\edit
zing project resolve-reference .\zing-workspace\edit
zing project study-reference .\zing-workspace\edit
```

Resolution uses the existing `uoink.media.handoff/1` bridge. It checks the
returned item reference, local file size and SHA-256, then records the absolute
path, digest, byte length, source URL and peer provenance under
`project.json` → `reference.resolution`. It creates no media copies or links.
`uoink:<id>` is translated to the canonical `uoink://item/<encoded-id>` wire
reference. Both forms are accepted.

If the helper is offline, unconfigured, missing the item, or returns a bad hash,
the manifest records `state: unresolved` and a reason. Inventory and brief
commands remain usable. Supply a file to continue locally:

```powershell
zing project resolve-reference .\zing-workspace\edit --file .\reference.mp4
```

This preserves the original reference and records the replacement as
`user_supplied_file`. The project study command verifies the recorded file
again and passes its local path to the existing study engine. It never supplies
the peer's source URL as a fallback. Study artifacts go to the Zing workspace
(`--workspace` can override it), and the breakdown is attached to the project
for brief recommendations. Keep project and workspace outputs outside Git or
under the ignored `zing-workspace/` directory.

## Search handoff

```powershell
zing project find-reference "soft cuts"
```

Results are listed without selecting a reference, changing a project, or
recording an engagement event. The bridge in this base has no existing search
operation. P19 adds a client handoff that requires the service manifest to
advertise `uoink.corpus.search/1`. This is a proposed optional capability;
support in a running Uoink installation has not been verified. A peer without
it returns a clear unavailable message. Zing never probes a guessed legacy
search route or builds its own reference index.

The advertised capability opts into this exact wire format:

```json
{"contract":"uoink.corpus.search","version":1,"query":"soft cuts","limit":20}
```

Send that body with `POST /api/corpus/v1/search`. Authentication uses only the
`X-Uoink-Token` header. The response has exact keys:

```json
{"ok":true,"contract":"uoink.corpus.search","version":1,"data":{"results":[{"item_ref":"uoink://item/ref-123","title":"Example reference","source_url":null}]}}
```

There may be zero to twenty results. Each has a canonical item reference, a
string title, and a null or HTTP(S) source URL. Unknown keys, invalid references,
or another contract version are refused. HTTP 404, 405 or 501 means search is
unavailable even if advertised. Queries are sent in the body, never in URLs.

## Choice receipts and the draft writer handoff

```powershell
zing plan choose .\zing-workspace\edit --draft A --note "Better opening"
zing plan choose .\zing-workspace\edit --draft A --share-choice
```

The base for P19 does not include the P17/P18 A/B/C writer. The default handoff
is an existing artifact at `<project>/drafts/A.json`, `B.json`, or `C.json`.
A writer using another layout can pass `--draft-file <plan-or-render-file>`.
Zing hashes that exact file; a label without a file is refused. The choice
command does not validate render quality or claim the artifact was rendered.

`choices.json` stores a project ID, the current selection, and versioned
receipts. Each receipt includes the draft label, artifact path and SHA-256,
reference ID and resolved hash when known, saved brief hash when present,
UTC timestamp, notes, sharing consent, and delivery state. A project lock and
atomic replacement protect writes. The receipt is saved before any peer
request, so an offline helper cannot discard the user's choice.

Only `--share-choice` attempts delivery. The existing
`uoink.engagement.ingest/1` contract accepts `opened`, `search_hit`,
`search_click`, `paste`, and `cite`; it has no `draft_selected` event or fields
for project metadata. P19 sends a `cite` event for the chosen draft's Uoink
reference. Choice details, notes, paths and hashes stay in Zing. The event ID
is derived from the durable project ID, draft label, artifact hash, reference
ID/hash and brief hash. It carries the same five fields as existing events:
`event_id`, `item_ref`, `event_type`, `source_product`, `occurred_at`.

Retry the same command with `--share-choice` after an uncertain delivery.
The event ID and timestamp stay unchanged; the engagement spool accounts for
accepted, duplicate, pending and rejected events. Completed events are not
resent. Editing a note does not mint an event. Changed draft bytes or changed
reference/brief identity produce a new receipt. Choosing without the sharing
flag never retries delivery. References without a Uoink item ID remain local.

These are observed choices and reference citations. They report no views,
likes, conversions, or other social performance. No command publishes a draft.

## Isolation and credentials

Zing uses the configured `UOINK_TOKEN` environment variable and never reads the
peer's token file. Credential values are refused in request URLs and redacted
from peer errors. Auth headers are not forwarded on redirects.

P19 tests use mocked HTTP and synthetic files under temporary Zing workspaces.
The suite patches default discovery, isolates runtime leases, clears inherited
peer credentials, and guards against real connections to port 5179 or access
to the live Windows Uoink library locations. No live Uoink search, media read,
or event delivery was used to validate this pass.
