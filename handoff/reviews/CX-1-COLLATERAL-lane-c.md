# CX-1 collateral review

**Date:** 2026-07-19

**Lens:** audience-facing launch copy, not product implementation

**Reviewed state:** Zing `561f9a0`; Uoink `origin/main` at `9905e2d`;
Writer `origin/main` at `9b76a9a`; Uoink site `origin/main` at `6388714`

## Verdict

Do not hand the current Decision Week packet to Ryan as a complete launch
brief. Three P1 contradictions can send a user to an installer that does not
exist, make the suite connection fail after the guide promises zero setup, or
ask Ryan to decide from inputs the queue itself no longer trusts.

The products are not broadly overclaimed. Writer is unusually clear about its
private status and ownership. The Uoink v3.7.0 draft is also disciplined: the
GitHub release is still a draft, its body says it is not published, and its two
artifact sizes and SHA-256 values match the evidence file. The launch risk is
the connective copy around those products.

**Count:** P1 × 3, P2 × 4, P3 × 5.

No product file was changed in this pass. Every P1/P2 is outside Lane C's
renderer and eval ownership, so each is routed below with a concrete fix.

## Coverage

| Surface | What was reviewed |
|---|---|
| Uoink README | Full public README plus every linked install, MCPB, privacy, security, and store document; current release and asset state were checked with GitHub |
| Zing README | Full README plus `docs/CONNECT.md`, `DEVELOPER-GUIDE.md`, `DIRECT-FLOW.md`, and `FETCH-TROUBLESHOOTING.md`; the taste directory was checked for launch claims and internal-language leaks |
| Writer README | Full README and `docs/ARCHITECTURE.md`, checked against current environment-variable and peer-client code |
| `SUITE-CONNECT.md` | Every instruction followed against the ratified token and discovery boundary |
| Uoink site | Public page copy, version constants, well-known MCP files, `llms*.txt`, and the creator/developer ownership story |
| store-listing drafts | Both tracked listing drafts and the canonical folder's submission checklist |
| v3.7.0 draft release notes | Checked the local note, GitHub draft body, source SHA, asset names, byte sizes, and SHA-256 values |
| Launch packet and launch copy | `DECISION-WEEK-PACKET.md`, `LAUNCH-PLAN.md`, the final fixlist, and the parked X launch thread |

## P1

### CX1-P1-1: the public Uoink install step still names an unavailable file

**Audience failure.** Uoink `README.md:75` tells a new user to download
`Uoink-Setup-3.6.0.exe` from the latest release. The latest published release
is v3.4.0 and contains the 3.4.0 installer. v3.7.0 is a private draft; there is
no public 3.6.0 asset at that URL. The same README also embeds
`assets/readme-hero-v3.1.png`, which is absent from `origin/main`.

**Reproduction.**

- `gh release list --repo ryanbiddy/uoink` reports v3.4.0 as Latest and v3.7.0
  as Draft.
- `git cat-file -e origin/main:assets/readme-hero-v3.1.png` exits 128.
- Following README step 1 cannot produce the named file.

**Why P1.** This is the first public install instruction. A user cannot finish
it, and the broken image is the first visual on the repository page.

**Fix.** Until Ryan publishes the candidate, name the actual v3.4.0 asset or
say “download the installer attached to the latest published release” without
hard-coding a future version. Restore the hero or remove the image reference.

**Route:** Codex/Uoink README owner. This also reopens FF-2; see the overnight
re-review.

### CX1-P1-2: the suite guide promises automatic integration but both clients require explicit tokens

**Audience failure.** `SUITE-CONNECT.md:31-41` says Zing needs “nothing to
configure; discovery is automatic” and Writer is “again automatic, no
wiring.” Discovery of a service manifest is automatic. Authentication is not.

Zing requires `UOINK_TOKEN` for the authenticated health and kept-media calls
(`docs/CONNECT.md:87-90`, `src/myzing/suite_peer.py:324-335`). Writer requires
`WRITER_UOINK_URL` and `WRITER_UOINK_TOKEN` (`README.md:35-43`,
`src/writer/suite_peer.py:23-24`). Writer explicitly says it never opens
Uoink's token file. That is the correct ratified security boundary.

**Reproduction.** With `UOINK_URL` and `UOINK_TOKEN` removed, `zing doctor
--json` did not report a healthy peer. The installed pre-candidate helper
answered the manifest probe with HTTP 403. Current source would still need the
token before its authenticated health call. This is expected behavior, not a
product bug.

**Why P1.** The Decision Week packet sends Ryan to this family scenario as the
integration proof. A user following the one page stops before the headline
flow starts and has no token setup instruction to recover with.

**Fix.** Say that service discovery is automatic but credentials are explicit.
Name `%LOCALAPPDATA%\Uoink\token.txt` for an installed Windows helper, then show
both products' environment variables. Do not suggest that Zing or Writer reads
the token file.

**Route:** suite-doc owner, with CX-4 as the verification gate.

### CX1-P1-3: the Decision Week packet calls incomplete and untrusted inputs complete

Three statements make the packet unsafe as a decision brief:

1. Its section 2 heading says “the complete list — nothing else pends,” while
   FF-8, FF-9, and CX-1 through CX-6 are open in the master queue.
2. It says “Full branding research ... is done.” Orchestrator item CX-6 now
   requires a trust audit before the design phase or Decision Week relies on
   the AG dossiers because their completion cadence was not credible.
3. It says “zing: tagged and PyPI-ready from source.” The public Zing
   repository has zero tags and zero releases, and
   `https://pypi.org/pypi/myzing/json` returns 404. “PyPI-ready from source”
   may be defensible; “tagged” is false.

**Why P1.** This artifact tells the decision-maker what evidence is settled.
It hides active work in its heading, overstates research confidence, and
misstates release state.

**Fix.** Mark the packet superseded until CX-1 and CX-6 land. Replace the
absolute heading with a dated open-decision list, label the branding dossiers
unverified, and describe Zing as public source with no tag, release, or PyPI
publication.

**Route:** orchestrator/Decision Week packet owner.

## P2

### CX1-P2-1: Zing's absolute local-only claim conflicts with its optional ElevenLabs provider

Zing `README.md:6-10` says it renders “all locally” and then says “No API keys,
no cloud.” The developer guide and live doctor describe optional ElevenLabs
TTS enabled by `ELEVENLABS_API_KEY`. Local Kokoro is the default, so the
product behavior is sound; the absolute copy is not.

**Fix.** Use “local by default, with no required API key or cloud service.”
Add one sentence that optional external TTS sends the voiceover request to the
selected provider.

**Route:** Zing README/docs owner.

### CX1-P2-2: the parked launch thread makes a privacy promise its next post disproves

The X draft says “Nothing leaves your machine” and later “runs entirely on
your machine.” Its next post says optional AI features use Anthropic. Uoink's
own privacy copy also correctly records source fetches to YouTube, X, RSS
hosts, and other requested URLs.

This is not published, so it is not a present user harm. It would become a
publicly quotable false claim if posted.

**Fix.** Say that the corpus stays on the user's machine, Uoink has no account,
hosted corpus, or application telemetry, source retrieval contacts the
requested source, and optional AI features contact the chosen provider.

**Route:** launch-copy owner; hold the thread until the privacy sentence is
replaced.

### CX1-P2-3: Uoink presents four version stories at once

Current public or launch-facing copy identifies Uoink as:

- v3.3.1 in the live `/.well-known/mcp.json`, site constants, and generated
  `llms*.txt`;
- v3.4.0 in the latest published GitHub release;
- 3.6.0 in the public README install step; and
- v3.7.0 in the provisional draft.

The draft itself is honest. The surrounding collateral has not been cut over
as one release set. A registry client, site visitor, README user, and release
reviewer therefore receive four different answers.

**Fix.** Treat version-bearing copy as one release checklist: source version,
README, site constant, well-known files, generated agent text, release body,
and artifact names must move together after Ryan approves the number. Until
then, the README must describe the published release rather than the draft.

**Route:** Codex/Uoink release and site owners. Keep all v3.7 assets draft.

### CX1-P2-4: two tracked store listings compete for the same manual submission

`docs/store/listing.md` calls itself “copy-paste ready,” uses `uoink.app`, and
points to `hi@uoink.app`. `docs/store-listing.md` is also a complete submission
draft but uses `uoink.video` and `hi@uoink.video`. The canonical checklist does
warn not to use an older `uoink.video` asset, and the old web URLs currently
308-redirect to `uoink.app`. That mitigation does not prevent a rushed human
from opening the plausible top-level draft and pasting it.

**Fix.** Remove the obsolete draft or replace its entire body with a pointer to
`docs/store/listing.md`. Keep exactly one manual submission source.

**Route:** Codex/Uoink store-doc owner.

## P3

1. **CX1-P3-1: audience copy exposes internal contract language.**
   `SUITE-CONNECT.md` uses “kept media,” “versioned read contract,” “peer,” and
   “absence is calm” before it explains the user action. Keep those terms in
   technical notes; the one-page path should say what to save, where to put the
   token, and what success looks like.
2. **CX1-P3-2: Zing's developer guide documents a retired team topology.**
   `docs/DEVELOPER-GUIDE.md:77-81` presents Lane D/Antigravity as the current
   workflow. The orchestrator retired that lane. A public contributor guide
   should describe code ownership, not a temporary agent roster.
3. **CX1-P3-3: old domain and contact strings remain in trust documents.**
   Uoink's privacy and security docs still name `hi@uoink.video`; the site
   privacy page calls `uoink.video` the marketing site. Web links redirect
   today, so this is drift rather than a broken path. Confirm the support
   mailbox before replacing every public contact in one pass.
4. **CX1-P3-4: the public site still assigns writing to Uoink.** The creator
   pages present Writing Studio and Voice DNA as Uoink features, while
   Writer's README says Writer owns drafts, scripts, voice samples, and Voice
   DNA. Compatibility routes make the current Uoink statement functionally
   true. Before the compatibility window narrows, Ryan needs one explicit
   public ownership choice and a coordinated copy change.
5. **CX1-P3-5: some client-compatibility claims lack cited evidence.** The
   Uoink README and well-known files say the MCP server was tested with Claude
   Desktop, Cursor, Cline, and Continue. No reviewed launch record proves the
   latter three. Preserve the claim only if CX-5 records the client/version and
   result.

## What held up

- **v3.7.0 draft release notes:** the GitHub release remains Draft, its body
  says nothing is published, and the two uploaded assets match the evidence:
  `Uoink-Setup-3.7.0.exe` is 339,807,188 bytes with SHA-256
  `902F104C9B8CBF68FEA79C0C451D63AF8D448058554642F72704E641F5DCB275`;
  `uoink-3.7.0.mcpb` is 38,792 bytes with SHA-256
  `495F065072BA29B620B5DD81F2F8E19A1ADC78940F22CCF37CBFC97C665D68C1`.
- **Writer README:** it plainly says the repository is private, has not been
  released, names the optional Uoink variables, rejects hidden providers, and
  separates Writer, Uoink, and Zing ownership.
- **Zing's pre-launch install wording:** `docs/CONNECT.md` now distinguishes
  install-from-source today from `myzing` on PyPI at launch. The package is not
  on PyPI, but this document no longer pretends that it is.
- **Uoink privacy detail:** the README and site privacy page distinguish local
  corpus storage from source fetches and optional Anthropic calls. The launch
  thread should inherit that precise wording.
- **Tone:** the three product READMEs have distinct but compatible voices.
  Uoink is direct and consumer-facing, Zing is technical and specific, and
  Writer is restrained. The embarrassing voice drift is concentrated in the
  suite guide's contract jargon, not in the product introductions.

## Re-review of overnight fixes

I would not have closed FF-2 from the Zing `CONNECT.md` evidence alone. The
fixlist item explicitly covered two failures: the unpublished `myzing` package
and the Uoink README's unavailable release. The Zing half is corrected. The
Uoink README half is unchanged on current `origin/main`, so FF-2 is only
partially fixed.

FF-6 delivered the missing one-page suite guide, but I would not have accepted
its zero-configuration language against the ratified token boundary. The
manifest may be discovered without a credential; authenticated sibling calls
still require user-supplied, product-specific environment variables. CX-4
should treat CX1-P1-2 as its first regression.

FF-1's rebuilt v3.7.0 draft set meets the evidence standard I would use. The
release stayed private, its copy distinguishes candidate state from published
state, and the asset metadata is internally consistent. I would keep that work
unchanged.

## Routing

| Finding | Owner | Required close evidence |
|---|---|---|
| CX1-P1-1 | Codex/Uoink README | public README names an asset present on the linked published release; hero target exists |
| CX1-P1-2 | suite-doc owner + CX-4 | fresh shell follows one page, sets both token variables, and reaches healthy sibling calls |
| CX1-P1-3 | orchestrator | packet lists current open gates, removes “tagged,” and marks AG research unverified until CX-6 |
| CX1-P2-1 | Zing README/docs owner | local-default claim and optional external TTS disclosure agree |
| CX1-P2-2 | launch-copy owner | privacy sentence names source fetches and opt-in provider calls before any post is authorized |
| CX1-P2-3 | Uoink release/site owner | one approved version across release, README, site, well-known files, and generated agent text |
| CX1-P2-4 | Uoink store-doc owner | one canonical listing remains; obsolete file cannot be mistaken for submission copy |

The review regression first failed because this evidence record did not exist.
Its contract requires every assigned surface, severity buckets, the overnight
re-review, and explicit routing. No release, site deployment, store
submission, post, spend, or product file was changed.
