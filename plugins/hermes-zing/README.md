# Zing for Hermes Agent

Turn a local episode into short clips, study a reference video, render drafts
and make memes through Hermes. This portable Agent Plugins v1 package starts
your installed `zing serve-mcp` command over stdio and adds one skill. It exposes
Zing's existing 44 tools. It contains JSON, Markdown and a license, with no code
or runtime installer.

It pairs with the Uoink plugin for saved references and local breakdown notes.

## Install

Use Hermes 0.23.0 or later. Install Zing first with Python 3.11 or later and uv.
`myzing` is not on PyPI. This command installs from the source repository with
the media extras, including MCP support.

```sh
uv tool install --from "git+https://github.com/ryanbiddy/zing" "myzing[all]"
uv tool update-shell
```

For only the MCP connection, replace `myzing[all]` with `myzing[mcp]`. That does
not install the media extras. See the [source install guide](https://github.com/ryanbiddy/zing/blob/main/llms-install.md).

Install FFmpeg and ffprobe 6.0 or later with libx264 and libass, and put both on
PATH. The [OS install guide](https://github.com/ryanbiddy/zing/blob/main/docs/INSTALL.md) gives the commands. Reopen
your terminal and run `zing doctor` to see which features are ready.

Factory rendering also needs Node.js 20 or later, Chrome or Edge, and the
[factory sidecar](https://github.com/ryanbiddy/zing/blob/main/tools/factory-sidecar/README.md). Keep a Zing source
checkout, run `npm ci` in its `tools/factory-sidecar` folder once, and set
`ZING_FACTORY_SIDECAR` to that folder's absolute path before starting Hermes.
Set `ZING_BROWSER_PATH` if browser detection needs help. Model downloads need
separate consent; installing the package does not fetch model weights.

Then install and enable the plugin.

```sh
hermes plugins install ryanbiddy/zing/plugins/hermes-zing --no-enable
hermes plugins enable zing
```

Restart Hermes and ask it to call `zing_status`. If tools are missing, check
`hermes plugins list` and `zing doctor` in the terminal that starts Hermes.
Remove a duplicate `zing` MCP entry only if you want this package's settings;
a user-configured server with the same name takes precedence.

Hermes checks for `zing` on PATH, then `%USERPROFILE%/.local/bin/zing.exe` on
Windows or `~/.local/bin/zing` on macOS and Linux. Missing Zing hides the tools.
The fallback paths check presence; keep `zing` on PATH so the stdio command can
start. No minimum Zing version is declared because Hermes has no command-based
version probe for this executable.

## Permissions and long calls

The server is `untrusted` because it writes files and starts jobs. Hermes gates
calls without `readOnlyHint: true`. Zing currently has no read-only annotations,
so all 44 tools are gated, including status calls. Hermes can remember approval
per tool; unanswered approvals fail closed in unattended runs.

The call timeout is 7200 seconds. Study, match, factory runs and EDL renders
return jobs to poll. `factory_edit` can synchronously re-render every shape;
it has no fixed internal deadline. The two-hour budget allows long edits but
cannot guarantee completion on every machine. A timeout is not cancellation.
Check the saved state before retrying a write.

## Disclosures

- Network requests come from installed Zing when you request work. Study fetches
  media from the URL you name; saved Uoink media can fall back to its source URL.
  Taste setup can fetch selected references. Online factory runs search and
  download visuals from Wikidata, Wikimedia Commons, NASA, Library of Congress,
  Internet Archive and Openverse, and can visit the named entity's site. Optional
  Pexels, Pixabay and Exa keys enable those services. Use `offline=true` for a
  factory project that must fetch nothing.
- A named meme template can download its blank image from `api.memegen.link`.
  Ordinary study can fetch missing OCR weights. Explicit speech setup downloads
  models. Ask before these downloads. The MCP tools do not publish or upload
  source videos or rendered clips to a remote service.
- MCP factory runs use Hermes as the judge. The separate CLI's optional Claude
  judge sends prompts and public contact sheets to Anthropic. Other CLI features
  can use YouTube API credentials or `GEMINI_API_KEY`; Gemini notes send a public
  YouTube URL and a rubric to Google. These CLI features are not exposed by this
  package. It does not forward those keys or run the Claude CLI.
- Hermes' model provider can receive tool text, transcripts and images.
  `get_frames`, `generate_thumbnails` and visual-pick `factory_prompt` calls
  return images. Local rendering does not make the AI conversation local.
- Hermes starts `zing serve-mcp`. Zing starts background study, match, studio
  and render workers, and local FFmpeg, Node and browser subprocesses as needed.
  Work can take minutes or longer. A disconnected or timed-out call does not
  guarantee child processes have stopped. No scheduler is installed.
- Zing reads the source files and folders you select outside the plugin folder.
  Studies, profiles and caches live in `ZING_HOME`, defaulting to `~/.zing`.
  Factory projects, prompts, answers, logs, receipts and renders use the project
  and output paths you supply. Files remain after uninstalling the plugin.
- Uoink is optional. Health checks and library operations contact its local
  helper. `push_to_uoink` writes a breakdown note only when requested. Supply
  `UOINK_URL` and `UOINK_TOKEN` through Hermes; the plugin never reads token files.
- The plugin stores no credentials. Its optional environment placeholders pass
  workspace, sidecar, browser, Uoink and visual-service settings from the user's
  shell or Hermes profile. Unset values are omitted. Installed Zing can also
  read stock-service keys from Windows user environment variables. Never paste
  secrets into `mcp.json` or a conversation.
- Zing and this plugin have no telemetry. The plugin does not update itself or
  fetch code at startup. The catalog pin covers the plugin files; the separately
  installed Zing command and its dependencies are outside that pin.

## Example session

Ask Hermes to make three vertical clips from `episode.mp4`, using `episode.vtt`
and only local assets, under a new `clips` folder. It calls `factory_new` with
`moments=3`, `shapes=["9x16"]` and `offline=true`, then `factory_run`. It polls
`factory_status`, reads each `factory_prompt`, supplies its own `factory_answer`
and resumes. When the clips are ready, it returns the review page and receipts.

Ask it to fix a caption word or shorten a clip. It uses `factory_edit` for the
word, or `factory_clip` and another run for the trim. Review the new render and
any context flags before choosing a clip to post.
