# Project inventory

Create a local inventory for one reference and a folder of clips:

```bash
zing project init --reference "https://example.com/reference.mp4" --clips ./clips --out ./project
zing project scan ./project
zing project status ./project --json
```

`--reference` also accepts a local file or `uoink:<item-id>`. Init records the
reference without opening, downloading, or studying it. A missing local reference
can be recorded. The clips folder must exist at initialization. Probing needs
`ffprobe` on PATH; `zing doctor` provides installation guidance.

Use `--supplied-by "Ryan" --license "CC0-1.0"` on init when those details are
known. Defaults are supplier `user` and license `user-supplied`; this records
provenance, not a verified grant of rights. Each asset and the reference have
their own source record.

The folder scan is recursive and includes regular files of any extension.
Unprobeable files remain in the inventory as unsupported. Symlink files and
directories are skipped. When the project folder is nested inside the clips
folder, its entire subtree is excluded. When both folders are the same,
`project.json`, `.project.lock`, and `.project-*.tmp` are reserved metadata names.
Keep rendered output outside the clips folder so it does not become an input.

`project.json` uses version 1 dataclasses in `myzing.project.models`; each record
supports `to_dict()` and `from_dict()`. Unsupported versions fail with an error.
Paths inside the project are stored relative to it, with forward slashes. External
paths are absolute. Relative stored paths resolve against the project folder,
regardless of the command's working directory. Moving a project with its internal
clips preserves its references; external clips still need their original paths.

Each asset stores its stable ID, current and original paths, previous paths,
streamed SHA-256, byte size, nanosecond mtime, source record, and ffprobe metadata.
Probe metadata includes raw streams, format metadata, duration in seconds, coded
width/height, rotation in degrees, rational fps, audio presence, and orientation
after quarter-turn rotation. Unknown duration/fps/orientation are null.

Scan reuses hashes when size and mtime are unchanged. A touch triggers hashing
but reuses the probe if the hash is unchanged. Changed content preserves the ID,
increments its revision, and replaces its probe. Removed files retain their
records with `state: missing`. Exact path/hash matches are reserved first, then
hash matches preserve IDs across moves, including name swaps and reused names.
Copies at multiple existing paths have distinct IDs. If several unmatched assets
have the same hash, present records are preferred over missing ones, then moves
are paired in sorted path order; identical bytes cannot establish which physical
copy moved. A missing record can share a historical path with its replacement.
A file that
both moves and changes content is a new asset plus a missing old record.

Status reads the manifest and checks current file stats without hashing or
writing. It reports ready, missing, changed, and unsupported assets. `needs_scan`
means the saved probe/hash may be out of date. After a content edit is scanned,
status continues to show changed for revisions above 1; the asset's manifest
state can be ready, and later consumers should compare `(id, sha256)` or revision
against their cached work. New files appear after a scan.

Explicit HDR/LOG metadata and a mismatch between average and nominal frame rates
produce unsupported flags. `vfr_suspected` is a metadata warning, not a frame
timestamp measurement. Matching frame rates do not prove CFR; absent color tags
do not prove SDR. No conversion or source-byte modification is performed.

Each scan builds a complete candidate manifest, flushes a temporary file beside
`project.json`, and replaces the manifest atomically. An exception leaves the last
successful manifest intact. Init first commits an empty manifest, so an interrupted
initial inventory can resume with `zing project scan`. Uncommitted work is retried;
there is no per-file checkpoint. A source that changes while being inspected
aborts the scan. Changes that preserve both size and mtime cannot be detected by
the incremental stat check.

An exclusive `.project.lock` prevents overlapping init/scan operations. A lock
whose local owner PID has exited is reported as stale; a live PID is never expired
by age. Foreign-host or incomplete locks are reported without guessing their
liveness. After confirming its owner has stopped, remove only `.project.lock`
and rerun scan. A normal exception releases the lock automatically. Status can
read the last committed manifest during a scan.

The later match pass can use `reference.study` (currently null) to attach its
study provenance and results. Inventory does not resolve Uoink IDs or implement
`zing match`. CLI and Python APIs are available; MCP scan tools are deferred
until scans can use the server's background-job contract.
