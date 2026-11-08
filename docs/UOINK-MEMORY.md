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

## Hand-off with Uoink

Uoink's "Make a Short with Zing" button can check support before launching a
project. `zing from-uoink --probe --json` prints exactly one JSON object and exits
0. It makes no network request and does not call Uoink.

```json
{"ok":true,"contract":"ryan.suite.handoff","version":1,"service":"zing","service_version":"<installed myzing version>","accepts":["uoink.item/1"],"needs":["uoink.media.handoff/1"]}
```

Launch the saved item with its canonical reference or `uoink:<id>` shorthand.

```sh
zing from-uoink uoink://item/short-123 --json --no-open
```

Zing resolves `uoink.media.handoff/1`, checks the kept file's size and SHA-256,
and creates a factory project through the same path as `zing factory new`.
The optional corpus metadata lookup supplies the title. The title and source
URL go in `source.json`; the canonical `uoink_ref` goes in `factory.json`.
No source video is downloaded or copied.

The default folder is `<workspace>/handoff/<title-or-item-slug>-<short-id>`.
The workspace follows `ZING_HOME`, defaulting to `~/.zing`. The short ID is
derived from the item reference. `--project DIR` chooses another folder.
A project from the same item is reused with its edits intact. A different
project in that folder is refused.

After binding an ephemeral port on `127.0.0.1`, Zing flushes this first stdout
line. Paths, port and dashboard token below are placeholders.

```json
{"ok":true,"contract":"ryan.suite.handoff","version":1,"project":"<absolute project path>","page":"http://127.0.0.1:<port>/?t=<dashboard-token>","item_ref":"uoink://item/short-123","reused":false}
```

Uoink can read this line and detach while Zing keeps serving in the same
process. The page opens in the browser unless `--no-open` is set. Without
`--json`, Zing prints the usual `Open ...` line. Press Run on the page to start
the factory. `--judge host` is the default and leaves prompts for the user's
agent. `--judge claude` passes judgments to Claude Code.

Ctrl+C or 60 minutes without an HTTP request stops the server with exit 0.
`--idle-minutes N` changes that limit and accepts whole minutes of at least 1.
Every HTTP request resets the idle timer.

Before the dashboard is ready, a failure prints this shape and exits 1 with
`--json`. Plain mode prints the message. Peer error details and the Uoink
credential are never printed.

```json
{"ok":false,"contract":"ryan.suite.handoff","version":1,"error":"media_unavailable","message":"The item's kept media is unavailable. Keep the video in Uoink and try again."}
```

| Error | Meaning |
|---|---|
| `invalid_ref` | The reference does not identify one Uoink item. |
| `uoink_unavailable` | Discovery, authentication or kept-media resolution failed. |
| `media_unavailable` | The item or kept file is missing, not kept, or fails verification. |
| `project_exists` | The chosen folder holds another project or other files. |
| `failed` | Invalid arguments or another startup error stopped the hand-off. |

### Save a source link

`uoink_bridge.capture(url, source_hint=None, wait_seconds=0)` supports the
planned `uoink.capture/1` capability. Uoink does not ship this capability yet.
Zing checks the suite manifest before calling the route. If it is absent,
capture returns a house error with `code="unsupported_capability"` and makes
no POST request.

When advertised, Zing sends `POST /api/suite/v1/capture` with JSON containing
`url` and, when supplied, `source_hint`. Only HTTP and HTTPS source URLs are
accepted. Peer discovery follows `UOINK_URL`, a valid runtime lease, then the
default loopback address. `UOINK_TOKEN` is sent only in the `X-Uoink-Token`
header. Redirects are refused. Credentials in input URLs are refused before
sending them.

Successful replies have exactly these keys, plus an optional text `message`.
`status` is `saved`, `queued` or `exists` (Uoink answers 200 or 202), and a polled
job can also report `error` with a message. A finished playlist is `saved` with a
null `item_id`. `source` is text, `canonical` is an HTTP or HTTPS URL, and `item_id`
and `job_id` are text or null. `item_uri` is the canonical reference for
`item_id`, or null.

```json
{"ok":true,"contract":"uoink.capture","version":1,"status":"saved","source":"youtube","item_id":"short-123","job_id":null,"canonical":"https://example.test/watch/123","item_uri":"uoink://item/short-123"}
```

Failure replies have exactly `ok`, `contract`, `version`, `error` and
`message`. `ok` is false, the contract is `uoink.capture`, and the version is 1.
`error` is `bad_request`, `unsupported_url`, `consent_required`,
`media_unavailable`, `busy`, `not_found` or `capture_failed`. `message` is text.
A 401 or 403 from Uoink's token gate returns a house error with
`code="unauthorized"`. Uoink keeps video jobs in memory, so a poll after a Uoink
restart returns `not_found`. Zing returns validated replies and redacts credentials in
error messages. Other shapes return a house error with `code="contract_mismatch"`
to identify a nonconformant peer.

With `wait_seconds > 0`, a queued reply with a job ID is polled using
`GET /api/suite/v1/capture/<encoded-job-id>` every 2 seconds. Polls use the same
token header and response checks. A completed result or error ends polling.
When time runs out, capture returns the last queued reply.

The existing MCP `study_video` tool accepts `save_source_to_uoink=true`.
For an HTTP or HTTPS source, it calls capture before starting the study and
adds the capture envelope as `uoink_capture` in the result. Capture failure
does not fail the study. The flag defaults to false and has no effect on
local files. This adds no MCP tool.

## Search handoff

```powershell
zing project find-reference "soft cuts"
```

Results are listed without selecting a reference, changing a project, or
recording an engagement event. Zing discovers `uoink.corpus.read/1` in the
service manifest and sends `GET /api/corpus/v1/search?q=soft+cuts&limit=20`.
Authentication uses only the `X-Uoink-Token` header. Queries appear in the URL;
do not put credentials in them. Zing sends no body, `mode`, `match` or
`search_details`. Uoink 3.11 therefore uses its default forgiving keyword search;
older peers can use strict matching.

The v1 response envelope has exactly `ok`, `contract`, `version`, `operation`
and `data`: contract is `uoink.corpus.read`, version is `1`, operation is
`search`, and data has exactly `items` and `page`. Page has exactly `state`,
`total`, `corpus_total`, `limit` and `offset`. Each item has exactly `id`,
`title`, `author`, `source_type`, `platform`, `source_url`, `captured_at`,
`duration_seconds`, `credit`, `facets` and `preview`; nested objects are also
validated against the committed upstream provider fixture.

Only after validation does Zing map each raw `id` to
`uoink://item/<encoded-id>` and retain `title` and `source_url`. Its CLI and MCP
callers still receive `{"ok":true,"results":[...],"selected":null}`, with each
candidate containing only `item_ref`, `title` and `source_url`. Wire pagination
and descriptive metadata are validated but omitted from this caller response.
Zing accepts at most 20 items. Unknown keys at any level, including the details
fields `citations`, `search_mode`, `requested_mode` and `fallback_reason`, are
rejected. The vendored `tests/fixtures/uoink_corpus_v1/provider.json` search
responses pass the parser unchanged; the adjacent sidecar pins their source
commit and SHA-256. HTTP 404, 405 or 501 reports search unavailable.

## Note titles

`push_to_uoink` titles the note `Zing breakdown: <title>`. Retained Uoink
files are named `media.mp4`, so the file name is the last resort. The title
is the first available of:

1. The Uoink corpus item's title. The kept-media handoff has no title field,
   so `zing project resolve-reference` asks for the same item with
   corpus.read/1 `get` (`GET /api/corpus/v1/items/<encoded-id>`, token
   header only, no query or body), but only when the service manifest
   advertises `uoink.corpus.read/1`, as search does. The envelope is
   exact-key validated like search (data has exactly `item`, `content` and
   `attachments`; the item has the search item's keys and the requested
   id). Only `title`, `author` and `source_url` are kept, as
   `reference.resolution.title` in `project.json` and as `title` in the
   breakdown's `project_reference` provenance. A breakdown studied before
   this has its title looked up at push time instead.
2. The platform title of a URL study.
3. The media container's `title` tag (read with ffprobe).
4. The project folder name (recorded as `project_name` by
   `zing project study-reference`).
5. The file name, then the slug.

Any failed lookup (offline, missing capability, `not_found`, drifted shape,
a garbled or truncated HTTP reply) falls through quietly to the next rule.
The reply is read up to 16 MiB: Uoink 3.11 caps `get` content at 2 MiB of
Markdown but writes it with ASCII JSON escapes, so a conformant reply with
CJK text can exceed 4 MiB. The push result names the rule in
`title_source` (`uoink_item`, `platform`, `container`, `project`,
`filename`, `slug`). The tests replay the vendored provider fixture's `get`,
`get_non_video` and `missing` responses unchanged.

## Choice receipts and the draft writer handoff

```powershell
zing plan choose .\zing-workspace\edit --draft A --note "Better opening"
zing plan choose .\zing-workspace\edit --draft A --share-choice
```

The default handoff is an existing artifact at `<project>/drafts/A.json`,
falling back to `plan-A.json` (likewise B/C). Both `zing plan drafts --out
<project>/drafts` and `zing match` write the latter names. For another layout,
pass `--draft-file <plan-or-render-file>`.
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
