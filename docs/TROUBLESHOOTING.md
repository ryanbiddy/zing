# When Zing cannot make a draft

Run `zing doctor` first. In a checkout, use `uv run --frozen zing doctor`.
Read the failed line and its fix. A ready FFmpeg check does not mean every
optional model is installed. [Install instructions](INSTALL.md) cover each OS.

## FFmpeg missing, too old or missing a filter

Run `zing setup --ffmpeg`. It shows the package-manager command for your OS
and needs a typed **yes** before running it. After installing, reopen the
terminal and run doctor again. FFmpeg and ffprobe must both be on PATH and at
least version 6.0. Doctor lists missing encoders and filters by name.

On Windows, use `winget install --id Gyan.FFmpeg -e`, or
`choco install ffmpeg-full` if you use Chocolatey. On Ubuntu/Debian, use
`sudo apt install ffmpeg`. On Fedora, full FFmpeg needs an appropriate repository;
`ffmpeg-free` may lack libx264. See [Linux installation](INSTALL.md#linux).

## No libass, or captions will not burn into the video

Installing a Python package cannot add libass to FFmpeg. On macOS, run
`brew install ffmpeg-full`, then put its commands first on PATH with
`export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"`. Keep that line in your
shell's startup file. The plain Homebrew bottle lacks libass. On Windows, use
the full build above. Doctor needs either the `ass` or `subtitles` filter.

If doctor finds the filter but rendering fails, read the render error too:
font files, paths and permissions can still be wrong. Doctor checks advertised
capabilities, not every possible render or native model load.

## No speech model, empty transcript or missing spoken captions

Run `zing doctor --speech-model small.en` for English and confirm the roughly
486 MB download, or select speech setup in Studio. For multilingual speech,
choose `large-v2` (about 3.09 GB). The ordinary study command defaults to
large-v2; `ZING_WHISPER_MODEL` can select another cached model or a complete
local model folder. Keep `ZING_HOME` consistent between setup and editing.

Skipping speech saves the download, but spoken captions and whole-line
continuity are unavailable. Clips without safe timing can be excluded and
leave too little footage. Start with the silent clip in [Studio](STUDIO.md)
to check rendering separately. Review names and timing even with a model.

## OCR model missing or corrupt

Doctor's `ocr` row checks the Python package. The `caption_geometry` row also
checks pinned model assets. In a checkout, explicitly fetch them with:

```console
uv run --frozen python -m myzing.study.caption_models --fetch
```

This downloads from ModelScope and verifies SHA-256. Run it with the same
`ZING_HOME` used for editing. For a tool install, use that tool's Python
interpreter with `-m myzing.study.caption_models --fetch`; your unrelated system
Python may not contain Zing. If the runtime is missing, reinstall the `all`
extra with the tool you used to install Zing, or rerun `uv sync --all-extras`
in the checkout. A corrupt download is not accepted as a working model.

Optional face-aware placement needs the layout runtime and an explicit
`zing layout fetch-model`. Extra fonts use `zing fonts fetch --all`. Both
commands authorize their listed downloads. They are not required for the first
silent draft. Missing face evidence must stay unknown, not "face safe."

## Windows permissions or paths

Use a project folder you own. Avoid Program Files and protected system folders.
Put quotes around paths containing spaces. In Studio, you can drag a file or
folder into the terminal; its surrounding quotes are accepted. Choose a fresh
output folder outside the input clips folder.

If `zing` is not recognized, reopen PowerShell after installation. In a
checkout use `uv run --frozen zing studio` from the folder containing
`pyproject.toml`. For pipx, run `pipx ensurepath`, then reopen PowerShell.
If Windows opens the Store instead of Python, use the Python installer from
python.org or uv as described in [Install](INSTALL.md).

An administrator prompt belongs to the package manager. Zing itself should
run as your normal user. A locked output may be open in a video player; close
it or choose a new output folder. Do not overwrite your source clips.

## Working offline

Install packages and explicitly fetch the models you need while connected.
Then use local files with Studio, Match or Explain. Missing models remain
warnings or can block a draft. Ordinary `zing study` has a legacy RapidOCR
auto-fetch path, so a local input alone is not an offline guarantee.

For memes, pass `--offline` to prevent an uncached template blank fetch.
This flag applies to that command, not to every Zing network operation.
Doctor may probe a local Uoink peer. There is no requirement to run Uoink for
local drafts. See [privacy](PRIVACY.md) for each network boundary and
[fetch troubleshooting](FETCH-TROUBLESHOOTING.md) for URL errors.
