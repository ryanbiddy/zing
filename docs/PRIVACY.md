# What stays local, and what connects

Zing measures and renders media on your machine. It has no telemetry or
analytics, requires no Zing account, and does not automatically publish drafts.
The CLI and stdio MCP server do not open a listening web service.
Your AI client has its own privacy policy and network behavior.

## Local media and AI clients

Local rendering, clip measurements, color matching, audio analysis and
local-photo meme rendering use local files. Results, reports and model caches
are saved on disk. Most MCP tools return paths and measurements. Reports can
also contain transcripts, captions, source URLs and filenames, which may be
sensitive even without a video upload.

**MCP `get_frames` returns image content to the connected client.** Use it only
with a client whose handling of those images you accept. A cloud AI client may
send images and other tool results to its provider. Timeline inspection returns
a local path. Choosing a local AI client is separate from installing Zing.

## Downloads you request

Installing Zing and its extras contacts package registries. `zing setup --ffmpeg`
shows an OS package-manager command and requires an interactive typed **yes**.
JSON and non-interactive modes print only. Zing does not host, bundle or directly
download FFmpeg binaries; the package manager handles its own sources and terms.

Speech setup in Studio or doctor names the model before confirmation. The
explicit model setup `--yes` flag is download consent when a model is selected.
The separate Studio plan `--yes` flag is not model-download consent.
Speech files come from pinned Hugging Face revisions and are SHA-256 checked.
The ordinary study command never downloads a speech model.

The explicit OCR fetch command downloads pinned RapidOCR assets from ModelScope.
Layout model fetching retrieves the pinned YuNet model from GitHub. Font fetches
use the pinned URLs and hashes in the font library manifest. Optional CED audio
model setup is also an explicit, pinned download. These files are cached under
the Zing workspace and their setup commands report paths and verification.
Existing model caches may be reused. See [third-party notices](THIRD-PARTY-NOTICES.md).

**Legacy OCR exception:** ordinary `zing study` can initialize RapidOCR's default
engine, which may fetch missing weights. It does not have the same explicit,
pinned provisioning boundary as the newer local-model path. Studio, Match and
Explain use local models only. For offline work use those paths and provision
models first. A local input to ordinary study is not a promise of zero network
access. This exception is why the install guide does not claim all commands
are offline by default.

## Reference URLs

Supplying a URL asks Zing's downloader to contact that site and download media.
Match and Explain require explicit `--allow-download`; Studio includes a
reference-download consent step. Ordinary study accepts a supplied URL as the
request to fetch it. Preset/taste setup can study reference URLs too. Do not
describe these older entry points as having an extra confirmation prompt.
The remote service sees an ordinary download request, including your IP address.
Local source clips are not uploaded to match a reference.

## Uoink peer

Doctor and suite-aware commands can probe Uoink over loopback HTTP, including
the default `127.0.0.1:5179` endpoint when no override is set. Explicit peer
configuration and credentials enable saved-reference lookup, verified kept-media
reuse, notes and engagement operations. Zing does not read Uoink's token file
or put tokens in URLs. It works without the peer.

A saved `uoink:<id>` may refer to retained local media or a source URL.
Match uses verified retained media without a web fallback. Other study paths
can fetch a handoff's source URL when retained media is unusable; that acquisition
needs to be part of the user's request. Sharing a draft choice is explicit.
See [Connect](CONNECT.md) for the credential and handoff contracts.

## Meme templates and voiceover

Meme catalog searches use shipped metadata. Local-photo renders stay offline.
Requesting a named template can fetch its blank image from `api.memegen.link`
on a cache miss. Pass `--offline` to refuse that fetch. This is an image download,
not an upload of your photo.

The default voice engine is local. ElevenLabs is optional: choosing that
provider and setting `ELEVENLABS_API_KEY` sends the voiceover text and voice
request to ElevenLabs. A key alone does not select the provider. Local Kokoro
needs its runtime and model files already installed; it never silently switches
to a cloud engine. See [voice providers](../src/myzing/tts_providers.py).

## Keeping or removing files

Zing keeps project inputs by reference, generated outputs, measurements and
model caches on disk. Uninstalling the Python package does not delete them.
Review the workspace before deleting it, and keep drafts you want. See
[uninstall](INSTALL.md#uninstall). Your AI client's conversation history and
any remote provider's retention are controlled separately.
