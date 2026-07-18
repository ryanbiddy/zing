# Plan critique — Lane B (surface: doctor, storage, MCP, prompts)

Author: Lane B (Claude Fable 5). Date: 2026-07-18. Phase 0 deliverable.
Read: vision doc, ROADMAP, SPRINT-1-D1, schemas.py, PRIOR-ART-OSS.
Ranked by leverage: each item = what's weak → why it matters → what to do.

## 1. The prompt pack has no delivery path to the AI that needs it

**Weak:** `prompts/study.md` ships "in the repo," but the user's AI touches
Zing over MCP, and a pip/uvx install buries the repo in site-packages. As
spec'd, the judgment loop — Zing's core thesis — only closes if the user
manually finds and pastes a prompt file. Nobody will.

**Recommendation:** treat prompts as package data and serve them through
every surface: (a) expose them via the MCP **prompts capability**
(`prompts/list` + `prompts/get` — first-class in the protocol, supported by
Claude Desktop) so the AI can pull "how do I judge this" the same way it
pulls tools; (b) add a `get_prompt(name)` tool as a fallback for clients
that only speak tools; (c) `zing prompt study` on the CLI for the
copy-paste flow. Lane B will build all three unless overruled — the spec
should name this, since it is the difference between "prompt pack" and
"prompt file nobody loads."

## 2. `study_video` over MCP will hit client timeouts and look broken

**Weak:** a real study run (yt-dlp fetch + whisper + OCR + scene detect) is
minutes, even at the performance budget. MCP clients time out or spin on
long tool calls; Claude Desktop's UX for a 3-minute silent tool call reads
as a hang. The spec treats `study_video(url_or_path)` as a plain
synchronous tool.

**Recommendation:** S1: keep it synchronous but (a) validate cheaply first
(URL reachable / file exists / doctor-critical tools present) so failures
return in seconds, honest and actionable; (b) emit MCP progress
notifications when the client provides a `progressToken`; (c) document the
known timeout risk in the tool description itself ("takes 1–5 minutes on
first run"). If wizard-of-oz shows clients giving up, S2 upgrades to a job
pattern (`study_video` returns a ticket; `zing_status` reports progress) —
design the tool result shape now so that upgrade isn't breaking.

## 3. `save_judgment` merge semantics are unspecified — that's where data dies

**Weak:** "merges into `Breakdown.judgment`" doesn't say shallow/deep,
doesn't version, doesn't record who wrote what. S2 profile aggregation and
Sol's eval scoring both need judgments that are comparable across models
and prompt versions; a free-form deep-merged dict silently accumulates
garbage.

**Recommendation:** namespace by section with per-section **replace** (not
deep merge): `judgment["study"] = {...}` wholesale. Lane B's
`save_judgment(slug, judgment, section="study")` stamps
`judgment[section]["_meta"] = {model?, prompt_version, written_at}` where
`prompt_version` comes from the prompt pack file used. The prompt pack
defines the expected judgment JSON shape and carries a version header;
save_judgment validates required keys minimally and rejects with an
actionable message otherwise. No schemas.py change needed — this all fits
inside the free-form dict — but the sprint spec should bless the
per-section-replace rule so Lane A and the eval harness rely on it.

## 4. Re-study destroys judgment; nobody owns the slug

**Weak:** the storage spec doesn't say what happens when the same URL is
studied twice. Naive overwrite of `breakdown.json` deletes
`Breakdown.judgment` — the one thing Zing *didn't* compute and can't
regenerate (it's the user's AI's work). Separately, "slug" appears in every
MCP tool signature but no lane is assigned to define it; Lane A and Lane B
will each invent one.

**Recommendation:** storage (Lane B, landing first) owns
`slug_for(url_or_path)` — deterministic from platform + video id for URLs,
stem + short content hash for files; collisions get suffixes. Re-study
policy: overwrite measurements, **preserve existing `judgment`** by merging
it back into the fresh Breakdown before write (plus one `.bak` of the prior
json). Lane A calls storage for slugs and paths and never invents either.

## 5. Doctor's exit semantics contradict the honest-skip design

**Weak:** "exit nonzero when core tools missing" — but which are core?
Whisper is spec'd as an *honest skip* in Lane A (empty words + warning);
yt-dlp is only needed for URLs; OCR is timeboxed best-effort. If doctor
fails the machine for a missing whisper model, doctor and the pipeline
disagree about what "working" means.

**Recommendation:** three explicit tiers — **required** (ffmpeg: no
measurements at all without it), **recommended** (yt-dlp, faster-whisper,
OCR backend: named degraded modes), **optional** (uoink reachable). Exit
nonzero only on missing *required*; every line prints the exact install
command for this OS. Add `zing doctor --json`, and implement the MCP
`zing_status()` tool on top of the same check functions — one source of
truth for "what works on this machine," reported identically to humans and
AIs.

## 6. The MCP surface is text-only, but hook judgment is a visual task

**Weak:** the vision doc promises "multimodal LLM on keyframes for
hook/beat classification," yet the S1 tool list gives the AI no way to see
a single frame. The AI judges hooks from transcript + numbers only; for a
visual-hook video (no speech in 0–3s), `prompts/study.md` will be asked to
judge blind.

**Recommendation:** don't build it in S1 (measurement first is right), but
spec `get_frames(slug, timestamps[])` → MCP image content (ffmpeg frame
extraction at call time, no storage cost) as the named S2 fast-follow, and
write `prompts/study.md` v0 to degrade honestly: when the hook has no
words/captions, the judgment must say "visual hook — cannot classify from
measurements" rather than hallucinate a label. The eval harness should
score that honesty.

## 7. Fresh-install weight will decide whether `uvx myzing` feels magic or broken

**Weak:** if faster-whisper + rapidocr + scenedetect are hard deps,
`uvx myzing` downloads hundreds of MB before doctor can even run; if
they're all extras, `zing study` on a fresh box does nothing useful.
The funnel in the done-criteria (`uvx myzing` → doctor → study) is the
first-run product and nothing in the plan owns its weight.

**Recommendation:** core install = stdlib + tiny deps only, so
`uvx myzing` → `zing doctor` is seconds; measurement deps live in extras
(`myzing[study]` or individual `[whisper]`/`[ocr]`) and doctor prints the
one command that installs what's missing. Decide the extras split
in-sprint (it's a pyproject decision, cheap now, breaking later) and have
Lane A import heavy deps lazily inside functions so doctor/MCP never pay
their import cost.

## 8. Don't invent a third MCP server implementation — copy the house pattern

**Weak:** the spec names uoink's C-01 smoke-test pattern but not the server
implementation choice. Hand-rolling JSON-RPC + initialize negotiation +
tools/list plumbing from scratch is a known time sink with protocol-version
gotchas; the official `mcp` SDK (MIT) is heavier but maintained.

**Recommendation:** port uoink's proven stdio server skeleton (64 tools in
production = it works; same author, same license) rather than writing new
protocol code or taking the SDK dependency in S1. If the uoink pattern
turns out not to be cleanly portable, take the official MIT SDK instead —
either way, zero novel protocol code in this repo. Revisit the SDK when we
want the prompts capability if the ported skeleton makes it awkward.

## 9. `media_path` as stored is non-portable (orchestrator, schemas nit)

**Weak:** `VideoMeta.media_path` will hold an absolute path inside the
workspace; move `~/.zing/` (or sync a breakdown to another machine) and
every breakdown silently points at a dead file.

**Recommendation (orchestrator decision, not a Lane B change):** document
that `media_path` is stored *relative to the breakdown's own directory*
(media sits next to breakdown.json), with storage providing resolution to
absolute at load. One-line semantic note in schemas.py's docstring when the
orchestrator next touches the contract; costs nothing now, saves a
migration later.

## 10. Tooling: one shared workspace fixture before three lanes hardcode paths

**Weak:** all three lanes write tests that touch the workspace; without a
shared fixture each invents its own tmpdir/env-var dance, and offline-CI
discipline erodes one test at a time.

**Recommendation:** Lane B's storage PR includes `tests/conftest.py` with a
`zing_workspace` fixture (tmp_path + env override via the storage module's
own env var) that every lane uses. Cheap, lands first, prevents the
"tests pass on my machine because ~/.zing exists" class of bug entirely.

---

**Not flagged as problems:** storage layout shape (`breakdowns/<slug>/…`)
is right; the five-tool MCP surface is the right minimal set for S1; the
stub-until-Lane-A-merges sequencing is clean; prompt-pack-over-API (no
bundled inference) is the correct architecture and the plan's best idea.
